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

	max_long_edge: int = 0            # 0 = ölçü sınırı yok
	max_megapixels: float = 0.0       # 0 = MP sınırı yok
	dpi_out: int = DEFAULT_DPI_OUT
	colorspace: str = "srgb"          # "srgb" | "preserve"
	orientation: str = "apply_exif"   # "apply_exif" | "preserve"
	fmt: str = ""                     # "" ya da "preserve" = kaynağı koru
	quality: int = 82
	lossless: bool = False
	strip_metadata: dict = field(default_factory=lambda: {"exif": True, "gps": True, "xmp": True, "icc": False})
	#: FR-028. `True` verilmesi sözleşme ihlalidir — `__post_init__` reddeder.
	allow_upscale: bool = False

	def __post_init__(self) -> None:
		if self.allow_upscale:
			raise ValueError("FR-028: normalleştirmede upscale yasak")
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
			max_megapixels=float(master.get("max_megapixels") or 0.0),
			dpi_out=int(master.get("dpi_out") or DEFAULT_DPI_OUT),
			colorspace=str(master.get("colorspace") or "srgb"),
			orientation=str(master.get("orientation") or "apply_exif"),
			fmt=str(master.get("format") or ""),
			strip_metadata=dict(master.get("strip_metadata") or {}),
			**kwargs,
		)

	@classmethod
	def from_master_spec(cls, spec, **kwargs) -> NormalizeSpec:
		"""`contracts.image.MasterSpec` → `NormalizeSpec` köprüsü."""
		return cls(
			max_long_edge=int(spec.max_long_edge or 0),
			max_megapixels=float(spec.max_megapixels or 0.0),
			dpi_out=int(spec.dpi_out or DEFAULT_DPI_OUT),
			colorspace=str(spec.colorspace or "srgb"),
			orientation=str(spec.orientation or "apply_exif"),
			fmt=str(spec.format or ""),
			quality=int(spec.quality or 82),
			lossless=bool(spec.lossless),
			strip_metadata=dict(spec.strip_metadata or {}),
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

	@property
	def size_bytes(self) -> int:
		return len(self.content)

	def to_dict(self) -> dict:
		return {
			"ok": self.ok,
			"fmt": self.fmt,
			"width": self.width,
			"height": self.height,
			"mode": self.mode,
			"dpi": list(self.dpi) if self.dpi else None,
			"dpi_written": self.dpi_written,
			"icc_embedded": self.icc_embedded,
			"resized": self.resized,
			"reason": self.reason,
			"notes": list(self.notes),
			"size_bytes": self.size_bytes,
		}


# ── Ölçü hesabı ─────────────────────────────────────────────────────────


def target_size(width: int, height: int, spec: NormalizeSpec) -> tuple[int, int]:
	"""Tavanlara uyan hedef ölçü. **Asla büyütmez** (FR-028).

	İki tavan birlikte uygulanır ve KÜÇÜK olan kazanır:
	  * `max_long_edge` — uzun kenar sınırı (CSS kutusundan türetilmiş)
	  * `max_megapixels` — toplam piksel sınırı (bellek ve encode maliyeti)

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

	if olcek >= 1.0:
		return (width, height)  # upscale YOK: kaynak zaten tavanın altında
	return (max(1, int(width * olcek)), max(1, int(height * olcek)))


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

	1. `strip["gps"]` — FR-039. GPS IFD'si her koşulda silinir; satıcının
	   evinin koordinatı ürün fotoğrafında taşınmaz. `strip["exif"]` False
	   olsa bile GPS gider.
	ÖLÇÜLDÜ (fixture `exif_gps.jpg`, strip={"exif": False, "gps": True}): çıktıda
	GPS işaretçi etiketi (34853) duruyor ama işaret ettiği IFD **boş**; ham
	baytlarda `GPS` dizgesi 0 kez geçiyor, yani koordinat sızmıyor. İşaretçiyi
	tamamen kaldırmak Pillow'un özel `_ifds` önbelleğine dokunmayı gerektirirdi
	— güvenlik özelliği (koordinat yok) zaten sağlandığı için yapılmadı.

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
	if strip.get("gps", True):
		# SIRA ÖNEMLİ: GPS IFD'si ayrı bir alt sözlükte tutuluyor ve üst
		# seviyedeki işaretçi etiketi ancak `get_ifd` çağrıldıktan sonra
		# sözlükte görünüyor. Önce alt IFD boşaltılır, sonra işaretçi silinir;
		# ters sırada koordinatlar `tobytes()` çıktısında kalabiliyor.
		try:
			exif.get_ifd(_EXIF_GPS_IFD).clear()
		except Exception:
			pass
		exif.pop(_EXIF_GPS_IFD, None)
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
	buf = io.BytesIO()
	im.save(buf, fmt, **kw)
	return buf.getvalue()


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
			return NormalizeResult(ok=False, reason=ret.probe.codes[0], probe=ret.probe, notes=("gate_reject",))

	try:
		from PIL import Image, ImageOps
	except Exception:
		return NormalizeResult(ok=False, reason="pillow_unavailable")

	try:
		veri = _as_bytes(src)
		im = Image.open(io.BytesIO(veri))
		kaynak_fmt = (im.format or "").upper()

		# Hareketli girdi: master TEK KARE'dir ve bu SESSİZCE yapılmaz.
		# `engine.optimize` hareketli dosyayı reddediyor (engine.py:97); burada
		# kapı zaten reddetmiş olabilir (`allow_animated=False`). Kapı bilerek
		# açıldıysa (ör. animasyonun poster karesi isteniyorsa) kayıp not edilir.
		if bool(getattr(im, "is_animated", False)):
			notlar.append(f"animation:flattened_first_frame_of_{getattr(im, 'n_frames', 1)}")

		# 2 — ICC'yi transpose'tan ÖNCE al (engine.py:101 ile aynı gerekçe).
		icc = im.info.get("icc_profile")

		# 3 — yön
		transpose_uygulandi = False
		if spec.orientation == "apply_exif":
			once = im.size
			im = ImageOps.exif_transpose(im)
			transpose_uygulandi = im.size != once
			if transpose_uygulandi:
				notlar.append("orientation:exif_applied")

		# 4 — renk uzayı
		icc_donusturuldu = False
		if spec.colorspace == "srgb":
			im, icc_donusturuldu = to_srgb(im, icc, notlar)
			if icc_donusturuldu:
				# Pikseller artık sRGB; eski profili taşımak YANLIŞ olurdu.
				icc = _srgb_profile_bytes()
		else:
			notlar.append("colorspace:preserved")

		# 5 — ölçü
		hedef = target_size(im.width, im.height, spec)
		kucultuldu = hedef != (im.width, im.height)
		if kucultuldu:
			im = im.resize(hedef, Image.LANCZOS, reducing_gap=2.0)
			notlar.append(f"resize:{hedef[0]}x{hedef[1]}")
		else:
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
			im = im.convert("RGB")

		strip = dict(spec.strip_metadata or {})
		if strip.get("icc", False):
			icc = None
			notlar.append("metadata:icc_stripped")
		exif = _exif_for_output(im, strip, transpose_uygulandi)
		if exif is None:
			notlar.append("metadata:exif_stripped")
		notlar.append("metadata:gps_removed")

		kw = _save_kwargs(cikis_fmt, spec, icc, exif)
		dpi_yazildi = "dpi" in kw
		if spec.dpi_out and not dpi_yazildi:
			notlar.append(f"dpi_not_supported_by_format:{cikis_fmt}")

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
			dpi=okunan.get("dpi"),
			dpi_written=bool(dpi_yazildi and okunan.get("dpi")),
			icc_embedded=bool(icc),
			resized=kucultuldu,
			notes=tuple(notlar),
			probe=p,
		)
	except Exception as exc:  # noqa: BLE001 — motor çağıranı hiçbir koşulda patlatmaz
		return NormalizeResult(ok=False, reason=f"error:{type(exc).__name__}: {exc}", probe=p, notes=tuple(notlar))


def _assert(src, filename: str, guard: GuardConfig) -> HeaderProbe:
	p = probe_header(src, filename=filename, config=guard)
	if not p.ok:
		raise ImageRejected(p)
	return p


def _as_bytes(src) -> bytes:
	if isinstance(src, (bytes, bytearray)):
		return bytes(src)
	return Path(src).read_bytes()


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
			return {
				"fmt": (im.format or "").upper(),
				"size": im.size,
				"dpi": (round(float(dpi[0]), 1), round(float(dpi[1]), 1)) if dpi else None,
			}
	except Exception:
		return None


__all__ = [
	"ALPHA_CAPABLE_FORMATS",
	"ALPHA_MODES",
	"DEFAULT_DPI_OUT",
	"DPI_CAPABLE_FORMATS",
	"NormalizeResult",
	"NormalizeSpec",
	"normalize",
	"target_size",
	"to_srgb",
]
