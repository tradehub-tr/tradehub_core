"""`ImageEngine`'in sentetik biçimle çalışan sahte uygulaması.

Sentetik biçim (`FIMG1`)
------------------------
    FIMG1|fmt=jpeg|w=3000|h=2000|mode=RGB|alpha=0|dpi=300|anim=0|q=88\n<dolgu>

Tek satır başlık + deterministik dolgu. Pillow GEREKMEZ; sözleşme testi
bağımlılıksız koşar. Amaç piksel doğruluğu değil **sözleşme davranışıdır**:
downscale-only, sabit nokta, alfa koruma, CMYK→sRGB, hata tipleri.

Dolgu uzunluğu (`_dolgu_uzunlugu`) yalnız (genişlik, yükseklik, kalite)'ye
bağlıdır. Bu, `make_master`'ın sabit noktalı olmasını mümkün kılar: bir
master'ı kendi spec'iyle yeniden işlemek aynı baytları verir.
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

from tradehub_core.media.pipeline.contracts.errors import (
	SEBEP_ALPHA_LOST,
	SEBEP_ANIMATED_NOT_ALLOWED,
	DecodeError,
	EncodeError,
	OversizedImage,
	UnsupportedFormat,
	kod_uret,
)
from tradehub_core.media.pipeline.contracts.image import (
	ALPHA_MODES,
	METRIC_SSIM,
	EncodedImage,
	ImageProbe,
	MasterSpec,
	QualityReport,
	RenditionSpec,
)

BASLIK: bytes = b"FIMG1"

# Sahte motorun desteklediği biçimler — `engine.SUPPORTED_FORMATS` ile aynı
# küme, artı çıktı biçimleri (webp zaten var, avif türev merdiveninde geçiyor).
DESTEKLENEN: Tuple[str, ...] = ("JPEG", "PNG", "WEBP", "TIFF", "AVIF")

# Alfa taşıyamayan çıktı biçimleri. FR-146: alfalı master bunlara düşürülemez.
ALFASIZ_BICIMLER: Tuple[str, ...] = ("JPEG", "TIFF-JPEG")

# sRGB dışı mod'lar — FR-145 gereği kabul yolunda çevrilir.
DONUSTURULECEK_MODLAR: Tuple[str, ...] = ("CMYK", "L", "P", "LA", "YCbCr")


def _dolgu_uzunlugu(width: int, height: int, quality: int) -> int:
	"""Deterministik dolgu boyu — yalnız ölçü ve kaliteye bağlı."""
	return max(16, (width * height * max(quality, 50)) // 5000)


def sentetik_gorsel(
	fmt: str = "JPEG",
	width: int = 100,
	height: int = 100,
	*,
	mode: str = "RGB",
	alpha: bool = False,
	dpi: int = 72,
	animated: bool = False,
	quality: int = 80,
) -> bytes:
	"""Test için sentetik görsel baytları üretir."""
	baslik = (
		f"FIMG1|fmt={fmt.upper()}|w={int(width)}|h={int(height)}|mode={mode}"
		f"|alpha={int(bool(alpha))}|dpi={int(dpi)}|anim={int(bool(animated))}|q={int(quality)}\n"
	)
	return baslik.encode("ascii") + bytes(_dolgu_uzunlugu(int(width), int(height), int(quality)))


def _coz(content: bytes) -> Dict[str, str]:
	"""Sentetik baytları başlık sözlüğüne çevir. Çözülemezse `DecodeError`."""
	if not content or not content.startswith(BASLIK):
		raise DecodeError("Sentetik görsel başlığı yok", detay={"bytes": len(content or b"")})
	satir = content.split(b"\n", 1)[0].decode("ascii", "replace")
	alanlar: Dict[str, str] = {}
	for parca in satir.split("|")[1:]:
		anahtar, _, deger = parca.partition("=")
		alanlar[anahtar] = deger
	for zorunlu in ("fmt", "w", "h"):
		if zorunlu not in alanlar:
			raise DecodeError(f"Sentetik başlıkta `{zorunlu}` yok")
	return alanlar


def _olcekle(width: int, height: int, max_long_edge: int) -> Tuple[int, int]:
	"""Yalnız KÜÇÜLTÜR (FR-028). Uzun kenar tavanın altındaysa dokunmaz."""
	uzun = max(width, height)
	if not max_long_edge or uzun <= max_long_edge:
		return width, height
	oran = max_long_edge / float(uzun)
	return max(1, int(width * oran)), max(1, int(height * oran))


def _megapiksel_kis(width: int, height: int, max_mp: float) -> Tuple[int, int]:
	"""Megapiksel tavanına göre ek küçültme."""
	if max_mp <= 0:
		return width, height
	mevcut = (width * height) / 1_000_000.0
	if mevcut <= max_mp:
		return width, height
	oran = (max_mp / mevcut) ** 0.5
	return max(1, int(width * oran)), max(1, int(height * oran))


class FakeImageEngine:
	"""Sentetik biçimle çalışan `ImageEngine` uygulaması."""

	def supported_formats(self) -> Tuple[str, ...]:
		return DESTEKLENEN

	def probe(self, content: bytes, *, max_megapixels: float = 0.0) -> ImageProbe:
		try:
			alanlar = _coz(content)
		except DecodeError:
			# Sözleşme: `probe` açılamayan içerikte HATA ATMAZ.
			return ImageProbe(fmt="", width=0, height=0, readable=False)
		width = int(alanlar.get("w") or 0)
		height = int(alanlar.get("h") or 0)
		mode = alanlar.get("mode") or "RGB"
		alpha = alanlar.get("alpha") == "1" or mode in ALPHA_MODES
		if max_megapixels and (width * height) / 1_000_000.0 > max_megapixels:
			raise OversizedImage(
				"Görsel megapiksel tavanını aşıyor",
				kod=kod_uret("media", "megapixel_bomb"),
				detay={"measured_mp": (width * height) / 1_000_000.0, "max_mp": max_megapixels},
			)
		dpi_deger = float(alanlar.get("dpi") or 72)
		return ImageProbe(
			fmt=(alanlar.get("fmt") or "").upper(),
			width=width,
			height=height,
			mode=mode,
			animated=alanlar.get("anim") == "1",
			readable=True,
			has_alpha=alpha,
			icc_profile=False,
			dpi=(dpi_deger, dpi_deger),
		)

	def make_master(self, content: bytes, spec: MasterSpec) -> EncodedImage:
		alanlar = _coz(content)
		kaynak_fmt = (alanlar.get("fmt") or "").upper()
		if kaynak_fmt not in DESTEKLENEN:
			raise UnsupportedFormat("Desteklenmeyen biçim", detay={"fmt": kaynak_fmt})
		if alanlar.get("anim") == "1":
			raise UnsupportedFormat(
				"Animasyonlu görselden master üretilemez",
				kod=kod_uret("media", SEBEP_ANIMATED_NOT_ALLOWED),
			)

		hedef_fmt = kaynak_fmt if spec.format.lower() == "preserve" else spec.format.upper()
		if hedef_fmt not in DESTEKLENEN:
			raise UnsupportedFormat("Hedef biçim desteklenmiyor", detay={"fmt": hedef_fmt})

		mode = alanlar.get("mode") or "RGB"
		alfa_var = alanlar.get("alpha") == "1" or mode in ALPHA_MODES
		if alfa_var and hedef_fmt in ALFASIZ_BICIMLER:
			raise UnsupportedFormat(
				"Alfa kanalı taşıyan master alfasız biçime düşürülemez",
				kod=kod_uret("media", SEBEP_ALPHA_LOST),
				detay={"fmt": hedef_fmt, "mode": mode},
			)

		notlar = []
		w, h = _olcekle(int(alanlar["w"]), int(alanlar["h"]), spec.max_long_edge)
		w, h = _megapiksel_kis(w, h, spec.max_megapixels)
		if (w, h) != (int(alanlar["w"]), int(alanlar["h"])):
			notlar.append(f"downscale:{alanlar['w']}x{alanlar['h']}->{w}x{h}")

		yeni_mode = mode
		if spec.colorspace == "srgb" and mode in DONUSTURULECEK_MODLAR:
			yeni_mode = "RGBA" if alfa_var else "RGB"
			notlar.append(f"colorspace:{mode}->srgb/{yeni_mode}")

		kalite = spec.quality or int(alanlar.get("q") or 80)
		if spec.dpi_out and int(alanlar.get("dpi") or 72) != spec.dpi_out:
			# DPI metadata'sı DEĞİŞİR, piksel sayısı DEĞİŞMEZ (FR-029).
			notlar.append(f"dpi:{alanlar.get('dpi')}->{spec.dpi_out} (piksel korundu)")
		if spec.strip_metadata.get("gps"):
			notlar.append("gps_stripped")

		cikti = sentetik_gorsel(
			hedef_fmt, w, h, mode=yeni_mode, alpha=alfa_var, dpi=spec.dpi_out, quality=kalite
		)
		if not cikti:
			raise EncodeError("Boş çıktı")
		return EncodedImage(
			content=cikti,
			fmt=hedef_fmt,
			width=w,
			height=h,
			quality=kalite,
			dpi=spec.dpi_out,
			notes=tuple(notlar),
		)

	def make_rendition(self, master: bytes, spec: RenditionSpec) -> EncodedImage:
		alanlar = _coz(master)
		kaynak_w = int(alanlar["w"])
		kaynak_h = int(alanlar["h"])
		notlar = []
		hedef_w = spec.width
		if hedef_w > kaynak_w:
			# Upscale YOK — üretilebilen en büyük ölçü döner (FR-033).
			hedef_w = kaynak_w
			notlar.append("under_spec")
		oran = hedef_w / float(kaynak_w) if kaynak_w else 1.0
		hedef_h = max(1, int(kaynak_h * oran))
		hedef_fmt = spec.format.upper()
		if hedef_fmt not in DESTEKLENEN:
			raise UnsupportedFormat("Türev biçimi desteklenmiyor", detay={"fmt": hedef_fmt})
		alfa_var = alanlar.get("alpha") == "1"
		if alfa_var and hedef_fmt in ALFASIZ_BICIMLER:
			raise UnsupportedFormat(
				"Türevde alfa düşürülemez", kod=kod_uret("media", SEBEP_ALPHA_LOST)
			)
		kalite = spec.quality or int(alanlar.get("q") or 80)
		cikti = sentetik_gorsel(
			hedef_fmt,
			hedef_w,
			hedef_h,
			mode=alanlar.get("mode") or "RGB",
			alpha=alfa_var,
			dpi=int(alanlar.get("dpi") or 72),
			quality=kalite,
		)
		return EncodedImage(
			content=cikti,
			fmt=hedef_fmt,
			width=hedef_w,
			height=hedef_h,
			quality=kalite,
			dpi=int(alanlar.get("dpi") or 72),
			notes=tuple(notlar),
		)

	def make_ladder(self, master: bytes, specs: Sequence[RenditionSpec]) -> Dict[str, EncodedImage]:
		# Kısmi başarı YOK: hepsi bellekte üretilir, biri düşerse hiçbiri dönmez.
		sonuc: Dict[str, EncodedImage] = {}
		for spec in specs:
			sonuc[spec.name] = self.make_rendition(master, spec)
		return sonuc

	def quality_score(
		self, reference: bytes, candidate: bytes, *, metric: str = METRIC_SSIM
	) -> QualityReport:
		try:
			a = _coz(reference)
			b = _coz(candidate)
		except DecodeError:
			return QualityReport(metric=metric, score=0.0, threshold=0.0, measured=False)
		if (a["w"], a["h"]) != (b["w"], b["h"]):
			# Farklı ölçüdeki iki görselin SSIM'i tanımsız — sayı uydurulmaz.
			return QualityReport(metric=metric, score=0.0, threshold=0.0, measured=False)
		fark = abs(int(a.get("q") or 0) - int(b.get("q") or 0)) / 100.0
		return QualityReport(metric=metric, score=max(0.0, 1.0 - fark), threshold=0.0)


__all__ = ["FakeImageEngine", "sentetik_gorsel", "BASLIK", "DESTEKLENEN"]
