"""T-018 — imgproxy için allowlist'li, HMAC-SHA256 imzalı URL üretimi.

Anahtar ve tuz yalnız imza hesabında kullanılır; dönen URL'e, ``repr``e veya
hata ayrıntısına yazılmaz. Dinamik boyut kabul edilmez: Faz 1 prototipinin beş
kanıt boyutu ``96, 192, 384, 768, 1280`` allowlist'idir.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass, field
from urllib.parse import urlsplit

IMGPROXY_WIDTHS: tuple[int, ...] = (96, 192, 384, 768, 1280)
RESIZE_TYPES: frozenset[str] = frozenset({"fit", "fill", "auto"})
OUTPUT_FORMATS: frozenset[str] = frozenset({"avif", "webp", "jpg", "png"})


class ImgproxyError(ValueError):
	"""İmzalı imgproxy yolu güvenle üretilemedi."""


def _hex_secret(value: str, label: str) -> bytes:
	try:
		decoded = bytes.fromhex(str(value or ""))
	except ValueError as exc:
		raise ImgproxyError(f"{label} geçerli hex olmalıdır") from exc
	if not decoded:
		raise ImgproxyError(f"{label} boş olamaz")
	return decoded


def encode_source_url(source_url: str) -> str:
	"""Kaynak URL'i imgproxy'nin URL-safe, padsiz base64 biçimine çevir."""
	parsed = urlsplit(str(source_url or ""))
	if parsed.scheme not in {"http", "https"} or not parsed.netloc:
		raise ImgproxyError("Kaynak URL yalnız http/https olabilir")
	if parsed.username or parsed.password:
		raise ImgproxyError("Kaynak URL kullanıcı bilgisi taşıyamaz")
	return base64.urlsafe_b64encode(source_url.encode("utf-8")).rstrip(b"=").decode("ascii")


def sign_path(path: str, *, key: bytes, salt: bytes) -> str:
	"""``base64url(HMAC-SHA256(key, salt + path))``; padding yazılmaz."""
	if not path.startswith("/"):
		raise ImgproxyError("İmzalanan imgproxy yolu '/' ile başlamalıdır")
	if not key or not salt:
		raise ImgproxyError("imgproxy anahtarı ve tuzu boş olamaz")
	digest = hmac.new(key, salt + path.encode("utf-8"), hashlib.sha256).digest()
	return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class ImgproxyConfig:
	base_url: str
	key_hex: str = field(repr=False)
	salt_hex: str = field(repr=False)
	widths: tuple[int, ...] = IMGPROXY_WIDTHS

	def __post_init__(self) -> None:
		base = urlsplit(self.base_url)
		if base.scheme not in {"http", "https"} or not base.netloc:
			raise ImgproxyError("imgproxy base_url geçerli http/https URL olmalıdır")
		if base.username or base.password:
			raise ImgproxyError("imgproxy base_url kullanıcı bilgisi taşıyamaz")
		_hex_secret(self.key_hex, "imgproxy key")
		_hex_secret(self.salt_hex, "imgproxy salt")
		if not self.widths or any(int(width) <= 0 for width in self.widths):
			raise ImgproxyError("imgproxy boyut allowlist'i pozitif olmalıdır")

	@property
	def key(self) -> bytes:
		return _hex_secret(self.key_hex, "imgproxy key")

	@property
	def salt(self) -> bytes:
		return _hex_secret(self.salt_hex, "imgproxy salt")


@dataclass(frozen=True)
class ImgproxyUrl:
	url: str
	path: str
	signature: str
	width: int
	height: int
	format: str


class ImgproxyUrlBuilder:
	def __init__(self, config: ImgproxyConfig) -> None:
		self.config = config

	def build(
		self,
		source_url: str,
		*,
		width: int,
		height: int = 0,
		resize_type: str = "fit",
		output_format: str = "webp",
		gravity: str = "sm",
	) -> ImgproxyUrl:
		w = int(width)
		h = int(height)
		resize = str(resize_type or "").lower()
		fmt = str(output_format or "").lower().replace("jpeg", "jpg")
		if w not in set(int(value) for value in self.config.widths):
			raise ImgproxyError(f"Boyut allowlist dışında: {w}; izinli={self.config.widths}")
		if h < 0:
			raise ImgproxyError("Yükseklik negatif olamaz")
		if resize not in RESIZE_TYPES:
			raise ImgproxyError(f"Desteklenmeyen resize_type: {resize!r}")
		if fmt not in OUTPUT_FORMATS:
			raise ImgproxyError(f"Desteklenmeyen çıktı biçimi: {fmt!r}")
		if gravity not in {"sm", "ce", "no", "so", "ea", "we"}:
			raise ImgproxyError(f"Desteklenmeyen gravity: {gravity!r}")

		encoded = encode_source_url(source_url)
		path = f"/rs:{resize}:{w}:{h}:0/g:{gravity}/{encoded}.{fmt}"
		signature = sign_path(path, key=self.config.key, salt=self.config.salt)
		base = self.config.base_url.rstrip("/")
		return ImgproxyUrl(
			url=f"{base}/{signature}{path}",
			path=path,
			signature=signature,
			width=w,
			height=h,
			format=fmt,
		)

	def ladder(
		self,
		source_url: str,
		*,
		output_format: str = "webp",
		resize_type: str = "fit",
	) -> tuple[ImgproxyUrl, ...]:
		"""Kanonik beş genişliğin tamamını üret."""
		return tuple(
			self.build(
				source_url,
				width=int(width),
				output_format=output_format,
				resize_type=resize_type,
			)
			for width in self.config.widths
		)


__all__ = [
	"IMGPROXY_WIDTHS",
	"ImgproxyConfig",
	"ImgproxyError",
	"ImgproxyUrl",
	"ImgproxyUrlBuilder",
	"encode_source_url",
	"sign_path",
]
