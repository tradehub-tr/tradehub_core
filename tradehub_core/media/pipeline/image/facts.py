"""Bir görsel dosyanın ÖLÇÜLEN künyesi: DPI, renk uzayı, alfa.

Panelin Kalite sekmesi kaynak ve sonuç dosyasını bu üç satırla karşılaştırır.
`Media Version.dpi/colorspace` bu iş için kullanılamaz: oradaki değerler
normalize politikasının KARARIDIR (`enrich.py` başlığı — dpi_out=72,
colorspace=srgb sabit), dosyanın kendisinden okunmuş değer değil. Burada her
alan dosyanın başlığından okunur; varsayılan bir değer ölçüm gibi yazılmaz.

Alanlar
-------
* ``dpi`` — konteyner DPI'ı (JPEG/PNG/TIFF) ya da EXIF X/YResolution (WebP/
  AVIF; `dpi.read_dpi`). Dosyada hiç yoksa **0**: "ölçüldü, dosyada DPI kaydı
  yok" demektir, "72 varsayıldı" DEĞİL.
* ``colorspace`` — gömülü ICC profilinin açıklamasından kanonik ad ("sRGB",
  "Adobe RGB", "Display P3", "ProPhoto RGB"; tanınmayan profilin açıklaması
  olduğu gibi). Profil yoksa piksel kipinden: "CMYK", "Gray", "RGB". Yalın
  "RGB" = ICC profili gömülü olmayan (etiketsiz) RGB — sRGB olduğu İDDİA
  EDİLMEZ; tarayıcılar onu sRGB varsayar ama bu dosyanın söylediği bir şey
  değil.
* ``has_alpha`` — kipte alfa kanalı var mı (RGBA/LA/PA) ya da palet/gri
  görselde `transparency` bilgisi var mı.

Yalnız başlık okunur (`Image.open` pikselleri çözmez) — 40 bin dosyalık
geriye dönük doldurma da bu yüzden ucuz. İstisna ATMAZ: okunamayan dosya
``ok=False`` döner.

`import frappe` YOKTUR.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from tradehub_core.media.pipeline.image.dpi import read_dpi

#: Renk uzayı alanının azami uzunluğu (DocType `Data` alanı 140; tanınmayan
#: profil açıklaması uzun olabilir).
MAX_COLORSPACE_LEN: int = 60

ALPHA_MODES: frozenset[str] = frozenset({"RGBA", "LA", "PA", "RGBa", "La"})
GRAY_MODES: frozenset[str] = frozenset({"1", "L", "LA", "La", "I", "I;16", "I;16B", "I;16L", "F"})

#: ICC açıklamasında aranan parça → kanonik ad. Sıra önemli: "display p3"
#: "p3"ten önce, "adobe rgb" "rgb"den önce denenir.
_ICC_NAMES: tuple[tuple[str, str], ...] = (
	("srgb", "sRGB"),
	("iec61966-2", "sRGB"),
	("adobergb", "Adobe RGB"),
	("adobe rgb", "Adobe RGB"),
	("displayp3", "Display P3"),
	("display p3", "Display P3"),
	("dcip3", "DCI-P3"),
	("dci-p3", "DCI-P3"),
	("prophoto", "ProPhoto RGB"),
	("romm", "ProPhoto RGB"),
	("rec2020", "Rec. 2020"),
	("rec. 2020", "Rec. 2020"),
	("bt.2020", "Rec. 2020"),
)


@dataclass(frozen=True)
class ImageFacts:
	ok: bool
	dpi: int = 0
	colorspace: str = ""
	has_alpha: bool = False
	icc: bool = False
	reason: str = ""

	def to_dict(self) -> dict:
		return {
			"dpi": self.dpi,
			"colorspace": self.colorspace,
			"has_alpha": self.has_alpha,
			"icc": self.icc,
		}


def icc_name(icc: bytes | None) -> str:
	"""ICC profilinin kanonik adı; okunamazsa boş dizge."""
	if not icc:
		return ""
	try:
		from PIL import ImageCms

		aciklama = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))) or ""
	except Exception:  # noqa: BLE001 — bozuk profil ölçümü düşürmez, adı boş kalır
		return ""
	yalin = " ".join(aciklama.split())
	arama = yalin.lower()
	sikisik = arama.replace(" ", "").replace("-", "").replace("_", "")
	for parca, ad in _ICC_NAMES:
		if parca in arama or parca.replace(" ", "").replace("-", "") in sikisik:
			return ad
	return yalin[:MAX_COLORSPACE_LEN]


def _mode_colorspace(mode: str) -> str:
	if mode == "CMYK":
		return "CMYK"
	if mode in GRAY_MODES:
		return "Gray"
	if mode == "YCbCr":
		return "YCbCr"
	if mode == "LAB":
		return "Lab"
	return "RGB"


def measure(source: bytes | bytearray | memoryview | str | Path) -> ImageFacts:
	"""Dosya baytlarından ya da yolundan künye çıkar. İstisna ATMAZ."""
	try:
		from PIL import Image

		if isinstance(source, (str, Path)):
			with open(source, "rb") as fh:
				veri = fh.read()
		else:
			veri = bytes(source)
		with Image.open(io.BytesIO(veri)) as im:
			mode = im.mode or ""
			icc = im.info.get("icc_profile")
			alfa = mode in ALPHA_MODES or (mode in ("P", "L", "RGB") and "transparency" in im.info)
		dpi_bilgi = read_dpi(veri)
	except Exception as exc:  # noqa: BLE001 — okunamayan dosya ölçüm sonucudur, hata değil
		return ImageFacts(ok=False, reason=f"{type(exc).__name__}: {exc}"[:200])

	dpi = 0
	if dpi_bilgi.dpi:
		try:
			dpi = max(0, round(float(dpi_bilgi.dpi[0])))
		except (TypeError, ValueError):
			dpi = 0
	# CMYK/Gri kipinde ICC profili de o uzayı anlatır; kip önce gelir ki
	# "U.S. Web Coated (SWOP)" gibi baskı profilleri "CMYK" diye okunsun.
	if mode == "CMYK" or mode in GRAY_MODES:
		renk = _mode_colorspace(mode)
	else:
		renk = icc_name(icc) or _mode_colorspace(mode)
	return ImageFacts(ok=True, dpi=dpi, colorspace=renk, has_alpha=bool(alfa), icc=bool(icc))


__all__ = ["ImageFacts", "icc_name", "measure"]
