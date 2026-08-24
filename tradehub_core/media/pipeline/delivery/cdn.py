"""T-018 — CDN purge prototipi ve content-addressed URL kararı.

Normal medya teslimatında URL sürümlüdür; yeni içerik yeni URL aldığı için
purge gerekmez. Aynı URL'in zorunlu olarak üzerine yazıldığı istisnai akışta
bu istemci Cloudflare, Bunny veya genel JSON purge ucunu kontrollü batch'ler.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping
from urllib.parse import quote, urlsplit

PROVIDER_GENERIC = "generic"
PROVIDER_CUSTOM = "custom"
PROVIDER_CLOUDFLARE = "cloudflare"
PROVIDER_BUNNY = "bunny"
PROVIDER_CLOUDFRONT = "cloudfront"
PROVIDERS: frozenset[str] = frozenset(
	{PROVIDER_GENERIC, PROVIDER_CUSTOM, PROVIDER_CLOUDFLARE, PROVIDER_BUNNY, PROVIDER_CLOUDFRONT}
)


class CdnPurgeError(RuntimeError):
	"""Purge isteği kurulamadı veya sağlayıcı tarafından reddedildi."""


@dataclass(frozen=True)
class HttpResponse:
	status: int
	body: bytes = b""
	headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[str, str, Mapping[str, str], bytes, float], HttpResponse]


@dataclass(frozen=True)
class CdnPurgeConfig:
	provider: str
	api_url: str
	token: str = field(repr=False)
	zone_id: str = ""
	timeout_seconds: float = 5.0
	max_batch: int = 30

	def __post_init__(self) -> None:
		provider = self.provider.lower()
		if provider not in PROVIDERS:
			raise CdnPurgeError(f"Bilinmeyen CDN sağlayıcısı: {self.provider!r}")
		parsed = urlsplit(self.api_url)
		if parsed.scheme != "https" or not parsed.netloc:
			raise CdnPurgeError("CDN purge api_url HTTPS olmalıdır")
		if parsed.username or parsed.password:
			raise CdnPurgeError("CDN purge api_url kullanıcı bilgisi taşıyamaz")
		if not self.token:
			raise CdnPurgeError("CDN purge token boş olamaz")
		if (
			provider == PROVIDER_CLOUDFLARE
			and not self.zone_id
			and not self.api_url.rstrip("/").endswith("/purge_cache")
		):
			raise CdnPurgeError(
				"Cloudflare için zone_id veya tam /purge_cache endpoint'i zorunludur"
			)
		if self.max_batch < 1 or self.max_batch > 100:
			raise CdnPurgeError("max_batch 1..100 aralığında olmalıdır")
		if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
			raise CdnPurgeError("timeout_seconds 0..30 aralığında olmalıdır")


@dataclass(frozen=True)
class PurgeBatch:
	urls: tuple[str, ...]
	status: int
	ok: bool


@dataclass(frozen=True)
class PurgeResult:
	provider: str
	requested: int
	purged: int
	batches: tuple[PurgeBatch, ...]

	@property
	def ok(self) -> bool:
		return bool(self.batches) and all(batch.ok for batch in self.batches)


def should_purge(*, old_url: str, new_url: str) -> bool:
	"""Content-addressed yeni URL purge istemez; yalnız aynı URL overwrite ister."""
	return bool(old_url and new_url and old_url == new_url)


def _validate_urls(urls: Iterable[str]) -> tuple[str, ...]:
	out: list[str] = []
	seen: set[str] = set()
	for raw in urls:
		url = str(raw or "").strip()
		parsed = urlsplit(url)
		if parsed.scheme not in {"http", "https"} or not parsed.netloc:
			raise CdnPurgeError("Purge URL yalnız http/https olabilir")
		if parsed.username or parsed.password:
			raise CdnPurgeError("Purge URL kullanıcı bilgisi taşıyamaz")
		if url not in seen:
			seen.add(url)
			out.append(url)
	return tuple(out)


def stdlib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> HttpResponse:
	request = urllib.request.Request(url, data=body or None, method=method, headers=dict(headers))
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL configte HTTPS gate'li
			return HttpResponse(int(response.status), response.read(64 * 1024), dict(response.headers.items()))
	except urllib.error.HTTPError as exc:
		return HttpResponse(int(exc.code), exc.read(64 * 1024), dict(exc.headers.items()) if exc.headers else {})


class CdnPurgeClient:
	def __init__(self, config: CdnPurgeConfig, *, transport: Transport | None = None) -> None:
		self.config = config
		self.transport = transport or stdlib_transport

	def _request(self, urls: tuple[str, ...]) -> tuple[str, str, dict[str, str], bytes]:
		provider = self.config.provider.lower()
		base = self.config.api_url.rstrip("/")
		if provider == PROVIDER_CLOUDFLARE:
			url = (
				f"{base}/zones/{quote(self.config.zone_id, safe='')}/purge_cache"
				if self.config.zone_id
				else base
			)
			headers = {"Authorization": f"Bearer {self.config.token}", "Content-Type": "application/json"}
			body = json.dumps({"files": list(urls)}, separators=(",", ":")).encode("utf-8")
			return "POST", url, headers, body
		if provider == PROVIDER_BUNNY:
			# Bunny tek URL purge eder; max_batch yapılandırması istemci tarafından
			# yine 1'e indirilir.
			url = f"{base}?url={quote(urls[0], safe='')}&async=false"
			return "POST", url, {"AccessKey": self.config.token}, b""
		headers = {"Authorization": f"Bearer {self.config.token}", "Content-Type": "application/json"}
		body = json.dumps({"urls": list(urls)}, separators=(",", ":")).encode("utf-8")
		return "POST", base, headers, body

	def purge(self, urls: Iterable[str]) -> PurgeResult:
		clean = _validate_urls(urls)
		if not clean:
			return PurgeResult(self.config.provider.lower(), 0, 0, ())
		batch_size = 1 if self.config.provider.lower() == PROVIDER_BUNNY else self.config.max_batch
		results: list[PurgeBatch] = []
		for start in range(0, len(clean), batch_size):
			batch = clean[start : start + batch_size]
			method, url, headers, body = self._request(batch)
			try:
				response = self.transport(method, url, headers, body, self.config.timeout_seconds)
			except Exception as exc:
				# Sağlayıcı/HTTP istemcisi hata içinde token döndürse bile dışarı
				# taşımayız; hata tipi operasyon için yeterlidir.
				raise CdnPurgeError(f"CDN purge taşıma hatası: {type(exc).__name__}") from exc
			ok = 200 <= int(response.status) < 300
			results.append(PurgeBatch(batch, int(response.status), ok))
			if not ok:
				raise CdnPurgeError(f"CDN purge HTTP {int(response.status)}")
		return PurgeResult(
			provider=self.config.provider.lower(),
			requested=len(clean),
			purged=sum(len(batch.urls) for batch in results if batch.ok),
			batches=tuple(results),
		)


__all__ = [
	"CdnPurgeClient",
	"CdnPurgeConfig",
	"CdnPurgeError",
	"PROVIDER_CUSTOM",
	"PROVIDER_CLOUDFRONT",
	"HttpResponse",
	"PurgeBatch",
	"PurgeResult",
	"should_purge",
	"stdlib_transport",
]
