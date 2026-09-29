"""13.1 Tarama planı — saf (Frappe'siz): tam / artımlı / örneklem seçimi, bütçe, hız sınırı.

- **Tam:** tüm adaylar.
- **Artımlı:** hiç taranmamış, `incremental_days`'den eski taranan ya da son taramadan sonra
  değişmiş (`changed`) adaylar.
- **Örneklem:** deterministik tohumla (aynı tohum + aynı aday kümesi = aynı örneklem) n adet ya da
  yüzde; sıralama öncelik puanına göre (yayında+indekslenebilir+son değişen önce) değil, karıştırma
  ile — örneklem "temsil" içindir, öncelikli küme `targeted` moduna aittir.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MODES = ("full", "incremental", "sample", "targeted", "audit")


def _dt(v) -> datetime | None:
	if v is None or v == "":
		return None
	if isinstance(v, datetime):
		return v
	try:
		return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
	except ValueError:
		return None


def select_urls(
	candidates: list[str],
	mode: str,
	*,
	last_crawled: dict[str, str | datetime] | None = None,
	changed: set[str] | None = None,
	incremental_days: int = 7,
	sample_size: int | None = None,
	sample_pct: float | None = None,
	seed: str = "",
	now: datetime | None = None,
) -> list[str]:
	"""Aday URL listesinden moda göre taranacakları seç (sıra deterministik, tekrar yok)."""
	if mode not in MODES:
		raise ValueError(f"bilinmeyen mod: {mode}")
	seen: set[str] = set()
	adaylar = [u for u in candidates if u and not (u in seen or seen.add(u))]
	if mode in ("full", "targeted", "audit"):
		return adaylar
	now = now or datetime.now()
	if mode == "incremental":
		esik = now - timedelta(days=int(incremental_days or 0))
		last = last_crawled or {}
		degisen = changed or set()
		out = []
		for u in adaylar:
			son = _dt(last.get(u))
			if u in degisen or son is None or son <= esik:
				out.append(u)
		return out
	# sample
	n = len(adaylar)
	if sample_size is None and sample_pct is not None:
		sample_size = max(1, int(round(n * float(sample_pct) / 100.0))) if n else 0
	k = min(int(sample_size or 0), n)
	if k <= 0:
		return []
	# tohumlu karıştırma: sha256(seed|url) sırası — aynı girdi aynı çıktı, yeni URL eski sırayı bozmaz
	skor = {u: hashlib.sha256(f"{seed}|{u}".encode()).hexdigest() for u in adaylar}
	return sorted(adaylar, key=lambda u: skor[u])[:k]


@dataclass
class Budget:
	"""Tarama bütçesi — herhangi biri aşılınca durur (13.1 'tarama bütçesi')."""

	max_pages: int = 0
	max_seconds: int = 0
	max_bytes: int = 0

	def exceeded(self, *, pages: int, seconds: float, bytes_: int) -> str | None:
		if self.max_pages and pages >= self.max_pages:
			return "max_pages"
		if self.max_seconds and seconds >= self.max_seconds:
			return "max_seconds"
		if self.max_bytes and bytes_ >= self.max_bytes:
			return "max_bytes"
		return None


@dataclass
class RateLimiter:
	"""Host başına token kovası — `rps` istek/sn (13.1 'hız sınırları'). Test için clock/sleep enjekte."""

	rps: float = 2.0
	burst: int = 1
	clock: Callable[[], float] = time.monotonic
	sleep: Callable[[float], None] = time.sleep
	_next: dict[str, float] = field(default_factory=dict)

	def wait(self, host: str) -> float:
		"""Bekleme süresini döndürür (ve bekler). rps<=0 ise sınır yok."""
		if not self.rps or self.rps <= 0:
			return 0.0
		aralik = 1.0 / float(self.rps)
		simdi = self.clock()
		hedef = self._next.get(host, simdi)
		bekle = max(0.0, hedef - simdi)
		if bekle > 0:
			self.sleep(bekle)
		self._next[host] = max(hedef, simdi) + aralik
		return bekle
