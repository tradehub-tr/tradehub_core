"""T-083 çekirdeği — `DeliveryManifest` sözleşmesinin çalışan uygulaması.

ÖLÇÜLEN BOŞLUK
--------------
`docs/reports/08-canli-olcum.md`: incelenen **31 görselin 0'ında** `srcset`
var (ana sayfa 22'nin 0'ı, listeleme 51'in 0'ı) ve ürün detay sayfası
**13,14 MB** görsel indiriyor — 900 KB hedefinin **15 katı**. Türev üretmek
(Faz 6) tek başına bu sayıyı düşürmez: tarayıcının doğru türevi SEÇMESİ
gerekir, o da `srcset`/`sizes` üretimine bağlıdır.

Bu modül üreten (motor) ile tüketen (storefront Alpine, admin-panel Vue)
arasındaki tek veri sözleşmesini üretir. **HTML üretmez** — gerekçe
`contracts/delivery.py` modül başlığında: iki frontend iki farklı şablon
motoru kullanıyor, işaretleme üretmek aynı kuralı iki yerde yazmak olurdu.

ÜRETİLMEMİŞ VARYANT `srcset`E GİRMEZ
------------------------------------
`build_image(available_profiles=[...])` bir SÜZGEÇTİR, temenni değil.
Üretilmemiş bir profili `srcset`e yazmak tarayıcıya 404 indirtir ve görsel
HİÇ görünmez — bugünkü "hiç srcset yok" durumundan daha kötü bir sonuçtur.
`api/delivery.py` bu listeyi her zaman varlık kaydından doldurur; `None`
geçmez.

`sizes` NEDEN VARSAYILAN OLARAK BOŞ
-----------------------------------
`sizes` dizgesi ölçülmüş CSS kutu genişliklerinden türetilir. Kutular
`docs/reports/03-render-envanteri.md` §3'te ÖLÇÜLÜ — ama aynı belge §3.1
altında şunu da kaydediyor: kutu genişliği viewport ile **monoton artmıyor**
(640px'te 296px, 768px'te 147px'e düşüyor, çünkü `lg` hem 3 sütuna geçiyor
hem 240px filtre çubuğunu açıyor). Bu, `sizes`in basit bir `(min-width: …)
Xvw` zinciriyle ifade EDİLEMEYECEĞİ, kırılım başına ayrı sabit değer
gerektireceği anlamına gelir.

O tabloyu türetmek ayrı bir iştir ve **BU FAZDA YAPILMADI (ÖLÇÜLMEDİ)**.
Bu yüzden `SIZES_TABLE` boş gelir ve `sizes_attribute()` bilinmeyen bağlamda
boş dizge döndürür. Sözleşmenin kendi ifadesiyle: *`sizes` yazmamak, YANLIŞ
`sizes` yazmaktan iyidir.* Tablo dışarıdan enjekte edilebilir; ölçüm
yapıldığında kod değişmeden dolar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.contracts.delivery import (
	LOADING_EAGER,
	LOADING_LAZY,
	RenderManifest,
	SourceSet,
	Variant,
	derivative_key,
	mime_for,
)
from tradehub_core.media.pipeline.contracts.errors import NoProfileAvailable
from tradehub_core.media.pipeline.contracts.storage import SCOPE_PUBLIC, ObjectRef
from tradehub_core.media.pipeline.image import render as render_mod

#: Biçim tercih sırası. Tarayıcı `<picture>` içinde İLK desteklediğini seçer,
#: bu yüzden en verimli biçim başta olmalı. AVIF > WebP > JPEG/PNG sırası
#: `policy/slots/*.json` profillerinin `formats` dizilimiyle aynı yöndedir.
FORMAT_ORDER: Tuple[str, ...] = ("avif", "webp", "jpeg", "jpg", "png")

#: Video kapsayıcı tercih sırası — `role: primary` WebM, `role: fallback` MP4
#: (policy/slots/company-cover-video.json).
CONTAINER_ORDER: Tuple[str, ...] = ("webm", "mp4")

#: LCP adayı görselde kullanılan öznitelikler (FR-124 komşusu). `sync` decoding
#: yalnız LCP adayında anlamlı; her görselde kullanmak ana iş parçacığını
#: bloklar.
LCP_LOADING: str = LOADING_EAGER
LCP_DECODING: str = "sync"
LCP_FETCHPRIORITY: str = "high"

#: Bağlam bazlı `sizes` tablosu — ÖLÇÜLMEDİ, bilinçli olarak BOŞ.
#: Biçim: {(slot_key, context): "sizes dizgesi"}. Modül başlığı §4'e bakın.
SIZES_TABLE: Dict[Tuple[str, str], str] = {}

#: `sizes` kaynağını yanıta yazmak için. İstemci "boş çünkü ölçülmedi" ile
#: "boş çünkü bu bağlamda gerekmiyor" arasını ayırt edebilmeli.
SIZES_SOURCE_TABLE: str = "table"
SIZES_SOURCE_CALLER: str = "caller"
SIZES_SOURCE_UNMEASURED: str = "unmeasured"

UrlResolver = Callable[[ObjectRef], str]

#: T-061/062/065 — `build_image(version_meta=…)` ile manifeste giren sürüm
#: alanları. Süzgeç bilinçli: çağıran DB satırını olduğu gibi geçebilir,
#: manifeste yalnız sözleşmedeki anahtarlar sızar (`policy_snapshot` gibi
#: iç alanlar dışarı çıkmaz).
VERSION_META_KEYS: Tuple[str, ...] = (
	"width",
	"height",
	"dpi",
	"colorspace",
	"has_alpha",
	"classification",
	"classification_confidence",
	"format_chain",
	"lqip",
	"lqip_data_uri",
	"dominant_color",
)


def default_url_for(ref: ObjectRef) -> str:
	"""Varsayılan URL çözücü — `ObjectRef.url`.

	Private kapsamda bu URL imzasızdır ve doğrudan servis EDİLEMEZ; imzalı
	URL üretimi `delivery/signed.py`'nin işidir ve `api/delivery.py` onu ayrı
	bir uçtan verir. Manifestin içine imzalı URL gömmek, manifestin ETag'ini
	her istekte değiştirir (imza `iat` taşır) ve önbelleği tamamen öldürürdü.
	"""
	return ref.url


@dataclass(frozen=True)
class VideoRendition:
	"""Politikanın `video.renditions[]` girdisinin kod karşılığı."""

	id: str
	container: str
	width: int = 0
	height: int = 0
	role: str = ""
	mime: str = ""
	max_bytes: int = 0
	served_when: str = ""
	implemented_today: bool = False

	@property
	def content_type(self) -> str:
		"""`mime` politikada yazılıysa o, değilse kapsayıcıdan türetilir."""
		return self.mime or mime_for(self.container)

	@classmethod
	def from_dict(cls, data: Mapping[str, Any]) -> VideoRendition:
		return cls(
			id=str(data.get("id") or ""),
			container=str(data.get("container") or ""),
			width=int(data.get("width") or 0),
			height=int(data.get("height") or 0),
			role=str(data.get("role") or ""),
			mime=str(data.get("mime") or ""),
			max_bytes=int(data.get("max_bytes") or 0),
			served_when=str(data.get("served_when") or ""),
			implemented_today=bool(data.get("implemented_today")),
		)


def video_renditions(slot_key: str) -> Tuple[VideoRendition, ...]:
	"""Slotun video türev listesi. Video slotu değilse boş demet."""
	policy = render_mod.load_slot_policy(slot_key)
	ham = ((policy.get("video") or {}).get("renditions")) or ()
	return tuple(VideoRendition.from_dict(r) for r in ham)


def poster_profiles(slot_key: str) -> Tuple[str, str]:
	"""`(birincil, yedek)` poster profil adları — politikadan.

	Boş dönerse slotun poster kuralı YAZILMAMIŞ demektir; çağıran poster
	üretemez ve bunu `poster_url=""` ile bildirir. Varsayılan bir profil adı
	UYDURULMAZ.
	"""
	policy = render_mod.load_slot_policy(slot_key)
	poster = (policy.get("video") or {}).get("poster") or {}
	return (str(poster.get("profile") or ""), str(poster.get("fallback_profile") or ""))


@dataclass
class ManifestBuilder:
	"""`contracts.delivery.DeliveryManifest` uygulaması. **Saf** — depoya bakmaz.

	Args:
	    url_for: `ObjectRef` → URL. Varsayılan `ObjectRef.url`.
	    sizes_table: `{(slot_key, context): sizes}`. Varsayılan BOŞ (ÖLÇÜLMEDİ).
	"""

	url_for: UrlResolver = default_url_for
	sizes_table: Dict[Tuple[str, str], str] = field(default_factory=lambda: dict(SIZES_TABLE))

	# ── görsel ─────────────────────────────────────────────────────────

	def build_image(
		self,
		slot_key: str,
		base: ObjectRef,
		*,
		intrinsic: Tuple[int, int] = (0, 0),
		alt: str = "",
		sizes: str = "",
		available_profiles: Optional[Sequence[str]] = None,
		is_lcp_candidate: bool = False,
		version_meta: Optional[Mapping[str, Any]] = None,
	) -> RenderManifest:
		"""Görsel manifesti. Yalnız ÜRETİLMİŞ profiller `srcset`e girer.

		`available_profiles=None` sözleşmenin tanımladığı "hepsi mevcut
		varsayılır" davranışıdır ve yalnız ölçüm/simülasyon içindir; üretim
		yolu (`api/delivery.py`) her zaman gerçek listeyi geçer.

		`version_meta` (T-061/062/065): `Media Version` satırının zenginleştirme
		alanları (`doctype/media_version.py::version_enrichment_for_assets`
		çıktısı). Verilirse `VERSION_META_KEYS` süzgecinden geçip manifeste
		`version` olarak girer; `lqip`/`dominant_color` üst düzey anahtar olarak
		da döner (`RenderManifest.to_dict`) — frontend'in yer tutucusu için
		`data:image/…` URI'si, o yoksa baskın renk seçilir (`delivery/
		picture.py::lqip_style` ikisini de kabul eder, ham ThumbHash'i ETMEZ).
		Bu parametre kw-only ve varsayılanı `None`: `contracts.delivery.
		DeliveryManifest` protokol imzası DEĞİŞMEDİ (signatures.golden.json).
		"""
		profiller = render_mod.load_profiles(slot_key)
		if not profiller:
			raise NoProfileAvailable(
				f"`{slot_key}` slotunda hiç türev profili tanımlı değil.",
				detay={"slot_key": slot_key},
			)

		suzgec = None if available_profiles is None else {str(p) for p in available_profiles}
		varyantlar: list = []
		for profil in profiller:
			mevcut = suzgec is None or profil.name in suzgec
			for fmt in profil.formats:
				anahtar = derivative_key(base.key, profil.name, fmt)
				ref = ObjectRef(key=anahtar, scope=base.scope)
				varyantlar.append(
					Variant(
						profile=profil.name,
						url=self.url_for(ref),
						width=profil.width,
						fmt=fmt,
						height=profil.height,
						available=mevcut,
					)
				)

		uretilmis = [v for v in varyantlar if v.available]
		if not uretilmis:
			# Boş `srcset` yazmak tarayıcıyı `src`ye düşürür ve "ölçüm yapıldı"
			# görüntüsü verir. Hata vermek, sessiz başarısızlıktan iyidir.
			raise NoProfileAvailable(
				f"`{slot_key}` için üretilmiş hiçbir türev yok; manifest kurulamaz.",
				detay={
					"slot_key": slot_key,
					"requested": sorted(suzgec) if suzgec is not None else [],
					"defined": [p.name for p in profiller],
				},
			)

		sizes_str = sizes or self.sizes_attribute(slot_key)
		kaynaklar = self._sources(uretilmis, sizes_str)
		fallback = self._fallback_url(uretilmis)

		ekstra: Dict[str, Any] = {
			"sizes_source": SIZES_SOURCE_CALLER
			if sizes
			else (SIZES_SOURCE_TABLE if sizes_str else SIZES_SOURCE_UNMEASURED),
			"available_profiles": sorted({v.profile for v in uretilmis}),
			"missing_profiles": sorted({v.profile for v in varyantlar if not v.available}),
		}
		surum = self._version_meta(version_meta)
		if surum:
			ekstra["version"] = surum
			# Yer tutucu SEÇİMİ burada verilir ki iki frontend iki ayrı kural
			# yazmasın: hazır data URI > baskın renk. Ham ThumbHash üst düzeye
			# ÇIKMAZ — `lqip_style` onu reddeder; kanonik hash `version.lqip`te.
			ekstra["lqip"] = str(surum.get("lqip_data_uri") or surum.get("dominant_color") or "")
			ekstra["dominant_color"] = str(surum.get("dominant_color") or "")

		return RenderManifest(
			slot_key=slot_key,
			fallback_url=fallback,
			variants=tuple(varyantlar),
			sources=kaynaklar,
			sizes=sizes_str,
			intrinsic_width=int(intrinsic[0] or 0),
			intrinsic_height=int(intrinsic[1] or 0),
			alt=alt or "",
			loading=LCP_LOADING if is_lcp_candidate else LOADING_LAZY,
			decoding=LCP_DECODING if is_lcp_candidate else "async",
			fetchpriority=LCP_FETCHPRIORITY if is_lcp_candidate else "",
			extra=ekstra,
		)

	@staticmethod
	def _version_meta(version_meta: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
		"""`version_meta` girdisini sözleşme anahtarlarına indir; boşları at."""
		if not version_meta:
			return {}
		return {
			k: version_meta[k]
			for k in VERSION_META_KEYS
			if version_meta.get(k) not in (None, "", [], ())
		}

	def _sources(self, variants: Sequence[Variant], sizes: str) -> Tuple[SourceSet, ...]:
		"""Biçim başına `<source>`. Sıra `FORMAT_ORDER`, genişlik ARTAN."""
		gruplar: Dict[str, list] = {}
		for v in variants:
			gruplar.setdefault(v.fmt.lower(), []).append(v)

		def sira(fmt: str) -> int:
			return FORMAT_ORDER.index(fmt) if fmt in FORMAT_ORDER else len(FORMAT_ORDER)

		cikti: list = []
		for fmt in sorted(gruplar, key=sira):
			# `srcset` içinde genişlik sırası tarayıcı için anlamlı değildir
			# ama okunabilirlik ve ETag kararlılığı için sabit tutulur.
			satirlar = sorted(gruplar[fmt], key=lambda v: v.width)
			cikti.append(
				SourceSet(fmt=fmt, srcset=", ".join(v.srcset_entry for v in satirlar), sizes=sizes)
			)
		return tuple(cikti)

	@staticmethod
	def _fallback_url(variants: Sequence[Variant]) -> str:
		"""`<img src>` — en yaygın desteklenen biçimin ORTA basamağı.

		En büyük basamağı fallback yapmak, `srcset` desteklemeyen (ya da JS
		kapalı) istemciye en pahalı dosyayı gönderirdi; en küçüğü yapmak ise
		bulanık görüntü verirdi. Orta basamak iki riski de sınırlar.
		"""
		tercih = [v for v in variants if v.fmt.lower() in ("jpeg", "jpg", "png")]
		aday = tercih or [v for v in variants if v.fmt.lower() == "webp"] or list(variants)
		aday = sorted(aday, key=lambda v: v.width)
		return aday[len(aday) // 2].url

	# ── video ──────────────────────────────────────────────────────────

	def build_video(
		self,
		slot_key: str,
		base: ObjectRef,
		*,
		poster: Optional[ObjectRef] = None,
		captions_url: str = "",
		intrinsic: Tuple[int, int] = (0, 0),
		available_renditions: Optional[Sequence[str]] = None,
	) -> RenderManifest:
		"""Video manifesti. Poster **zorunlu alandır**, üretimi değil.

		Poster verilmezse politikanın poster profilinden adres TÜRETİLİR
		(FR-042). Politika poster profili tanımlamamışsa `poster_url` boş
		kalır ve `extra["poster_reason"]` sebebi taşır — sessizce boş
		bırakmak, "poster üretildi ama URL kayboldu" ile aynı görünürdü.
		"""
		renditions = video_renditions(slot_key)
		if not renditions:
			raise NoProfileAvailable(
				f"`{slot_key}` slotunda video türevi tanımlı değil.",
				detay={"slot_key": slot_key},
			)

		suzgec = None if available_renditions is None else {str(r) for r in available_renditions}
		varyantlar: list = []
		for r in renditions:
			anahtar = derivative_key(base.key, r.id, r.container)
			ref = ObjectRef(key=anahtar, scope=base.scope)
			varyantlar.append(
				Variant(
					profile=r.id,
					url=self.url_for(ref),
					width=r.width,
					fmt=r.container,
					height=r.height,
					available=suzgec is None or r.id in suzgec,
				)
			)

		uretilmis = [v for v in varyantlar if v.available]
		if not uretilmis:
			raise NoProfileAvailable(
				f"`{slot_key}` için üretilmiş video türevi yok.",
				detay={"slot_key": slot_key, "defined": [r.id for r in renditions]},
			)

		mime_by_id = {r.id: r.content_type for r in renditions}
		# Videoda `srcset` yoktur; her rendition AYRI bir `<source src>`tir.
		# `SourceSet.srcset` alanı bu yüzden tek URL taşır — `<source>`
		# etiketinin `src` özniteliğine doğrudan yazılır.
		# Kapsayıcı sırası: WebM önce, MP4 sonra. Tarayıcı ilk OYNATABİLDİĞİNİ
		# seçer; VP9/Opus daha küçük dosyadır, MP4 yalnız yedektir (politikada
		# `role: fallback`).
		kaynaklar = tuple(
			SourceSet(fmt=v.fmt, srcset=v.url, sizes="")
			for v in sorted(uretilmis, key=lambda v: (CONTAINER_ORDER.index(v.fmt)
				if v.fmt in CONTAINER_ORDER else len(CONTAINER_ORDER), v.profile))
		)

		poster_url, poster_reason = self._poster(slot_key, base, poster)

		return RenderManifest(
			slot_key=slot_key,
			fallback_url=uretilmis[0].url,
			variants=tuple(varyantlar),
			sources=kaynaklar,
			sizes="",
			intrinsic_width=int(intrinsic[0] or 0),
			intrinsic_height=int(intrinsic[1] or 0),
			loading=LOADING_LAZY,
			decoding="async",
			poster_url=poster_url,
			captions_url=captions_url or "",
			extra={
				"poster_reason": poster_reason,
				"mime_by_rendition": mime_by_id,
				"available_renditions": sorted({v.profile for v in uretilmis}),
				"missing_renditions": sorted({v.profile for v in varyantlar if not v.available}),
			},
		)

	def _poster(
		self, slot_key: str, base: ObjectRef, poster: Optional[ObjectRef]
	) -> Tuple[str, str]:
		if poster is not None:
			return (self.url_for(poster), "explicit")
		birincil, _yedek = poster_profiles(slot_key)
		if not birincil:
			return ("", "policy_has_no_poster_profile")
		profiller = {p.name: p for p in render_mod.load_profiles(slot_key)}
		p = profiller.get(birincil)
		if p is None:
			return ("", f"poster_profile_not_in_profiles:{birincil}")
		fmt = p.formats[0]
		ref = ObjectRef(key=derivative_key(base.key, p.name, fmt), scope=base.scope)
		return (self.url_for(ref), "derived_from_policy")

	# ── sizes / seçim ──────────────────────────────────────────────────

	def sizes_attribute(self, slot_key: str, *, context: str = "") -> str:
		"""Slot + render bağlamı için `sizes`. Tanımsızsa BOŞ dizge.

		Tablo bugün boştur (ÖLÇÜLMEDİ — modül başlığı §4). Boş dönmek bir
		eksiklik bildirimidir, bir varsayılan değil.
		"""
		return self.sizes_table.get((slot_key, context or ""), "")

	def pick(self, slot_key: str, css_width_px: float, *, dpr: float = 1.0) -> Variant:
		"""Verilen CSS kutusu × DPR için seçilecek basamak — tarayıcı taklidi.

		Hedefi KARŞILAYAN en küçük profil seçilir; hiçbiri karşılamıyorsa en
		büyüğü döner (büyütme yerine yetersiz servis — FR-028 ile tutarlı).

		Dönen `Variant` bir ADRES taşımaz (`url=""`): seçim politikadan
		yapılır, nesneden değil. Gerçek URL'li seçim için `pick_from()`.
		"""
		profiller = render_mod.load_profiles(slot_key)
		if not profiller:
			raise NoProfileAvailable(
				f"`{slot_key}` slotunda türev profili yok.", detay={"slot_key": slot_key}
			)
		hedef = self._target_width(css_width_px, dpr)
		sirali = sorted(profiller, key=lambda p: p.width)
		secilen = next((p for p in sirali if p.width >= hedef), sirali[-1])
		return Variant(
			profile=secilen.name,
			url="",
			width=secilen.width,
			fmt=secilen.formats[0],
			height=secilen.height,
			available=True,
		)

	@staticmethod
	def pick_from(manifest: RenderManifest, css_width_px: float, *, dpr: float = 1.0) -> Variant:
		"""`pick` ile aynı kural, ama GERÇEK varyantlar arasından.

		Üretilmemiş varyantlar elenir: aksi hâlde seçim 404'e işaret ederdi.
		"""
		uretilmis = [v for v in manifest.variants if v.available]
		if not uretilmis:
			raise NoProfileAvailable(
				f"`{manifest.slot_key}` manifestinde üretilmiş varyant yok.",
				detay={"slot_key": manifest.slot_key},
			)
		hedef = ManifestBuilder._target_width(css_width_px, dpr)
		sirali = sorted(uretilmis, key=lambda v: (v.width, v.fmt))
		return next((v for v in sirali if v.width >= hedef), sirali[-1])

	def overshoot(self, slot_key: str, css_width_px: float, *, dpr: float = 1.0) -> float:
		"""Seçilen basamağın hedefe göre fazlalığı (`varyant / hedef`).

		Politikadaki `profiles[].max_overshoot` (ürün görselinde 1,85) bu
		sayının tavanıdır. Hedef 0 ise 0.0 döner — bölme hatası yerine
		"ölçülemedi".
		"""
		hedef = self._target_width(css_width_px, dpr)
		if hedef <= 0:
			return 0.0
		return self.pick(slot_key, css_width_px, dpr=dpr).width / float(hedef)

	@staticmethod
	def _target_width(css_width_px: float, dpr: float) -> int:
		"""Gerekli cihaz pikseli. Yukarı yuvarlanır: 0,5 piksel eksik servis
		etmek, tarayıcının bir üst basamağı seçmesiyle aynı sonucu vermez."""
		try:
			w = float(css_width_px) * float(dpr or 1.0)
		except (TypeError, ValueError):
			return 0
		return max(0, int(math.ceil(w)))


def build_default(url_for: Optional[UrlResolver] = None) -> ManifestBuilder:
	"""Varsayılan üretici — public kapsam, ölçülmemiş `sizes` tablosu."""
	return ManifestBuilder(url_for=url_for or default_url_for)


def ref_from_url(url: str, *, scope: str = SCOPE_PUBLIC) -> ObjectRef:
	"""`file_url` → `ObjectRef`. Yol geçişi `key_from_url` içinde reddedilir."""
	from tradehub_core.media.pipeline.contracts.storage import key_from_url

	key, cozulen = key_from_url(url)
	return ObjectRef(key=key, scope=cozulen or scope)


__all__ = [
	"FORMAT_ORDER",
	"CONTAINER_ORDER",
	"LCP_LOADING",
	"LCP_DECODING",
	"LCP_FETCHPRIORITY",
	"SIZES_TABLE",
	"SIZES_SOURCE_TABLE",
	"SIZES_SOURCE_CALLER",
	"SIZES_SOURCE_UNMEASURED",
	"VERSION_META_KEYS",
	"UrlResolver",
	"default_url_for",
	"VideoRendition",
	"video_renditions",
	"poster_profiles",
	"ManifestBuilder",
	"build_default",
	"ref_from_url",
]
