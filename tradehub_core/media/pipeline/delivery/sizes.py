"""T-121 — `sizes` özniteliğinin GERÇEK yerleşimden türetilmesi ve DOĞRULANMASI.

KAPATILAN BOŞLUK
----------------
`delivery/manifest.py` başlığı `SIZES_TABLE`'ı bilinçli olarak boş bırakır ve
gerekçesini yazar: kutu genişliği viewport ile monoton artmıyor
(`docs/reports/03-render-envanteri.md` §3.1 — 640px'te 296px, 768px'te 147px'e
DÜŞÜYOR, çünkü `lg` hem 3 sütuna geçiyor hem 240px filtre çubuğunu açıyor),
dolayısıyla basit bir `Xvw` zinciri yanlış olur. Sonuç: `sizes_attribute()`
bugün her bağlamda boş dizge veriyor ve manifest `sizes_source=unmeasured`
işaretliyor.

Bu modül o tabloyu doldurur. İki iş yapar:

  1. **Türetme.** `tradehub_core/media/pipeline/simulator/srcset.py` zaten kutu kuralını
     `placements.json`'dan CSS `calc()`/`min()` ifadesine çeviriyor
     (`sizes_attribute(region, layout)`). O kod TEKRAR YAZILMADI; burada
     sarılıyor ve `{(slot_key, context): sizes}` sözlüğüne dönüştürülüyor —
     `ManifestBuilder`'ın beklediği biçim.

  2. **Doğrulama.** Türetilen dizge, `docs/reports/03-render-envanteri.md`
     §3.1–§3.8'de ELLE ÖLÇÜLMÜŞ piksel tablosuna karşı sınanır. `sizes`
     dizgesi bir CSS ifadesidir; bu modül onu değerlendiren küçük bir
     yorumlayıcı taşır (`evaluate`) ve her viewport için çıkan sayıyı rapordaki
     satırla karşılaştırır.

İKİNCİ ADIM NEDEN ZORUNLU
-------------------------
`sizes` YANLIŞ yazıldığında hiçbir hata çıkmaz: tarayıcı sessizce yanlış
basamağı indirir. Bugünkü "hiç `sizes` yok" durumu en azından görünürdür.
Rapordaki tablo, `placements.json`'dan bağımsız bir ikinci ölçümdür (biri
Tailwind sınıflarından elle, diğeri veri dosyasından programla türetildi); ikisi
uyuşmuyorsa BİRİ yanlıştır ve `verify()` hangisi olduğunu satır satır söyler.

`evaluate` NEYİ MODELLEMEZ
-------------------------
CSS `sizes` dilbilgisinin tamamı değil, `srcset.py`'nin ÜRETTİĞİ altkümesi
desteklenir: `min()`, `max()`, `calc()`, `+ - * /`, `px`/`vw`/`vh` birimleri ve
`(min-width: Npx)` koşulu. `em`/`rem`/`ch`, `clamp()`, `and`/`or` bileşik
koşulları ve konteyner sorguları **desteklenmez** — üretilen dizgede geçmezler;
geçerse `SizesError` atılır, sessizce 0 dönmez.

Kaydırma çubuğu MODELLENMEZ: `100vw` masaüstünde çubuk dâhil ölçülür, gerçek
içerik ~15px dardır. Rapor §1.2 aynı notu düşüyor; etki ≤ %1 ve basamak
seçimini değiştirmiyor.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.simulator import srcset as sim

#: Rapor tablosundaki sayılar 0,1px'e yuvarlanmış; türetilen ifade tam
#: aritmetik yapar. Varsayılan tolerans bu yuvarlamayı soğurur.
DEFAULT_TOLERANCE_PX: float = 0.6

#: Swiper kesirli `slidesPerView`de slayt genişliğini çalışma anında hesaplar;
#: rapor §3.7 kendi satırlarını "≈" ile işaretleyip ±5px sapma bildiriyor.
SLIDER_TOLERANCE_PX: float = 5.0


class SizesError(ValueError):
	"""`sizes` üretilemedi ya da desteklenmeyen CSS ifadesi geldi."""


# ── Ölçülmüş piksel tablosu (docs/reports/03-render-envanteri.md §3) ────


@dataclass(frozen=True)
class MeasuredRow:
	"""Rapordaki tek satır: bu viewport'ta ölçülen CSS kutu genişliği."""

	viewport: int
	css_box: float


@dataclass(frozen=True)
class MeasuredBox:
	"""Bir render bölgesinin rapordaki ölçüm bloğu.

	`region_key` `placements.json`'daki `sayfa/bölge` anahtarıdır; ikisini
	birbirine bağlayan tek yer burasıdır.
	"""

	region_key: str
	section: str
	rows: Tuple[MeasuredRow, ...]
	tolerance_px: float = DEFAULT_TOLERANCE_PX
	note: str = ""


def _rows(*pairs: Tuple[int, float]) -> Tuple[MeasuredRow, ...]:
	return tuple(MeasuredRow(viewport=v, css_box=b) for v, b in pairs)


#: Raporun §3.1–§3.8 tablolarının BİREBİR kopyası. Sayılar burada
#: HESAPLANMAZ — belgeden alınır; hesaplayan taraf `srcset.py`'dir ve
#: `verify()` ikisini karşılaştırır.
MEASURED: Tuple[MeasuredBox, ...] = (
	MeasuredBox(
		region_key="listing/card_grid",
		section="§3.1 Ürün listeleme sayfası",
		rows=_rows(
			(360, 156.0), (390, 171.0), (430, 191.0), (640, 296.0), (768, 146.7),
			(1024, 226.7), (1280, 180.8), (1440, 212.8), (1536, 225.6), (1920, 286.4),
		),
		note="Kutu MONOTON DEĞİL: 640→296px, 768→147px. `sizes` kırılım başına sabit değer ister.",
	),
	MeasuredBox(
		region_key="home/hero_showcase_grid",
		section="§3.2 Ana sayfa ürün vitrini",
		rows=_rows(
			(360, 156.0), (390, 171.0), (430, 191.0), (640, 192.0), (768, 172.0),
			(1024, 152.0), (1280, 194.7), (1440, 221.3), (1536, 196.6), (1920, 240.0),
		),
	),
	MeasuredBox(
		region_key="home/top_deals",
		section="§3.3 Ana sayfa En İyi Fırsatlar",
		rows=_rows(
			(360, 160.0), (390, 175.0), (430, 195.0), (640, 194.7), (768, 172.0),
			(1024, 152.0), (1280, 194.7), (1440, 221.3), (1536, 232.0), (1920, 282.7),
		),
	),
	MeasuredBox(
		region_key="home/tailored_grid",
		section="§3.4 Size Özel + Çok Satanlar",
		rows=_rows(
			(360, 158.0), (390, 173.0), (430, 193.0), (640, 194.7), (768, 172.0),
			(1024, 185.6), (1280, 236.8), (1440, 268.8), (1536, 281.6), (1920, 342.4),
		),
	),
	MeasuredBox(
		region_key="product_detail/main_image",
		section="§3.5 + §3.6 Ürün detay ana görsel (masaüstü + mobil)",
		rows=_rows(
			(360, 360.0), (390, 390.0), (430, 430.0), (640, 640.0), (768, 768.0),
			(1023, 1023.0), (1024, 300.0), (1280, 377.0), (1536, 502.0),
		),
		note="Sistemdeki en yüksek piksel talebi; mobilde kutu = TAM viewport (§3.6).",
	),
	MeasuredBox(
		region_key="product_detail/related_slider",
		section="§3.7 İlgili ürünler (Swiper)",
		rows=_rows(
			(360, 226.0), (390, 247.0), (430, 276.0), (640, 193.0), (768, 236.0),
			(1024, 157.0), (1280, 145.0), (1440, 177.0), (1920, 236.0),
		),
		tolerance_px=SLIDER_TOLERANCE_PX,
		note="Rapor bu satırları `≈` ile işaretliyor: Swiper slayt genişliğini çalışma anında hesaplar.",
	),
	MeasuredBox(
		region_key="product_detail/thumb_rail",
		section="§3.8 Sabit kutular — PD galeri karosu",
		rows=_rows((360, 70.0), (1920, 70.0)),
	),
	MeasuredBox(
		region_key="product_detail/lightbox_thumb",
		section="§3.8 Sabit kutular — PD lightbox karosu",
		rows=_rows((360, 52.0), (1920, 52.0)),
	),
	MeasuredBox(
		region_key="cart_checkout/sku_row",
		section="§3.8 Sabit kutular — sepet SKU satırı",
		rows=_rows((360, 36.0), (1920, 40.0)),
		note="Rapor @1x sütununda 40 yazar (`sm:` hâli); 480px altı 36px.",
	),
	MeasuredBox(
		region_key="cart_checkout/product_item",
		section="§3.8 Sabit kutular — sepet ürün başlığı",
		rows=_rows((360, 40.0), (1920, 60.0)),
	),
	MeasuredBox(
		region_key="cart_checkout/summary_strip",
		section="§3.8 Sabit kutular — checkout özet şeridi",
		rows=_rows((360, 48.0), (430, 56.0), (1920, 64.0)),
	),
	MeasuredBox(
		region_key="cart_checkout/drawer_thumb",
		section="§3.8 Sabit kutular — sepet çekmecesi",
		rows=_rows((360, 56.0), (1920, 64.0)),
	),
)

#: BİLİNEN ve AÇIKLANMIŞ sapmalar — `(bölge, viewport) → gerekçe`.
#:
#: Rapor §3.7 satırlarını `≈` ile işaretler ve slayt genişliğini
#: `(kapsayıcı − spaceBetween) / slidesPerView` ile yaklaşıklar; yani BİR TANE
#: boşluk düşer. Swiper'ın gerçek formülü ise
#: `(kapsayıcı − spaceBetween × (slidesPerView − 1)) / slidesPerView`'dır ve
#: `placements.json` onu uygular (`simulator/srcset.py::box_width` docstring'i).
#: `slidesPerView = 1.4` iken iki formülün farkı `space × 0,6 / 1,4` ≈ 5,1px'tir
#: ve yalnız 390px'te toleransı (±5) 0,3px aşar. TÜRETİLEN DEĞER DOĞRU OLANDIR;
#: rapor satırı yaklaşıktır. Rapor düzeltilmedi (o dosya bu görevin kapsamı
#: dışında), sapma burada kayda geçirildi.
KNOWN_DEVIATIONS: Dict[Tuple[str, int], str] = {
	("product_detail/related_slider", 390): (
		"Rapor §3.7 tek boşluk düşüyor, Swiper (n−1) boşluk düşürüyor; "
		"türetilen 252,3px Swiper'ın gerçek formülüdür."
	),
}

#: Rapor tablosu OLMAYAN bölgeler. Doğrulama bunları atlar ve nedenini yazar —
#: sessizce "geçti" saymak, ölçülmemiş bir satırı ölçülmüş göstermek olurdu.
UNVERIFIED: Dict[str, str] = {
	"listing/brand_grid": "Rapor §3.1 dipnotu yalnız 1920px satırını veriyor (342,4px); tam tablo YOK.",
	"product_detail/lightbox_main": (
		"Rapor §3.8 tek satır türetiyor (≈636px) ve viewport YÜKSEKLİĞİNE bağlı; "
		"`sizes` yüksekliği ifade edemez (aşağıdaki `height_bound` uyarısı)."
	),
	"seller_shop/product_grid": "Mağaza ızgarasının piksel tablosu raporda YOK — ÖLÇÜLMEDİ.",
}


# ── CSS uzunluk yorumlayıcısı ──────────────────────────────────────────

_TOKEN = re.compile(
	r"\s*(?:(?P<num>-?\d+(?:\.\d+)?)(?P<unit>px|vw|vh|%)?|(?P<fn>calc|min|max)\s*\(|"
	r"(?P<punc>[(),*/+-]))"
)
_CONDITION = re.compile(r"^\(\s*min-width\s*:\s*(\d+(?:\.\d+)?)px\s*\)$", re.IGNORECASE)


@dataclass
class _Lexer:
	metin: str
	poz: int = 0
	tokens: List[Tuple[str, Any]] = field(default_factory=list)
	i: int = 0

	def __post_init__(self) -> None:
		while self.poz < len(self.metin):
			if self.metin[self.poz].isspace():
				self.poz += 1
				continue
			m = _TOKEN.match(self.metin, self.poz)
			if not m:
				raise SizesError(f"Çözümlenemeyen CSS parçası: {self.metin[self.poz:self.poz + 20]!r}")
			self.poz = m.end()
			if m.group("num") is not None:
				self.tokens.append(("num", (float(m.group("num")), m.group("unit") or "")))
			elif m.group("fn"):
				self.tokens.append(("fn", m.group("fn")))
			else:
				self.tokens.append(("punc", m.group("punc")))

	def peek(self) -> Optional[Tuple[str, Any]]:
		return self.tokens[self.i] if self.i < len(self.tokens) else None

	def next(self) -> Tuple[str, Any]:
		t = self.peek()
		if t is None:
			raise SizesError("CSS ifadesi beklenmedik yerde bitti")
		self.i += 1
		return t

	def expect(self, punc: str) -> None:
		t = self.next()
		if t != ("punc", punc):
			raise SizesError(f"{punc!r} bekleniyordu, gelen: {t!r}")


def evaluate(expr: str, viewport: int, *, viewport_height: int = 0) -> float:
	"""Tek bir CSS uzunluk ifadesini piksele çevir.

	`vh` içeren bir ifadeyi `viewport_height` vermeden değerlendirmek
	`SizesError`'dır — 0 varsaymak sessizce yanlış kutu üretir.
	"""
	lex = _Lexer(expr)
	deger = _expr(lex, viewport, viewport_height)
	if lex.peek() is not None:
		raise SizesError(f"İfadenin sonunda artık var: {expr!r}")
	return deger


def _expr(lex: _Lexer, vw: int, vh: int) -> float:
	sol = _term(lex, vw, vh)
	while True:
		t = lex.peek()
		if t is None or t[0] != "punc" or t[1] not in ("+", "-"):
			return sol
		lex.next()
		sag = _term(lex, vw, vh)
		sol = sol + sag if t[1] == "+" else sol - sag


def _term(lex: _Lexer, vw: int, vh: int) -> float:
	sol = _factor(lex, vw, vh)
	while True:
		t = lex.peek()
		if t is None or t[0] != "punc" or t[1] not in ("*", "/"):
			return sol
		lex.next()
		sag = _factor(lex, vw, vh)
		if t[1] == "/":
			if sag == 0:
				raise SizesError("CSS ifadesinde sıfıra bölme")
			sol = sol / sag
		else:
			sol = sol * sag


def _factor(lex: _Lexer, vw: int, vh: int) -> float:
	t = lex.next()
	if t[0] == "num":
		sayi, birim = t[1]
		if birim in ("", "px"):
			return sayi
		if birim == "vw":
			return sayi * vw / 100.0
		if birim == "vh":
			if not vh:
				raise SizesError("`vh` içeren ifade `viewport_height` olmadan değerlendirilemez")
			return sayi * vh / 100.0
		raise SizesError(f"Desteklenmeyen birim: {birim!r}")
	if t[0] == "fn":
		ad = t[1]
		argumanlar = [_expr(lex, vw, vh)]
		while lex.peek() == ("punc", ","):
			lex.next()
			argumanlar.append(_expr(lex, vw, vh))
		lex.expect(")")
		if ad == "calc":
			if len(argumanlar) != 1:
				raise SizesError("`calc()` tek argüman alır")
			return argumanlar[0]
		return min(argumanlar) if ad == "min" else max(argumanlar)
	if t == ("punc", "("):
		deger = _expr(lex, vw, vh)
		lex.expect(")")
		return deger
	if t == ("punc", "-"):
		return -_factor(lex, vw, vh)
	raise SizesError(f"Beklenmeyen belirteç: {t!r}")


def resolve(sizes: str, viewport: int, *, viewport_height: int = 0) -> float:
	"""Tam `sizes` dizgesini bu viewport için çöz — tarayıcının yaptığı iş.

	Kurallar (HTML şartnamesi): parçalar SOLDAN SAĞA denenir, koşulu tutan İLK
	parça kazanır; koşulsuz parça her zaman tutar ve sonuncu olmalıdır.
	"""
	metin = (sizes or "").strip()
	if not metin:
		raise SizesError("Boş `sizes` çözülemez — bu bir eksiklik bildirimidir, değer değil.")
	for parca in _split_top_level(metin):
		kosul, ifade = _split_condition(parca)
		if kosul is None:
			return evaluate(ifade, viewport, viewport_height=viewport_height)
		if viewport >= kosul:
			return evaluate(ifade, viewport, viewport_height=viewport_height)
	raise SizesError(f"{viewport}px için eşleşen `sizes` parçası yok: {sizes!r}")


def _split_top_level(metin: str) -> List[str]:
	"""Virgülle ayır — ama `min(…, …)` içindeki virgülleri BÖLME."""
	parcalar: List[str] = []
	derinlik = 0
	son = 0
	for i, ch in enumerate(metin):
		if ch == "(":
			derinlik += 1
		elif ch == ")":
			derinlik -= 1
			if derinlik < 0:
				raise SizesError(f"Fazla kapanan parantez: {metin!r}")
		elif ch == "," and derinlik == 0:
			parcalar.append(metin[son:i].strip())
			son = i + 1
	if derinlik:
		raise SizesError(f"Kapanmayan parantez: {metin!r}")
	parcalar.append(metin[son:].strip())
	return [p for p in parcalar if p]


def _split_condition(parca: str) -> Tuple[Optional[float], str]:
	"""`(min-width: Npx) ifade` → `(N, "ifade")`; koşulsuzda `(None, parça)`."""
	metin = parca.strip()
	if not metin.startswith("("):
		return (None, metin)
	derinlik = 0
	for i, ch in enumerate(metin):
		if ch == "(":
			derinlik += 1
		elif ch == ")":
			derinlik -= 1
			if derinlik == 0:
				bas, kalan = metin[: i + 1], metin[i + 1:].strip()
				m = _CONDITION.match(bas)
				if m and kalan:
					return (float(m.group(1)), kalan)
				# `(100vw - 32px) / 5` gibi parantezle BAŞLAYAN ifade: koşul değil.
				return (None, metin)
	raise SizesError(f"Kapanmayan koşul parantezi: {parca!r}")


# ── Türetme ────────────────────────────────────────────────────────────


def _layout() -> sim.Layout:
	return sim.load_layout()


def region_keys(layout: Optional[sim.Layout] = None) -> Tuple[str, ...]:
	"""`placements.json`'daki tüm `sayfa/bölge` anahtarları."""
	yerlesim = layout or _layout()
	return tuple(r.key for r in yerlesim.all_regions())


def sizes_for(region_key: str, layout: Optional[sim.Layout] = None) -> str:
	"""Tek bölgenin `sizes` dizgesi — `srcset.py` üzerinden CSS'ten türetilir."""
	yerlesim = layout or _layout()
	sayfa, _, bolge = region_key.partition("/")
	if not bolge:
		raise SizesError(f"Bölge anahtarı `sayfa/bölge` olmalı: {region_key!r}")
	return sim.sizes_attribute(yerlesim.region_of(sayfa, bolge), yerlesim)


def sizes_table(layout: Optional[sim.Layout] = None) -> Dict[Tuple[str, str], str]:
	"""`{(slot_key, context): sizes}` — `ManifestBuilder.sizes_table` biçimi.

	`context` bölge anahtarıdır (`product_detail/main_image`). Aynı slot farklı
	sayfalarda farklı kutuya oturduğu için anahtar slot TEK BAŞINA olamaz;
	`contracts/delivery.py::sizes_attribute` sözleşmesi de bu yüzden `context`
	parametresi taşıyor.
	"""
	yerlesim = layout or _layout()
	out: Dict[Tuple[str, str], str] = {}
	for bolge in yerlesim.all_regions():
		out[(bolge.slot_key, bolge.key)] = sim.sizes_attribute(bolge, yerlesim)
	return out


def install(builder: Any, layout: Optional[sim.Layout] = None) -> int:
	"""Üretilmiş tabloyu bir `ManifestBuilder` örneğine yükle; satır sayısı döner.

	`ManifestBuilder` içe aktarılmaz — ördek tiplemesi yeterli ve `delivery`
	paketinde döngüsel bağımlılık kurmak istemiyoruz.
	"""
	tablo = sizes_table(layout)
	builder.sizes_table.update(tablo)
	return len(tablo)


def height_bound_regions(layout: Optional[sim.Layout] = None) -> Tuple[str, ...]:
	"""Kutusu viewport YÜKSEKLİĞİNE bağlı bölgeler — `sizes` bunları ifade EDEMEZ.

	`sizes` yalnız genişlik koşulu (`min-width`) alır. `vh` tabanlı bir kutuda
	üretilen dizge sözdizimsel olarak geçerlidir ama tarayıcı `vh`yi `sizes`
	içinde çözerken viewport yüksekliğini kullanır — bu doğrudur; buradaki uyarı
	DOĞRULAMA içindir: rapor tablosu yükseklik vermediği için o satır
	sınanamaz.
	"""
	yerlesim = layout or _layout()
	out: List[str] = []
	for bolge in yerlesim.all_regions():
		if any("vh_pct" in adim for adim in bolge.box):
			out.append(bolge.key)
	return tuple(out)


# ── Doğrulama ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Deviation:
	"""Türetilen `sizes` ile rapordaki ölçüm arasındaki tek sapma."""

	region_key: str
	section: str
	viewport: int
	measured_px: float
	derived_px: float
	tolerance_px: float

	@property
	def delta(self) -> float:
		return self.derived_px - self.measured_px

	def __str__(self) -> str:
		return (
			f"{self.region_key} @{self.viewport}px: rapor {self.measured_px:.1f} · "
			f"türetilen {self.derived_px:.1f} · fark {self.delta:+.1f}px "
			f"(tolerans ±{self.tolerance_px:.1f})"
		)


@dataclass(frozen=True)
class VerifyResult:
	"""Tüm bölgelerin doğrulama sonucu."""

	checked: int
	deviations: Tuple[Deviation, ...]
	skipped: Dict[str, str]
	sizes: Dict[str, str]

	@property
	def unexpected(self) -> Tuple[Deviation, ...]:
		"""`KNOWN_DEVIATIONS`'ta açıklanmamış sapmalar — asıl bakılacak liste."""
		return tuple(
			d for d in self.deviations if (d.region_key, d.viewport) not in KNOWN_DEVIATIONS
		)

	@property
	def ok(self) -> bool:
		"""Açıklanmamış tek bir sapma bile yoksa `True`."""
		return not self.unexpected

	def report(self) -> str:
		satirlar = [
			f"Doğrulanan satır: {self.checked} · sapma: {len(self.deviations)} "
			f"(açıklanmamış: {len(self.unexpected)}) · atlanan bölge: {len(self.skipped)}"
		]
		for d in self.deviations:
			gerekce = KNOWN_DEVIATIONS.get((d.region_key, d.viewport))
			etiket = "BİLİNEN" if gerekce else "SAPMA  "
			satirlar.append(f"  {etiket} {d}")
			if gerekce:
				satirlar.append(f"          → {gerekce}")
		for k, v in sorted(self.skipped.items()):
			satirlar.append(f"  ATLANDI {k}: {v}")
		return "\n".join(satirlar)


def verify(layout: Optional[sim.Layout] = None) -> VerifyResult:
	"""Türetilen `sizes`i rapordaki ölçüm tablosuna karşı sına.

	Her `MEASURED` satırı için: türetilen dizge o viewport'ta çözülür ve
	rapordaki kutu genişliğiyle karşılaştırılır. Tolerans aşılırsa `Deviation`.
	"""
	yerlesim = layout or _layout()
	uretilmis = {r.key: sim.sizes_attribute(r, yerlesim) for r in yerlesim.all_regions()}

	sapmalar: List[Deviation] = []
	sayac = 0
	atlanan = dict(UNVERIFIED)
	olculen_bolgeler = {m.region_key for m in MEASURED}
	for anahtar in uretilmis:
		if anahtar not in olculen_bolgeler and anahtar not in atlanan:
			atlanan[anahtar] = "Rapor §3'te bu bölgenin piksel tablosu yok — ÖLÇÜLMEDİ."

	for olcum in MEASURED:
		dizge = uretilmis.get(olcum.region_key)
		if dizge is None:
			atlanan[olcum.region_key] = "`placements.json` içinde böyle bir bölge yok."
			continue
		for satir in olcum.rows:
			sayac += 1
			turetilen = resolve(dizge, satir.viewport)
			if abs(turetilen - satir.css_box) > olcum.tolerance_px:
				sapmalar.append(
					Deviation(
						region_key=olcum.region_key,
						section=olcum.section,
						viewport=satir.viewport,
						measured_px=satir.css_box,
						derived_px=turetilen,
						tolerance_px=olcum.tolerance_px,
					)
				)

	return VerifyResult(
		checked=sayac,
		deviations=tuple(sapmalar),
		skipped=atlanan,
		sizes=uretilmis,
	)


def required_px(region_key: str, viewport: int, dpr: float, *, layout: Optional[sim.Layout] = None) -> int:
	"""Bu bölgenin bu cihazdaki piksel talebi: `sizes` × DPR, yukarı yuvarlanmış.

	`ManifestBuilder.pick` bu sayıyı bekler; `simulator` aynı sayıyı kutudan
	hesaplar. İkisinin AYNI çıkması, `sizes` dizgesinin doğru türetildiğinin
	kanıtıdır ve `tests/test_delivery_sizes.py` tam olarak bunu sınar.
	"""
	dizge = sizes_for(region_key, layout)
	return math.ceil(resolve(dizge, viewport) * float(dpr))


def main(argv: Optional[Sequence[str]] = None) -> int:
	"""`python -m tradehub_core.media.pipeline.delivery.sizes` — tabloyu bas, doğrula."""
	sonuc = verify()
	print("# Türetilen `sizes` tablosu (kaynak: placements.json + 03-render-envanteri.md)\n")
	for anahtar in sorted(sonuc.sizes):
		print(f"{anahtar}\n    {sonuc.sizes[anahtar]}")
	print("\n# Doğrulama\n")
	print(sonuc.report())
	return 0 if sonuc.ok else 1


__all__ = [
	"DEFAULT_TOLERANCE_PX",
	"SLIDER_TOLERANCE_PX",
	"SizesError",
	"MeasuredRow",
	"MeasuredBox",
	"MEASURED",
	"KNOWN_DEVIATIONS",
	"UNVERIFIED",
	"evaluate",
	"resolve",
	"region_keys",
	"sizes_for",
	"sizes_table",
	"install",
	"height_bound_regions",
	"Deviation",
	"VerifyResult",
	"verify",
	"required_px",
	"main",
]


if __name__ == "__main__":  # pragma: no cover
	raise SystemExit(main())
