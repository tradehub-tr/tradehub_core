"""T-061/062/065 — `Media Version` zenginleştirmesi: tek kaynaktan tek künye.

Ne işe yarar
------------
Üretim hattı (`media/pipeline_bridge.py::_ensure_version` → `Media Version`
controller'ı) sürüm kaydını açarken bu modülü çağırır ve üç görevin çıktısını
TEK okumada toplar:

  * **T-061** — normalize alanları: `width/height` (EXIF uygulanmış görünen
    ölçü), `dpi` (normalize kararı: `normalize.DEFAULT_DPI_OUT`, INV-02 —
    metadata 72 yazılır, piksel DEĞİŞMEZ), `colorspace` (normalize hedefi
    sRGB), `has_alpha` (başlıktan).
  * **T-062** — sınıflandırma + biçim zinciri: `classify.classify()` sınıfı
    ve `FORMAT_CHAINS` zincirini verir; ikisi de kayda AYNEN yazılır ki
    "hangi kural neden uygulandı" sorusu sonradan cevaplanabilsin.
  * **T-065** — LQIP + baskın renk: `lqip.encode()` ThumbHash'i (<30 bayt,
    base64 kanonik değer), baskın rengi (`#rrggbb`) ve teslim katmanının
    beklediği hazır `data:image/png;base64,…` URI'sini üretir.

Neden `dpi`/`colorspace` ölçüm değil KARAR
------------------------------------------
Köprü bugün normalize master dosyası ÜRETMİYOR; türevler kaynaktan doğrudan
kodlanıyor. `Media Version.dpi` ve `.colorspace` alanlarının şartnamedeki
anlamı "normalize master'ın değerleri"dir ve normalize politikası bu iki
değeri SABİTLER (dpi_out=72, colorspace=srgb — `normalize.NormalizeSpec`).
Kaynağın kendi DPI'ını buraya yazmak, INV-02'nin tam tersini — "master
kaynağın DPI'ını taşır" iddiasını — kayda geçirmek olurdu.

İstisna ATMAZ: `ok=False` + `reason` döner. Zenginleştirme bir süslemedir;
başarısız olması sürüm kaydının açılmasını asla engellememelidir.

`import frappe` YOKTUR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tradehub_core.media.pipeline.image import classify as classify_mod
from tradehub_core.media.pipeline.image import lqip as lqip_mod
from tradehub_core.media.pipeline.image.normalize import DEFAULT_DPI_OUT
from tradehub_core.media.pipeline.image.probe import HeaderProbe, probe_header

#: Normalize master'ın renk uzayı — `NormalizeSpec.colorspace="srgb"` kararının
#: kayıt/manifest gösterim biçimi (`Media Version.colorspace` varsayılanıyla aynı).
MASTER_COLORSPACE: str = "sRGB"

#: `Media Version.classification` alanına yazılabilen sınıflar —
#: `classify.FORMAT_CHAINS` anahtarlarıyla birebir.
CLASSIFICATIONS: tuple[str, ...] = (
	classify_mod.SINIF_PHOTO,
	classify_mod.SINIF_GRAPHIC,
	classify_mod.SINIF_TRANSPARENT,
	classify_mod.SINIF_ANIMATION,
	classify_mod.SINIF_TEXT,
)


@dataclass(frozen=True)
class VersionEnrichment:
	"""Zenginleştirme çıktısı. `ok=False` ise hiçbir alan yazılmamalı."""

	ok: bool
	reason: str = ""
	# — T-061: normalize alanları —
	width: int = 0
	height: int = 0
	dpi: int = DEFAULT_DPI_OUT
	colorspace: str = MASTER_COLORSPACE
	has_alpha: bool = False
	# — T-062: sınıflandırma + biçim zinciri —
	classification: str = ""
	classification_confidence: str = ""
	#: `classify.FormatStep.to_dict()` sözlükleri, zincir sırasıyla.
	format_chain: tuple = field(default_factory=tuple)
	# — T-065: LQIP + baskın renk —
	#: ThumbHash'in base64'ü — kanonik değer, ham hali <30 bayt.
	lqip: str = ""
	#: Teslim katmanının beklediği hazır `data:image/png;base64,…`.
	lqip_data_uri: str = ""
	#: `#rrggbb` — saydam pikseller sayılmadan en çok yer kaplayan renk.
	dominant_color: str = ""

	@property
	def format_chain_names(self) -> tuple[str, ...]:
		"""Zincirin yalın biçim adları — `("AVIF", "WEBP", "JPEG")` gibi."""
		return tuple(str(a.get("fmt") or "") for a in self.format_chain)

	def to_dict(self) -> dict:
		return {
			"ok": self.ok,
			"reason": self.reason,
			"width": self.width,
			"height": self.height,
			"dpi": self.dpi,
			"colorspace": self.colorspace,
			"has_alpha": self.has_alpha,
			"classification": self.classification,
			"classification_confidence": self.classification_confidence,
			"format_chain": [dict(a) for a in self.format_chain],
			"lqip": self.lqip,
			"lqip_data_uri": self.lqip_data_uri,
			"dominant_color": self.dominant_color,
		}


def enrich(
	source: bytes | bytearray | str | Path,
	*,
	filename: str = "",
) -> VersionEnrichment:
	"""Kaynaktan sürüm künyesi çıkar. İstisna ATMAZ.

	Sınıflandırma ve LQIP BİRBİRİNDEN BAĞIMSIZ denenir: biri düşerse öbürünün
	çıktısı yine döner (`ok=True`, eksik alan boş). İkisi de düşerse
	`ok=False` + ilk sebep döner — "yarı dolu" ile "hiç ölçülemedi" ayrımı
	çağıranın log kararı için gerekli.
	"""
	siniflandirma: classify_mod.Classification | None = None
	sinif_hatasi = ""
	try:
		siniflandirma = classify_mod.classify(source, filename=filename)
		if not siniflandirma.ok:
			sinif_hatasi = siniflandirma.error
	except Exception as exc:  # noqa: BLE001 — zenginleştirme çağıranı patlatmaz
		sinif_hatasi = f"classify:{type(exc).__name__}: {exc}"

	lqip_sonuc = lqip_mod.encode(source)
	lqip_hatasi = "" if lqip_sonuc.ok else (lqip_sonuc.reason or "lqip_failed")

	probe: HeaderProbe | None = siniflandirma.probe if siniflandirma else None
	if probe is None or not probe.readable:
		try:
			probe = probe_header(source, filename=filename)
		except Exception as exc:  # noqa: BLE001
			probe = None
			if not sinif_hatasi:
				sinif_hatasi = f"probe:{type(exc).__name__}: {exc}"

	okunabilir = bool(probe and probe.readable)
	if not okunabilir and not lqip_sonuc.ok:
		return VersionEnrichment(ok=False, reason=sinif_hatasi or lqip_hatasi or "unreadable")

	genislik, yukseklik = probe.display_size if probe else (0, 0)
	alfa = bool(probe.has_alpha) if probe else bool(lqip_sonuc.has_alpha)

	sinif = ""
	guven = ""
	zincir: tuple = ()
	# Kapı reddi/özellik hatası sınıfı "photo varsayıldı" olarak döndürür ama
	# `measured=False` işaretler — ÖLÇÜLMEMİŞ sınıfı kayda yazmak, tahmini
	# ölçüm gibi göstermek olurdu; boş bırakılır ve sebep `reason`da taşınır.
	if siniflandirma is not None and siniflandirma.ok:
		sinif = siniflandirma.klass
		guven = siniflandirma.confidence
		zincir = tuple(adim.to_dict() for adim in siniflandirma.chain)

	uri = ""
	if lqip_sonuc.ok:
		try:
			uri = lqip_mod.thumb_hash_to_data_uri(lqip_sonuc.hash)
		except Exception as exc:  # noqa: BLE001 — URI süslemedir, hash kanoniktir
			lqip_hatasi = f"data_uri:{type(exc).__name__}: {exc}"

	return VersionEnrichment(
		ok=True,
		reason="; ".join(s for s in (sinif_hatasi, lqip_hatasi) if s),
		width=int(genislik or 0),
		height=int(yukseklik or 0),
		dpi=DEFAULT_DPI_OUT,
		colorspace=MASTER_COLORSPACE,
		has_alpha=alfa,
		classification=sinif,
		classification_confidence=guven,
		format_chain=zincir,
		lqip=lqip_sonuc.base64 if lqip_sonuc.ok else "",
		lqip_data_uri=uri,
		dominant_color=lqip_sonuc.dominant_hex if lqip_sonuc.ok else "",
	)


__all__ = [
	"CLASSIFICATIONS",
	"MASTER_COLORSPACE",
	"VersionEnrichment",
	"enrich",
]
