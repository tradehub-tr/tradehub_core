"""T-061 — Normalleştirme: yön, renk uzayı, DPI, piksel tavanı.

Bu modül `tradehub_core/media/pipeline.py`'nin **yerine geçmez**, eksiğini kapatır.
`engine.optimize()` bugün üç şeyi zaten doğru yapıyor ve buradan da aynı şekilde
yapılıyor:

    exif_transpose        pikselleri fiziksel döndürür (engine.py:102)
    icc_profile taşıma    profili transpose'tan ÖNCE alır (engine.py:101)
    yalnız küçültme       `thumbnail` upscale yapmaz (engine.py:103)

Eksik olan ve burada eklenen üçü:

1. **DPI çıktısı** — ÖLÇÜLDÜ (yerel, Pillow 11.3.0, `engine.optimize(2000, 85)`):

       dpi_3000x3000_300dpi.tif   giriş 300 dpi → ÇIKTI (1, 1)
       fmt_tiff_lzw.tif           giriş  (1,1)  → ÇIKTI (1, 1)
       ok_product_1x1_2400.jpg    giriş  None   → ÇIKTI None

   `engine.py` hiçbir yerde `dpi=` yazmıyor. TIFF'te Pillow varsayılan olarak
   çözünürlüğü **(1, 1)** yazıyor: yani 3000×3000 piksellik bir görsel "3000
   inç × 3000 inç" ilan ediliyor. Baskı alan her araç bunu yanlış ölçekler.
   Bu bir HATA'dır ve burada `dpi_out` AÇIKÇA yazılarak kapatılır.

2. **Renk uzayı** — CMYK / paletli / gri girdiler sRGB'ye çevrilir (FR-145).
   ICC profili varsa dönüşüm `ImageCms` ile **profil üzerinden** yapılır;
   yoksa Pillow'un naif `convert()`'i kullanılır ve bu not olarak işaretlenir
   (canlı ölçüm: 38 CMYK dosya var, ICC'li olup olmadığı dosya bazında değişir).

3. **Piksel tavanı** — `max_long_edge` ve `max_megapixels` birlikte uygulanır;
   **upscale hiçbir koşulda yapılmaz** (FR-028). Kaynak zaten tavanın altındaysa
   ölçü DEĞİŞMEZ.

ÖLÇÜLEN SINIR — WEBP ve AVIF DPI TAŞIMAZ
-----------------------------------------
Pillow 11.3.0 ile ölçüldü (64×48 test görseli, `dpi=(72,72)` verilerek):

    JPEG   → geri okunan dpi (72, 72)        ✔
    PNG    → (72.009, 72.009)  (pHYs metre başına saklar, tam sayı yuvarlaması)
    TIFF   → (72.0, 72.0), tag 282/283/296 yazıldı  ✔
    WEBP   → None  — `dpi=` sessizce yok sayıldı
    AVIF   → None  — `dpi=` sessizce yok sayıldı

Slot politikalarının 7'si `master.format = "webp"` ve `dpi_out = 72` diyor.
Bu ikisi bir arada **teknik olarak sağlanamaz**: WebP konteynerinde çözünürlük
alanı yoktur. Sonuç uydurulmuyor: `NormalizeResult.dpi_written = False` ve
`notes` içine `dpi_not_supported_by_format` düşülüyor. Politika tarafındaki
karar (dpi_out'u webp master'da anlamsız ilan etmek ya da master'ı JPEG/PNG
tutmak) bu modülün işi değil, ama ölçüm burada kayıtlı.

`import frappe` YOKTUR.
"""

from __future__ import annotations

import io
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from tradehub_core.media.pipeline.image.probe import (
	DEFAULT_GUARD,
	GuardConfig,
	HeaderProbe,
	ImageRejected,
	probe_header,
)

#: Çıktı DPI'ının **yazılabildiği** biçimler. ÖLÇÜLDÜ (modül başlığı).
DPI_CAPABLE_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "TIFF"})

#: Ekranda gösterilecek görselin standart çözünürlük beyanı. 72, CSS
#: pikselinin tarihsel referansıdır ve `slot-policy.schema.json` `dpi_out`
#: varsayılanıdır — burada tekrar tanımlanmıyor, oradan geliyor.
DEFAULT_DPI_OUT: int = 72

#: Alfa taşıyabilen Pillow modları — `contracts/image.py:ALPHA_MODES` ile aynı.
ALPHA_MODES: frozenset[str] = frozenset({"RGBA", "LA", "PA"})

#: Alfayı taşıyabilen çıktı biçimleri. JPEG YOK: FR-146 gereği alfalı bir
#: master alfasız biçime düşürülemez.
ALPHA_CAPABLE_FORMATS: frozenset[str] = frozenset({"PNG", "WEBP", "AVIF", "TIFF", "GIF"})

#: Kodlayıcı çıktısının RAM'de tutulacak üst sınırı. Daha büyük çıktı
#: `SpooledTemporaryFile` tarafından geçici dosyaya taşınır; sonuç sözleşmesi
#: `bytes` olduğu için yalnız son okuma çıktı boyutu kadar bellek kullanır.
NORMALIZE_SPOOL_MAX_BYTES: int = 8 * 1024 * 1024

#: Pillow, RGBA yeniden örneklemede doğru alfa için tam çözünürlükte ek tampon
#: kurar. Bu eşiğin üstündeki non-JPEG rasterlar libvips sequential ön-decode
#: yoluna alınır; bağımlılık yoksa OOM'a sessizce geri düşülmez.
BOUNDED_PREDECODE_MIN_MEGAPIXELS: float = 20.0
BOUNDED_DECODER_UNAVAILABLE: str = "bounded_decoder_unavailable"
BOUNDED_PREDECODE_FAILED: str = "bounded_predecode_failed"
BOUNDED_TARGET_NOT_REDUCED: str = "bounded_target_not_reduced"
BOUNDED_COLORSPACE_UNSUPPORTED: str = "bounded_colorspace_unsupported"

#: INV-04 varsayılanı. GPS güvenlik kuralı ayrıca zorunludur; çağıran
#: ``gps=False`` verse bile yayın çıktısına koordinat taşınmaz.
DEFAULT_STRIP_METADATA: dict[str, bool] = {
	"exif": True,
	"gps": True,
	"xmp": True,
	"icc": False,
}

#: EXIF etiket numaraları — yeniden yazmak yerine sabit.
_EXIF_ORIENTATION = 0x0112
_EXIF_GPS_IFD = 0x8825


#: `engine.TIFF_COMPRESSION` ile AYNI seçim; oradan içe aktarılır ki iki
#: dosyada iki ayrı sıkıştırma kararı olmasın.
def _tiff_compression() -> str:
	try:
		from tradehub_core.media.pipeline import TIFF_COMPRESSION

		return TIFF_COMPRESSION
	except Exception:
		# tradehub_core yoksa (paket tek başına kullanılıyorsa) aynı değer.
		return "tiff_deflate"


@dataclass(frozen=True)
class NormalizeSpec:
	"""Normalleştirme parametreleri — slot politikasının `master` bloğu.

	Alan adları `tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json` `master`
	özellikleriyle aynı; `from_policy()` doğrudan JSON'dan kurar.
	"""

	max_long_edge: int = 0  # 0 = ölçü sınırı yok
	max_megapixels: float = 0.0  # 0 = MP sınırı yok
	dpi_out: int = DEFAULT_DPI_OUT
	colorspace: str = "srgb"  # "srgb" | "preserve"
	orientation: str = "apply_exif"  # "apply_exif" | "preserve"
	fmt: str = ""  # "" ya da "preserve" = kaynağı koru
	quality: int = 82
	lossless: bool = False
	strip_metadata: dict = field(default_factory=lambda: dict(DEFAULT_STRIP_METADATA))
	#: FR-028. `True` verilmesi sözleşme ihlalidir — `__post_init__` reddeder.
	allow_upscale: bool = False
	#: Kaynak bu eşiğin üstündeyse tavan hesabı uzun kenarı bunun altına
	#: indirmez. Kaynak küçükse FR-028 gereği yine büyütülmez. Eski konumsal
	#: kurucuları bozmamak için yeni alan sözleşmenin sonundadır.
	min_long_edge: int = 0  # 0 = alt sınır yok

	def __post_init__(self) -> None:
		if self.allow_upscale:
			raise ValueError("FR-028: normalleştirmede upscale yasak")
		if self.max_long_edge < 0 or self.min_long_edge < 0 or self.max_megapixels < 0:
			raise ValueError("Piksel sınırları negatif olamaz")
		if self.max_long_edge and self.min_long_edge > self.max_long_edge:
			raise ValueError("min_long_edge, max_long_edge değerini aşamaz")
		if self.colorspace not in ("srgb", "preserve"):
			raise ValueError(f"Bilinmeyen colorspace: {self.colorspace!r}")
		if self.orientation not in ("apply_exif", "preserve"):
			raise ValueError(f"Bilinmeyen orientation: {self.orientation!r}")

	@property
	def target_format(self) -> str:
		f = (self.fmt or "").strip().upper()
		return "" if f in ("", "PRESERVE") else ("JPEG" if f == "JPG" else f)

	@classmethod
	def from_policy(cls, master: dict, **kwargs) -> NormalizeSpec:
		"""Slot politikasının `master` bloğundan kurar."""
		return cls(
			max_long_edge=int(master.get("max_long_edge") or 0),
			min_long_edge=int(master.get("min_long_edge") or master.get("min_pixel_edge") or 0),
			max_megapixels=float(master.get("max_megapixels") or 0.0),
			dpi_out=int(master.get("dpi_out") or DEFAULT_DPI_OUT),
			colorspace=str(master.get("colorspace") or "srgb"),
			orientation=str(master.get("orientation") or "apply_exif"),
			fmt=str(master.get("format") or ""),
			strip_metadata={**DEFAULT_STRIP_METADATA, **dict(master.get("strip_metadata") or {})},
			**kwargs,
		)

	@classmethod
	def from_master_spec(cls, spec, **kwargs) -> NormalizeSpec:
		"""`contracts.image.MasterSpec` → `NormalizeSpec` köprüsü."""
		return cls(
			max_long_edge=int(spec.max_long_edge or 0),
			min_long_edge=int(getattr(spec, "min_long_edge", 0) or getattr(spec, "min_pixel_edge", 0) or 0),
			max_megapixels=float(spec.max_megapixels or 0.0),
			dpi_out=int(spec.dpi_out or DEFAULT_DPI_OUT),
			colorspace=str(spec.colorspace or "srgb"),
			orientation=str(spec.orientation or "apply_exif"),
			fmt=str(spec.format or ""),
			quality=int(spec.quality or 82),
			lossless=bool(spec.lossless),
			strip_metadata={**DEFAULT_STRIP_METADATA, **dict(spec.strip_metadata or {})},
			**kwargs,
		)


@dataclass(frozen=True)
class NormalizeResult:
	"""Normalleştirme çıktısı. `ok=False` ise `content` boştur ve `reason` doludur.

	`engine.OptimizeResult` ile aynı sözleşme: başarısızlıkta ASLA yarım çıktı
	dönmez, çağıran orijinali korur.
	"""

	ok: bool
	content: bytes = b""
	fmt: str = ""
	width: int = 0
	height: int = 0
	mode: str = ""
	dpi: tuple[float, float] | None = None
	dpi_written: bool = False
	icc_embedded: bool = False
	resized: bool = False
	reason: str = ""
	notes: tuple[str, ...] = ()
	probe: HeaderProbe | None = None
	#: Yeni kanıt alanları eski konumsal kurucuları bozmamak için sondadır.
	colorspace: str = ""
	icc_profile: str = ""

	@property
	def size_bytes(self) -> int:
		return len(self.content)

	@property
	def has_alpha(self) -> bool:
		return self.mode in ALPHA_MODES

	@property
	def applied_steps(self) -> tuple[str, ...]:
		"""Kabul sözleşmesindeki ad; mevcut ``notes`` alanının kayıpsız takma adı."""
		return self.notes

	def to_dict(self) -> dict:
		return {
			"ok": self.ok,
			"fmt": self.fmt,
			"width": self.width,
			"height": self.height,
			"mode": self.mode,
			"has_alpha": self.has_alpha,
			"colorspace": self.colorspace,
			"dpi": list(self.dpi) if self.dpi else None,
			"dpi_written": self.dpi_written,
			"icc_embedded": self.icc_embedded,
			"icc_profile": self.icc_profile,
			"resized": self.resized,
			"reason": self.reason,
			"notes": list(self.notes),
			"applied_steps": list(self.applied_steps),
			"size_bytes": self.size_bytes,
		}


# ── Ölçü hesabı ─────────────────────────────────────────────────────────


def target_size(width: int, height: int, spec: NormalizeSpec) -> tuple[int, int]:
	"""Tavanlara uyan hedef ölçü. **Asla büyütmez** (FR-028).

	İki tavan birlikte uygulanır ve KÜÇÜK olan kazanır:
	  * `max_long_edge` — uzun kenar sınırı (CSS kutusundan türetilmiş)
	  * `max_megapixels` — toplam piksel sınırı (bellek ve encode maliyeti)
	`min_long_edge`, kaynak yeterince büyükse, sonucun kabul alt sınırının
	altına inmesini engeller; küçük kaynak yine büyütülmez.

	Oran korunur; yuvarlama aşağı yapılır ve kenar en az 1 piksel kalır.
	"""
	if width <= 0 or height <= 0:
		return (width, height)

	olcek = 1.0
	if spec.max_long_edge:
		uzun = max(width, height)
		if uzun > spec.max_long_edge:
			olcek = min(olcek, spec.max_long_edge / uzun)
	if spec.max_megapixels:
		tavan = spec.max_megapixels * 1_000_000.0
		alan = float(width * height)
		if alan > tavan:
			# Alan kenarın karesiyle büyür → kenar ölçeği karekök.
			olcek = min(olcek, (tavan / alan) ** 0.5)

	uzun = max(width, height)
	if spec.min_long_edge and uzun >= spec.min_long_edge:
		olcek = max(olcek, spec.min_long_edge / uzun)

	if olcek >= 1.0:
		return (width, height)  # upscale YOK: kaynak zaten tavanın altında
	return (max(1, int(width * olcek)), max(1, int(height * olcek)))


# ── Renk farkı ölçümü ──────────────────────────────────────────────────


def delta_e_2000(
	lab_a: tuple[float, float, float],
	lab_b: tuple[float, float, float],
) -> float:
	"""İki CIE L*a*b* rengi arasındaki CIEDE2000 (ΔE00) farkı.

	Saf fonksiyondur; ICC dönüşüm testleri aynı piksel örneklerini Lab'a
	taşıdıktan sonra bu metriği kullanır. Uygulama Sharma vd. referans
	çiftleriyle test edilir; böylece ``RGB oldu`` gibi yalnız kip kontrolüne
	dayanan yalancı renk-uyumu kanıtı üretilmez.
	"""
	l1, a1, b1 = (float(v) for v in lab_a)
	l2, a2, b2 = (float(v) for v in lab_b)
	c1 = math.hypot(a1, b1)
	c2 = math.hypot(a2, b2)
	c_ortalama = (c1 + c2) / 2.0
	c7 = c_ortalama**7
	g = 0.5 * (1.0 - math.sqrt(c7 / (c7 + 25.0**7)))

	a1p = (1.0 + g) * a1
	a2p = (1.0 + g) * a2
	c1p = math.hypot(a1p, b1)
	c2p = math.hypot(a2p, b2)

	def _aci(a: float, b: float) -> float:
		deger = math.degrees(math.atan2(b, a))
		return deger + 360.0 if deger < 0.0 else deger

	h1p = _aci(a1p, b1)
	h2p = _aci(a2p, b2)
	delta_l = l2 - l1
	delta_c = c2p - c1p
	if c1p * c2p == 0.0:
		delta_h_acisi = 0.0
	elif abs(h2p - h1p) <= 180.0:
		delta_h_acisi = h2p - h1p
	elif h2p <= h1p:
		delta_h_acisi = h2p - h1p + 360.0
	else:
		delta_h_acisi = h2p - h1p - 360.0
	delta_h = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(delta_h_acisi / 2.0))

	l_ortalama = (l1 + l2) / 2.0
	c_ortalama_p = (c1p + c2p) / 2.0
	if c1p * c2p == 0.0:
		h_ortalama = h1p + h2p
	elif abs(h1p - h2p) <= 180.0:
		h_ortalama = (h1p + h2p) / 2.0
	elif h1p + h2p < 360.0:
		h_ortalama = (h1p + h2p + 360.0) / 2.0
	else:
		h_ortalama = (h1p + h2p - 360.0) / 2.0

	t = (
		1.0
		- 0.17 * math.cos(math.radians(h_ortalama - 30.0))
		+ 0.24 * math.cos(math.radians(2.0 * h_ortalama))
		+ 0.32 * math.cos(math.radians(3.0 * h_ortalama + 6.0))
		- 0.20 * math.cos(math.radians(4.0 * h_ortalama - 63.0))
	)
	delta_theta = 30.0 * math.exp(-(((h_ortalama - 275.0) / 25.0) ** 2))
	rc = 2.0 * math.sqrt(c_ortalama_p**7 / (c_ortalama_p**7 + 25.0**7))
	sl = 1.0 + (0.015 * (l_ortalama - 50.0) ** 2) / math.sqrt(20.0 + (l_ortalama - 50.0) ** 2)
	sc = 1.0 + 0.045 * c_ortalama_p
	sh = 1.0 + 0.015 * c_ortalama_p * t
	rt = -math.sin(math.radians(2.0 * delta_theta)) * rc

	l_terim = delta_l / sl
	c_terim = delta_c / sc
	h_terim = delta_h / sh
	return math.sqrt(l_terim**2 + c_terim**2 + h_terim**2 + rt * c_terim * h_terim)


# ── Renk uzayı ──────────────────────────────────────────────────────────


def _profile_is_srgb(icc: bytes | None) -> bool | None:
	"""Gömülü profil zaten sRGB mi. `None` = ölçülemedi (ImageCms yok/bozuk).

	Neden sorulduğu: sRGB→sRGB dönüşümü lcms'te birebir aynı pikseli vermez
	(yuvarlama). `make_master` sabit noktalı olmak zorunda olduğu için
	(contracts/image.py "İDEMPOTENSİ") gereksiz dönüşüm ATLANIR.
	"""
	if not icc:
		return None
	try:
		from PIL import ImageCms

		prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
		aciklama = (ImageCms.getProfileDescription(prof) or "").lower()
		return "srgb" in aciklama.replace(" ", "").replace("-", "")
	except Exception:
		return None


def _profile_description(icc: bytes | None) -> str:
	"""ICC açıklamasını tek satırlık kanıt alanına çevir."""
	if not icc:
		return ""
	try:
		from PIL import ImageCms

		prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
		return " ".join((ImageCms.getProfileDescription(prof) or "").split())
	except Exception:
		return "unreadable"


def to_srgb(im, icc: bytes | None, notlar: list[str]):
	"""Görseli sRGB'ye taşı. Alfa KORUNUR (FR-146).

	    Üç yol var ve hangisinin kullanıldığı `notlar`'a yazılır:

	  icc_transform   gömülü profil var → ImageCms ile profil dönüşümü (doğru yol)
	  naive_convert   profil yok → Pillow'un sabit matrisi (CMYK'de yaklaşık)
	  no_change       zaten sRGB RGB/RGBA

	CMYK için profilsiz dönüşüm bir YAKLAŞIMDIR: Pillow'un `convert("RGB")`'si
	baskı profili bilmediği için doygunluğu kaydırır. Canlı ölçümde 38 CMYK
	dosya var; hangisinin ICC taşıdığı dosya bazında değişir, o yüzden iki yol
	da gerekli.
	"""
	mode = im.mode
	alfali = mode in ALPHA_MODES or (mode == "P" and "transparency" in im.info)

	if icc:
		srgb_mi = _profile_is_srgb(icc)
		if srgb_mi is False:
			try:
				from PIL import ImageCms

				kaynak = ImageCms.ImageCmsProfile(io.BytesIO(icc))
				hedef = ImageCms.createProfile("sRGB")
				cikis = "RGBA" if alfali else "RGB"
				im = ImageCms.profileToProfile(im, kaynak, hedef, outputMode=cikis)
				notlar.append("colorspace:icc_transform")
				return im, True
			except Exception as exc:  # noqa: BLE001 — dönüşüm başarısızsa naif yola düş
				notlar.append(f"colorspace:icc_transform_failed:{type(exc).__name__}")
		elif srgb_mi is True:
			notlar.append("colorspace:already_srgb_profile")
		else:
			notlar.append("colorspace:profile_unreadable")

	if mode in ("RGB", "RGBA"):
		return im, False
	if mode == "P":
		hedef = "RGBA" if "transparency" in im.info else "RGB"
		notlar.append(f"colorspace:palette_to_{hedef.lower()}")
		return im.convert(hedef), False
	if mode == "CMYK":
		notlar.append("colorspace:cmyk_naive_convert")
		return im.convert("RGB"), False
	if mode in ("L", "I;16", "I", "F"):
		notlar.append(f"colorspace:{mode.lower()}_to_rgb")
		return im.convert("RGB"), False
	if mode == "LA":
		notlar.append("colorspace:la_to_rgba")
		return im.convert("RGBA"), False
	notlar.append(f"colorspace:naive_convert_from_{mode.lower()}")
	return im.convert("RGBA" if alfali else "RGB"), False


# ── EXIF ────────────────────────────────────────────────────────────────


def _exif_for_output(im, strip: dict, transpose_uygulandi: bool) -> bytes | None:
	"""Çıktıya yazılacak EXIF bloğu. `None` = EXIF hiç yazılmayacak.

	İKİ KURAL, İKİSİ DE ZORUNLU:

	1. GPS — FR-039. GPS IFD'si her koşulda silinir; satıcının evinin
	   koordinatı ürün fotoğrafında taşınmaz. `strip["exif"]` veya eski bir
	   politikada `strip["gps"]` False olsa bile GPS gider.
	ÖLÇÜLDÜ (fixture `exif_gps.jpg`, strip={"exif": False, "gps": False}): GPS
	IFD'si ve üst seviye işaretçi etiketi (34853) birlikte silinir. Pillow,
	boşaltılmış alt IFD'yi özel `_ifds` önbelleğinde tutarsa `tobytes()`
	işaretçiyi yeniden üretir; bu nedenle aynı anahtar önbellekten de kaldırılır.

	2. Orientation etiketi transpose uygulandıysa SİLİNİR. Silinmezse görüntü
	   iki kez döner: pikseller zaten döndürüldü, etiket kalırsa görüntüleyici
	   bir kez daha döndürür. `engine.py` EXIF'i hiç yazmadığı için bu hatayı
	   bugün yaşamıyor; burada EXIF korunabildiği için kural açıkça gerekli.
	"""
	if strip.get("exif", True):
		return None
	try:
		exif = im.getexif()
	except Exception:
		return None
	if not exif:
		return None
	# GPS ayarla geri açılamaz: koordinat kişisel veridir ve INV-04 zorunludur.
	# SIRA ÖNEMLİ: GPS IFD'si ayrı bir alt sözlükte tutuluyor ve üst seviyedeki
	# işaretçi etiketi ancak `get_ifd` çağrıldıktan sonra sözlükte görünüyor.
	try:
		exif.get_ifd(_EXIF_GPS_IFD).clear()
	except Exception:
		pass
	exif.pop(_EXIF_GPS_IFD, None)
	# Pillow 11.x: boş alt IFD `_ifds`te kalırsa `tobytes()` 34853 işaretçisini
	# yeniden ekler. İç API yoksa güvenli biçimde atlanır.
	if isinstance(getattr(exif, "_ifds", None), dict):
		exif._ifds.pop(_EXIF_GPS_IFD, None)
	if transpose_uygulandi:
		exif.pop(_EXIF_ORIENTATION, None)
	try:
		return exif.tobytes()
	except Exception:
		return None


# ── Kodlama ─────────────────────────────────────────────────────────────


def _save_kwargs(fmt: str, spec: NormalizeSpec, icc: bytes | None, exif: bytes | None) -> dict:
	"""Biçime göre kaydetme parametreleri + DPI.

	DPI her DPI-yetenekli biçime AÇIKÇA yazılır. Yazılmadığında ne olduğu
	ölçüldü: TIFF (1, 1) yazıyor (modül başlığı). "Yazmamak" nötr değil.
	"""
	kw: dict = {}
	if icc:
		kw["icc_profile"] = icc
	if exif:
		kw["exif"] = exif

	if fmt in DPI_CAPABLE_FORMATS and spec.dpi_out:
		kw["dpi"] = (spec.dpi_out, spec.dpi_out)

	if fmt == "JPEG":
		kw.update(quality=spec.quality, optimize=True, progressive=True)
	elif fmt == "PNG":
		kw.update(optimize=True)  # PNG kayıpsız; quality geçersiz
	elif fmt == "TIFF":
		kw.update(compression=_tiff_compression())
	elif fmt == "WEBP":
		kw.update(quality=spec.quality, method=4, lossless=spec.lossless)
	elif fmt == "AVIF":
		kw.update(quality=spec.quality)
	return kw


def _encode(im, fmt: str, kw: dict) -> bytes:
	# `BytesIO` çıktı büyüdükçe aynı süreçte birden fazla büyük tampon
	# ayırabilir. Spool ilk 8 MiB'ı RAM'de tutar, sonrası diske akar; dönüş
	# sözleşmesi bytes olduğu için son okumada yalnız gerçek çıktı kadar ek
	# bellek gerekir. Bu, 30 MB kaynak ölçümündeki bounded-output ayağıdır.
	with tempfile.SpooledTemporaryFile(max_size=NORMALIZE_SPOOL_MAX_BYTES, mode="w+b") as buf:
		im.save(buf, fmt, **kw)
		buf.seek(0)
		return buf.read()


def _display_size(
	width: int,
	height: int,
	orientation: int | None,
	apply_orientation: bool,
) -> tuple[int, int]:
	"""EXIF yönü uygulandıktan sonra görülecek ölçü; piksel decode etmez."""
	if apply_orientation and orientation in (5, 6, 7, 8):
		return height, width
	return width, height


def _jpeg_decoder_draft(
	im,
	*,
	source_format: str,
	orientation: int | None,
	apply_orientation: bool,
	target_display: tuple[int, int],
	notes: list[str],
) -> None:
	"""JPEG'i hedefe en yakın DCT ölçeğinde çözdürerek peak RAM'i sınırla.

	Pillow'un ``resize`` çağrısı tek başına bounded değildir: önce bütün JPEG'i
	RGB tampona açar. ``draft`` libjpeg'e 1/2, 1/4 veya 1/8 çözüm ölçeğini decode
	aşamasında seçtirir; böylece 72 MP fixture 2400 px hedef için tam 72 MP
	tamponu hiç üretmez. Kip aynı istenir, dolayısıyla CMYK/ICC dönüşümü daha
	sonra hâlâ kaynak profili üzerinden yapılır.
	"""
	if source_format != "JPEG":
		return
	gorunen = _display_size(im.width, im.height, orientation, apply_orientation)
	if target_display == gorunen:
		return
	# Decoder saklanan eksenlerle çalışır; EXIF 5–8 bu eksenleri takas eder.
	decoder_target = target_display
	if apply_orientation and orientation in (5, 6, 7, 8):
		decoder_target = (target_display[1], target_display[0])
	once = im.size
	try:
		im.draft(im.mode, decoder_target)
	except Exception as exc:  # noqa: BLE001 — draft yalnız optimizasyon; doğru sonuç devam eder
		notes.append(f"io:jpeg_decoder_draft_failed:{type(exc).__name__}")
		return
	if im.size != once:
		notes.append(f"io:jpeg_decoder_draft:{once[0]}x{once[1]}->{im.width}x{im.height}")


def _resize_with_alpha(im, target: tuple[int, int], image_module, notes: list[str]):
	"""Alfalı yeniden örneklemede premultiply → resize → unpremultiply sırası.

	Tam saydam piksellerin görünmez RGB değerleri düz kenara sızmamalıdır.
	Pillow ``RGBa`` kipini premultiplied alpha olarak tanımlar; ara tamponlar
	hemen kapatılır ve çağıran eski kaynak tamponunu ayrıca bırakır.
	"""
	if im.mode != "RGBA":
		return im.resize(target, image_module.LANCZOS, reducing_gap=2.0)
	premultiplied = im.convert("RGBa")
	resized = None
	try:
		resized = premultiplied.resize(target, image_module.LANCZOS, reducing_gap=2.0)
		result = resized.convert("RGBA")
		notes.append("alpha:premultiply_resize_unpremultiply")
		return result
	finally:
		premultiplied.close()
		if resized is not None:
			resized.close()


@dataclass(frozen=True)
class _BoundedPredecodeResult:
	"""libvips ara çıktısı; ``path=None`` ise ``reason`` makine kodudur."""

	path: Path | None = None
	reason: str = ""
	notes: tuple[str, ...] = ()
	resized: bool = False
	orientation_applied: bool = False


def _load_pyvips():
	"""libvips Python köprüsünü düşük önbellek bütçesiyle yükle.

	``pyvips`` paketinin kurulmuş olması tek başına yeterli değildir; paylaşılan
	``libvips`` kütüphanesi yoksa import ``OSError`` atar. İki durum da çağıran
	için aynı, açık ``bounded_decoder_unavailable`` sonucudur.
	"""
	os.environ.setdefault("VIPS_CONCURRENCY", "1")
	try:
		import pyvips
	except (ImportError, OSError):
		return None

	# Global işlem önbelleği uzun ömürlü worker'da önceki rasterları tutmasın.
	for ad, deger in (
		("cache_set_max_mem", 64 * 1024 * 1024),
		("cache_set_max", 32),
		("cache_set_max_files", 8),
	):
		ayar = getattr(pyvips, ad, None)
		if ayar is not None:
			try:
				ayar(deger)
			except Exception:
				# Eski pyvips sürümündeki cache ayarı decoder yeteneği değildir.
				pass
	return pyvips


def _requires_bounded_predecode(probe: HeaderProbe | None) -> bool:
	"""Tam-frame Pillow decode'u yasak olan büyük non-JPEG kaynağı seç."""
	return bool(
		probe
		and probe.fmt.upper() != "JPEG"
		and probe.megapixels > BOUNDED_PREDECODE_MIN_MEGAPIXELS
	)


def _temporary_source(src: bytes | bytearray, fmt: str) -> Path:
	"""Bellekteki kodlu girdiyi libvips'in sequential dosya yoluna taşı."""
	uzantilar = {
		"PNG": ".png",
		"TIFF": ".tif",
		"WEBP": ".webp",
		"GIF": ".gif",
		"BMP": ".bmp",
		"AVIF": ".avif",
	}
	with tempfile.NamedTemporaryFile(
		prefix="tradehub-normalize-source-",
		suffix=uzantilar.get(fmt.upper(), ".image"),
		delete=False,
	) as gecici:
		gecici.write(src)
		return Path(gecici.name)


def _bounded_predecode(
	src: bytes | bytearray | str | Path,
	probe: HeaderProbe,
	spec: NormalizeSpec,
	target_display: tuple[int, int],
) -> _BoundedPredecodeResult:
	"""Büyük non-JPEG'i sequential okuyup küçük, güvenli PNG ara dosyasına yaz.

	Pillow bu fonksiyon başarıyla bittikten sonra yalnız ``target_display``
	ölçüsündeki ara dosyayı görür. Böylece 72 MP RGBA kaynağın yanında ikinci
	bir 291 MB RGBA/RGB tamponu kurulmaz. ICC dönüşümü LittleCMS üzerinden
	perceptual intent ile, alfa resize'ı premultiply sırasıyla yapılır.
	"""
	notlar: list[str] = []
	pyvips = _load_pyvips()
	if pyvips is None:
		return _BoundedPredecodeResult(
			reason=BOUNDED_DECODER_UNAVAILABLE,
			notes=("io:pyvips_or_libvips_unavailable",),
		)
	if spec.colorspace != "srgb":
		return _BoundedPredecodeResult(
			reason=BOUNDED_COLORSPACE_UNSUPPORTED,
			notes=("colorspace:bounded_preserve_unsupported",),
		)

	kaynak_gorunen = (
		probe.display_size
		if spec.orientation == "apply_exif"
		else (probe.width, probe.height)
	)
	if target_display == kaynak_gorunen:
		# Tam ölçülü ara PNG daha sonra Pillow'da yeniden tam raster olur.
		return _BoundedPredecodeResult(
			reason=BOUNDED_TARGET_NOT_REDUCED,
			notes=("io:bounded_target_must_reduce",),
		)

	kaynak_gecici: Path | None = None
	cikti_gecici: Path | None = None
	try:
		if isinstance(src, (bytes, bytearray)):
			kaynak_gecici = _temporary_source(src, probe.fmt)
			kaynak_yolu = kaynak_gecici
		else:
			kaynak_yolu = Path(src)

		with tempfile.NamedTemporaryFile(
			prefix="tradehub-normalize-vips-",
			suffix=".png",
			delete=False,
		) as gecici:
			cikti_gecici = Path(gecici.name)

		im = pyvips.Image.new_from_file(str(kaynak_yolu), access="sequential")
		yon_uygulandi = spec.orientation == "apply_exif" and probe.exif_orientation not in (None, 1)
		if spec.orientation == "apply_exif":
			im = im.autorot()
			if yon_uygulandi:
				notlar.append("orientation:exif_applied")

		profil_var = bool(im.get_typeof("icc-profile-data"))
		if profil_var:
			# Açık intent, libvips'in relative varsayılanına düşüp ΔE kaydırmasını
			# önler; embedded=True kaynak profilin gerçekten kullanıldığını söyler.
			im = im.icc_transform("srgb", embedded=True, intent="perceptual")
			notlar.append("colorspace:icc_transform")
		elif str(im.interpretation).lower() not in ("srgb", "rgb"):
			kaynak_yorum = str(im.interpretation).lower()
			im = im.colourspace("srgb")
			notlar.append(f"colorspace:{str(probe.mode or kaynak_yorum).lower()}_naive_convert")

		alfa_var = bool(probe.has_alpha)
		if alfa_var:
			im = im.premultiply()
		yatay = target_display[0] / im.width
		dikey = target_display[1] / im.height
		im = im.resize(yatay, vscale=dikey, kernel="lanczos3")
		if alfa_var:
			im = im.unpremultiply().cast("uchar")
			notlar.append("alpha:premultiply_resize_unpremultiply")
		elif im.format != "uchar":
			im = im.cast("uchar")

		if (im.width, im.height) != target_display:
			raise RuntimeError(
				f"vips target mismatch: {im.width}x{im.height} != {target_display[0]}x{target_display[1]}"
			)
		# ICC/EXIF ara dosyada kalsın; nihai metadata politikasını ortak aşama uygular.
		im.pngsave(str(cikti_gecici), compression=1, strip=False)
		notlar.extend(
			(
				"io:vips_sequential_predecode",
				f"resize:{target_display[0]}x{target_display[1]}",
			)
		)
		return _BoundedPredecodeResult(
			path=cikti_gecici,
			notes=tuple(notlar),
			resized=True,
			orientation_applied=yon_uygulandi,
		)
	except Exception as exc:  # noqa: BLE001 — Pillow OOM yoluna ASLA geri düşme
		if cikti_gecici is not None:
			cikti_gecici.unlink(missing_ok=True)
		return _BoundedPredecodeResult(
			reason=BOUNDED_PREDECODE_FAILED,
			notes=(*notlar, f"io:vips_predecode_failed:{type(exc).__name__}"),
		)
	finally:
		if kaynak_gecici is not None:
			kaynak_gecici.unlink(missing_ok=True)


# ── Ana giriş ───────────────────────────────────────────────────────────


def normalize(
	src: bytes | bytearray | str | Path,
	spec: NormalizeSpec,
	*,
	filename: str = "",
	guard: GuardConfig = DEFAULT_GUARD,
	skip_guard: bool = False,
) -> NormalizeResult:
	"""Görseli normalleştir ve kodla. İstisna ATMAZ — `ok=False` döner.

	Sıra ANLAMLIDIR:

	    1. kapı (T-060)        bomba/kesik/tehlikeli içerik buradan geçemez
	    2. ICC'yi al           `exif_transpose` yeni bir Image döndürür, profil
	                           o nesnede taşınmaz (engine.py:101 ile aynı tuzak)
	    3. EXIF transpose      pikselleri fiziksel döndür
	    4. renk uzayı          sRGB'ye taşı (alfa korunarak)
	    5. ölçü                yalnız küçült
	    6. metadata + DPI      GPS her hâlükârda gider, DPI açıkça yazılır
	    7. kodla + doğrula     çıktı geri açılamıyorsa BAŞARISIZ sayılır

	4. adımın 5.'den ÖNCE olması bilinçli: paletli (P) bir görseli önce RGB'ye
	çevirmeden küçültmek, en yakın komşu kuantizasyonu yüzünden bantlanmaya yol
	açar (fixture `mode_palette_p.png` bunun regresyon testidir).
	"""
	notlar: list[str] = []

	p: HeaderProbe | None = None
	if not skip_guard:
		try:
			p = _assert(src, filename, guard)
		except ImageRejected as ret:
			return NormalizeResult(
				ok=False, reason=ret.probe.codes[0], probe=ret.probe, notes=("gate_reject",)
			)
	else:
		# Kapı kararı atlanabilir; header ölçümü bellek yolu için yine gereklidir.
		# Rejection'lar bilinçli olarak uygulanmaz, fakat büyük non-JPEG'nin tam
		# Pillow decode'una sessizce düşmesine de izin verilmez.
		try:
			p = probe_header(src, filename=filename, config=guard)
		except Exception:
			p = None

	try:
		from PIL import Image, ImageOps
	except Exception:
		return NormalizeResult(ok=False, reason="pillow_unavailable")

	im = None
	bounded_path: Path | None = None
	bounded: _BoundedPredecodeResult | None = None
	try:
		pillow_src: bytes | bytearray | str | Path = src
		if _requires_bounded_predecode(p):
			assert p is not None  # ``_requires_bounded_predecode`` bunu garanti eder.
			notlar.append("io:bounded_decode_required")
			kaynak_gorunen = (
				p.display_size
				if spec.orientation == "apply_exif"
				else (p.width, p.height)
			)
			hedef = target_size(*kaynak_gorunen, spec)
			bounded = _bounded_predecode(src, p, spec, hedef)
			notlar.extend(bounded.notes)
			if bounded.reason or bounded.path is None:
				return NormalizeResult(
					ok=False,
					reason=bounded.reason or BOUNDED_PREDECODE_FAILED,
					probe=p,
					notes=tuple(notlar),
				)
			bounded_path = bounded.path
			pillow_src = bounded_path

		# Yol girdisi baştan sona `read_bytes()` ile çoğaltılmaz. Pillow dosya
		# tanıtıcısından ihtiyaç oldukça okur; kapı da yalnız baş+kuyruk okur.
		# bytes girdisi zaten çağıranın belleğindedir ve BytesIO ile sarılır.
		im = _open_source(pillow_src, Image)
		notlar.append("io:path_streamed" if not isinstance(src, (bytes, bytearray)) else "io:bytes_source")
		kaynak_fmt = ((p.fmt if bounded is not None and p else "") or im.format or "").upper()

		# Hareketli girdi: master TEK KARE'dir ve bu SESSİZCE yapılmaz.
		# `engine.optimize` hareketli dosyayı reddediyor (engine.py:97); burada
		# kapı zaten reddetmiş olabilir (`allow_animated=False`). Kapı bilerek
		# açıldıysa (ör. animasyonun poster karesi isteniyorsa) kayıp not edilir.
		if (p and p.animated) or bool(getattr(im, "is_animated", False)):
			kare_sayisi = p.frame_count if p and p.animated else getattr(im, "n_frames", 1)
			notlar.append(f"animation:flattened_first_frame_of_{kare_sayisi}")

		# 2 — ICC'yi transpose'tan ÖNCE al (engine.py:101 ile aynı gerekçe).
		icc = im.info.get("icc_profile")

		# Header ölçüsü ve EXIF etiketiyle nihai hedef decode'dan ÖNCE bellidir.
		# JPEG böylece tam piksel tamponu üretmeden DCT ölçeğinde açılabilir.
		if bounded is not None and p is not None:
			kaynak_yon = None
			kaynak_gorunen = (
				p.display_size
				if spec.orientation == "apply_exif"
				else (p.width, p.height)
			)
			hedef = target_size(*kaynak_gorunen, spec)
			kucultuldu = bounded.resized
		else:
			try:
				kaynak_yon = im.getexif().get(_EXIF_ORIENTATION)
			except Exception:
				kaynak_yon = None
			kaynak_gorunen = _display_size(
				im.width,
				im.height,
				kaynak_yon,
				spec.orientation == "apply_exif",
			)
			hedef = target_size(*kaynak_gorunen, spec)
			kucultuldu = hedef != kaynak_gorunen
			_jpeg_decoder_draft(
				im,
				source_format=kaynak_fmt,
				orientation=kaynak_yon,
				apply_orientation=spec.orientation == "apply_exif",
				target_display=hedef,
				notes=notlar,
			)

		# 3 — yön. Etiket yok/1 ise ``exif_transpose`` çağrılmaz: Pillow bu
		# durumda bile önce tam decode edip bir piksel kopyası üretir.
		if bounded is None and spec.orientation == "apply_exif" and kaynak_yon not in (None, 1):
			yeni = ImageOps.exif_transpose(im)
			im = _replace_image(im, yeni)
			notlar.append("orientation:exif_applied")

		# 4 — renk uzayı
		if spec.colorspace == "srgb":
			renk_notu_baslangici = len(notlar)
			yeni, _icc_donusturuldu = to_srgb(im, icc, notlar)
			im = _replace_image(im, yeni)
			renk_notlari = notlar[renk_notu_baslangici:]
			if icc and any(
				n == "colorspace:profile_unreadable" or n.startswith("colorspace:icc_transform_failed:")
				for n in renk_notlari
			):
				# Bilinmeyen RGB sayılarını sRGB diye yeniden etiketlemek renk
				# dönüşümü değildir. Çağıran bu durumda orijinali korur.
				return NormalizeResult(
					ok=False,
					reason="icc_transform_failed",
					probe=p,
					notes=tuple(notlar),
				)
			# Pikseller artık sRGB'dir. Kaynak profilsizse kip dönüşümünün ardından
			# kanonik profil gömülür; bozuk profil yukarıda güvenli biçimde düşer.
			icc = _srgb_profile_bytes()
			if icc is None:
				notlar.append("colorspace:srgb_profile_unavailable")
		else:
			notlar.append("colorspace:preserved")

		# 5 — ölçü. ``hedef`` özgün/header ölçüsünden hesaplandı; draft edilmiş
		# ara ölçüden yeniden hesaplanmaz. Decoder nadiren hedefin altına inerse
		# FR-028 gereği ara tampon da büyütülmez.
		if im.width < hedef[0] or im.height < hedef[1]:
			notlar.append(f"io:jpeg_decoder_draft_undershoot:{im.width}x{im.height}")
			hedef = (im.width, im.height)
		if hedef != (im.width, im.height):
			yeni = _resize_with_alpha(im, hedef, Image, notlar)
			im = _replace_image(im, yeni)
			notlar.append(f"resize:{hedef[0]}x{hedef[1]}")
		elif bounded is None:
			notlar.append("resize:none")

		# 6 — çıktı biçimi ve metadata
		cikis_fmt = spec.target_format or kaynak_fmt
		if cikis_fmt not in ("JPEG", "PNG", "WEBP", "TIFF", "AVIF"):
			# GIF/BMP gibi girdiler master olarak korunamaz — WebP'ye taşınır.
			notlar.append(f"format:{cikis_fmt or '?'}_to_webp")
			cikis_fmt = "WEBP"

		alfali = im.mode in ALPHA_MODES
		if alfali and cikis_fmt not in ALPHA_CAPABLE_FORMATS:
			# FR-146: alfalı master alfasız biçime DÜŞÜRÜLMEZ. Reddetmek yerine
			# alfayı taşıyan en yakın biçime geçilir ve bu not edilir.
			notlar.append(f"alpha:format_upgraded_{cikis_fmt.lower()}_to_webp")
			cikis_fmt = "WEBP"
		if not alfali and im.mode not in ("RGB", "L", "CMYK"):
			yeni = im.convert("RGB")
			im = _replace_image(im, yeni)

		strip = {**DEFAULT_STRIP_METADATA, **dict(spec.strip_metadata or {})}
		if strip.get("icc", False):
			icc = None
			notlar.append("metadata:icc_stripped")
		# Orientation=1 de dahil, apply_exif seçildiyse yön etiketi çıktıda
		# kalmaz; pikseller artık kanonik yöndedir.
		exif = _exif_for_output(im, strip, spec.orientation == "apply_exif")
		if exif is None:
			notlar.append("metadata:exif_stripped")
		notlar.append("metadata:gps_removed")
		notlar.append("metadata:xmp_stripped")

		kw = _save_kwargs(cikis_fmt, spec, icc, exif)
		dpi_yazildi = "dpi" in kw
		if spec.dpi_out and not dpi_yazildi:
			notlar.append(f"dpi_not_supported_by_format:{cikis_fmt}")
		notlar.append(f"io:output_spool_max={NORMALIZE_SPOOL_MAX_BYTES}")

		out = _encode(im, cikis_fmt, kw)
		if not out:
			return NormalizeResult(ok=False, reason="empty_output", probe=p, notes=tuple(notlar))

		okunan = _verify(out)
		if okunan is None:
			return NormalizeResult(ok=False, reason="decode_failed", probe=p, notes=tuple(notlar))

		return NormalizeResult(
			ok=True,
			content=out,
			fmt=cikis_fmt,
			width=im.width,
			height=im.height,
			mode=im.mode,
			colorspace="sRGB" if spec.colorspace == "srgb" else "preserve",
			dpi=okunan.get("dpi"),
			dpi_written=bool(dpi_yazildi and okunan.get("dpi")),
			icc_embedded=bool(okunan.get("icc_profile")),
			icc_profile=str(okunan.get("icc_profile") or ""),
			resized=kucultuldu,
			notes=tuple(notlar),
			probe=p,
		)
	except Exception as exc:  # noqa: BLE001 — motor çağıranı hiçbir koşulda patlatmaz
		return NormalizeResult(
			ok=False, reason=f"error:{type(exc).__name__}: {exc}", probe=p, notes=tuple(notlar)
		)
	finally:
		if im is not None:
			try:
				im.close()
			except Exception:
				pass
		if bounded_path is not None:
			bounded_path.unlink(missing_ok=True)


def _assert(src, filename: str, guard: GuardConfig) -> HeaderProbe:
	p = probe_header(src, filename=filename, config=guard)
	if not p.ok:
		raise ImageRejected(p)
	return p


def _open_source(src, image_module):
	"""Pillow kaynağı: path tampona alınmaz, bytes yalnız sarılır."""
	if isinstance(src, bytes):
		return image_module.open(io.BytesIO(src))
	if isinstance(src, bytearray):
		return image_module.open(io.BytesIO(bytes(src)))
	return image_module.open(str(Path(src)))


def _replace_image(old, new):
	"""Yeni Pillow görüntüsüne geçerken büyük eski piksel tamponunu bırak."""
	if new is not old:
		try:
			old.close()
		except Exception:
			pass
	return new


def _srgb_profile_bytes() -> bytes | None:
	"""Gömülecek sRGB profili. `ImageCms` yoksa `None` — profil uydurulmaz."""
	try:
		from PIL import ImageCms

		return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
	except Exception:
		return None


def _verify(content: bytes) -> dict | None:
	"""Üretilen baytlar geri açılabiliyor mu ve DPI gerçekten yazılmış mı.

	`engine._verify` yalnız "açılıyor mu" diye soruyor. Burada aynı açılışta
	DPI da geri OKUNUYOR: `dpi=` vermek yazıldığı anlamına gelmiyor (WEBP/AVIF
	sessizce yok sayıyor — modül başlığındaki ölçüm). Beyan değil, ölçüm.
	"""
	try:
		from PIL import Image

		with Image.open(io.BytesIO(content)) as im:
			im.verify()
		with Image.open(io.BytesIO(content)) as im:
			dpi = im.info.get("dpi")
			icc = im.info.get("icc_profile")
			return {
				"fmt": (im.format or "").upper(),
				"size": im.size,
				"dpi": (round(float(dpi[0]), 1), round(float(dpi[1]), 1)) if dpi else None,
				"icc_profile": _profile_description(icc),
				"icc_is_srgb": _profile_is_srgb(icc) is True,
			}
	except Exception:
		return None


__all__ = [
	"ALPHA_CAPABLE_FORMATS",
	"ALPHA_MODES",
	"BOUNDED_COLORSPACE_UNSUPPORTED",
	"BOUNDED_DECODER_UNAVAILABLE",
	"BOUNDED_PREDECODE_FAILED",
	"BOUNDED_PREDECODE_MIN_MEGAPIXELS",
	"BOUNDED_TARGET_NOT_REDUCED",
	"DEFAULT_DPI_OUT",
	"DEFAULT_STRIP_METADATA",
	"DPI_CAPABLE_FORMATS",
	"NORMALIZE_SPOOL_MAX_BYTES",
	"NormalizeResult",
	"NormalizeSpec",
	"delta_e_2000",
	"normalize",
	"target_size",
	"to_srgb",
]
