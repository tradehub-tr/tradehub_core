"""T-063 — Türev (rendition) üretimi. Faz 6'nın en kritik modülü.

**Çözdüğü problem.** Bugün canlıda varlık başına TEK bir çıktı üretiliyor:
`tradehub_core/media/pipeline.py::to_webp` koşulsuz `thumbnail((1920, 1920))` +
WebP yazıyor ve iş bitiyor. Ölçüm bunun sonucunu gösteriyor: ürün detay sayfası
13,14 MB görsel indiriyor (900 KB hedefinin 15 katı) ve `srcset` üreten tek bir
render noktası yok — 31 görselin 0'ında `srcset` var (`docs/reports/
03-render-envanteri.md`). Tek genişlik varken `srcset` zaten yazılamaz.

Bu modül **profil matrisini** uygular: slot politikasındaki `profiles[]` bloğu
× her profilin `formats[]` zinciri. Matris KOD DEĞİL VERİDİR — genişlikler,
biçimler, kalite ve `fit` değerleri `tradehub_core/media/pipeline/policy/slots/*.json`'dan
okunur. Yeni bir genişlik eklemek bu dosyayı değiştirmez.

**Yeniden yazılmayanlar** (kural 8):

    tradehub_core/media/pipeline.py   Pillow encode yolu — `optimize`'ın
                                    exif_transpose + ICC taşıma davranışı
                                    `_prepare_source` içinde birebir korunur.
    tradehub_core/media/pipeline/core/crop.py       kırpma penceresi çözümü (T-041 zinciri):
                                    `resolve_crop` burada TEKRAR YAZILMAZ.
    tradehub_core/media/pipeline/quality/ssim.py    adaptif kalite araması (T-013): en fazla
                                    4 encode ile hedef SSIM'i tutan en düşük
                                    kalite. `search_quality`'nin `encoder`/
                                    `reference` enjeksiyon kancaları tam bu
                                    kullanım için vardı.
    tradehub_core/media/pipeline/policy/engine.py   `PolicyRegistry` — slot dosyası okuma.

GARANTİLER
----------
1. **Upscale YASAK (FR-028).** Hedef genişlik kaynaktan büyükse çıktı
   büyütülmez; üretilebilen en büyük ölçü döner ve `under_spec` notu düşülür.
   `fit="pad"` durumunda tuval de aynı oranda küçülür — dolgu kutusu şişip
   içerik ortada minik kalmaz.
2. **Lanczos3.** `Image.LANCZOS` Pillow'un a=3 Lanczos çekirdeğidir.
3. **Premultiplied alpha.** Yeniden örnekleme `RGBa` (çarpılmış alfa) modunda
   yapılır; şeffaf kenarda halo oluşmaz. ÖLÇÜM (bu depoda,
   `tests/test_render.py::test_premultiplied_alfa_halo_uretmez`): Pillow
   11.3.0'ın doğrudan `RGBA` yeniden örneklemesi de aynı sonucu veriyor, yani
   Pillow bunu içeride zaten yapıyor. Açık `RGBa` yolu yine de korunur:
   garanti Pillow'un iç davranışına değil bu modüle ait olsun.
4. **Fayda kapısı (INV-05).** Bir biçimin çıktısı KAYNAKTAN büyük ya da eşitse
   o çıktı ATILIR ve `formats[]` zincirinde bir alta düşülür. Zincirin tamamı
   düşerse kaynak olduğu gibi geçirilir (`passthrough=True`) — hiçbir koşulda
   dosyayı büyüten bir türev yazılmaz.
5. **Determinizm.** Aynı (kaynak, profil, biçim, crop_intent) her zaman aynı
   baytları verir. `tests/test_render_regression.py` kilitler.

KULLANIM
--------
    from tradehub_core.media.pipeline.image.render import load_profiles, render, render_ladder

    profil = load_profiles("product.image")[3]          # w640
    baytlar = render(kaynak_baytlari, profil, None)      # tek türev

    for sonuc in render_ladder(kaynak_baytlari, "product.image"):
        print(sonuc.profile.name, sonuc.format, sonuc.size_bytes, sonuc.ssim)
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.core import crop as crop_mod
from tradehub_core.media.pipeline.quality import ssim as ssim_mod

# --- Sabitler ---------------------------------------------------------------

ENGINE_ID: str = "tradehub_core.media.pipeline.image.render"
ENGINE_VERSION: str = "1.0.0"
"""Encode parametrelerini etkileyen HER değişiklikte artırılır. `reprocess.py`
idempotensi anahtarına bu sürümü katar: motor değişince türev bayat sayılır."""

_POLICY_DIR = Path(__file__).resolve().parents[1] / "policy" / "slots"

FIT_CONTAIN: str = "contain"
FIT_COVER: str = "cover"
FIT_PAD: str = "pad"
FITS: Tuple[str, ...] = (FIT_CONTAIN, FIT_COVER, FIT_PAD)

LOSSLESS: str = "lossless"
"""`encoder_quality` içinde tamsayı yerine gelebilen kip seçimi (şema v1.3.0)."""

WEBP_METHOD: int = 4
"""WebP encoder çabası. `tradehub_core/media/pipeline.py::to_webp` ile AYNI değer —
mevcut motorla ayrışmamak için. ÖLÇÜM (bu depo, 640×640 ürün fixture'ı, q80):
method=4 → 37.250 bayt, method=6 → 37.340 bayt. Yani method 6 bu görselde
KAZANDIRMIYOR; 4'te kalmak için ölçülmüş bir gerekçe var."""

AVIF_SPEED: Optional[int] = None
"""AVIF encoder hızı. `None` = Pillow/libavif varsayılanı. ÖLÇÜM (aynı görsel,
q80): varsayılan → 28.897 bayt / 59 ms, speed=8 → 41.060 bayt / 51 ms. Hız
kazancı bayta değmiyor, varsayılanda kalınıyor."""

JPEG_SAVE_KW = {"optimize": True, "progressive": True}
"""`engine.optimize`'ın JPEG dalıyla aynı bayraklar."""

DEFAULT_MAX_ENCODES: int = 4
"""Görev sözleşmesi: adaptif kalite en fazla 4 encode denemesi."""

ALPHA_MODES: Tuple[str, ...] = ("RGBA", "LA", "PA", "RGBa")
ALPHA_CAPABLE_FORMATS: Tuple[str, ...] = ("WEBP", "AVIF", "PNG")
"""Alfa taşıyabilen çıktı biçimleri. JPEG bu listede YOK: alfalı bir kaynak
JPEG'e giderken dolgu rengine kompozit edilir ve `alpha_flattened` notu düşülür
(FR-146 ihlali değil — kompozit bilinçli ve raporda görünür)."""

PIL_FORMAT = {"webp": "WEBP", "avif": "AVIF", "jpeg": "JPEG", "png": "PNG"}
EXTENSION = {"webp": ".webp", "avif": ".avif", "jpeg": ".jpg", "png": ".png"}

DEFAULT_PAD_COLOR: str = "#FFFFFF"
TRANSPARENT: str = "transparent"

# Not kodları — raporda (report.py) Türkçe karşılıklarına çevrilir.
NOTE_UNDER_SPEC: str = "under_spec"
NOTE_ALPHA_FLATTENED: str = "alpha_flattened"
NOTE_CMYK_TO_SRGB: str = "cmyk_to_srgb"
NOTE_PALETTE_EXPANDED: str = "palette_expanded"
NOTE_EXIF_APPLIED: str = "exif_applied"
NOTE_PREMULTIPLIED: str = "premultiplied_resample"
NOTE_PADDED: str = "padded"
NOTE_CROPPED: str = "cropped"
NOTE_PASSTHROUGH: str = "passthrough_no_benefit"
NOTE_OVERSIZE: str = "derivative_oversize"
NOTE_NO_DOWNSCALE: str = "no_downscale"
NOTE_SSIM_UNREACHED: str = "ssim_target_unreached"
NOTE_SSIM_UNKNOWN: str = "ssim_target_unknown"
NOTE_QUALITY_FLOOR: str = "quality_floor_reached"
NOTE_LOSSLESS: str = "lossless_encode"
NOTE_ICC_KEPT: str = "icc_kept"
NOTE_SSIM_PROXY: str = "ssim_measured_on_proxy"
"""SSIM tam çözünürlükte DEĞİL, küçültülmüş bir vekil üzerinde ölçüldü.
`quality/ssim.py` numpy yoksa her iki görseli de `PURE_MAX_PIXELS` (512×512)
altına indirir. Küçültme sıkıştırma artefaktlarını siler, yani SSIM İYİMSER
çıkar ve adaptif kalite gereğinden düşük kalite seçer. ÖLÇÜLDÜ (aynı fixture,
product.image/w1280, hedef 0,96): numpy YOK → q70 / SSIM 0,99127 / 53.131 bayt;
numpy VAR → q82 / SSIM 0,96036 / 258.309 bayt. Aynı kod, 4,9 kat bayt farkı.
Bu yüzden bayrak künyeye ve rapora taşınır — sessiz kalması yasak."""


class RenderError(ValueError):
	"""Türev üretilemedi. Yarım çıktı ASLA dönmez (NFR-041)."""


# --- Profil (veri) ----------------------------------------------------------


@dataclass(frozen=True)
class RenditionProfile:
	"""Politikanın `profiles[]` girdisinin kod karşılığı — TÜREVİ OLMAYAN VERİ.

	Alan adları `policy/schema/slot-policy.schema.json` ile birebir aynıdır;
	`from_dict` sözlüğü doğrudan kabul eder. `profile_key` / `aspect_ratio`
	özellikleri `tradehub_core/media/pipeline/core/crop.py::resolve_crop`'un beklediği isimleri
	karşılar — kırpma modülü bu sınıfı tanımak zorunda kalmasın diye.
	"""

	slot_key: str
	name: str
	width: int
	formats: Tuple[str, ...]
	fit: str = FIT_CONTAIN
	height: int = 0
	encoder_quality: Tuple[Tuple[str, Any], ...] = ()
	target_ratio: str = ""
	pad_color: str = ""
	max_bytes: int = 0
	derived_from: str = ""
	serves: Tuple[str, ...] = ()

	def __post_init__(self) -> None:
		if self.width <= 0:
			raise RenderError(f"{self.name}: width pozitif olmalı ({self.width})")
		if self.fit not in FITS:
			raise RenderError(f"{self.name}: bilinmeyen fit {self.fit!r}")
		if not self.formats:
			raise RenderError(f"{self.name}: formats boş")
		for f in self.formats:
			if f not in PIL_FORMAT:
				raise RenderError(f"{self.name}: desteklenmeyen biçim {f!r}")

	# ── crop.resolve_crop uyumu ──────────────────────────────────────

	@property
	def profile_key(self) -> str:
		return self.name

	@property
	def aspect_ratio(self) -> str:
		return self.target_ratio

	# ── türetilmiş ───────────────────────────────────────────────────

	@property
	def quality_map(self) -> dict:
		return dict(self.encoder_quality)

	@property
	def target_ratio_value(self) -> Optional[float]:
		"""Hedef oranın sayısal karşılığı; oran yoksa `None`."""
		if not self.target_ratio:
			return None
		return crop_mod.parse_aspect_ratio(self.target_ratio)

	def quality_for(self, fmt: str) -> Any:
		"""Politikadaki kalite değeri: tamsayı, `"lossless"` ya da `None`.

		`None` = HENÜZ KALİBRE EDİLMEDİ (şema v1.3.0). Bu modül null'ı sayı
		uydurarak doldurmaz — adaptif arama gerçek değeri ÖLÇER ve `report.py`
		onu kalibrasyon için raporlar.
		"""
		return self.quality_map.get(fmt)

	def is_lossless(self, fmt: str) -> bool:
		return self.quality_for(fmt) == LOSSLESS

	def rendition_names(self) -> Tuple[str, ...]:
		"""`slot/profil.biçim` biçiminde matris satır adları."""
		return tuple(f"{self.name}.{f}" for f in self.formats)

	@classmethod
	def from_dict(cls, slot_key: str, data: dict) -> "RenditionProfile":
		eq = data.get("encoder_quality") or {}
		return cls(
			slot_key=slot_key,
			name=str(data["name"]),
			width=int(data["width"]),
			formats=tuple(str(f) for f in data["formats"]),
			fit=str(data.get("fit") or FIT_CONTAIN),
			height=int(data.get("height") or 0),
			encoder_quality=tuple(sorted((str(k), v) for k, v in eq.items())),
			target_ratio=str(data.get("target_ratio") or ""),
			pad_color=str(data.get("pad_color") or ""),
			max_bytes=int(data.get("max_bytes") or 0),
			derived_from=str(data.get("derived_from") or ""),
			serves=tuple(str(s) for s in (data.get("serves") or ())),
		)


@lru_cache(maxsize=None)
def _slot_files() -> dict:
	"""`slots/*.json` → {slot_key: (policy, path)}. `PolicyRegistry` ile aynı
	kural: dosya adı değil `slot_key` anahtardır."""
	out: dict = {}
	if not _POLICY_DIR.is_dir():
		return out
	for p in sorted(_POLICY_DIR.glob("*.json")):
		# Gizli dosyalar politika DEĞİLDİR. macOS'tan kopyalanan bir ağaçta
		# AppleDouble artıkları (`._brand-logo.json`) bu klasöre düşebilir; bunlar
		# UTF-8 bile değildir ve okunmaya çalışılırsa MOTORUN TAMAMI açılmaz
		# (ÖLÇÜLDÜ: `docker cp media_engine` sonrası konteynerde UnicodeDecodeError,
		# 9 slotun 9'u okunamadı). Editör geçici dosyaları da (`.#`, `.~`) aynı yere
		# düşebilir. Tek bir artık dosya bütün türev üretimini durdurmamalı.
		if p.name.startswith("."):
			continue
		data = json.loads(p.read_text(encoding="utf-8"))
		key = data.get("slot_key")
		if not key:
			raise RenderError(f"slot_key yok: {p}")
		if key in out:
			raise RenderError(f"slot_key iki dosyada: {key}")
		out[key] = (data, p)
	return out


def slot_keys() -> Tuple[str, ...]:
	return tuple(sorted(_slot_files()))


def load_slot_policy(slot_key: str) -> dict:
	try:
		return _slot_files()[slot_key][0]
	except KeyError as exc:
		raise RenderError(
			f"Bilinmeyen slot: {slot_key!r}. Tanımlı: {', '.join(slot_keys())}"
		) from exc


@lru_cache(maxsize=None)
def load_profiles(slot_key: str) -> Tuple[RenditionProfile, ...]:
	"""Slotun profil merdiveni — POLİTİKADAN, kodda sabit liste yok."""
	pol = load_slot_policy(slot_key)
	return tuple(RenditionProfile.from_dict(slot_key, p) for p in (pol.get("profiles") or ()))


def profile_for(slot_key: str, name: str) -> RenditionProfile:
	for p in load_profiles(slot_key):
		if p.name == name:
			return p
	raise RenderError(f"{slot_key}: {name!r} profili yok")


def rendition_matrix(slot_key: str) -> Tuple[Tuple[RenditionProfile, str], ...]:
	"""(profil, biçim) çiftlerinin tamamı — bu slotun üretim matrisi."""
	return tuple((p, f) for p in load_profiles(slot_key) for f in p.formats)


def matrix_size() -> dict:
	"""Slot başına ve toplam rendition tanımı sayısı. Rapor/ölçüm için."""
	out = {k: len(rendition_matrix(k)) for k in slot_keys()}
	out["_toplam"] = sum(out.values())
	return out


def quality_targets(slot_key: str) -> dict:
	"""Politikanın `quality` bloğu (hedef SSIM'ler, tasarruf tabanı)."""
	return dict(load_slot_policy(slot_key).get("quality") or {})


def strip_rules(slot_key: str) -> dict:
	return dict((load_slot_policy(slot_key).get("master") or {}).get("strip_metadata") or {})


# --- Sonuç tipleri ----------------------------------------------------------


@dataclass(frozen=True)
class FormatAttempt:
	"""Format zincirinin tek halkası — kabul veya INV-05 ile ret."""

	format: str
	quality: Any
	out_bytes: int
	ssim: float
	encodes: int
	elapsed_ms: float
	accepted: bool
	reason: str = ""


@dataclass(frozen=True)
class GeometryPlan:
	"""Piksel planı — encode'dan ÖNCE hesaplanır, encode'dan bağımsız test edilir."""

	source_size: Tuple[int, int]
	crop_box: Tuple[int, int, int, int]  # (left, top, w, h)
	inner_size: Tuple[int, int]
	canvas_size: Tuple[int, int]
	paste_at: Tuple[int, int]
	scale: float
	upscale_blocked: bool
	crop_method: str
	padded: bool

	@property
	def nominal_width(self) -> int:
		return self.canvas_size[0]


@dataclass
class RenditionResult:
	"""Tek bir türevin künyesi. `content` boş olamaz — hata `RenderError`'dır."""

	slot_key: str
	profile: RenditionProfile
	format: str
	content: bytes
	width: int
	height: int
	quality: Any
	ssim: float
	ssim_target: float
	content_class: str
	geometry: GeometryPlan
	encodes: int
	elapsed_ms: float
	source_bytes: int
	attempts: Tuple[FormatAttempt, ...] = ()
	notes: Tuple[str, ...] = ()
	passthrough: bool = False
	ssim_backend: str = ""
	"""SSIM'i hangi arka uç ölçtü: "numpy" | "pure" | "" (ölçülmedi)."""
	ssim_proxy: bool = False
	"""SSIM küçültülmüş vekil üzerinde ölçüldüyse True — sayı iyimserdir."""

	@property
	def size_bytes(self) -> int:
		return len(self.content)

	@property
	def name(self) -> str:
		return f"{self.profile.name}.{self.format}"

	@property
	def filename_suffix(self) -> str:
		return f"_{self.profile.name}{EXTENSION.get(self.format, '')}"

	@property
	def saving_ratio(self) -> float:
		if not self.source_bytes:
			return 0.0
		return 1.0 - (self.size_bytes / self.source_bytes)

	@property
	def upscale_blocked(self) -> bool:
		return self.geometry.upscale_blocked

	@property
	def ssim_ok(self) -> bool:
		"""Ölçülmediyse (hedef yok) kapı DÜŞMEZ — `measured` ayrımı raporda."""
		if self.ssim_target <= 0:
			return True
		return self.ssim >= self.ssim_target

	@property
	def megapixels(self) -> float:
		return (self.width * self.height) / 1_000_000.0

	def as_dict(self) -> dict:
		return {
			"slot": self.slot_key,
			"profile": self.profile.name,
			"format": self.format,
			"width": self.width,
			"height": self.height,
			"bytes": self.size_bytes,
			"quality": self.quality,
			"ssim": round(self.ssim, 6) if self.ssim else 0.0,
			"ssim_target": self.ssim_target,
			"ssim_ok": self.ssim_ok,
			"ssim_backend": self.ssim_backend or None,
			"ssim_proxy": self.ssim_proxy,
			"content_class": self.content_class,
			"encodes": self.encodes,
			"elapsed_ms": round(self.elapsed_ms, 3),
			"crop_method": self.geometry.crop_method,
			"upscale_blocked": self.upscale_blocked,
			"passthrough": self.passthrough,
			"notes": list(self.notes),
			"attempts": [
				{
					"format": a.format,
					"quality": a.quality,
					"bytes": a.out_bytes,
					"ssim": round(a.ssim, 6) if a.ssim else 0.0,
					"encodes": a.encodes,
					"elapsed_ms": round(a.elapsed_ms, 3),
					"accepted": a.accepted,
					"reason": a.reason,
				}
				for a in self.attempts
			],
		}


# --- Renk / mod normalleştirme ---------------------------------------------


def _pil():
	try:
		from PIL import Image, ImageOps  # noqa: F401
	except Exception as exc:  # pragma: no cover
		raise RenderError("Pillow yok") from exc
	from PIL import Image, ImageOps

	return Image, ImageOps


def parse_pad_color(value: str) -> Tuple[int, int, int, int]:
	"""`#RRGGBB` / `#RGB` / `transparent` → RGBA dörtlüsü."""
	text = (value or DEFAULT_PAD_COLOR).strip().lower()
	if text == TRANSPARENT:
		return (0, 0, 0, 0)
	if not text.startswith("#"):
		raise RenderError(f"Geçersiz pad_color: {value!r}")
	h = text[1:]
	if len(h) == 3:
		h = "".join(c * 2 for c in h)
	if len(h) != 6:
		raise RenderError(f"Geçersiz pad_color: {value!r}")
	return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def _open(src) -> Any:
	Image, _ = _pil()
	if isinstance(src, Image.Image):
		return src
	if isinstance(src, (str, Path)):
		return Image.open(str(src))
	return Image.open(io.BytesIO(src))


def prepare_source(src) -> tuple:
	"""EXIF rotasyonunu piksele işle + renk modunu normalleştir.

	`engine.optimize` sırasının aynısı: `Image.open` → (ICC'yi al) →
	`exif_transpose` → mod dönüşümü. ICC transpose'tan ÖNCE alınır çünkü
	`exif_transpose` yeni bir `Image` döndürür ve `info` taşımayabilir —
	bu, mevcut motorda zaten yazılı olan tuzaktır.

	Dönüş: `(image, icc_profile_bytes|None, notes)`.
	"""
	Image, ImageOps = _pil()
	im = _open(src)
	fmt = (getattr(im, "format", "") or "").upper()
	icc = im.info.get("icc_profile")
	notes: list = []

	orientation = 1
	try:
		exif = im.getexif()
		orientation = int(exif.get(274, 1) or 1)
	except Exception:
		orientation = 1
	im = ImageOps.exif_transpose(im)
	if orientation not in (0, 1):
		notes.append(NOTE_EXIF_APPLIED)

	mode = im.mode
	if mode == "P":
		alfali = "transparency" in im.info
		im = im.convert("RGBA" if alfali else "RGB")
		notes.append(NOTE_PALETTE_EXPANDED)
	elif mode == "CMYK":
		im = im.convert("RGB")
		notes.append(NOTE_CMYK_TO_SRGB)
		# CMYK ICC profili RGB çıktıda geçersizdir — taşınmaz.
		icc = None
	elif mode in ("L", "1", "I", "I;16", "F"):
		im = im.convert("RGB")
	elif mode == "LA":
		im = im.convert("RGBA")
	elif mode == "RGBa":
		im = im.convert("RGBA")
	elif mode not in ("RGB", "RGBA"):
		im = im.convert("RGBA" if "A" in mode else "RGB")

	if icc:
		notes.append(NOTE_ICC_KEPT)
	return im, icc, tuple(notes)


def has_alpha(im) -> bool:
	return im.mode in ALPHA_MODES


# --- Geometri ---------------------------------------------------------------


def plan_geometry(
	source_size: Tuple[int, int],
	profile: RenditionProfile,
	crop_intent: Any = None,
) -> GeometryPlan:
	"""Kırpma + ölçek + dolgu planını üret. **Encode YOK, saf aritmetik.**

	Upscale yasağı üç `fit` için de burada uygulanır:

	  contain  ölçek = min(1, hedef_w / kırpma_w); tuval = ölçeklenmiş görüntü.
	  cover    kırpma penceresi zaten hedef orandadır; ölçek yine 1 ile sınırlı.
	  pad      görüntü hedef kutuya SIĞDIRILIR. Kutu ölçeği 1'i aşacaksa
	           (kaynak küçük) tuvalin KENDİSİ aynı oranda küçültülür; oran
	           korunur, içerik minik kalmaz.
	"""
	src_w, src_h = source_size
	if src_w <= 0 or src_h <= 0:
		raise RenderError(f"Kaynak boyutu pozitif olmalı: {source_size}")

	asset = {"width": src_w, "height": src_h, "crop_intent": crop_intent}
	win = crop_mod.resolve_crop(asset, profile, intent=crop_intent)
	crop_mod.verify_window(win)
	left, top, cw, ch = win.to_pixels(src_w, src_h)
	cropped = (cw, ch) != (src_w, src_h)

	want_w = int(profile.width)
	ratio = profile.target_ratio_value
	if profile.height:
		want_h = int(profile.height)
	elif ratio and profile.fit in (FIT_COVER, FIT_PAD):
		want_h = max(1, int(round(want_w / ratio)))
	else:
		want_h = max(1, int(round(want_w * ch / cw)))

	padded = False
	if profile.fit == FIT_PAD and (ratio or profile.height):
		fit_scale = min(want_w / cw, want_h / ch)
		scale = min(fit_scale, 1.0)
		k = scale / fit_scale if fit_scale > 0 else 1.0
		canvas_w = max(1, int(round(want_w * k)))
		canvas_h = max(1, int(round(want_h * k)))
		inner_w = max(1, min(canvas_w, int(round(cw * scale))))
		inner_h = max(1, min(canvas_h, int(round(ch * scale))))
		padded = (inner_w, inner_h) != (canvas_w, canvas_h)
	else:
		# contain ve cover: tuval = ölçeklenmiş görüntünün kendisi.
		fit_scale = want_w / cw
		if profile.height or (ratio and profile.fit == FIT_COVER):
			fit_scale = min(want_w / cw, want_h / ch)
		scale = min(fit_scale, 1.0)
		inner_w = max(1, int(round(cw * scale)))
		inner_h = max(1, int(round(ch * scale)))
		canvas_w, canvas_h = inner_w, inner_h

	paste = ((canvas_w - inner_w) // 2, (canvas_h - inner_h) // 2)
	return GeometryPlan(
		source_size=(src_w, src_h),
		crop_box=(left, top, cw, ch),
		inner_size=(inner_w, inner_h),
		canvas_size=(canvas_w, canvas_h),
		paste_at=paste,
		scale=scale,
		upscale_blocked=fit_scale > 1.0 + 1e-9,
		crop_method=win.method,
		padded=padded,
	)


def resize_premultiplied(im, size: Tuple[int, int]):
	"""Lanczos3 ile yeniden örnekle; alfa varsa ÇARPILMIŞ alfa uzayında.

	Şeffaf kenardaki gizli RGB değeri (çoğu PNG'de siyah) düz alfa uzayında
	komşu opak piksellere sızar ve koyu bir halo bırakır. `RGBa` Pillow'un
	çarpılmış alfa modudur; dönüşüm çekirdeği C tarafındadır.
	"""
	Image, _ = _pil()
	if tuple(im.size) == tuple(size):
		return im.copy()
	if has_alpha(im):
		return im.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
	return im.resize(size, Image.LANCZOS)


def build_canvas(im, profile: RenditionProfile, plan: GeometryPlan) -> tuple:
	"""Kırp → ölçekle → (gerekiyorsa) dolgula. Encode ÖNCESİ son piksel hâli."""
	Image, _ = _pil()
	left, top, cw, ch = plan.crop_box
	notes: list = []
	if (cw, ch) != tuple(im.size):
		im = im.crop((left, top, left + cw, top + ch))
		notes.append(NOTE_CROPPED)

	inner = resize_premultiplied(im, plan.inner_size)
	if has_alpha(im):
		notes.append(NOTE_PREMULTIPLIED)

	if plan.inner_size == plan.canvas_size:
		return inner, tuple(notes)

	pad = parse_pad_color(profile.pad_color or DEFAULT_PAD_COLOR)
	if pad[3] == 0:
		canvas = Image.new("RGBA", plan.canvas_size, (0, 0, 0, 0))
		if inner.mode != "RGBA":
			inner = inner.convert("RGBA")
		canvas.paste(inner, plan.paste_at)
	elif has_alpha(inner):
		canvas = Image.new("RGBA", plan.canvas_size, pad)
		canvas.alpha_composite(inner, plan.paste_at)
	else:
		canvas = Image.new("RGB", plan.canvas_size, pad[:3])
		canvas.paste(inner, plan.paste_at)
	notes.append(NOTE_PADDED)
	return canvas, tuple(notes)


# --- Encode -----------------------------------------------------------------


def encode(im, fmt: str, quality: Any, *, icc: Optional[bytes] = None,
		   pad_color: str = DEFAULT_PAD_COLOR) -> tuple:
	"""Tek encode. Dönüş `(bytes, notes)`. Deterministiktir.

	`quality` `"lossless"` ise kayıpsız kip seçilir (WebP `lossless=True`,
	PNG zaten kayıpsız, AVIF `quality=100`). AVIF'in gerçekten kayıpsız olması
	libavif'in renk alt örneklemesine de bağlıdır; bu yüzden AVIF kayıpsız
	yolu `subsampling="4:4:4"` ile çağrılır.
	"""
	Image, _ = _pil()
	fmt = fmt.lower()
	pil_fmt = PIL_FORMAT.get(fmt)
	if not pil_fmt:
		raise RenderError(f"Desteklenmeyen biçim: {fmt!r}")

	notes: list = []
	out_im = im
	if pil_fmt not in ALPHA_CAPABLE_FORMATS and has_alpha(im):
		bg = parse_pad_color(pad_color)
		zemin = Image.new("RGBA", im.size, (bg[0], bg[1], bg[2], 255))
		out_im = Image.alpha_composite(zemin, im.convert("RGBA")).convert("RGB")
		notes.append(NOTE_ALPHA_FLATTENED)
	elif pil_fmt == "JPEG" and im.mode != "RGB":
		out_im = im.convert("RGB")

	kw: dict = {}
	if icc:
		kw["icc_profile"] = icc

	lossless = quality == LOSSLESS
	buf = io.BytesIO()
	if pil_fmt == "WEBP":
		if lossless:
			out_im.save(buf, "WEBP", lossless=True, quality=100, method=WEBP_METHOD, **kw)
			notes.append(NOTE_LOSSLESS)
		else:
			out_im.save(buf, "WEBP", quality=int(quality), method=WEBP_METHOD, **kw)
	elif pil_fmt == "AVIF":
		if AVIF_SPEED is not None:
			kw["speed"] = AVIF_SPEED
		if lossless:
			out_im.save(buf, "AVIF", quality=100, subsampling="4:4:4", **kw)
			notes.append(NOTE_LOSSLESS)
		else:
			out_im.save(buf, "AVIF", quality=int(quality), **kw)
	elif pil_fmt == "JPEG":
		out_im.save(buf, "JPEG", quality=int(100 if lossless else quality), **JPEG_SAVE_KW, **kw)
	else:  # PNG — kayıpsız, `quality` anlamsız
		out_im.save(buf, "PNG", optimize=True, **kw)
		notes.append(NOTE_LOSSLESS)

	data = buf.getvalue()
	if not data:
		raise RenderError(f"{fmt}: boş çıktı")
	return data, tuple(notes)


def _verify(data: bytes) -> bool:
	"""Üretilen baytlar gerçekten açılıyor mu — `engine._verify` ile aynı kapı."""
	try:
		Image, _ = _pil()
		with Image.open(io.BytesIO(data)) as im:
			im.verify()
		return True
	except Exception:
		return False


# --- Adaptif kalite ---------------------------------------------------------


def ssim_measurement_mode(canvas_size: Tuple[int, int]) -> Tuple[str, bool]:
	"""SSIM hangi arka uçla, tam çözünürlükte mi ölçülecek? `(backend, proxy_mi)`.

	`quality/ssim.py::compute_ssim`'in kendi kararını TEKRARLAMADAN önceden
	okur: numpy yoksa sınır `PURE_MAX_PIXELS`'tir ve tuval bundan büyükse her
	iki görsel de küçültülür. Burada SSIM YENİDEN HESAPLANMAZ (pahalı olurdu);
	yalnız aynı koşul değerlendirilir.
	"""
	numpy_var = ssim_mod._numpy_varsa() is not None
	backend = "numpy" if numpy_var else "pure"
	piksel = max(1, canvas_size[0]) * max(1, canvas_size[1])
	return backend, (not numpy_var and piksel > ssim_mod.PURE_MAX_PIXELS)


def resolve_target_ssim(slot_key: str, content_class: str) -> float:
	"""Politikadan hedef SSIM. 0.0 = SSIM aranmaz (bit_exact) ya da tanımsız."""
	deger = ssim_mod.target_for(slot_key, content_class)
	return float(deger) if deger else 0.0


def _encode_with_search(
	canvas,
	profile: RenditionProfile,
	fmt: str,
	*,
	icc: Optional[bytes],
	target_ssim: float,
	source_bytes: int,
	max_encodes: int,
	quality_range: Tuple[int, int],
) -> tuple:
	"""Bir biçim için baytları üret. Dönüş `(bytes, quality, ssim, encodes, notes)`.

	Üç yol var ve hangisinin seçildiği raporda görünür:

	  1. `encoder_quality = "lossless"` ya da politikanın metriği `bit_exact`
	     → tek kayıpsız encode, arama yok.
	  2. Hedef SSIM var → `ssim.search_quality` ile en fazla `max_encodes`
	     encode; hedefi tutan EN DÜŞÜK kalite seçilir.
	  3. Hedef yok ve politika tamsayı kalite veriyor → tek encode o kalitede.
	     Politika `null` (kalibre edilmedi) ve hedef de yoksa hata verilir —
	     modül kalite sayısı UYDURMAZ.
	"""
	notes: list = []
	pad = profile.pad_color or DEFAULT_PAD_COLOR
	politika_q = profile.quality_for(fmt)

	if politika_q == LOSSLESS or target_ssim <= 0.0:
		if politika_q == LOSSLESS:
			data, n = encode(canvas, fmt, LOSSLESS, icc=icc, pad_color=pad)
			return data, LOSSLESS, 1.0, 1, tuple(notes) + n + (NOTE_SSIM_UNKNOWN,)
		if isinstance(politika_q, int):
			data, n = encode(canvas, fmt, politika_q, icc=icc, pad_color=pad)
			return data, politika_q, 0.0, 1, tuple(notes) + n + (NOTE_SSIM_UNKNOWN,)
		raise RenderError(
			f"{profile.slot_key}/{profile.name}/{fmt}: hedef SSIM de kalibre kalite de yok — "
			"kalite uydurulamaz (politikada encoder_quality null ve quality.metric SSIM değil)"
		)

	def _enc(_content, _max_dim, q):
		try:
			data, _n = encode(canvas, fmt, int(q), icc=icc, pad_color=pad)
		except Exception as exc:  # noqa: BLE001
			return b"", f"encode_error:{type(exc).__name__}"
		return data, ""

	sonuc = ssim_mod.search_quality(
		b"\x00" * max(1, source_bytes),
		target_ssim=target_ssim,
		max_dim=max(canvas.size),
		quality_range=quality_range,
		max_encodes=max_encodes,
		encoder=_enc,
		reference=canvas,
	)
	if not sonuc.content:
		raise RenderError(f"{profile.name}/{fmt}: encode başarısız ({sonuc.reason})")
	if not sonuc.ok:
		notes.append(NOTE_SSIM_UNREACHED)
	if sonuc.reason == "floor_reached":
		notes.append(NOTE_QUALITY_FLOOR)
	return sonuc.content, sonuc.quality, sonuc.ssim, sonuc.encodes, tuple(notes)


# --- Ana giriş --------------------------------------------------------------


def render_rendition(
	source,
	profile: RenditionProfile,
	crop_intent: Any = None,
	*,
	fmt: Optional[str] = None,
	content_class: Optional[str] = None,
	target_ssim: Optional[float] = None,
	max_encodes: int = DEFAULT_MAX_ENCODES,
	quality_range: Tuple[int, int] = ssim_mod.DEFAULT_QUALITY_RANGE,
	allow_passthrough: bool = True,
) -> RenditionResult:
	"""Tek türev üret — künyesiyle birlikte.

	`fmt` verilmezse profilin `formats[]` zinciri baştan denenir ve **fayda
	kapısını (INV-05) geçen ilk biçim** kazanır. Verilirse yalnız o biçim
	denenir (ölçüm ve regresyon testleri için).
	"""
	t0 = time.perf_counter()
	source_bytes = len(source) if isinstance(source, (bytes, bytearray)) else 0
	im, icc, hazirlik_notlari = prepare_source(source)
	if strip_rules(profile.slot_key).get("icc", False):
		icc = None  # politika ICC'yi de siliyor

	plan = plan_geometry(im.size, profile, crop_intent)
	canvas, tuval_notlari = build_canvas(im, profile, plan)

	if content_class is None:
		content_class = ssim_mod.guess_content_class(canvas)
	if target_ssim is None:
		target_ssim = resolve_target_ssim(profile.slot_key, content_class)

	ssim_backend, ssim_proxy = ssim_measurement_mode(plan.canvas_size)
	if target_ssim <= 0.0:
		ssim_backend, ssim_proxy = "", False

	zincir: Sequence[str] = (fmt,) if fmt else profile.formats
	denemeler: list = []
	kazanan = None

	for f in zincir:
		tf = time.perf_counter()
		try:
			data, q, s, enc_sayisi, notlar = _encode_with_search(
				canvas,
				profile,
				f,
				icc=icc,
				target_ssim=target_ssim,
				source_bytes=source_bytes,
				max_encodes=max_encodes,
				quality_range=quality_range,
			)
		except RenderError as exc:
			denemeler.append(
				FormatAttempt(f, None, 0, 0.0, 0, (time.perf_counter() - tf) * 1000.0, False, str(exc))
			)
			continue
		gecen = (time.perf_counter() - tf) * 1000.0

		if not _verify(data):
			denemeler.append(FormatAttempt(f, q, len(data), s, enc_sayisi, gecen, False, "decode_failed"))
			continue

		# INV-05 — fayda kapısı. Çıktı kaynaktan küçük DEĞİLSE bu türev
		# hiçbir işe yaramaz: aynı baytı iki kez saklamış oluruz.
		if source_bytes and len(data) >= source_bytes:
			denemeler.append(
				FormatAttempt(f, q, len(data), s, enc_sayisi, gecen, False, "no_benefit_vs_source")
			)
			continue

		denemeler.append(FormatAttempt(f, q, len(data), s, enc_sayisi, gecen, True))
		kazanan = (f, data, q, s, enc_sayisi, notlar)
		break

	notes = list(hazirlik_notlari) + list(tuval_notlari)
	if plan.upscale_blocked:
		notes.append(NOTE_UNDER_SPEC)
	if plan.scale >= 1.0 - 1e-9:
		notes.append(NOTE_NO_DOWNSCALE)

	if kazanan is None:
		if not allow_passthrough or not source_bytes:
			gerekce = "; ".join(f"{a.format}:{a.reason}" for a in denemeler) or "deneme yok"
			raise RenderError(f"{profile.slot_key}/{profile.name}: hiçbir biçim üretilemedi ({gerekce})")
		# Zincirin tamamı fayda kapısından döndü → kaynak olduğu gibi geçer.
		kaynak_fmt = (getattr(_open(source), "format", "") or "").lower()
		notes.append(NOTE_PASSTHROUGH)
		return RenditionResult(
			slot_key=profile.slot_key,
			profile=profile,
			format=kaynak_fmt or "unknown",
			content=bytes(source),
			width=im.width,
			height=im.height,
			quality=None,
			ssim=1.0,
			ssim_target=target_ssim,
			content_class=content_class,
			geometry=plan,
			encodes=sum(a.encodes for a in denemeler),
			elapsed_ms=(time.perf_counter() - t0) * 1000.0,
			source_bytes=source_bytes,
			attempts=tuple(denemeler),
			notes=tuple(dict.fromkeys(notes)),
			passthrough=True,
			ssim_backend=ssim_backend,
			ssim_proxy=ssim_proxy,
		)

	f, data, q, s, enc_sayisi, encode_notlari = kazanan
	notes.extend(encode_notlari)
	if profile.max_bytes and len(data) > profile.max_bytes:
		notes.append(NOTE_OVERSIZE)
	if ssim_proxy:
		notes.append(NOTE_SSIM_PROXY)

	return RenditionResult(
		slot_key=profile.slot_key,
		profile=profile,
		format=f,
		content=data,
		width=plan.canvas_size[0],
		height=plan.canvas_size[1],
		quality=q,
		ssim=s,
		ssim_target=target_ssim,
		content_class=content_class,
		geometry=plan,
		encodes=sum(a.encodes for a in denemeler),
		elapsed_ms=(time.perf_counter() - t0) * 1000.0,
		source_bytes=source_bytes,
		attempts=tuple(denemeler),
		notes=tuple(dict.fromkeys(notes)),
		ssim_backend=ssim_backend,
		ssim_proxy=ssim_proxy,
	)


def render(source, profile: RenditionProfile, crop_intent: Any = None) -> bytes:
	"""**Görev sözleşmesinin imzası:** `render(source, profile, crop_intent) → bytes`.

	Künye gerekiyorsa `render_rendition` kullanılır; bu sarmalayıcı yalnız
	baytları verir.
	"""
	return render_rendition(source, profile, crop_intent).content


def render_ladder(
	source,
	slot_key: str,
	crop_intent: Any = None,
	*,
	profiles: Optional[Iterable[RenditionProfile]] = None,
	formats: Optional[Sequence[str]] = None,
	max_encodes: int = DEFAULT_MAX_ENCODES,
	per_format: bool = False,
) -> list:
	"""Bir varlığın türev merdiveninin TAMAMI.

	`per_format=False` (varsayılan): her profil için format zinciri denenir ve
	kazanan TEK türev döner — üretim davranışı, INV-05 zinciri.
	`per_format=True`: her (profil × biçim) ayrı üretilir — `<picture>` için
	gereken çoklu `<source>` seti ve ölçüm tablosu bu moddan çıkar.

	Kısmi başarı yoktur: bir profil üretilemezse `RenderError` yükselir
	(sözleşme `contracts/image.py::make_ladder` ile aynı — eksik merdiven
	`srcset` içinde 404 demektir).
	"""
	profiller = tuple(profiles) if profiles is not None else load_profiles(slot_key)
	if not profiller:
		raise RenderError(f"{slot_key}: profil yok")

	# İçerik sınıfı ve künye varlık başına BİR KEZ hesaplanır.
	im, _icc, _n = prepare_source(source)
	content_class = ssim_mod.guess_content_class(im)
	target = resolve_target_ssim(slot_key, content_class)

	out: list = []
	for p in profiller:
		zincir = tuple(formats) if formats else (p.formats if per_format else (None,))
		for f in zincir:
			if f is not None and f not in PIL_FORMAT:
				raise RenderError(f"Desteklenmeyen biçim: {f!r}")
			out.append(
				render_rendition(
					source,
					p,
					crop_intent,
					fmt=f,
					content_class=content_class,
					target_ssim=target,
					max_encodes=max_encodes,
				)
			)
	return out


def ladder_totals(results: Sequence[RenditionResult]) -> dict:
	"""Merdivenin toplamları — rapor ve ölçüm için tek yerden."""
	if not results:
		return {"count": 0, "bytes": 0, "elapsed_ms": 0.0, "encodes": 0}
	toplam = sum(r.size_bytes for r in results)
	return {
		"count": len(results),
		"bytes": toplam,
		"kb": round(toplam / 1024.0, 1),
		"elapsed_ms": round(sum(r.elapsed_ms for r in results), 1),
		"encodes": sum(r.encodes for r in results),
		"passthrough": sum(1 for r in results if r.passthrough),
		"under_spec": sum(1 for r in results if r.upscale_blocked),
		"ssim_min": round(min((r.ssim for r in results if r.ssim), default=0.0), 6),
		"largest": max(results, key=lambda r: r.size_bytes).name,
	}


__all__ = [
	"ENGINE_ID",
	"ENGINE_VERSION",
	"RenderError",
	"RenditionProfile",
	"GeometryPlan",
	"FormatAttempt",
	"RenditionResult",
	"slot_keys",
	"load_slot_policy",
	"load_profiles",
	"profile_for",
	"rendition_matrix",
	"matrix_size",
	"quality_targets",
	"parse_pad_color",
	"prepare_source",
	"plan_geometry",
	"resize_premultiplied",
	"build_canvas",
	"encode",
	"resolve_target_ssim",
	"render",
	"render_rendition",
	"render_ladder",
	"ladder_totals",
]
