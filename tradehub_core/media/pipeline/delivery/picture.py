"""T-120 — `RenderManifest` → `<picture>` HTML.

NEDEN BU MODÜL, "HTML ÜRETMİYORUZ" KARARINDAN SONRA VAR
--------------------------------------------------------
`contracts/delivery.py` modül başlığı manifestin **veri** döndürdüğünü, HTML
döndürmediğini söyler ve gerekçesi geçerlidir: storefront Alpine, admin panel
Vue kullanıyor; işaretlemeyi sözleşmeye gömmek aynı kuralı iki şablon motoruna
mahkûm etmek olurdu.

Bu modül o kararı BOZMAZ, üstüne bir katman ekler. `delivery/manifest.py` hâlâ
tek gerçek kaynaktır; burada tek satır seçim kuralı, tek satır profil bilgisi
YOKTUR — girdi bitmiş bir `RenderManifest`'tir. Üç somut tüketicisi var:

  1. **Sunucu tarafı işaretleme** — Frappe web template'i, e-posta, `og:image`
     eşliğindeki `<noscript>` gövdesi. Bunların Alpine'ı da Vue'su da yok.
  2. **Referans uygulama** — iki frontend'in üreteceği işaretlemenin ölçütü.
     `tests/test_delivery_picture.py` bu çıktının üstünde koşar; frontend
     ekibinin elinde "doğru çıktı şudur" diye gösterilecek bir dizge olur.
  3. **Ölçüm** — üretilen HTML'i tarayıcıya vermeden `srcset`/`sizes`/
     `width`/`height`/`fetchpriority` var mı diye denetleyebilmek.
     `docs/reports/03-performans-taban-cizgisi.md` §2.2'nin ölçtüğü tablo tam
     olarak budur ve bugün dört sayfada da **0/22, 0/51, 0/31, 0/26**'dır.

TASARIM KARARLARI
-----------------
`width`/`height` **HER ZAMAN** yazılır. Yazılamıyorsa `PictureError` atılır —
öznitelik sessizce düşürülmez. Gerekçe: `03-performans-taban-cizgisi.md`
§2.3'te mobil ürün listelemede ölçülen **CLS 0,51** (eşik 0,25) ve §4.3'ün
tespiti: bugün yazılan `width`/`height` değerleri gerçek en-boy oranını
YANSITMIYOR; sayfayı ayakta tutan şey Tailwind `aspect-*` kapları. Yanlış oran
yazmak ile hiç yazmamak arasında seçim yapmıyoruz: oran bilinmiyorsa üretim
durur.

**Tek biçim varsa `<picture>` sarmalı üretilmez.** `product.image` merdiveninin
`w96`/`w192` basamakları yalnız `webp` taşır (politika); tek `<source>`lu bir
`<picture>` tarayıcıya hiçbir seçim sunmaz, yalnız DOM düğümü ekler.

**Yedek biçim `<source>` olarak DEĞİL, `<img>` üstünde taşınır.** Biçim
listesinin sonuncusu (en yaygın desteklenen) `<img srcset>`'e yazılır; aynı
`srcset`i hem `<source>` hem `<img>` olarak iki kez basmak baytı çoğaltır ve
seçimi değiştirmez.

`priority=True` DAVRANIŞI
-------------------------
    loading         özniteliği HİÇ YAZILMAZ (varsayılan `eager` zaten budur;
                    `loading="eager"` yazmak bazı tarayıcılarda lazy-load
                    sezgiselini gereksiz yere devreye sokar)
    fetchpriority   "high"
    decoding        "sync"

Ölçülen durum (§2.2): dört sayfanın hiçbirinde `fetchpriority` yok; LCP
görselinin dördü de "ilk belgede keşfedilebilir" denetiminden düşüyor. İkinci
sorun için `preload_link()` var.

LQIP
----
`lqip` verilirse `<img>`'in `background-image`'ı olur. `tradehub_core/media/pipeline/image/
lqip.py` ThumbHash üretir; buraya **hazır data URI** ya da düz renk gelir — bu
modül kodlama yapmaz, yalnız yazar.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.contracts.delivery import (
	LOADING_EAGER,
	LOADING_LAZY,
	RenderManifest,
	SourceSet,
	Variant,
)

#: `<img>` üzerinde öznitelik sırası. Sabittir: çıktının ETag'i ve testteki
#: karşılaştırma dizgesi öznitelik sırasına bağlıdır.
IMG_ATTR_ORDER: Tuple[str, ...] = (
	"src",
	"srcset",
	"sizes",
	"alt",
	"width",
	"height",
	"loading",
	"decoding",
	"fetchpriority",
	"class",
	"id",
	"style",
)

#: `<source>` üzerinde öznitelik sırası.
SOURCE_ATTR_ORDER: Tuple[str, ...] = ("type", "srcset", "sizes", "media", "width", "height")

#: Kabul edilen şema önekleri. `javascript:` ve `vbscript:` HER ZAMAN reddedilir
#: — manifest bizim ürettiğimiz adresleri taşısa bile, `url_for` çözücüsü
#: dışarıdan enjekte edilebilir bir kancadır.
_DANGEROUS_SCHEME = re.compile(r"^\s*(javascript|vbscript|file)\s*:", re.IGNORECASE)

#: LQIP data URI'sinin kabul edilen biçimi. CSS `url()` içine tırnaksız
#: yazılacağı için boşluk/tırnak/parantez taşıyan bir dizge REDDEDİLİR.
_DATA_URI = re.compile(r"^data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+$")

#: Düz renk placeholder — `#rgb`, `#rrggbb`, `#rrggbbaa`.
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class PictureError(ValueError):
	"""İşaretleme üretilemedi — eksik `width`/`height`, güvensiz URL vb.

	Bu hata bilinçli olarak "sessiz düşürme"nin yerini alır: eksik öznitelikle
	HTML basmak, ölçüm tablosunda (`03-performans-taban-cizgisi.md` §2.2)
	"var" görünüp CLS/LCP tarafında karşılığı olmayan bir satır üretir.
	"""


# ── Yardımcılar ────────────────────────────────────────────────────────


def escape_attr(value: Any) -> str:
	"""Öznitelik değerini kaçışla. `&`, `<`, `>`, `"`, `'` dönüştürülür."""
	return html.escape(str(value), quote=True)


def safe_url(url: str) -> str:
	"""URL'i doğrula ve kaçışla. Tehlikeli şema `PictureError`'dır."""
	metin = str(url or "")
	if not metin.strip():
		raise PictureError("Boş URL ile `<img src>` üretilemez.")
	if _DANGEROUS_SCHEME.match(metin):
		raise PictureError(f"Güvensiz URL şeması reddedildi: {metin[:40]!r}")
	return escape_attr(metin)


#: Boş değerle bile YAZILAN öznitelikler. `alt=""` bilinçli "dekoratif" işaretidir;
#: düşürülürse ekran okuyucu dosya adını okur — boş `alt` ile eksik `alt` aynı şey değildir.
KEEP_EMPTY: Tuple[str, ...] = ("alt",)


def _attrs(pairs: Sequence[Tuple[str, Any]], order: Sequence[str]) -> str:
	"""`(ad, değer)` çiftlerini sabit sırayla öznitelik dizgesine çevir.

	Değeri `None` ya da boş dizge olan öznitelik YAZILMAZ — `KEEP_EMPTY`
	listesindekiler hariç.
	"""
	sozluk = {k: v for k, v in pairs if v is not None and (v != "" or k in KEEP_EMPTY)}
	bilinmeyen = [k for k in sozluk if k not in order]
	if bilinmeyen:
		raise PictureError(f"Sıralamada yeri olmayan öznitelik: {sorted(bilinmeyen)}")
	parcalar = [f'{k}="{sozluk[k]}"' for k in order if k in sozluk]
	return " ".join(parcalar)


def _variant_for_url(manifest: RenderManifest, url: str) -> Optional[Variant]:
	for v in manifest.variants:
		if v.url == url:
			return v
	return None


# ── İçsel ölçü (CLS) ───────────────────────────────────────────────────


def intrinsic_size(manifest: RenderManifest) -> Tuple[int, int]:
	"""`width`/`height` için kullanılacak içsel ölçü. Bilinmiyorsa HATA.

	Üç kaynak, bu sırayla:

	  1. `manifest.intrinsic_width/height` — çağıran ölçtüyse tek doğru kaynak.
	  2. Yedek varyantın `width`/`height` alanı — `render.py` `fit: pad`
	     profillerinde ikisini de doldurur.
	  3. Politikanın `target_ratio`'su + varyant genişliği — `fit: pad`
	     basamaklarda tuval oranı GARANTİDİR (`build_canvas`), dolayısıyla
	     yükseklik türetmek varsayım değil hesaptır.

	Hiçbiri yoksa `PictureError`. `fit: contain` basamaklarda oran kaynağın
	oranıdır ve manifest onu taşımıyorsa **ÖLÇÜLMEMİŞTİR** — uydurmak yerine
	durulur.
	"""
	w, h = int(manifest.intrinsic_width or 0), int(manifest.intrinsic_height or 0)
	if w > 0 and h > 0:
		return (w, h)

	varyant = _variant_for_url(manifest, manifest.fallback_url)
	if varyant is not None and varyant.width > 0 and varyant.height > 0:
		return (int(varyant.width), int(varyant.height))

	if varyant is not None and varyant.width > 0:
		oran = _policy_ratio(manifest.slot_key, varyant.profile)
		if oran:
			return (int(varyant.width), int(round(varyant.width / oran)))

	raise PictureError(
		f"`{manifest.slot_key}`: içsel ölçü bilinmiyor, `width`/`height` yazılamaz. "
		"Manifest `intrinsic` ile kurulmalı — oran uydurmak CLS'i ölçülemez kılar."
	)


def _policy_ratio(slot_key: str, profile_name: str) -> float:
	"""`fit: pad` profilinin garanti ettiği en-boy oranı; yoksa 0.0."""
	try:
		from tradehub_core.media.pipeline.image import render as render_mod

		profil = render_mod.profile_for(slot_key, profile_name)
	except Exception:
		return 0.0
	if getattr(profil, "fit", "") != "pad":
		return 0.0
	deger = profil.target_ratio_value
	return float(deger) if deger else 0.0


# ── Seçenekler ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PictureOptions:
	"""İşaretleme seçenekleri. Hiçbiri manifestin verisini EZMEZ, ekler.

	Args:
	    priority: `None` → manifestten oku (`loading == "eager"`). `True` →
	        LCP adayı işaretlemesi (`loading` yok, `fetchpriority="high"`,
	        `decoding="sync"`). `False` → `loading="lazy"`.
	    sizes: manifestteki `sizes`i ezer. Boş bırakılırsa manifestinki.
	    lqip: `data:image/...;base64,...` ya da `#rrggbb`. Arka plan olur.
	    css_class / img_class: `<picture>` ve `<img>` sınıfları.
	    pretty: satır sonu + sekme ile biçimlendir (okuma/gözle denetim için).
	    require_alt: boş `alt` ile üretimi reddet (bilinçli dekoratif görselde
	        `False` bırakılır).
	"""

	priority: Optional[bool] = None
	sizes: str = ""
	alt: Optional[str] = None
	lqip: str = ""
	css_class: str = ""
	img_class: str = ""
	img_id: str = ""
	extra_style: str = ""
	pretty: bool = False
	require_alt: bool = False


DEFAULT_OPTIONS = PictureOptions()


# ── Yardımcı hesaplar ──────────────────────────────────────────────────


def is_priority(manifest: RenderManifest, options: PictureOptions = DEFAULT_OPTIONS) -> bool:
	"""LCP adayı mı — seçenek verilmişse o, yoksa manifestin `loading`i."""
	if options.priority is not None:
		return bool(options.priority)
	return manifest.loading == LOADING_EAGER or manifest.fetchpriority == "high"


def loading_attrs(priority: bool) -> Dict[str, str]:
	"""`loading` / `decoding` / `fetchpriority` üçlüsü.

	`priority` iken `loading` anahtarı sözlükte HİÇ BULUNMAZ — `_attrs` boş
	değeri atlamakla kalmaz, buradan zaten gelmez. `loading="eager"` yazmak
	varsayılanı tekrar etmektir ve bazı tarayıcılarda lazy-load sezgiselini
	gereksiz yere uyandırır.
	"""
	if priority:
		return {"decoding": "sync", "fetchpriority": "high"}
	return {"loading": LOADING_LAZY, "decoding": "async"}


def lqip_style(lqip: str) -> str:
	"""LQIP'ten CSS `background` bildirimi. Boşsa boş dizge.

	Kabul edilen iki biçim: `data:image/…;base64,…` ve `#rrggbb`. Başka bir
	şey `PictureError`'dır — serbest metin CSS'e yazmak öznitelik kaçışı
	(`style` içinden `</style>` ya da `url(javascript:…)`) demektir.
	"""
	deger = (lqip or "").strip()
	if not deger:
		return ""
	if _HEX_COLOR.match(deger):
		return f"background-color:{deger}"
	if _DATA_URI.match(deger):
		return (
			f"background-image:url({deger});background-size:cover;"
			"background-position:center;background-repeat:no-repeat"
		)
	raise PictureError(
		"LQIP yalnız `data:image/*;base64,…` ya da `#rrggbb` olabilir; "
		f"gelen: {deger[:32]!r}"
	)


def _style(options: PictureOptions) -> str:
	parcalar = [p for p in (lqip_style(options.lqip), (options.extra_style or "").strip()) if p]
	return ";".join(parcalar)


def _sizes(manifest: RenderManifest, options: PictureOptions) -> str:
	return options.sizes or manifest.sizes or ""


def _alt(manifest: RenderManifest, options: PictureOptions) -> str:
	metin = manifest.alt if options.alt is None else options.alt
	metin = metin or ""
	if options.require_alt and not metin.strip():
		raise PictureError(
			f"`{manifest.slot_key}`: `alt` boş ve `require_alt` açık. "
			"Dekoratif görselde `require_alt=False` bırakılır."
		)
	return metin


def _image_sources(manifest: RenderManifest) -> Tuple[SourceSet, ...]:
	"""Boş `srcset` taşıyan kaynakları ele.

	Manifest üretimi zaten üretilmemiş varyantı dışarıda bırakır; bu süzgeç
	video manifestini yanlışlıkla buraya vermeye karşı ikinci settir.
	"""
	return tuple(s for s in manifest.sources if (s.srcset or "").strip())


# ── Ana üretim ─────────────────────────────────────────────────────────


def render_picture(manifest: RenderManifest, options: PictureOptions = DEFAULT_OPTIONS) -> str:
	"""Manifestten `<picture>` (ya da tek biçimde düz `<img>`) HTML'i.

	Biçim sırası manifestin `sources` sırasıdır — `delivery/manifest.py`
	`FORMAT_ORDER` ile AVIF → WebP → JPEG/PNG olarak sabitlenmiştir; burada
	yeniden sıralama YAPILMAZ (iki yerde iki sıra olmasın diye).

	Raises:
	    PictureError: içsel ölçü yoksa, hiç kaynak yoksa, URL güvensizse.
	"""
	kaynaklar = _image_sources(manifest)
	if not kaynaklar:
		raise PictureError(
			f"`{manifest.slot_key}`: manifestte `srcset` taşıyan kaynak yok; "
			"`<picture>` üretmek boş bir kabuk demektir."
		)

	img = render_img(manifest, options, _sources=kaynaklar)
	if len(kaynaklar) == 1:
		# Tek biçim → `<picture>` hiçbir seçim sunmaz, yalnız düğüm ekler.
		return img

	sizes = _sizes(manifest, options)
	source_etiketleri: List[str] = []
	for s in kaynaklar[:-1]:
		# Sonuncu biçim `<img>` üstünde taşınır; burada tekrar edilmez.
		gov = _attrs(
			[("type", escape_attr(s.type)), ("srcset", escape_attr(s.srcset)),
			 ("sizes", escape_attr(s.sizes or sizes))],
			SOURCE_ATTR_ORDER,
		)
		source_etiketleri.append(f"<source {gov}>")

	sinif = f' class="{escape_attr(options.css_class)}"' if options.css_class else ""
	if options.pretty:
		ic = "\n\t".join(source_etiketleri + [img])
		return f"<picture{sinif}>\n\t{ic}\n</picture>"
	return f"<picture{sinif}>" + "".join(source_etiketleri) + img + "</picture>"


def render_img(
	manifest: RenderManifest,
	options: PictureOptions = DEFAULT_OPTIONS,
	*,
	_sources: Optional[Sequence[SourceSet]] = None,
) -> str:
	"""Tek `<img>` etiketi — `<picture>` sarmalı olmadan.

	`srcset` YEDEK biçimden (biçim listesinin sonuncusu) alınır. `<picture>`
	içinde de aynı etiket kullanılır; iki kod yolu olmasın diye ayrılmadı.
	"""
	kaynaklar = tuple(_sources) if _sources is not None else _image_sources(manifest)
	if not kaynaklar:
		raise PictureError(f"`{manifest.slot_key}`: `srcset` taşıyan kaynak yok.")

	genislik, yukseklik = intrinsic_size(manifest)
	oncelik = is_priority(manifest, options)
	yedek = kaynaklar[-1]
	sizes = _sizes(manifest, options)

	ciftler: List[Tuple[str, Any]] = [
		("src", safe_url(manifest.fallback_url)),
		("srcset", escape_attr(yedek.srcset)),
		("sizes", escape_attr(yedek.sizes or sizes)),
		("alt", escape_attr(_alt(manifest, options))),
		("width", genislik),
		("height", yukseklik),
		("class", escape_attr(options.img_class) if options.img_class else ""),
		("id", escape_attr(options.img_id) if options.img_id else ""),
		("style", escape_attr(_style(options))),
	]
	ciftler.extend((k, v) for k, v in loading_attrs(oncelik).items())

	return f"<img {_attrs(ciftler, IMG_ATTR_ORDER)}>"


def preload_link(
	manifest: RenderManifest,
	options: PictureOptions = DEFAULT_OPTIONS,
	*,
	fmt: str = "",
) -> str:
	"""LCP görseli için `<link rel="preload" as="image">`.

	ÖLÇÜLEN GEREKÇE: `docs/reports/03-performans-taban-cizgisi.md` §1 — dört
	sayfanın DÖRDÜNDE de LCP görseli "ilk belgede keşfedilebilir" denetiminden
	**FAILED**; storefront istemci-taraflı render olduğu için ham HTML'de
	`<img>` sayısı **0**. Yani LCP görseli ancak JS çalıştıktan sonra
	keşfediliyor. `preload` bu zinciri kısaltan tek işaretleme aracıdır.

	`imagesrcset` + `imagesizes` çifti `srcset`li görselde ZORUNLUDUR; yalnız
	`href` vermek tarayıcıya yanlış (çoğu zaman en büyük) adayı indirtir.

	Args:
	    fmt: hangi biçim ön yüklensin. Boşsa manifestin İLK biçimi (AVIF)
	        seçilir — `<picture>` sırasıyla aynı tercih.
	"""
	kaynaklar = _image_sources(manifest)
	if not kaynaklar:
		raise PictureError(f"`{manifest.slot_key}`: ön yüklenecek kaynak yok.")
	secilen = kaynaklar[0]
	if fmt:
		eslesen = [s for s in kaynaklar if s.fmt.lower() == fmt.lower()]
		if not eslesen:
			raise PictureError(
				f"`{manifest.slot_key}`: `{fmt}` biçimi manifestte yok "
				f"({[s.fmt for s in kaynaklar]})."
			)
		secilen = eslesen[0]

	sizes = _sizes(manifest, options)
	ciftler = [
		("rel", "preload"),
		("as", "image"),
		("type", escape_attr(secilen.type)),
		("imagesrcset", escape_attr(secilen.srcset)),
		("imagesizes", escape_attr(secilen.sizes or sizes)),
		("fetchpriority", "high"),
	]
	gov = " ".join(f'{k}="{v}"' for k, v in ciftler if v)
	return f"<link {gov}>"


def audit(html_metni: str) -> Dict[str, Any]:
	"""Üretilen işaretlemeyi `03-performans-taban-cizgisi.md` §2.2 tablosuna göre denetle.

	Aynı sayımı yapan tarayıcı tarafı ölçüm bugün **0/22, 0/51, 0/31, 0/26**
	veriyor. Bu fonksiyon "sonra" sütununu HTML'e bakarak, tarayıcı açmadan
	doldurur; Faz 12 kabul raporunun aracıdır.
	"""
	img_sayisi = len(re.findall(r"<img\b", html_metni))
	return {
		"img": img_sayisi,
		"picture": len(re.findall(r"<picture\b", html_metni)),
		"source": len(re.findall(r"<source\b", html_metni)),
		"srcset": len(re.findall(r"\bsrcset=", html_metni)),
		"sizes": len(re.findall(r"\bsizes=", html_metni)),
		"width_height": len(re.findall(r'\bwidth="\d+"\s+height="\d+"', html_metni)),
		"loading_lazy": len(re.findall(r'loading="lazy"', html_metni)),
		"fetchpriority_high": len(re.findall(r'fetchpriority="high"', html_metni)),
		"decoding": len(re.findall(r"\bdecoding=", html_metni)),
		"preload": len(re.findall(r'rel="preload"', html_metni)),
		"alt": len(re.findall(r"\balt=", html_metni)),
		"eksik_boyut": img_sayisi - len(re.findall(r'\bwidth="\d+"\s+height="\d+"', html_metni)),
	}


def render_many(
	manifestler: Iterable[RenderManifest],
	options: PictureOptions = DEFAULT_OPTIONS,
	*,
	first_is_priority: bool = False,
) -> str:
	"""Bir listedeki tüm manifestleri sırayla bas.

	`first_is_priority=True` ise İLK öğe LCP adayı işaretlemesi alır, kalanı
	`lazy`. Karusel/galeri kuralı budur: ilk slayt eager, kalanı lazy
	(`docs/plans/faz12-lcp.md` §3).
	"""
	cikti: List[str] = []
	for i, m in enumerate(manifestler):
		if first_is_priority:
			opt = PictureOptions(
				priority=(i == 0),
				sizes=options.sizes,
				alt=options.alt,
				lqip=options.lqip,
				css_class=options.css_class,
				img_class=options.img_class,
				img_id=options.img_id,
				extra_style=options.extra_style,
				pretty=options.pretty,
				require_alt=options.require_alt,
			)
		else:
			opt = options
		cikti.append(render_picture(m, opt))
	return ("\n" if options.pretty else "").join(cikti)


__all__ = [
	"IMG_ATTR_ORDER",
	"KEEP_EMPTY",
	"SOURCE_ATTR_ORDER",
	"PictureError",
	"PictureOptions",
	"DEFAULT_OPTIONS",
	"escape_attr",
	"safe_url",
	"intrinsic_size",
	"is_priority",
	"loading_attrs",
	"lqip_style",
	"render_picture",
	"render_img",
	"preload_link",
	"render_many",
	"audit",
]
