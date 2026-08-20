"""T-041 — Kırpma niyeti ve öncelik zinciri.

Bu modül tek bir soruyu cevaplar: **bir varlık, belirli bir profil için nereden
kırpılacak?** Cevap beş kaynaktan gelebilir ve hangisinin kazandığı tek yerde,
test edilebilir biçimde yazılıdır:

    1. Profile-specific manual crop override   (kullanıcı o profil için elle çizdi)
    2. Taban bölge + odak noktası              (kenar sıkıştırmalı; taban bölge
       zoom+merkezden (`zoom_region_of`) ya da güvenli alandan gelir — zoom
       yazılmışsa o kazanır, güvenli alan panelde ondan türetiliyor)
    3. Genel odak noktası
    4. Smartcrop önerisi                       (güven >= eşik)
    5. Merkez kırpım                           (fallback; taban bölge varsa
       onun merkezi)

**INV-10 — tüm koordinatlar 0-1 normalize.** Piksel yok. Sebebi teorik değil:
aynı görselin master'ı, arşiv kopyası ve satıcının yeniden yüklediği hâli farklı
piksel boyutlarında olabiliyor. Kadraj piksel cinsinden saklanırsa 2 kat
küçültülmüş bir kaynakta kadraj kayar. Normalize koordinatta kaymaz — ve bu
modülün matematiği kaynağın piksel boyutlarını HİÇ kullanmaz, yalnız **en-boy
oranını** kullanır (bkz. `_cover_window`). Bu yüzden INV-10 bir test değil, bir
yapı özelliğidir.

**Simülatörle birebir aynı matematik.** Kaynak dokümanın `docs/simulator.html`
dosyasındaki `cropWindow()` fonksiyonu üretimin referansıdır; ikisi ayrışırsa
kullanıcı önizlemede gördüğünden başka bir kadraj alır. Referans JS (birebir):

    function cropWindow(targetAR) {
      const W = S.natW, H = S.natH;
      const bx = S.base.x*W, by = S.base.y*H, bw = S.base.w*W, bh = S.base.h*H;
      if (!targetAR) return { x:bx, y:by, w:bw, h:bh };
      let w, h;
      if (bw / bh > targetAR) { h = bh; w = h * targetAR; }
      else                    { w = bw; h = w / targetAR; }
      let x = S.focal.x*W - w/2;
      let y = S.focal.y*H - h/2;
      x = clamp(x, bx, bx + bw - w);
      y = clamp(y, by, by + bh - h);
      return { x, y, w, h };
    }

Bizim sürümümüz aynı işi **normalize uzayda** yapar. Dönüşüm cebirseldir:
piksel uzayında hedef oran `AR = w_px/h_px`; normalize uzayda aynı pencerenin
oranı `w_n/h_n = AR * (H/W) = AR / kaynak_oranı`. Yani tek fark, hedef oranın
kaynak oranına bölünmesidir; sonuç piksele çevrildiğinde JS ile aynı sayıyı
verir (bkz. `tests/test_crop.py::AltinSimulatorTesti`).

`import frappe` ve `import PIL` **YOKTUR** — bilinçli. Bu modül site, bench, DB
ya da Pillow olmadan çalışır ve test edilir; `tradehub_core/media/pipeline.py`
aynı disiplini izliyor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

# Kayan nokta karşılaştırmalarında kullanılan tolerans. Kadraj matematiği
# bölme içerdiği için tam eşitlik aranmaz; bu değer "aynı sayı" eşiğidir.
EPS: float = 1e-9

# T-041 kabul kriteri: "istenen orana tam uyuyor" — testte kullanılan tolerans
# kaynak dokümandan alındı (%0,5).
RATIO_TOLERANCE: float = 0.005

# Smartcrop önerisinin kullanılabilmesi için gereken asgari güven.
# ÖLÇÜLMEDİ — kalibrasyon T-041 kapsamında yapılmadı, saliency modeli henüz
# yok (Faz 3 mimarisinde "AI Worker (L5)" olarak planlanmış). Bu taban değer bir
# ölçüm sonucu DEĞİLDİR; Media Engine Settings.smartcrop_confidence_threshold
# doldurulduğunda o kazanır ve buradaki sayı devre dışı kalır.
SMARTCROP_CONFIDENCE_THRESHOLD: float = 0.5

# Öncelik zincirinin seviye adları. CropWindow.method bu değerlerden birini
# taşır ve UI rozeti ("öneri", "elle kırpıldı") buradan seçilir.
METHOD_OVERRIDE = "override"
METHOD_SAFE_FOCAL = "safe_focal"
METHOD_FOCAL = "focal"
METHOD_SMARTCROP = "smartcrop"
METHOD_CENTER = "center"

METHODS: Tuple[str, ...] = (
	METHOD_OVERRIDE,
	METHOD_SAFE_FOCAL,
	METHOD_FOCAL,
	METHOD_SMARTCROP,
	METHOD_CENTER,
)

# Zoom sınırları — `core/crop_geometry.py::ZOOM_MIN/ZOOM_MAX` ile AYNI değerler.
# Oradan import EDİLMEZ: bu modül parite üreticisi tarafından paket bağlamı
# olmadan, dosya yolundan yüklenir (`admin-panel/frontend/scripts/
# gen_crop_pixel_vectors.py::load_crop_core`) ve bir kardeş import o yüklemeyi
# kırardı. İki sabit ayrışırsa `tests/test_crop_intent_zoom.py` kırmızıya döner.
ZOOM_MIN: float = 1.0
ZOOM_MAX: float = 16.0

# Zincirdeki sıra numarası — testler ve loglar "hangi seviye kazandı" sorusunu
# metin karşılaştırmadan cevaplayabilsin.
METHOD_PRIORITY: dict = {m: i + 1 for i, m in enumerate(METHODS)}

FULL_FRAME = (0.0, 0.0, 1.0, 1.0)


class CropError(ValueError):
	"""Kırpma girdisi tutarsız — pencere üretilemez."""


def _clamp(value: float, low: float, high: float) -> float:
	"""`value`'yu [low, high] aralığına sıkıştır.

	`high < low` durumunda (kayan nokta hatasıyla oluşabilir) `low` döner:
	pencere taban bölgeden büyükse sol/üst kenara yaslanmak, dışarı taşmaktan
	iyidir.
	"""
	if high < low:
		return low
	return low if value < low else (high if value > high else value)


def _as_float(value: Any) -> Optional[float]:
	"""Frappe alanları None/""/Decimal olarak gelebiliyor; hepsini float'a indir."""
	if value is None or value == "":
		return None
	try:
		out = float(value)
	except (TypeError, ValueError):
		return None
	if math.isnan(out) or math.isinf(out):
		return None
	return out


def _get(obj: Any, key: str) -> Any:
	"""Hem dict hem Frappe Document'tan alan oku.

	DocType'lar bugün YOK (tradehub_core/media/pipeline/doctype_specs/ altında şema olarak
	duruyor). Bu modül o yüzden nesne tipine bağlanmaz: dict, dataclass ya da
	ileride gerçek `Media Crop Intent` belgesi — üçü de çalışır.
	"""
	if obj is None:
		return None
	if isinstance(obj, Mapping):
		return obj.get(key)
	return getattr(obj, key, None)


@dataclass(frozen=True)
class Rect:
	"""0-1 normalize dikdörtgen (INV-10)."""

	x: float
	y: float
	w: float
	h: float

	def __post_init__(self) -> None:
		if self.w <= 0 or self.h <= 0:
			raise CropError(f"Dikdörtgenin eni ve boyu pozitif olmalı: w={self.w} h={self.h}")

	@property
	def right(self) -> float:
		return self.x + self.w

	@property
	def bottom(self) -> float:
		return self.y + self.h

	@property
	def cx(self) -> float:
		return self.x + self.w / 2.0

	@property
	def cy(self) -> float:
		return self.y + self.h / 2.0

	def contains(self, other: "Rect", eps: float = 1e-6) -> bool:
		return (
			other.x >= self.x - eps
			and other.y >= self.y - eps
			and other.right <= self.right + eps
			and other.bottom <= self.bottom + eps
		)

	def clamped_to_unit(self) -> "Rect":
		"""Birim kareye sıkıştır — kaynak sınırları dışına asla taşma."""
		w = min(self.w, 1.0)
		h = min(self.h, 1.0)
		return Rect(_clamp(self.x, 0.0, 1.0 - w), _clamp(self.y, 0.0, 1.0 - h), w, h)


@dataclass(frozen=True)
class CropWindow:
	"""Çözülmüş kırpma penceresi. Koordinatlar 0-1 normalize (INV-10)."""

	x: float
	y: float
	w: float
	h: float
	method: str
	profile: str = ""
	# Hedef oran (genişlik/yükseklik, PİKSEL cinsinden). None = serbest oran
	# (contain/pad profilleri): pencere taban bölgenin kendisidir.
	target_ratio: Optional[float] = None
	# Kaynağın piksel oranı. Normalize pencereyi piksele çevirmek ve orana
	# uygunluğu doğrulamak için gerekli — pencerenin kendisi bunu içermez.
	source_ratio: float = 1.0
	confidence: float = 1.0
	approved_by_user: bool = False

	@property
	def rect(self) -> Rect:
		return Rect(self.x, self.y, self.w, self.h)

	@property
	def priority(self) -> int:
		"""Zincirde kaçıncı seviyenin kazandığı (1 = en yüksek)."""
		return METHOD_PRIORITY.get(self.method, len(METHODS) + 1)

	@property
	def is_suggestion(self) -> bool:
		"""UI'da 'öneri' rozeti gösterilmeli mi.

		T-041: smartcrop önerisi `approved_by_user=0` iken de KULLANILIR, ama
		kullanıcıya öneri olduğu söylenir. Onaysız kullanmak ile onaylanmış gibi
		göstermek iki ayrı şeydir; ikincisi kullanıcıyı yanıltır.
		"""
		return self.method == METHOD_SMARTCROP and not self.approved_by_user

	@property
	def effective_ratio(self) -> float:
		"""Pencerenin PİKSEL cinsinden gerçekleşen oranı."""
		return (self.w / self.h) * self.source_ratio

	def to_pixels(self, width: int, height: int) -> Tuple[int, int, int, int]:
		"""Piksel kutusuna çevir: `(left, top, w, h)` — PIL `crop` ile uyumlu.

		Yuvarlama SONDA yapılır ve genişlik/yükseklik en az 1 piksel tutulur.
		Önce yuvarlayıp sonra hesaplamak, küçük türevlerde (80 px sepet küçük
		resmi) oranı gözle görülür biçimde kaydırır.
		"""
		if width <= 0 or height <= 0:
			raise CropError(f"Kaynak boyutu pozitif olmalı: {width}x{height}")
		left = int(round(self.x * width))
		top = int(round(self.y * height))
		w = max(1, int(round(self.w * width)))
		h = max(1, int(round(self.h * height)))
		# Yuvarlama sonrası sağ/alt kenar taşabilir — geri çek.
		left = min(left, width - w)
		top = min(top, height - h)
		return (max(0, left), max(0, top), w, h)

	def as_dict(self) -> dict:
		return {
			"x": self.x,
			"y": self.y,
			"w": self.w,
			"h": self.h,
			"method": self.method,
			"priority": self.priority,
			"profile": self.profile,
			"target_ratio": self.target_ratio,
			"source_ratio": self.source_ratio,
			"confidence": self.confidence,
			"approved_by_user": self.approved_by_user,
			"is_suggestion": self.is_suggestion,
		}


# ─────────────────────────────────────────────────────────────────────────────
# Girdi normalizasyonu
# ─────────────────────────────────────────────────────────────────────────────


def parse_aspect_ratio(value: Any) -> Optional[float]:
	"""'16:9' / '1:1' / 1.7778 → float. Boş, 'free', None → None (serbest oran).

	Media Profile.aspect_ratio alanı metin ('G:Y'), aspect_ratio_value sayı.
	İkisi de buradan geçer; ayrı iki ayrıştırıcı yazmak ikisinin ayrışması
	demektir.
	"""
	if value is None:
		return None
	if isinstance(value, (int, float)) and not isinstance(value, bool):
		out = float(value)
		return out if out > 0 else None
	text = str(value).strip().lower()
	if text in ("", "free", "none", "null", "0", "0:0"):
		return None
	if ":" in text or "/" in text:
		sep = ":" if ":" in text else "/"
		parts = text.split(sep)
		if len(parts) != 2:
			raise CropError(f"Oran çözümlenemedi: {value!r}")
		try:
			num, den = float(parts[0]), float(parts[1])
		except ValueError:
			raise CropError(f"Oran çözümlenemedi: {value!r}")
		if num <= 0 or den <= 0:
			return None
		return num / den
	try:
		out = float(text)
	except ValueError:
		raise CropError(f"Oran çözümlenemedi: {value!r}")
	return out if out > 0 else None


def source_ratio_of(asset: Any) -> float:
	"""Kaynağın piksel oranı (genişlik/yükseklik).

	`source_ratio` doğrudan verilmişse o kullanılır; yoksa `width`/`height`'tan
	türetilir. İkisi de yoksa 1.0 (kare) varsayılır — ve bu **varsayım olarak
	işaretlenir**: kare varsaymak, oranı bilmeden kırpmaktan iyidir ama doğru
	değildir. Çağıranın oranı bilmesi beklenir; Media Source.width/height zaten
	yükleme sırasında ölçülür.
	"""
	direct = _as_float(_get(asset, "source_ratio"))
	if direct is not None:
		# Açıkça yazılmış ama geçersiz bir oran SESSİZCE düzeltilmez: 1.0'a
		# düşmek, kare olmayan bir görseli kare sanıp kadrajı kaydırırdı.
		if direct <= 0:
			raise CropError(f"Kaynak oranı pozitif olmalı: {direct}")
		return direct
	w = _as_float(_get(asset, "width"))
	h = _as_float(_get(asset, "height"))
	if w is not None and h is not None:
		if w <= 0 or h <= 0:
			raise CropError(f"Kaynak boyutu pozitif olmalı: {w}x{h}")
		return w / h
	return 1.0


def safe_region_of(intent: Any) -> Optional[Rect]:
	"""Güvenli alanı `Rect` olarak döndür; tanımlı değilse None.

	Tam kadraj (0,0,1,1) güvenli alan sayılmaz: "her yer güvenli" ile "güvenli
	alan belirtilmemiş" aynı kapıya çıkar ve ikisini ayırmak zincirde gereksiz
	bir seviye üretir.
	"""
	if intent is None:
		return None
	x = _as_float(_get(intent, "safe_x"))
	y = _as_float(_get(intent, "safe_y"))
	w = _as_float(_get(intent, "safe_w"))
	h = _as_float(_get(intent, "safe_h"))
	if None in (x, y, w, h):
		return None
	if w <= 0 or h <= 0:
		return None
	rect = Rect(x, y, w, h).clamped_to_unit()
	if (
		abs(rect.x) < 1e-6
		and abs(rect.y) < 1e-6
		and abs(rect.w - 1.0) < 1e-6
		and abs(rect.h - 1.0) < 1e-6
	):
		return None
	return rect


def zoom_region_of(intent: Any, width: Any = None, height: Any = None) -> Optional[Rect]:
	"""Zoom + pan merkezinden taban bölgeyi üret; zoom yazılmamışsa None.

	Stüdyo kadrajını `cropWindow(zoomBase(zoom, center), targetAR, focal)` ile
	kurar (`crop_geometry.ts::zoom_base` — panel vendor'ı). Yük eskiden yalnız
	odağı taşıdığı için sunucu pencereyi daima tam kadrajdan kuruyor ve
	kullanıcının yakınlaştırması SESSİZCE atılıyordu (ölçüldü:
	`cropPixelParity` B sınıfı 120 vakanın 119'unda 7391 px'e kadar sapma).
	Bu fonksiyon o kaybı kapatır: niyet `zoom`/`center_x`/`center_y`
	taşıyorsa taban bölge burada, `crop_geometry.py::zoom_base` ile AYNI işlem
	sırasıyla yeniden kurulur.

	`crop_geometry` buradan import EDİLMEZ (modül başlığındaki saflık sözü +
	parite üreticisinin dosya-yolundan yüklemesi); matematik piksel uzayında
	birebir aynı sırayla tekrarlanır ve `tests/test_crop_intent_zoom.py`
	iki uygulamayı aynı girdilerle karşılaştırır.

	Kurallar:
	  * `zoom` < 1 → yazılmamış sayılır ve None döner. Frappe `Float` kolonu
	    `NOT NULL DEFAULT 0` olduğu için "hiç yazılmadı" DB'den 0 olarak döner;
	    0'ı hata saymak, zoom kullanmayan her kaydı kırardı (safe alanla aynı
	    gerekçe, bkz. `media_crop_intent.py::_validate_safe_box`).
	  * `center_x`/`center_y` yoksa None — yarım yazılmış üçlü sessizce bir
	    alt seviyeye düşer (`override_for` ile aynı okuma-tarafı kuralı).
	  * `width`/`height` (piksel) verilmişse `MIN_EDGE_PX` tabanı da uygulanır
	    — `zoom_base` 1 px'in altına inen taban bölgeyi 1 px'e sabitler ve
	    dejenere kaynakta (3×2 px) bu fark penceresi değiştirir. Ölçü
	    bilinmiyorsa taban uygulanamaz; normalize kurulum kullanılır.
	  * Tam kadraja çözülen bölge (zoom=1) None döner — `safe_region_of` ile
	    aynı kural: "her yeri göster" ile "taban belirtilmemiş" aynı kapıya
	    çıkar ve ayrı tutmak zincire gereksiz bir seviye eklerdi.
	"""
	z = _as_float(_get(intent, "zoom"))
	if z is None or z < ZOOM_MIN:
		return None
	cx = _as_float(_get(intent, "center_x"))
	cy = _as_float(_get(intent, "center_y"))
	if cx is None or cy is None:
		return None
	z = _clamp(z, ZOOM_MIN, ZOOM_MAX)
	cx = _clamp(cx, 0.0, 1.0)
	cy = _clamp(cy, 0.0, 1.0)

	w = _as_float(width)
	h = _as_float(height)
	if w is not None and h is not None and w > 0 and h > 0:
		# Piksel uzayı — `crop_geometry.py::zoom_base` ile birebir aynı sıra.
		bw = w / z
		bh = h / z
		min_w = 1.0 if w > 1.0 else w  # MIN_EDGE_PX
		min_h = 1.0 if h > 1.0 else h
		if bw < min_w:
			bw = min_w
		if bh < min_h:
			bh = min_h
		if bw > w:
			bw = w
		if bh > h:
			bh = h
		px = cx * w
		py = cy * h
		x = _clamp(px - bw / 2.0, 0.0, w - bw)
		y = _clamp(py - bh / 2.0, 0.0, h - bh)
		rect = Rect(x / w, y / h, bw / w, bh / h).clamped_to_unit()
	else:
		bw = 1.0 / z
		bh = 1.0 / z
		x = _clamp(cx - bw / 2.0, 0.0, 1.0 - bw)
		y = _clamp(cy - bh / 2.0, 0.0, 1.0 - bh)
		rect = Rect(x, y, bw, bh).clamped_to_unit()

	if (
		abs(rect.x) < 1e-6
		and abs(rect.y) < 1e-6
		and abs(rect.w - 1.0) < 1e-6
		and abs(rect.h - 1.0) < 1e-6
	):
		return None
	return rect


def focal_of(intent: Any) -> Optional[Tuple[float, float]]:
	"""Odak noktası (0-1). Yazılmamışsa None — merkez (0.5, 0.5) DEĞİL.

	Ayrım önemli: kullanıcının merkezi seçmesi ile hiç seçmemiş olması zincirde
	farklı seviyelerdir (3 vs 5). İkisini birleştirmek, "odak noktası var" diye
	smartcrop önerisini gereksiz yere devre dışı bırakır.
	"""
	if intent is None:
		return None
	x = _as_float(_get(intent, "focal_x"))
	y = _as_float(_get(intent, "focal_y"))
	if x is None or y is None:
		return None
	return (_clamp(x, 0.0, 1.0), _clamp(y, 0.0, 1.0))


def override_for(intent: Any, profile_key: str) -> Optional[Rect]:
	"""Bu profil için elle çizilmiş kırpma varsa `Rect` olarak döndür.

	`overrides` bir child table (Media Crop Override) ya da düz liste/sözlük
	olabilir; üçü de desteklenir çünkü DocType henüz yok ve testler düz veri
	kullanıyor.
	"""
	if intent is None or not profile_key:
		return None
	rows = _get(intent, "overrides") or _get(intent, "crop_overrides") or []
	if isinstance(rows, Mapping):
		rows = [dict(v, profile=k) if isinstance(v, Mapping) else v for k, v in rows.items()]
	for row in rows:
		key = _get(row, "profile") or _get(row, "profile_key")
		if str(key or "") != profile_key:
			continue
		x = _as_float(_get(row, "x"))
		y = _as_float(_get(row, "y"))
		w = _as_float(_get(row, "w"))
		h = _as_float(_get(row, "h"))
		if None in (x, y, w, h) or w <= 0 or h <= 0:
			# Yarım yazılmış override sessizce KULLANILMAZ; zincir bir alt
			# seviyeye düşer. Yanlış kadraj, kadrajsızlıktan kötüdür.
			continue
		return Rect(x, y, w, h).clamped_to_unit()
	return None


def smartcrop_suggestion_of(intent: Any) -> Optional[Rect]:
	"""Smartcrop'un önerdiği bölge — `method='smartcrop'` ve bölge yazılıysa.

	Öneri iki biçimde gelebilir: ayrı `suggested_*` alanları, ya da
	`method='smartcrop'` iken güvenli alanın kendisi (saliency kutusu). İlki
	tercih edilir; ikincisi geriye dönük uyumluluk içindir.
	"""
	if intent is None:
		return None
	x = _as_float(_get(intent, "suggested_x"))
	y = _as_float(_get(intent, "suggested_y"))
	w = _as_float(_get(intent, "suggested_w"))
	h = _as_float(_get(intent, "suggested_h"))
	if None not in (x, y, w, h) and w > 0 and h > 0:
		return Rect(x, y, w, h).clamped_to_unit()
	if str(_get(intent, "method") or "") == METHOD_SMARTCROP:
		return safe_region_of(intent)
	return None


# ─────────────────────────────────────────────────────────────────────────────
# Çekirdek geometri — simülatörün cropWindow()'u, normalize uzayda
# ─────────────────────────────────────────────────────────────────────────────


def _cover_window(base: Rect, target_ratio: Optional[float], source_ratio: float,
				  focal: Tuple[float, float]) -> Rect:
	"""Taban bölge içinde, hedef orana uyan EN BÜYÜK pencereyi odak etrafında kur.

	Adımlar (simülatörle birebir):
	  1. Hedef oran yoksa taban bölgenin kendisi döner (contain/pad).
	  2. Hedef oran normalize uzaya çevrilir: `R = target_ratio / source_ratio`.
	  3. Taban bölge hedeften genişse yükseklik doldurulur, değilse genişlik.
	  4. Pencere odak noktasında merkezlenir.
	  5. Taban bölge sınırlarına sıkıştırılır (kenar sıkıştırma) — odak köşede
	     olsa bile pencere dışarı taşmaz.
	"""
	if target_ratio is None:
		return base
	if source_ratio <= 0:
		raise CropError(f"Kaynak oranı pozitif olmalı: {source_ratio}")

	r = target_ratio / source_ratio  # normalize uzaydaki hedef oran
	if base.w / base.h > r:
		h = base.h
		w = h * r
	else:
		w = base.w
		h = w / r

	# Kayan nokta artığı taban bölgeyi birkaç ULP aşabilir; kırp.
	w = min(w, base.w)
	h = min(h, base.h)

	x = focal[0] - w / 2.0
	y = focal[1] - h / 2.0
	x = _clamp(x, base.x, base.x + base.w - w)
	y = _clamp(y, base.y, base.y + base.h - h)
	return Rect(x, y, w, h)


def _fit_ratio_keeping_center(rect: Rect, target_ratio: Optional[float],
							  source_ratio: float, bounds: Rect) -> Rect:
	"""Elle çizilmiş bir dikdörtgeni hedef orana OTURT, merkezini koru.

	Override ve smartcrop önerisi kullanıcı/algoritma tarafından serbest oranda
	çizilmiş olabilir; profil ise belirli bir oran ister. T-041 kabul kriteri
	"pencere istenen orana tam uyuyor" diyor, bu yüzden oran zorlanır:
	dikdörtgen **küçültülerek** orana oturtulur (büyütmek, kullanıcının dışarıda
	bıraktığı alanı kadraja sokar — istemediği şeyi göstermek olur), sonra
	merkez korunarak sınırlara sıkıştırılır.
	"""
	if target_ratio is None:
		return Rect(*_intersect_or_self(rect, bounds))
	r = target_ratio / source_ratio
	if rect.w / rect.h > r:
		h = rect.h
		w = h * r
	else:
		w = rect.w
		h = w / r
	w = min(w, bounds.w)
	h = min(h, bounds.h)
	# Oran, sınırlara sığdırmak için w/h kırpıldıysa bozulmuş olabilir — orana
	# göre yeniden dengele.
	if w / h > r:
		w = h * r
	else:
		h = w / r
	x = _clamp(rect.cx - w / 2.0, bounds.x, bounds.x + bounds.w - w)
	y = _clamp(rect.cy - h / 2.0, bounds.y, bounds.y + bounds.h - h)
	return Rect(x, y, w, h)


def _intersect_or_self(rect: Rect, bounds: Rect) -> Tuple[float, float, float, float]:
	"""`rect`'i `bounds` içine sıkıştır (boyutu koruyarak kaydır, gerekirse kırp)."""
	w = min(rect.w, bounds.w)
	h = min(rect.h, bounds.h)
	x = _clamp(rect.x, bounds.x, bounds.x + bounds.w - w)
	y = _clamp(rect.y, bounds.y, bounds.y + bounds.h - h)
	return (x, y, w, h)


# ─────────────────────────────────────────────────────────────────────────────
# Öncelik zinciri
# ─────────────────────────────────────────────────────────────────────────────


def resolve_crop(asset: Any, profile: Any, intent: Any = None,
				 confidence_threshold: Optional[float] = None) -> CropWindow:
	"""Bir varlık + profil için kırpma penceresini çöz. **Zincirin tek girişi.**

	Parametreler
	------------
	asset
	    `width`/`height` (ya da `source_ratio`) taşıyan herhangi bir nesne;
	    ayrıca `crop_intent` alanı varsa `intent` oradan okunur.
	profile
	    `profile_key` + `aspect_ratio` (ya da `aspect_ratio_value`) ve `fit`
	    taşıyan nesne. `fit` 'contain'/'pad' ise oran ZORLANMAZ: kırpma yoktur,
	    pencere taban bölgenin kendisidir.
	intent
	    `Media Crop Intent` karşılığı. Verilmezse `asset.crop_intent` denenir.
	confidence_threshold
	    Smartcrop eşiği. Verilmezse `SMARTCROP_CONFIDENCE_THRESHOLD` (ÖLÇÜLMEDİ).

	Dönüş
	-----
	`CropWindow` — 0-1 normalize, daima kaynak sınırları içinde, hedef oran
	verilmişse ona uyar.
	"""
	if intent is None:
		intent = _get(asset, "crop_intent")

	profile_key = str(_get(profile, "profile_key") or _get(profile, "name") or "")
	fit = str(_get(profile, "fit") or "cover").lower()

	ratio_raw = _get(profile, "aspect_ratio_value")
	if ratio_raw in (None, "", 0):
		ratio_raw = _get(profile, "aspect_ratio")
	target_ratio = parse_aspect_ratio(ratio_raw)

	# contain/pad: görsel kırpılmaz, oran letterbox ile sağlanır. Kırpma
	# penceresi bu durumda "neyi göstereceğiz" değil "neyi koruyacağız"
	# sorusudur — cevap taban bölgenin tamamıdır.
	if fit in ("contain", "pad"):
		target_ratio = None

	src_ratio = source_ratio_of(asset)
	if src_ratio <= 0:
		raise CropError(f"Kaynak oranı pozitif olmalı: {src_ratio}")

	threshold = (
		confidence_threshold
		if confidence_threshold is not None
		else SMARTCROP_CONFIDENCE_THRESHOLD
	)
	full = Rect(*FULL_FRAME)
	safe = safe_region_of(intent)
	# Zoom + pan merkezi, güvenli alanla AYNI role sahiptir: pencerenin
	# kurulacağı taban bölge. İkisi birden yazılmışsa zoom kazanır — panel
	# güvenli alanı zoom tabanından TÜRETİP gönderiyor (`useCropStudio.js::
	# safeArea`), yani ikisi aynı kadrajın iki yazımıdır ve zoom, 6 basamağa
	# yuvarlanmış türetilmiş kutu yerine niyetin kendisidir.
	zoom_region = zoom_region_of(intent, _get(asset, "width"), _get(asset, "height"))
	base_region = zoom_region if zoom_region is not None else safe
	focal = focal_of(intent)
	confidence = _as_float(_get(intent, "confidence"))
	approved = bool(_get(intent, "approved_by_user"))

	def _win(rect: Rect, method: str, conf: float) -> CropWindow:
		rect = rect.clamped_to_unit()
		return CropWindow(
			x=rect.x, y=rect.y, w=rect.w, h=rect.h,
			method=method, profile=profile_key,
			target_ratio=target_ratio, source_ratio=src_ratio,
			confidence=conf, approved_by_user=approved,
		)

	# ── 1. Profil bazlı manuel override ────────────────────────────────
	ovr = override_for(intent, profile_key)
	if ovr is not None:
		return _win(_fit_ratio_keeping_center(ovr, target_ratio, src_ratio, full),
					METHOD_OVERRIDE, 1.0)

	# ── 2. Taban bölge (zoom ya da güvenli alan) + odak noktası ────────
	if base_region is not None and focal is not None:
		# Odak, taban bölgenin dışında olabilir (kullanıcı ikisini ayrı ayrı
		# taşımış). Sıkıştır: taban bölge bir KISIT, odak bir TERCİHTİR.
		f = (
			_clamp(focal[0], base_region.x, base_region.right),
			_clamp(focal[1], base_region.y, base_region.bottom),
		)
		return _win(
			_cover_window(base_region, target_ratio, src_ratio, f), METHOD_SAFE_FOCAL, 1.0
		)

	# ── 3. Genel odak noktası ──────────────────────────────────────────
	if focal is not None:
		return _win(_cover_window(full, target_ratio, src_ratio, focal), METHOD_FOCAL, 1.0)

	# ── 4. Smartcrop önerisi (güven >= eşik) ───────────────────────────
	suggestion = smartcrop_suggestion_of(intent)
	if suggestion is not None and confidence is not None and confidence >= threshold:
		return _win(
			_fit_ratio_keeping_center(suggestion, target_ratio, src_ratio, full),
			METHOD_SMARTCROP,
			confidence,
		)

	# ── 5. Taban bölge var ama odak yok: bölgenin merkezi ──────────────
	# Ayrı bir seviye değil, 5. seviyenin taban bölgesi değişir. Zoom ya da
	# güvenli alan yazılmışken tüm kadrajın merkezinden kırpmak, kullanıcının
	# işaretlediği bölgeyi görmezden gelmek olurdu.
	base = base_region if base_region is not None else full
	return _win(_cover_window(base, target_ratio, src_ratio, (base.cx, base.cy)),
				METHOD_CENTER, 1.0)


def resolve_crop_pixels(asset: Any, profile: Any, width: int, height: int,
						intent: Any = None) -> Tuple[int, int, int, int]:
	"""`resolve_crop` + piksel kutusu. PIL `Image.crop` için `(l, t, r, b)` DEĞİL,
	`(left, top, w, h)` döner — `to_pixels` ile aynı sözleşme."""
	win = resolve_crop(asset, profile, intent=intent)
	return win.to_pixels(width, height)


def verify_window(win: CropWindow, *, tolerance: float = RATIO_TOLERANCE) -> None:
	"""Pencereyi kabul kriterlerine karşı doğrula; ihlalde `CropError`.

	Üretim yolunda ucuz bir emniyet ağı, testlerde ortak doğrulayıcı: aynı
	kontrolü iki yerde ayrı yazmak, birinin gevşemesi demektir.
	"""
	if not (0.0 - EPS <= win.x and 0.0 - EPS <= win.y):
		raise CropError(f"Pencere kaynak dışında (sol/üst): {win.as_dict()}")
	if win.x + win.w > 1.0 + 1e-6 or win.y + win.h > 1.0 + 1e-6:
		raise CropError(f"Pencere kaynak dışında (sağ/alt): {win.as_dict()}")
	if win.w <= 0 or win.h <= 0:
		raise CropError(f"Pencere boyutu pozitif değil: {win.as_dict()}")
	if win.target_ratio is not None:
		got = win.effective_ratio
		sapma = abs(got - win.target_ratio) / win.target_ratio
		if sapma > tolerance:
			raise CropError(
				f"Oran sapması %{sapma * 100:.3f} > %{tolerance * 100:.3f}: "
				f"hedef={win.target_ratio:.6f} gerçekleşen={got:.6f}"
			)
