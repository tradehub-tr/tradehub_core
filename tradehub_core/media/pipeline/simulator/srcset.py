"""T-112 — Tarayıcı `srcset` seçiminin sunucu tarafında simülasyonu.

SORU
----
"Bu cihaz, bu sayfanın bu bölgesinde HANGİ türevi indirir?" — ve devamında:
"indirdiği türev yeter mi, yoksa aşırı mı servis ediyoruz?"

Bugün bu soru sorulamıyor: storefront'ta `srcset` kullanan tek bir render
noktası yok (`docs/reports/03-render-envanteri.md` §4) ve backend varlık başına
tek boy üretiyor. Faz 6 türevleri üretti (`tradehub_core/media/pipeline/image/render.py`), Faz 2
profil merdivenini politikaya yazdı (`tradehub_core/media/pipeline/policy/slots/*.json`). Eksik
olan halka, o merdivenin GERÇEK cihazlarda GERÇEK CSS kutularına oturup
oturmadığının kanıtı. Bu modül o kanıtı üretir.

NASIL
-----
Üç girdi, tek çıktı:

    devices.json      13 referans cihaz — CSS viewport, DPR
    placements.json   5 sayfa × 15 bölge — kutu genişliğinin CSS'ten türetilmiş
                      kuralı (grid / slider / sabit px / viewport yüzdesi /
                      viewport YÜKSEKLİĞİ yüzdesi)
    slot politikası   profil merdiveni (product.image: 96…1920)
                      → `Selection`

TARAYICI SEÇİM KURALI (taklit edilen davranış)
----------------------------------------------
`w` tanımlayıcılı `srcset` + `sizes` verildiğinde tarayıcı:

  1. `sizes`'ı çözer → efektif kutu genişliği (CSS px),
  2. kutu × DPR = gereken piksel genişliği,
  3. gereken genişliği KARŞILAYAN EN KÜÇÜK adayı seçer,
  4. hiçbiri karşılamıyorsa EN BÜYÜĞÜNÜ seçer.

Bu, Chrome/Firefox/Safari'nin gözlenen davranışıdır ve
`tradehub_core/media/pipeline/contracts/delivery.py::DeliveryManifest.pick` sözleşmesiyle
BİREBİR aynıdır — iki yerde iki farklı kural olmasın diye kural burada da
kopyalanmadı, aynı ifade kullanıldı.

**Şartname sapması (kasıtlı basitleştirme):** HTML şartnamesi tarayıcıya
takdir hakkı verir — ağ durumu, veri tasarrufu modu ve önbellekte zaten duran
daha büyük bir aday seçimi değiştirebilir. Bu simülatör o etkenleri MODELLEMEZ;
"ideal koşulda hangi basamak" sorusunu cevaplar. Gerçek dağılım ancak alandan
ölçülür (docs/ui/faz11-simulator.md §5).

ÜRETİLEN UYARILAR
-----------------
    kaynak_yetersiz   merdivenin en büyük basamağı bile gereken genişliği
                      karşılamıyor → görsel bulanık basılır (FR-028 upscale
                      yasağı gereği büyütmüyoruz, kabul edip raporluyoruz)
    asiri_servis      seçilen basamak / gereken > politikadaki max_overshoot
                      → merdivende basamak eksik, boşuna bayt iniyor
    zoom_yetersiz     yalnız ürün detay ana görselinde: hover-zoom 1,85×
                      ölçekliyor, seçilen türev o ölçekte yetmiyor
    profil_yok        slotta hiç profil tanımlı değil

`sizes` ÜRETİMİ
---------------
`sizes_attribute()` bölgenin kutu kuralını CSS `calc()`/`min()` ifadesine
çevirir. Elle yazılmış `sizes` dizgeleri, kırılım noktaları değiştiğinde
sessizce yanlışa döner; buradaki dizge CSS'in TEK kaynağı olan
`placements.json`'dan üretildiği için kırılım değişince otomatik değişir.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from tradehub_core.media.pipeline.simulator import DEVICES_PATH, PLACEMENTS_PATH

# ── Uyarı kodları ───────────────────────────────────────────────────────
WARN_SOURCE_INSUFFICIENT = "kaynak_yetersiz"
WARN_OVERSHOOT = "asiri_servis"
WARN_ZOOM_INSUFFICIENT = "zoom_yetersiz"
WARN_NO_PROFILE = "profil_yok"


class SimulatorDataError(ValueError):
	"""`devices.json` / `placements.json` beklenen yapıda değil."""


# ── Veri modelleri ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Device:
	"""Tek bir referans cihaz. Ölçülmedi — emülasyon değeri (bkz. devices.json)."""

	id: str
	label: str
	device_class: str
	css_width: int
	css_height: int
	dpr: float
	physical_width: int
	physical_height: int
	scrollbar_px: int = 0
	source: str = ""
	why: str = ""

	@property
	def hesaplanan_fiziksel(self) -> tuple[int, int]:
		"""`round(css × dpr)` — dosyadaki `physical` ile tutarlılık kontrolü içindir."""
		return (round(self.css_width * self.dpr), round(self.css_height * self.dpr))


@dataclass(frozen=True)
class Container:
	"""CSS kapsayıcısı: `min(max_width, viewport) − padding − subtract`.

	`padding` ve `subtract` adımlarındaki `px` değerleri TOPLAMDIR (iki yan
	birden), tek yan değil: `px-4` → 32.
	"""

	name: str
	max_width: int | None = None
	padding: tuple[dict, ...] = ()
	base: str = ""
	subtract: tuple[dict, ...] = ()
	derived_from: str = ""


@dataclass(frozen=True)
class Region:
	"""Bir sayfadaki tek render bölgesi ve kutu genişliği kuralı."""

	page: str
	region: str
	title: str
	slot_key: str
	render_point: str
	box: tuple[dict, ...]
	lcp_candidate: bool = False
	demand_multiplier: tuple[dict, ...] = ()
	derived_from: str = ""
	extra: dict = field(default_factory=dict)

	@property
	def key(self) -> str:
		return f"{self.page}/{self.region}"


@dataclass(frozen=True)
class Page:
	page: str
	title: str
	url: str
	primary_region: str
	regions: tuple[Region, ...]

	def region_of(self, name: str) -> Region:
		for r in self.regions:
			if r.region == name:
				return r
		raise KeyError(f"{self.page} sayfasında bölge yok: {name!r}")

	@property
	def primary(self) -> Region:
		return self.region_of(self.primary_region)


@dataclass(frozen=True)
class Rendition:
	"""Merdivendeki tek basamak — politikadaki `profiles[]` girdisinin özeti."""

	name: str
	width: int
	formats: tuple[str, ...] = ()
	max_overshoot: float | None = None
	clamped_from: int = 0

	@property
	def clamped(self) -> bool:
		"""Kaynak küçük olduğu için basamak aşağı çekildi mi (FR-028)."""
		return bool(self.clamped_from)


@dataclass(frozen=True)
class Selection:
	"""Tek (cihaz × bölge) kombinasyonunun sonucu."""

	device: Device
	region: Region
	css_box_px: float
	required_px: int
	chosen: Rendition | None
	candidates: tuple[Rendition, ...]
	demand_multiplier: float = 1.0
	warnings: tuple[str, ...] = ()

	@property
	def chosen_width(self) -> int:
		return self.chosen.width if self.chosen else 0

	@property
	def chosen_name(self) -> str:
		return self.chosen.name if self.chosen else "-"

	@property
	def sufficient(self) -> bool:
		"""Seçilen basamak gereken genişliği karşılıyor mu."""
		return bool(self.chosen) and self.chosen_width >= self.required_px

	@property
	def deficit_px(self) -> int:
		"""Eksik piksel; yeterliyse 0."""
		return max(0, self.required_px - self.chosen_width)

	@property
	def overshoot(self) -> float:
		"""`seçilen / gereken`. Gereken 0 ya da seçim yoksa 0,0 (ölçülemedi)."""
		if not self.chosen or self.required_px <= 0:
			return 0.0
		return self.chosen_width / self.required_px

	@property
	def zoom_required_px(self) -> int:
		"""Zoom/ölçek çarpanı uygulanmış gerçek piksel talebi."""
		return math.ceil(self.css_box_px * self.device.dpr * self.demand_multiplier)

	@property
	def zoom_sufficient(self) -> bool:
		return bool(self.chosen) and self.chosen_width >= self.zoom_required_px

	def to_dict(self) -> dict[str, Any]:
		return {
			"device": self.device.id,
			"page": self.region.page,
			"region": self.region.region,
			"slot_key": self.region.slot_key,
			"css_box_px": round(self.css_box_px, 2),
			"dpr": self.device.dpr,
			"required_px": self.required_px,
			"chosen_profile": self.chosen_name,
			"chosen_width": self.chosen_width,
			"sufficient": self.sufficient,
			"deficit_px": self.deficit_px,
			"overshoot": round(self.overshoot, 3),
			"demand_multiplier": self.demand_multiplier,
			"zoom_required_px": self.zoom_required_px,
			"zoom_sufficient": self.zoom_sufficient,
			"warnings": list(self.warnings),
		}


# ── Yükleme ─────────────────────────────────────────────────────────────


def load_devices(path: Path | str | None = None) -> tuple[Device, ...]:
	"""`devices.json` → `Device` demeti (dosyadaki sırayla)."""
	data = _read_json(path or DEVICES_PATH)
	ham = data.get("devices")
	if not isinstance(ham, list) or not ham:
		raise SimulatorDataError("devices.json içinde `devices` dizisi yok ya da boş")
	out: list[Device] = []
	for d in ham:
		vp = d.get("css_viewport") or {}
		ph = d.get("physical") or {}
		out.append(
			Device(
				id=str(d["id"]),
				label=str(d.get("label", d["id"])),
				device_class=str(d.get("class", "")),
				css_width=int(vp["width"]),
				css_height=int(vp["height"]),
				dpr=float(d["dpr"]),
				physical_width=int(ph.get("width", 0)),
				physical_height=int(ph.get("height", 0)),
				scrollbar_px=int(d.get("scrollbar_px", 0)),
				source=str(d.get("source", "")),
				why=str(d.get("why", "")),
			)
		)
	return tuple(out)


class Layout:
	"""`placements.json`'ın çözümlenmiş hâli: kapsayıcılar + sayfalar."""

	def __init__(self, data: dict) -> None:
		self.raw = data
		self.breakpoints: dict[str, int] = dict(data.get("breakpoints") or {})
		self.containers: dict[str, Container] = {}
		for ad, c in (data.get("containers") or {}).items():
			self.containers[ad] = Container(
				name=ad,
				max_width=c.get("max_width"),
				padding=tuple(c.get("padding") or ()),
				base=str(c.get("base", "")),
				subtract=tuple(c.get("subtract") or ()),
				derived_from=str(c.get("derived_from", "")),
			)
		self.pages: tuple[Page, ...] = tuple(self._page(p) for p in (data.get("pages") or ()))
		if not self.pages:
			raise SimulatorDataError("placements.json içinde `pages` yok")

	@staticmethod
	def _page(p: dict) -> Page:
		bolgeler = []
		for r in p.get("regions") or ():
			bilinen = {
				"region",
				"title",
				"slot_key",
				"render_point",
				"box",
				"lcp_candidate",
				"demand_multiplier",
				"derived_from",
			}
			bolgeler.append(
				Region(
					page=str(p["page"]),
					region=str(r["region"]),
					title=str(r.get("title", r["region"])),
					slot_key=str(r["slot_key"]),
					render_point=str(r.get("render_point", "")),
					box=tuple(r["box"]),
					lcp_candidate=bool(r.get("lcp_candidate", False)),
					demand_multiplier=tuple(r.get("demand_multiplier") or ()),
					derived_from=str(r.get("derived_from", "")),
					extra={k: v for k, v in r.items() if k not in bilinen},
				)
			)
		if not bolgeler:
			raise SimulatorDataError(f"{p.get('page')} sayfasında bölge yok")
		return Page(
			page=str(p["page"]),
			title=str(p.get("title", p["page"])),
			url=str(p.get("url", "")),
			primary_region=str(p.get("primary_region") or bolgeler[0].region),
			regions=tuple(bolgeler),
		)

	# ── kapsayıcı genişliği ────────────────────────────────────────

	def container_width(self, name: str, viewport_px: int) -> float:
		"""Kapsayıcının İÇERİK genişliği (padding ve rezerve sütunlar düşülmüş)."""
		flat = self.flatten_container(name, viewport_px)
		mw, deduct = flat
		w = min(mw, viewport_px) if mw else float(viewport_px)
		return max(0.0, w - deduct)

	def flatten_container(self, name: str, viewport_px: int) -> tuple[int | None, float]:
		"""`(max_width, toplam_düşülen)` — `sizes` üretimi de bunu kullanır.

		Zincirdeki `base` kapsayıcılar düzleştirilir: iç içe kapsayıcının
		max-width'i dış kapsayıcınınkiyle çakışırsa DAHA KÜÇÜĞÜ bağlayıcıdır.
		"""
		try:
			c = self.containers[name]
		except KeyError as exc:
			raise SimulatorDataError(f"Tanımsız kapsayıcı: {name!r}") from exc
		if c.base:
			mw, deduct = self.flatten_container(c.base, viewport_px)
		else:
			mw, deduct = c.max_width, 0.0
		if c.max_width is not None:
			mw = c.max_width if mw is None else min(mw, c.max_width)
		deduct += float(_step(c.padding, viewport_px, "px", 0))
		deduct += float(_step(c.subtract, viewport_px, "px", 0))
		return mw, deduct

	# ── erişim ─────────────────────────────────────────────────────

	def page_of(self, name: str) -> Page:
		for p in self.pages:
			if p.page == name:
				return p
		raise KeyError(f"Bilinmeyen sayfa: {name!r}. Tanımlı: {', '.join(p.page for p in self.pages)}")

	def region_of(self, page: str, region: str) -> Region:
		return self.page_of(page).region_of(region)

	def all_regions(self) -> tuple[Region, ...]:
		return tuple(r for p in self.pages for r in p.regions)

	def primary_regions(self) -> tuple[Region, ...]:
		return tuple(p.primary for p in self.pages)


def load_layout(path: Path | str | None = None) -> Layout:
	"""`placements.json` → `Layout`."""
	return Layout(_read_json(path or PLACEMENTS_PATH))


def _read_json(path: Path | str) -> dict:
	with open(path, encoding="utf-8") as fh:
		return json.load(fh)


def _step(steps: Iterable[dict], viewport_px: int, key: str, default: Any = None) -> Any:
	"""Kırılım adımlarından viewport'a uyan İLKİNİ (en büyük `min_vw`) seç."""
	uygun = [s for s in steps if viewport_px >= int(s.get("min_vw", 0))]
	if not uygun:
		return default
	kazanan = max(uygun, key=lambda s: int(s.get("min_vw", 0)))
	return kazanan.get(key, default)


def _matching_step(steps: Sequence[dict], viewport_px: int) -> dict:
	uygun = [s for s in steps if viewport_px >= int(s.get("min_vw", 0))]
	if not uygun:
		raise SimulatorDataError(f"{viewport_px}px için eşleşen adım yok (min_vw=0 adımı eksik)")
	return max(uygun, key=lambda s: int(s.get("min_vw", 0)))


# ── Kutu genişliği ──────────────────────────────────────────────────────


def box_width(region: Region, device: Device, layout: Layout) -> float:
	"""Bölgenin bu cihazdaki CSS kutu genişliği (px).

	Desteklenen adım türleri — hepsi VERİDEN gelir, burada sayfa adı geçmez:

	    px       sabit CSS px
	    vw_pct   kapsayıcı içerik genişliğinin yüzdesi (`container` verilmezse
	             viewport)
	    vh_pct   viewport YÜKSEKLİĞİNİN yüzdesi, `cap_px` tavanı ve `minus_px`
	             düşümüyle — yalnız lightbox gibi yüksekliğe oturan kutular
	    grid     `(kapsayıcı − subtract_px − gap×(cols−1)) / cols`
	    slider   `(kapsayıcı − subtract_px − space×(per_view−1)) / per_view`
	              (Swiper'ın gerçek formülü)

	Her adımda isteğe bağlı `cap_px` sonuca `min()` tavanı uygular.
	"""
	adim = _matching_step(region.box, device.css_width)
	vw = device.css_width

	if "px" in adim:
		deger = float(adim["px"])
	elif "vw_pct" in adim:
		kap = self_container(adim, layout, vw)
		deger = kap * float(adim["vw_pct"]) / 100.0
	elif "vh_pct" in adim:
		ham = device.css_height * float(adim["vh_pct"]) / 100.0
		tavan = adim.get("cap_px")
		if tavan is not None:
			ham = min(ham, float(tavan))
		deger = ham - float(adim.get("minus_px", 0))
		return max(0.0, deger)
	elif "grid" in adim:
		g = adim["grid"]
		kap = layout.container_width(str(g.get("container", "viewport")), vw)
		cols = int(g["cols"])
		gap = float(g.get("gap", 0))
		deger = (kap - float(g.get("subtract_px", 0)) - gap * (cols - 1)) / cols
	elif "slider" in adim:
		s = adim["slider"]
		kap = layout.container_width(str(s.get("container", "viewport")), vw)
		per = float(s["per_view"])
		space = float(s.get("space", 0))
		deger = (kap - float(s.get("subtract_px", 0)) - space * (per - 1)) / per
	else:
		raise SimulatorDataError(f"{region.key}: tanınmayan kutu adımı {sorted(adim)}")

	tavan = adim.get("cap_px")
	if tavan is not None:
		deger = min(deger, float(tavan))
	return max(0.0, deger)


def self_container(adim: dict, layout: Layout, viewport_px: int) -> float:
	"""Adımın `container` alanını çöz; yoksa çıplak viewport."""
	ad = str(adim.get("container", "viewport"))
	return layout.container_width(ad, viewport_px)


def demand_multiplier(region: Region, device: Device) -> float:
	"""Bölgenin bu viewport'taki talep çarpanı (zoom/ölçek). Yoksa 1,0."""
	if not region.demand_multiplier:
		return 1.0
	return float(_step(region.demand_multiplier, device.css_width, "value", 1.0))


# ── Profil merdiveni ────────────────────────────────────────────────────


def renditions_for(slot_key: str, registry: Any = None, source_width: int = 0) -> tuple[Rendition, ...]:
	"""Slot politikasındaki profil merdivenini `Rendition` demetine çevir.

	`registry` verilmezse `media_engine.policy.engine.PolicyRegistry` kullanılır
	— profil listesi BURADA TANIMLI DEĞİLDİR, politikadan okunur (kural 8).

	`source_width` verilirse **FR-028 upscale yasağı** uygulanır: kaynaktan
	geniş basamaklar kaynağın genişliğine KELEPÇELENİR ve aynı genişliğe düşen
	basamaklar tekilleştirilir. Kelepçelenen basamak `clamped_from` taşır —
	"bu basamak istendi ama üretilemedi" bilgisi kaybolmasın.
	"""
	if registry is None:
		from tradehub_core.media.pipeline.policy.engine import PolicyRegistry

		registry = PolicyRegistry()
	politika = registry.get(slot_key)
	ham = politika.get("profiles") or []

	basamaklar: list[Rendition] = []
	for p in ham:
		w = p.get("width")
		if not w:
			continue
		w = int(w)
		clamped_from = 0
		if source_width and w > source_width:
			clamped_from = w
			w = int(source_width)
		basamaklar.append(
			Rendition(
				name=str(p.get("name", f"w{w}")),
				width=w,
				formats=tuple(p.get("formats") or ()),
				max_overshoot=(float(p["max_overshoot"]) if p.get("max_overshoot") else None),
				clamped_from=clamped_from,
			)
		)

	basamaklar.sort(key=lambda r: (r.width, r.clamped_from))
	tekil: list[Rendition] = []
	for r in basamaklar:
		if tekil and tekil[-1].width == r.width:
			continue
		tekil.append(r)
	return tuple(tekil)


def select_rendition(renditions: Sequence[Rendition], required_px: int) -> Rendition | None:
	"""Tarayıcının seçimi: gerekeni karşılayan EN KÜÇÜK; yoksa EN BÜYÜK.

	`tradehub_core/media/pipeline/contracts/delivery.py::DeliveryManifest.pick` ile aynı kural.
	"""
	if not renditions:
		return None
	sirali = sorted(renditions, key=lambda r: r.width)
	for r in sirali:
		if r.width >= required_px:
			return r
	return sirali[-1]


# ── Simülasyon ──────────────────────────────────────────────────────────


def simulate(
	device: Device,
	region: Region,
	layout: Layout,
	renditions: Sequence[Rendition],
) -> Selection:
	"""Tek (cihaz × bölge) kombinasyonunu çöz."""
	kutu = box_width(region, device, layout)
	gereken = math.ceil(kutu * device.dpr)
	carpan = demand_multiplier(region, device)
	secilen = select_rendition(renditions, gereken)

	uyarilar: list[str] = []
	if secilen is None:
		uyarilar.append(WARN_NO_PROFILE)
	else:
		if secilen.width < gereken:
			uyarilar.append(WARN_SOURCE_INSUFFICIENT)
		tavan = secilen.max_overshoot
		if tavan and gereken > 0 and secilen.width / gereken > tavan:
			uyarilar.append(WARN_OVERSHOOT)
		if carpan > 1.0 and secilen.width < math.ceil(kutu * device.dpr * carpan):
			uyarilar.append(WARN_ZOOM_INSUFFICIENT)

	return Selection(
		device=device,
		region=region,
		css_box_px=kutu,
		required_px=gereken,
		chosen=secilen,
		candidates=tuple(renditions),
		demand_multiplier=carpan,
		warnings=tuple(uyarilar),
	)


def simulate_matrix(
	devices: Sequence[Device],
	regions: Sequence[Region],
	layout: Layout,
	*,
	registry: Any = None,
	source_width: int = 0,
) -> tuple[Selection, ...]:
	"""Tüm (cihaz × bölge) çarpımı. Profil merdiveni slot başına bir kez okunur."""
	onbellek: dict[str, tuple[Rendition, ...]] = {}
	out: list[Selection] = []
	for region in regions:
		if region.slot_key not in onbellek:
			onbellek[region.slot_key] = renditions_for(
				region.slot_key, registry=registry, source_width=source_width
			)
		merdiven = onbellek[region.slot_key]
		for device in devices:
			out.append(simulate(device, region, layout, merdiven))
	return tuple(out)


# ── `sizes` üretimi ─────────────────────────────────────────────────────


def _band_edges(region: Region, layout: Layout) -> tuple[int, ...]:
	"""Kutu kuralının değiştiği tüm viewport eşikleri (kapsayıcı padding'i dahil).

	Bölgenin kendi `min_vw` eşikleri yetmez: kapsayıcının padding'i başka bir
	eşikte değişiyorsa (`boxed` 1536'da 32→64) o bant da ayrılmalıdır, yoksa
	üretilen `sizes` o bantta yanlış olur.
	"""
	esikler: set[int] = {0}
	for adim in region.box:
		esikler.add(int(adim.get("min_vw", 0)))
		for anahtar in ("grid", "slider"):
			if anahtar in adim:
				esikler |= _container_edges(str(adim[anahtar].get("container", "viewport")), layout)
		if "vw_pct" in adim:
			esikler |= _container_edges(str(adim.get("container", "viewport")), layout)
	return tuple(sorted(esikler))


def _container_edges(name: str, layout: Layout) -> set[int]:
	c = layout.containers.get(name)
	if c is None:
		return {0}
	esikler = {int(s.get("min_vw", 0)) for s in c.padding}
	esikler |= {int(s.get("min_vw", 0)) for s in c.subtract}
	if c.base:
		esikler |= _container_edges(c.base, layout)
	return esikler or {0}


def _css_length(adim: dict, layout: Layout, viewport_px: int) -> str:
	"""Adımın bu bant içindeki CSS uzunluk ifadesi."""
	if "px" in adim:
		govde = f"{_num(adim['px'])}px"
	elif "vh_pct" in adim:
		ic = f"{_num(adim['vh_pct'])}vh"
		tavan = adim.get("cap_px")
		if tavan is not None:
			ic = f"min({ic}, {_num(tavan)}px)"
		eksi = float(adim.get("minus_px", 0))
		govde = f"calc({ic} - {_num(eksi)}px)" if eksi else ic
	elif "vw_pct" in adim:
		kap = _container_css(str(adim.get("container", "viewport")), layout, viewport_px)
		oran = float(adim["vw_pct"]) / 100.0
		if oran == 1.0:
			# `calc(100vw)` yerine `100vw`: aritmetik yoksa calc sarmalamak gürültü.
			govde = kap if ("-" not in kap and "+" not in kap) else f"calc({kap})"
		else:
			govde = f"calc(({kap}) * {_num(oran)})"
	elif "grid" in adim:
		g = adim["grid"]
		kap = _container_css(str(g.get("container", "viewport")), layout, viewport_px)
		cols = int(g["cols"])
		dus = float(g.get("subtract_px", 0)) + float(g.get("gap", 0)) * (cols - 1)
		govde = f"calc(({kap} - {_num(dus)}px) / {cols})"
	elif "slider" in adim:
		s = adim["slider"]
		kap = _container_css(str(s.get("container", "viewport")), layout, viewport_px)
		per = float(s["per_view"])
		dus = float(s.get("subtract_px", 0)) + float(s.get("space", 0)) * (per - 1)
		govde = f"calc(({kap} - {_num(dus)}px) / {_num(per)})"
	else:
		raise SimulatorDataError(f"CSS'e çevrilemeyen adım: {sorted(adim)}")

	tavan = adim.get("cap_px")
	if tavan is not None and "vh_pct" not in adim:
		govde = f"min({_num(tavan)}px, {govde})"
	return govde


def _container_css(name: str, layout: Layout, viewport_px: int) -> str:
	mw, dus = layout.flatten_container(name, viewport_px)
	taban = "100vw" if mw is None else f"min(100vw, {_num(mw)}px)"
	return f"{taban} - {_num(dus)}px" if dus else taban


def _num(x: float | int) -> str:
	"""Gereksiz `.0` basmadan sayı yaz."""
	f = float(x)
	return str(int(f)) if f.is_integer() else f"{f:g}"


def sizes_attribute(region: Region, layout: Layout) -> str:
	"""Bölgenin `sizes` dizgesi — CSS'ten üretilir, elle yazılmaz.

	Ardışık bantlar aynı ifadeyi veriyorsa BİRLEŞTİRİLİR; gereksiz media
	koşulu üretmek `sizes`'ı okunamaz hâle getirir ve gözden kaçan hataları
	saklar.
	"""
	kenarlar = _band_edges(region, layout)
	parcalar: list[tuple[int, str]] = []
	for kenar in kenarlar:
		olcum = max(kenar, 1)
		adim = _matching_step(region.box, olcum)
		ifade = _css_length(adim, layout, olcum)
		if parcalar and parcalar[-1][1] == ifade:
			continue
		parcalar.append((kenar, ifade))

	parcalar.sort(key=lambda t: t[0], reverse=True)
	cikti: list[str] = []
	for kenar, ifade in parcalar:
		cikti.append(ifade if kenar == 0 else f"(min-width: {kenar}px) {ifade}")
	return ", ".join(cikti)


def srcset_attribute(renditions: Sequence[Rendition], url_template: str = "{name}.webp") -> str:
	"""`<url> <width>w` girdilerinden `srcset` dizgesi.

	`url_template` içinde `{name}` ve `{width}` kullanılabilir. Gerçek URL
	üretimi bu modülün işi DEĞİLDİR — `tradehub_core/media/pipeline/contracts/delivery.py::
	derivative_key` oradaki tek kaynaktır; buradaki şablon yalnız simülasyon
	çıktısını okunur kılmak içindir.
	"""
	return ", ".join(
		f"{url_template.format(name=r.name, width=r.width)} {r.width}w"
		for r in sorted(renditions, key=lambda r: r.width)
	)


# ── Tablo ───────────────────────────────────────────────────────────────

_BASLIK = ("Cihaz", "DPR", "Sayfa/Bölge", "Kutu", "Gereken", "Seçilen", "Genişlik", "Fazlalık", "Uyarı")


def format_table(selections: Sequence[Selection]) -> str:
	"""Simülasyon sonuçlarını hizalı metin tablosuna çevir."""
	satirlar = [
		(
			s.device.id,
			_num(s.device.dpr),
			s.region.key,
			f"{s.css_box_px:.0f}",
			str(s.required_px),
			s.chosen_name,
			str(s.chosen_width),
			f"{s.overshoot:.2f}×" if s.overshoot else "-",
			",".join(s.warnings) or "-",
		)
		for s in selections
	]
	genislik = [max(len(_BASLIK[i]), *(len(r[i]) for r in satirlar)) for i in range(len(_BASLIK))]
	sinir = "-+-".join("-" * g for g in genislik)
	out = [" | ".join(h.ljust(genislik[i]) for i, h in enumerate(_BASLIK)), sinir]
	out += [" | ".join(c.ljust(genislik[i]) for i, c in enumerate(r)) for r in satirlar]
	return "\n".join(out)


def summarize(selections: Sequence[Selection]) -> dict[str, Any]:
	"""Toplu sayım — testin ve raporun okuduğu tek özet."""
	toplam = len(selections)
	yetersiz = [s for s in selections if WARN_SOURCE_INSUFFICIENT in s.warnings]
	asiri = [s for s in selections if WARN_OVERSHOOT in s.warnings]
	zoom = [s for s in selections if WARN_ZOOM_INSUFFICIENT in s.warnings]
	fazlaliklar = [s.overshoot for s in selections if s.overshoot]
	return {
		"toplam": toplam,
		"kaynak_yetersiz": len(yetersiz),
		"kaynak_yetersiz_liste": [f"{s.device.id}×{s.region.key}" for s in yetersiz],
		"asiri_servis": len(asiri),
		"asiri_servis_liste": [f"{s.device.id}×{s.region.key}" for s in asiri],
		"zoom_yetersiz": len(zoom),
		"zoom_yetersiz_liste": [f"{s.device.id}×{s.region.key}" for s in zoom],
		"ortalama_fazlalik": (sum(fazlaliklar) / len(fazlaliklar)) if fazlaliklar else 0.0,
		"en_yuksek_fazlalik": max(fazlaliklar) if fazlaliklar else 0.0,
		"secilen_dagilim": _dagilim(selections),
	}


def _dagilim(selections: Sequence[Selection]) -> dict[str, int]:
	out: dict[str, int] = {}
	for s in selections:
		out[s.chosen_name] = out.get(s.chosen_name, 0) + 1
	return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main(argv: Sequence[str] | None = None) -> int:
	"""`python3 -m tradehub_core.media.pipeline.simulator.srcset [--all] [--source-width N]`."""
	import argparse

	ap = argparse.ArgumentParser(description="Önizleme simülatörü — srcset seçimi")
	ap.add_argument("--all", action="store_true", help="Yalnız birincil bölgeler yerine 15 bölgenin tamamı")
	ap.add_argument("--source-width", type=int, default=0, help="Kaynak görselin genişliği (upscale yasağı)")
	ap.add_argument("--sizes", action="store_true", help="Bölge başına üretilen `sizes` dizgesini bas")
	ns = ap.parse_args(argv)

	devices = load_devices()
	layout = load_layout()
	regions = layout.all_regions() if ns.all else layout.primary_regions()
	sonuc = simulate_matrix(devices, regions, layout, source_width=ns.source_width)

	print(format_table(sonuc))
	print()
	ozet = summarize(sonuc)
	print(
		f"toplam={ozet['toplam']}  kaynak_yetersiz={ozet['kaynak_yetersiz']}  "
		f"asiri_servis={ozet['asiri_servis']}  zoom_yetersiz={ozet['zoom_yetersiz']}  "
		f"ort_fazlalik={ozet['ortalama_fazlalik']:.2f}×"
	)
	if ns.sizes:
		print()
		for r in regions:
			print(f"{r.key}\n  sizes=\"{sizes_attribute(r, layout)}\"")
	return 0


if __name__ == "__main__":  # pragma: no cover
	raise SystemExit(main())


__all__ = [
	"WARN_SOURCE_INSUFFICIENT",
	"WARN_OVERSHOOT",
	"WARN_ZOOM_INSUFFICIENT",
	"WARN_NO_PROFILE",
	"SimulatorDataError",
	"Device",
	"Container",
	"Region",
	"Page",
	"Rendition",
	"Selection",
	"Layout",
	"load_devices",
	"load_layout",
	"box_width",
	"demand_multiplier",
	"renditions_for",
	"select_rendition",
	"simulate",
	"simulate_matrix",
	"sizes_attribute",
	"srcset_attribute",
	"format_table",
	"summarize",
	"main",
]
