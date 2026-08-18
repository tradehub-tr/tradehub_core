"""T-100 — Crop Studio'nun saf geometrisi (PİKSEL uzayı).

Bu modül tek bir söz verir: **aynı girdi, TypeScript ve Python'da aynı sayı.**
Kullanıcı tarayıcıda bir kadraj çizer, sunucu o kadrajı keser. İkisi ayrışırsa
kullanıcı önizlemede gördüğünden başka bir görsel alır — ve bu, kullanıcının
"kırpma bozuk" diye bildireceği ama kimsenin yeniden üretemeyeceği türden bir
hatadır. Bu yüzden ikizi `crop_geometry.ts` satır satır aynı sırayla yazıldı ve
`tradehub_core/tests/fixtures/crop_vectors.json` iki tarafı da aynı vektörlerle bağlar.

`crop.py` ile ilişkisi — ikisi AYNI ŞEY DEĞİL
---------------------------------------------
`tradehub_core/media/pipeline/core/crop.py` (T-041) **niyet** çözer: beş kaynaklı öncelik
zinciri (override → güvenli alan+odak → odak → smartcrop → merkez), 0-1
NORMALİZE uzayda, çünkü kadraj farklı piksel boyutlarındaki türevlerde
kaymamalı (INV-10).

Bu modül **etkileşim** çözer: kullanıcı fareyle sürüklerken, zoom yaparken,
tutamağı çekerken pencere nereye gider? Bu iş piksel uzayında yapılır, çünkü
tutamak 8 pikselliktir ve "1 piksel kaydır" normalize uzayda bir sayı değildir.

İkisi çakışmaz, üst üste biner: `crop.py` kadrajın NEREDE başlayacağını söyler,
bu modül kullanıcının onu NASIL taşıyacağını. Ortak matematik — orana oturtma ve
kenar sıkıştırma — `crop.py::_cover_window` ile cebirsel olarak aynıdır; fark
yalnız uzaydır (normalize `R = AR / kaynak_oranı`, burada doğrudan `AR`).
`tests/test_crop_geometry.py::CaprazTutarlilikTesti` iki modülün aynı pencereyi
verdiğini doğrular. `crop.py` YENİDEN YAZILMADI.

Parite kuralları (bozarsan TS ile ayrışırsın)
---------------------------------------------
1. Tüm aritmetik IEEE-754 double. `int` bölmesi, `Fraction`, `decimal` YOK.
2. `round()` KULLANILMAZ — Python bankacı yuvarlaması yapar (`round(0.5) == 0`),
   JS `Math.round` yukarı yuvarlar (`Math.round(0.5) === 1`). Yerine iki tarafta
   da `floor(v + 0.5)` (`_round_half_up`).
3. İşlem SIRASI iki dosyada birebir aynı. `a*b/c` ile `a*(b/c)` farklı sayıdır.
4. `min`/`max` yerine açık `clamp()` — okunurluk değil, parite için: tek bir
   karşılaştırma zinciri iki dilde de aynı davranır.
5. Bağımlılık YOK: `frappe`, `PIL`, `numpy` — hiçbiri. Yalnız `math`.

Ölçüm notu: parite İDDİA DEĞİL, ÖLÇÜLDÜ. `tests/tools/run_ts_vectors.ts`
node ile TS ikizini aynı vektörler üzerinde koşturur; sonuç
`tests/test_crop_geometry.py` çıktısında raporlanır.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Sabitler — TS ikizinde AYNI değerlerle tekrarlanır
# ─────────────────────────────────────────────────────────────────────────────

# "Aynı sayı" eşiği. Kadraj matematiği bölme içerir; tam eşitlik aranmaz.
EPS: float = 1e-9

# Diller arası kabul edilen azami sapma (piksel). T-100 kabul kriteri.
# Uygulamada ölçülen sapma bundan çok daha küçüktür (bkz. test çıktısı), ama
# sözleşme 0,5 px'tir: yarım pikselden fazla sapma, yuvarlama sonrası FARKLI bir
# piksel kutusu demektir ve orada "yaklaşık aynı" diye bir şey yoktur.
PARITY_TOLERANCE_PX: float = 0.5

# Zoom sınırları. ZOOM_MIN=1 → kaynağın dışına çıkılamaz; kırpma penceresi
# olmayan pikseli gösteremez. ZOOM_MAX ÖLÇÜLMEDİ (kullanılabilirlik testi
# yapılmadı); 16, kısa kenar p50=1.120 px olan bir kaynakta 70 px'lik bir
# bölgeye inmeye karşılık gelir ve pratikte tutamakların anlamlı kaldığı
# sınırdır. Kalibre edilirse burası ve TS ikizi BİRLİKTE değişmelidir.
ZOOM_MIN: float = 1.0
ZOOM_MAX: float = 16.0

# Bir pencerenin/taban bölgenin en küçük kenarı. Sıfır genişlikte kadraj
# geçerli bir görsel üretmez; 1 px üretir.
MIN_EDGE_PX: float = 1.0

# ratio_fit kipleri.
FIT_INSIDE: str = "inside"  # contain — hedef orana uyan EN BÜYÜK iç dikdörtgen
FIT_OUTSIDE: str = "outside"  # cover — hedef orana uyan EN KÜÇÜK dış dikdörtgen

FIT_MODES: Tuple[str, ...] = (FIT_INSIDE, FIT_OUTSIDE)


class CropGeometryError(ValueError):
	"""Geometri girdisi geçersiz — pencere üretilemez.

	TS ikizinde `CropGeometryError extends Error` olarak karşılanır; vektör
	dosyasında `"error": true` ile işaretlenen vakalar iki tarafta da ATMALIDIR.
	Sessizce bir varsayılana düşmek, kullanıcıya yanlış kadrajı doğruymuş gibi
	göstermenin en kısa yoludur.
	"""


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────────────────────


def clamp(value: float, low: float, high: float) -> float:
	"""`value`'yu [low, high] aralığına sıkıştır.

	`high < low` ise `low` döner. Bu durum kayan nokta artığıyla oluşabilir
	(pencere taban bölgeden bir kaç ULP büyük); sol/üst kenara yaslanmak dışarı
	taşmaktan iyidir.

	Aralık içindeki bir değer DEĞİŞMEDEN döner — bit düzeyinde aynı float. Bu,
	`clamp_window`'un geçerli bir pencerede tam no-op olmasını sağlar ve
	pariteyi korur.
	"""
	if high < low:
		return low
	if value < low:
		return low
	if value > high:
		return high
	return value


def _round_half_up(value: float) -> int:
	"""JS `Math.round` ile birebir aynı yuvarlama.

	Python'un `round()`'u bankacı yuvarlaması yapar: `round(0.5) == 0`,
	`round(2.5) == 2`. JS `Math.round(0.5) === 1`. Bu fark 80 px'lik sepet
	küçük resminde bir piksel, ama iki dilin FARKLI kutu üretmesi demektir.
	`floor(v + 0.5)` ikisinde de aynıdır (negatif yarımlar dahil:
	`Math.round(-0.5) === -0`, `floor(-0.5 + 0.5) == 0`).
	"""
	return int(math.floor(value + 0.5))


def _require_finite(value: float, name: str) -> float:
	"""Sayı mı, sonlu mu? NaN/inf kadrajı sessizce zehirler — burada durdur."""
	try:
		out = float(value)
	except (TypeError, ValueError):
		raise CropGeometryError(f"{name} sayı olmalı: {value!r}")
	if math.isnan(out) or math.isinf(out):
		return _raise_not_finite(name, value)
	return out


def _raise_not_finite(name: str, value: object) -> float:
	raise CropGeometryError(f"{name} sonlu bir sayı olmalı: {value!r}")


def _require_positive(value: float, name: str) -> float:
	out = _require_finite(value, name)
	if out <= 0.0:
		raise CropGeometryError(f"{name} pozitif olmalı: {out}")
	return out


# ─────────────────────────────────────────────────────────────────────────────
# Rect — piksel uzayında dikdörtgen
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rect:
	"""Piksel uzayında dikdörtgen. Kaynağın sol-üst köşesi (0, 0).

	`crop.py::Rect` 0-1 normalize çalışır; bu ikisi bilerek ayrı tiplerdir.
	Aynı ada sahip iki farklı uzayı tek tipte toplamak, birim hatasının en
	sessiz biçimidir (normalize 0,5'i piksel 0,5 sanmak).
	"""

	x: float
	y: float
	w: float
	h: float

	def __post_init__(self) -> None:
		for name in ("x", "y", "w", "h"):
			_require_finite(getattr(self, name), f"Rect.{name}")
		if self.w <= 0.0 or self.h <= 0.0:
			raise CropGeometryError(f"Dikdörtgenin eni ve boyu pozitif olmalı: w={self.w} h={self.h}")

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

	@property
	def ratio(self) -> float:
		"""Piksel cinsinden en-boy oranı (genişlik/yükseklik)."""
		return self.w / self.h

	def as_tuple(self) -> Tuple[float, float, float, float]:
		return (self.x, self.y, self.w, self.h)

	def as_dict(self) -> dict:
		return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

	@staticmethod
	def from_any(value: object) -> "Rect":
		"""dict / dizi / Rect → Rect. Vektör dosyası dict taşır."""
		if isinstance(value, Rect):
			return value
		if isinstance(value, dict):
			return Rect(float(value["x"]), float(value["y"]), float(value["w"]), float(value["h"]))
		if isinstance(value, (list, tuple)) and len(value) == 4:
			return Rect(float(value[0]), float(value[1]), float(value[2]), float(value[3]))
		raise CropGeometryError(f"Rect'e çevrilemedi: {value!r}")


# ─────────────────────────────────────────────────────────────────────────────
# ratioFit — orana oturtma
# ─────────────────────────────────────────────────────────────────────────────


def ratio_fit(w: float, h: float, target_ar: Optional[float], mode: str = FIT_INSIDE) -> Tuple[float, float]:
	"""`w x h` kutusunu `target_ar` oranına oturt; yeni `(w, h)` döndür.

	`mode`:
	  * ``inside``  (contain) — kutunun İÇİNE sığan en büyük hedef-oranlı
	    dikdörtgen. Kırpma bunu kullanır: pencere taban bölgeden taşamaz.
	  * ``outside`` (cover) — kutuyu KAPSAYAN en küçük hedef-oranlı dikdörtgen.
	    "kaynağı doldur" davranışı ve zoom-to-fill için.

	`target_ar is None` → serbest oran, kutu değişmeden döner. Bu, kilidi açık
	tutamak sürüklemesidir ve bir hata değildir.

	`inside` kipinde sonuç, kayan nokta artığına karşı kutuya geri kırpılır
	(`min`). Bir kaç ULP taşma, `clamp_window` içinde pencereyi kenara
	yapıştırır ve kullanıcı kadrajın "kaydığını" görür.
	"""
	bw = _require_positive(w, "w")
	bh = _require_positive(h, "h")
	if target_ar is None:
		return (bw, bh)
	ar = _require_positive(target_ar, "target_ar")
	if mode not in FIT_MODES:
		raise CropGeometryError(f"Bilinmeyen fit kipi: {mode!r} (beklenen: {FIT_MODES})")

	if mode == FIT_INSIDE:
		if bw / bh > ar:
			out_h = bh
			out_w = out_h * ar
		else:
			out_w = bw
			out_h = out_w / ar
		# Kutunun dışına taşma — yalnız kayan nokta artığı kadar olabilir.
		if out_w > bw:
			out_w = bw
		if out_h > bh:
			out_h = bh
		return (out_w, out_h)

	# FIT_OUTSIDE
	if bw / bh > ar:
		out_w = bw
		out_h = out_w / ar
	else:
		out_h = bh
		out_w = out_h * ar
	if out_w < bw:
		out_w = bw
	if out_h < bh:
		out_h = bh
	return (out_w, out_h)


# ─────────────────────────────────────────────────────────────────────────────
# clampWindow — pencereyi sınırların içine hapset
# ─────────────────────────────────────────────────────────────────────────────


def clamp_window(win: Rect, bounds: Rect, keep_ratio: bool = False) -> Rect:
	"""`win`'i `bounds` içine sıkıştır.

	Gövde sürüklemesinin ve tutamak çekmesinin tek çıkış kapısı burasıdır:
	kullanıcı pencereyi kaynağın dışına iteklediğinde pencere KAYAR, küçülmez.
	Küçültmek, en-boy kilidini sessizce bozar ve kullanıcı 1:1 kilitliyken
	1,03:1 bir kadraj alır.

	`keep_ratio=False` (varsayılan): pencere sınırlardan büyükse kenarlar
	BAĞIMSIZ kırpılır — serbest oranlı kırpmada doğru davranış.

	`keep_ratio=True`: iki kenar da AYNI çarpanla küçültülür, oran korunur.
	En-boy kilidi açıkken kullanılması gereken kip budur.

	Sınırların içinde duran bir pencere BİT DÜZEYİNDE değişmeden döner —
	`clamp` aralık içi değerleri olduğu gibi geçirir. Bu, fonksiyonun
	`crop_window` içinde no-op olarak çağrılabilmesini ve parite vektörlerinin
	bozulmamasını sağlar.
	"""
	w = win.w
	h = win.h

	if keep_ratio:
		# Tek çarpan: hangi eksen daha çok taşıyorsa o belirler.
		scale = 1.0
		if w > bounds.w:
			scale = bounds.w / w
		if h > bounds.h:
			other = bounds.h / h
			if other < scale:
				scale = other
		if scale < 1.0:
			w = w * scale
			h = h * scale
			# Çarpanın kendisi bölmeden geldiği için sonuç sınırı bir kaç ULP
			# aşabilir; geri kırp.
			if w > bounds.w:
				w = bounds.w
			if h > bounds.h:
				h = bounds.h
	else:
		if w > bounds.w:
			w = bounds.w
		if h > bounds.h:
			h = bounds.h

	x = clamp(win.x, bounds.x, bounds.x + bounds.w - w)
	y = clamp(win.y, bounds.y, bounds.y + bounds.h - h)
	return Rect(x, y, w, h)


# ─────────────────────────────────────────────────────────────────────────────
# zoomBase — zoom + pan → taban bölge
# ─────────────────────────────────────────────────────────────────────────────


def zoom_base(source_w: float, source_h: float, zoom: float, center_x: float, center_y: float) -> Rect:
	"""Zoom ve pan merkezinden **taban bölgeyi** (görünür kaynak parçası) üret.

	`zoom=1` → kaynağın tamamı. `zoom=z` → kenarları `1/z` oranında küçülmüş,
	`(center_x, center_y)` etrafında ortalanmış ve kaynağın içine sıkıştırılmış
	bölge.

	`center_x/center_y` **0-1 normalize** (kaynağın tamamına göre). Piksel değil:
	pan merkezi kullanıcı niyetidir ve türevler arasında taşınabilir olmalıdır —
	`crop.py`'nin odak noktasıyla aynı birim, bilerek.

	Zoom `[ZOOM_MIN, ZOOM_MAX]` aralığına ve ayrıca `MIN_EDGE_PX`'e göre
	sıkıştırılır: 1 px'in altına inen bir taban bölge kırpılabilir bir görsel
	değildir. Sıkıştırma SESSİZDİR ve olması gerektiği gibidir — kullanıcı fare
	tekerleğini çevirmeye devam ettiğinde hata görmemeli, kadraj durmalıdır.

	Dönen bölge `crop_window`'a doğrudan `base` olarak verilir.
	"""
	sw = _require_positive(source_w, "source_w")
	sh = _require_positive(source_h, "source_h")
	z = clamp(_require_finite(zoom, "zoom"), ZOOM_MIN, ZOOM_MAX)

	bw = sw / z
	bh = sh / z

	# 1 px tabanı — kaynak zaten 1 px'ten darsa kaynağın kendisi.
	min_w = MIN_EDGE_PX if sw > MIN_EDGE_PX else sw
	min_h = MIN_EDGE_PX if sh > MIN_EDGE_PX else sh
	if bw < min_w:
		bw = min_w
	if bh < min_h:
		bh = min_h
	if bw > sw:
		bw = sw
	if bh > sh:
		bh = sh

	cx = clamp(_require_finite(center_x, "center_x"), 0.0, 1.0) * sw
	cy = clamp(_require_finite(center_y, "center_y"), 0.0, 1.0) * sh

	x = clamp(cx - bw / 2.0, 0.0, sw - bw)
	y = clamp(cy - bh / 2.0, 0.0, sh - bh)
	return Rect(x, y, bw, bh)


def zoom_from_base(source_w: float, source_h: float, base: Rect) -> float:
	"""`zoom_base`'in tersi: taban bölgeden zoom çarpanını geri oku.

	Kullanıcı pencereyi tutamaktan çekip taban bölgeyi değiştirdiğinde zoom
	kaydırıcısının doğru yere gitmesi için gerekli. Genişlik üzerinden okunur;
	`zoom_base` iki kenarı da aynı çarpanla küçülttüğü için yükseklikten okumak
	aynı sayıyı verir (bölme artığı kadar farkla).
	"""
	sw = _require_positive(source_w, "source_w")
	_require_positive(source_h, "source_h")
	return clamp(sw / base.w, ZOOM_MIN, ZOOM_MAX)


# ─────────────────────────────────────────────────────────────────────────────
# cropWindow — çekirdek
# ─────────────────────────────────────────────────────────────────────────────


def crop_window(
	source_w: float,
	source_h: float,
	base: Rect,
	target_ar: Optional[float],
	focal_x: float,
	focal_y: float,
) -> Rect:
	"""Taban bölge içinde, hedef orana uyan EN BÜYÜK pencereyi odakta merkezle.

	Kaynak dokümandaki `docs/simulator.html::cropWindow()` fonksiyonunun
	referans uygulaması. Adımlar (sıra pariteyi belirler, değiştirme):

	  1. Taban bölge kaynağın içine sıkıştırılır (geçerli tabanda no-op).
	  2. Hedef oran yoksa taban bölgenin kendisi döner — serbest kırpma.
	  3. Taban bölge hedef orana `inside` kipiyle oturtulur (`ratio_fit`).
	  4. Pencere odak noktasında merkezlenir. Odak 0-1 normalize, KAYNAĞIN
	     tamamına göredir — taban bölgeye göre değil. Sebebi: kullanıcı zoom
	     yaptığında odağın görsel üzerindeki yeri değişmemeli.
	  5. Pencere taban bölgeye sıkıştırılır — **kenar sıkıştırma**. Odak sol üst
	     köşede olsa bile pencere dışarı taşmaz; taşsaydı kırpma boş piksel
	     üretirdi.

	`crop.py::_cover_window` ile aynı matematik, farklı uzay. Orada hedef oran
	`AR / kaynak_oranı` ile normalize uzaya çevrilir; burada uzay zaten piksel
	olduğu için `AR` doğrudan kullanılır. İkisinin aynı pencereyi verdiği
	`tests/test_crop_geometry.py::CaprazTutarlilikTesti` ile doğrulanır.
	"""
	sw = _require_positive(source_w, "source_w")
	sh = _require_positive(source_h, "source_h")
	region = clamp_window(base, Rect(0.0, 0.0, sw, sh))

	if target_ar is None:
		return region

	ar = _require_positive(target_ar, "target_ar")
	w, h = ratio_fit(region.w, region.h, ar, FIT_INSIDE)

	fx = clamp(_require_finite(focal_x, "focal_x"), 0.0, 1.0) * sw
	fy = clamp(_require_finite(focal_y, "focal_y"), 0.0, 1.0) * sh

	x = clamp(fx - w / 2.0, region.x, region.x + region.w - w)
	y = clamp(fy - h / 2.0, region.y, region.y + region.h - h)
	return Rect(x, y, w, h)


def focal_from_window(win: Rect, source_w: float, source_h: float) -> Tuple[float, float]:
	"""`crop_window`'un tersi: pencereden onu üreten odak noktasını geri oku.

	Kullanıcı pencereyi gövdesinden sürüklediğinde UI'nın elinde bir pencere
	vardır, ama saklanması gereken şey odak noktasıdır (INV-10: normalize,
	türevler arasında taşınabilir). Pencerenin merkezi, o pencereyi üreten
	odakların en temsilcisidir — kenar sıkıştırma devredeyse birden çok odak
	aynı pencereyi verir ve merkez bunların içinde tek kararlı seçimdir.
	"""
	sw = _require_positive(source_w, "source_w")
	sh = _require_positive(source_h, "source_h")
	return (clamp(win.cx / sw, 0.0, 1.0), clamp(win.cy / sh, 0.0, 1.0))


def round_window(
	win: Rect, source_w: Optional[float] = None, source_h: Optional[float] = None
) -> Tuple[int, int, int, int]:
	"""Pencereyi tam piksel kutusuna çevir: `(left, top, w, h)` — PIL uyumlu.

	Yuvarlama **sonda** yapılır. Önce yuvarlayıp sonra hesaplamak, 80 px'lik
	sepet küçük resminde oranı gözle görülür biçimde kaydırır (aynı gerekçe
	`crop.py::CropWindow.to_pixels` içinde de yazılı).

	`source_w/source_h` verilirse yuvarlama sonrası taşan sağ/alt kenar geri
	çekilir: `floor(x+0.5) + floor(w+0.5)` kaynağı bir piksel aşabilir ve
	`PIL.Image.crop` bunu sessizce siyah dolgu ile doldurur.
	"""
	left = _round_half_up(win.x)
	top = _round_half_up(win.y)
	w = _round_half_up(win.w)
	h = _round_half_up(win.h)
	if w < 1:
		w = 1
	if h < 1:
		h = 1
	if source_w is not None and source_h is not None:
		sw = _round_half_up(_require_positive(source_w, "source_w"))
		sh = _round_half_up(_require_positive(source_h, "source_h"))
		if w > sw:
			w = sw
		if h > sh:
			h = sh
		if left > sw - w:
			left = sw - w
		if top > sh - h:
			top = sh - h
	if left < 0:
		left = 0
	if top < 0:
		top = 0
	return (left, top, w, h)


# ─────────────────────────────────────────────────────────────────────────────
# camelCase takma adlar — TS ikiziyle AYNI isimler
# ─────────────────────────────────────────────────────────────────────────────
#
# Python tarafında snake_case kanonik; ama T-100'ün sözleşmesi "aynı isim, aynı
# sonuç"tur. Vektör dosyası fonksiyonları ADIYLA çağırır ve iki dilde de aynı
# anahtar kullanılabilsin diye camelCase adlar da dışa verilir.

cropWindow = crop_window
clampWindow = clamp_window
ratioFit = ratio_fit
zoomBase = zoom_base
zoomFromBase = zoom_from_base
focalFromWindow = focal_from_window
roundWindow = round_window

__all__ = [
	"EPS",
	"PARITY_TOLERANCE_PX",
	"ZOOM_MIN",
	"ZOOM_MAX",
	"MIN_EDGE_PX",
	"FIT_INSIDE",
	"FIT_OUTSIDE",
	"FIT_MODES",
	"CropGeometryError",
	"Rect",
	"clamp",
	"ratio_fit",
	"ratioFit",
	"clamp_window",
	"clampWindow",
	"zoom_base",
	"zoomBase",
	"zoom_from_base",
	"zoomFromBase",
	"crop_window",
	"cropWindow",
	"focal_from_window",
	"focalFromWindow",
	"round_window",
	"roundWindow",
]
