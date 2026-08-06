"""Görsel optimizasyon motoru — saf Pillow.

**Bu modülde `import frappe` YOKTUR ve olmamalıdır.** Sebebi:
  - Site kurmadan test edilebilir (DB, bench, request context gerekmez).
  - Pillow yavaş kalırsa yalnız bu dosya pyvips'e çevrilir, üst katman değişmez.
  - `bulk_import/image_matcher.py` de aynı fonksiyonu çağırır — kod iki yerde durmaz.

Format KORUNUR (JPEG→JPEG, PNG→PNG, WEBP→WEBP); uzantı değişmediği için `file_url`
sabit kalır ve `Listing.primary_image` gibi referanslar kırılmaz.

EXIF/ICC notu (GORSEL-OPTIMIZASYON.md §3): `convert("RGB")` EXIF ve ICC profilini
düşürür. Orijinal saklanmadığı senaryoda yan dönmüş fotoğrafın telafisi olmadığı için
`exif_transpose` ile pikseller fiziksel döndürülür ve ICC profili çıktıya taşınır.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

SUPPORTED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP", "TIFF"})

# TIFF bir konteyner: içindeki sıkıştırma değiştirilebilir, uzantı ve dolayısıyla
# `file_url` sabit kalır. Ölçüm (8 gerçek dosya, 101,7 MB):
#   2000px + LZW      → 19,2 MB  (%81)
#   2000px + Deflate  → 13,3 MB  (%87)   ← seçilen: kayıpsız ve alpha'yı korur
#   2000px + JPEG-in-TIFF →  4,0 MB (%96) — kayıplı, eski okuyucularda sorunlu
# Deflate seçildi: 9 MB fazla kazanç için kayıplı gitmeye değmiyor.
TIFF_COMPRESSION: str = "tiff_deflate"


@dataclass(frozen=True)
class Probe:
	"""Görselin optimize edilmeden önce okunan künyesi."""

	fmt: str
	width: int
	height: int
	animated: bool
	readable: bool

	@property
	def max_dim(self) -> int:
		return max(self.width, self.height)


@dataclass(frozen=True)
class OptimizeResult:
	"""Optimizasyon çıktısı. `ok=False` ise `content` boştur, `reason` doludur."""

	ok: bool
	content: bytes = b""
	reason: str = ""
	width: int = 0
	height: int = 0


def probe(content: bytes) -> Probe:
	"""Görseli açmadan künyesini çıkar. Açılamıyorsa `readable=False` döner."""
	try:
		from PIL import Image

		with Image.open(io.BytesIO(content)) as im:
			return Probe(
				fmt=(im.format or "").upper(),
				width=im.width,
				height=im.height,
				animated=bool(getattr(im, "is_animated", False)),
				readable=True,
			)
	except Exception:
		return Probe(fmt="", width=0, height=0, animated=False, readable=False)


def optimize(content: bytes, max_dim: int, quality: int) -> OptimizeResult:
	"""Görseli `max_dim`'e küçült ve yeniden sıkıştır. Yalnız downscale — upscale yok.

	Başarısızlıkta asla yarım çıktı dönmez: `ok=False` ile çağıran orijinali korur.
	"""
	try:
		from PIL import Image, ImageOps
	except Exception:
		return OptimizeResult(ok=False, reason="pillow_unavailable")

	try:
		im = Image.open(io.BytesIO(content))
		fmt = (im.format or "").upper()
		if fmt not in SUPPORTED_FORMATS:
			return OptimizeResult(ok=False, reason="unsupported_format")
		if getattr(im, "is_animated", False):
			return OptimizeResult(ok=False, reason="animated")

		# ICC profilini transpose'tan ÖNCE al — exif_transpose yeni bir Image döndürür.
		icc = im.info.get("icc_profile")
		im = ImageOps.exif_transpose(im)
		im.thumbnail((max_dim, max_dim))  # yalnız küçültür

		buf = io.BytesIO()
		if fmt == "JPEG":
			im.convert("RGB").save(
				buf, "JPEG", quality=quality, optimize=True, progressive=True, icc_profile=icc
			)
		elif fmt == "PNG":
			# PNG kayıpsızdır; quality parametresi geçerli değil.
			im.save(buf, "PNG", optimize=True, icc_profile=icc)
		elif fmt == "TIFF":
			# Kayıpsız: mode'a dokunulmuyor, alpha kanalı korunuyor.
			# `convert("RGB")` burada YAPILMAZ — TIFF'ler CMYK/RGBA olabilir ve
			# dönüştürmek renk yönetimini bozar.
			im.save(buf, "TIFF", compression=TIFF_COMPRESSION, icc_profile=icc)
		else:
			im.save(buf, "WEBP", quality=quality, icc_profile=icc)

		out = buf.getvalue()
		if not out:
			return OptimizeResult(ok=False, reason="empty_output")

		# Çıktı gerçekten açılabiliyor mu — bozuk dosya diske yazılmasın.
		if not _verify(out):
			return OptimizeResult(ok=False, reason="decode_failed")

		return OptimizeResult(ok=True, content=out, width=im.width, height=im.height)
	except Exception as exc:  # noqa: BLE001 — motor hiçbir koşulda çağıranı patlatmamalı
		return OptimizeResult(ok=False, reason=f"error:{type(exc).__name__}")


def _verify(content: bytes) -> bool:
	"""Üretilen baytlar geçerli bir görsel mi."""
	try:
		from PIL import Image

		with Image.open(io.BytesIO(content)) as im:
			im.verify()
		return True
	except Exception:
		return False
