"""DeliveryManifest sözleşmesi — `srcset`/`sizes`/`<picture>` üretimi.

Ölçülen durum (docs/reports/03-render-envanteri.md, 08-canli-olcum.md):

  - `srcset`/`sizes` **31 görselin 0'ında** kullanılıyor (ana sayfa 22'nin 0'ı,
    listeleme 51'in 0'ı).
  - Ürün detay sayfası **13,14 MB** görsel indiriyor; hedef 900 KB — **15 katı**.

Yani bu sözleşmenin çözdüğü sorun teorik değil: türev merdiveni üretilse bile
onu HTML'e doğru yazacak bir katman yok. Manifest, üreten (motor) ile tüketen
(storefront Alpine bileşenleri, admin-panel Vue bileşenleri) arasındaki tek
veri sözleşmesidir; iki frontend de aynı sözlüğü okur.

Neden HTML üretmiyor
--------------------
Manifest **veri** döndürür, işaretleme değil. İki frontend iki farklı şablon
motoru kullanıyor (Alpine + Vue) ve interpolasyon sözdizimleri farklı (FR-067).
HTML üretmek, aynı kuralı iki yerde tekrar yazmak (NFR-046) ya da bir tarafı
diğerinin sözdizimine mahkûm etmek olurdu.

İDEMPOTENSİ
-----------
Tümü saf fonksiyondur: aynı politika + aynı nesne + aynı ölçüler her zaman aynı
manifest. Depoya bakmaz, varyantın gerçekten üretilmiş olup olmadığını
DOĞRULAMAZ — `available` alanı çağıran tarafından doldurulur. Doğrulamayı
sözleşmeye koymak, her render'da diske gitmek demekti.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Sequence, Tuple, runtime_checkable

from tradehub_core.media.pipeline.contracts.storage import ObjectKey, ObjectRef

# Türev dosya adı ayracı — FR-040: türevler orijinalin YANINDA, AYNI shard
# dizininde, ekli sonek ile durur. `__` seçildi: içerik-hash'li adlarda
# (yalnız [0-9a-f]) hiç geçmez, dolayısıyla ayrıştırma tersine çevrilebilir.
VARIANT_SEPARATOR: str = "__"

# MIME karşılıkları — `<source type="...">` için.
MIME_BY_FORMAT: Dict[str, str] = {
	"webp": "image/webp",
	"avif": "image/avif",
	"jpeg": "image/jpeg",
	"jpg": "image/jpeg",
	"png": "image/png",
	"tiff": "image/tiff",
	"webm": "video/webm",
	"mp4": "video/mp4",
}

# `loading` / `decoding` varsayılanları. LCP adayı görselde `eager` + `high`
# olmalı; sözleşme kararı vermez, çağıran `is_lcp_candidate` ile bildirir.
LOADING_LAZY: str = "lazy"
LOADING_EAGER: str = "eager"


def mime_for(fmt: str) -> str:
	"""Biçim adından MIME. Bilinmeyen biçim `application/octet-stream`."""
	return MIME_BY_FORMAT.get((fmt or "").lower(), "application/octet-stream")


def derivative_key(base: ObjectKey, profile: str, fmt: str) -> ObjectKey:
	"""Türevin anahtarı — orijinalle AYNI shard, ekli sonek (FR-040).

	`abc123….jpg` + `w96` + `webp` → `abc123…__w96.webp`

	Shard korunur çünkü ad değişmeyen bir hash ile başlar; bu, türevi
	orijinalin yanında tutar ve dizin dağılımını (NFR-051) bozmaz.
	"""
	govde = os.path.splitext(base.name)[0]
	ext = (fmt or "").lower().lstrip(".")
	name = f"{govde}{VARIANT_SEPARATOR}{profile}.{ext}"
	return ObjectKey(shard=base.shard, name=name)


@dataclass(frozen=True)
class Variant:
	"""Tek bir teslim edilebilir varyant.

	`available` varyantın gerçekten üretilmiş olduğunu söyler. `False` olan
	varyant `srcset`'e YAZILMAZ — yazılırsa tarayıcı 404 indirir ve görsel
	hiç görünmez. FR-033'ün "under-spec" durumu tam olarak budur: master
	küçük olduğu için üst basamaklar üretilememiştir.
	"""

	profile: str
	url: str
	width: int
	fmt: str
	height: int = 0
	size_bytes: int = 0
	available: bool = True

	@property
	def mime(self) -> str:
		return mime_for(self.fmt)

	@property
	def srcset_entry(self) -> str:
		"""`<url> <width>w` — `srcset` içindeki tek girdi."""
		return f"{self.url} {self.width}w"


@dataclass(frozen=True)
class SourceSet:
	"""Tek bir biçim için `<source>` girdisi.

	Biçim sırası ÖNEMLİ: tarayıcı ilk desteklediğini seçer, bu yüzden en
	verimli biçim (avif → webp → jpeg) başta olmalıdır.
	"""

	fmt: str
	srcset: str
	sizes: str = ""

	@property
	def type(self) -> str:
		return mime_for(self.fmt)


@dataclass(frozen=True)
class RenderManifest:
	"""Bir medya nesnesinin teslim sözleşmesi — iki frontend'in de okuduğu sözlük.

	`intrinsic_width`/`intrinsic_height` CLS koruması içindir (FR-124): kutu
	oranı bunlardan rezerve edilir. `0` ise oran bilinmiyor demektir ve çağıran
	sabit ölçü kullanmalıdır — sayı uydurmamalıdır (FR-066).
	"""

	slot_key: str
	fallback_url: str
	variants: Tuple[Variant, ...] = ()
	sources: Tuple[SourceSet, ...] = ()
	sizes: str = ""
	intrinsic_width: int = 0
	intrinsic_height: int = 0
	alt: str = ""
	loading: str = LOADING_LAZY
	decoding: str = "async"
	fetchpriority: str = ""
	poster_url: str = ""
	captions_url: str = ""
	extra: Dict[str, Any] = field(default_factory=dict)

	@property
	def aspect_ratio(self) -> float:
		"""Genişlik / yükseklik; ölçülemiyorsa 0.0."""
		return (
			self.intrinsic_width / self.intrinsic_height
			if self.intrinsic_width and self.intrinsic_height
			else 0.0
		)

	@property
	def srcset(self) -> str:
		"""Birincil (ilk) biçimin `srcset` dizgesi; yoksa boş."""
		return self.sources[0].srcset if self.sources else ""

	def to_dict(self) -> Dict[str, Any]:
		"""Frontend'e gidecek düz sözlük.

		Anahtarlar HTML özniteliklerinin adıyla aynı (`srcset`, `sizes`,
		`loading`) — çeviri katmanı olmasın diye. Boş alanlar KORUNUR:
		bir alanın "yok" olması ile "üretilmedi" olması aynı şey değil ve
		frontend ikisini ayırt edebilmeli.
		"""
		return {
			"slot_key": self.slot_key,
			"src": self.fallback_url,
			"sizes": self.sizes,
			"alt": self.alt,
			"loading": self.loading,
			"decoding": self.decoding,
			"fetchpriority": self.fetchpriority,
			"width": self.intrinsic_width,
			"height": self.intrinsic_height,
			"aspect_ratio": self.aspect_ratio,
			"sources": [
				{"type": s.type, "srcset": s.srcset, "sizes": s.sizes or self.sizes}
				for s in self.sources
			],
			"poster": self.poster_url,
			"captions": self.captions_url,
		}


@runtime_checkable
class DeliveryManifest(Protocol):
	"""Teslim manifestosu üreticisi.

	Depoya, veritabanına ve `frappe`'ye dokunmaz. Girdi: slot politikası +
	nesne adresi + render bağlamı. Çıktı: `RenderManifest`.
	"""

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
	) -> RenderManifest:
		"""Görsel için manifest üret.

		`available_profiles` verilirse yalnız o profiller `srcset`'e girer;
		`None` ise politikadaki tüm profiller mevcut varsayılır. Üretilmemiş
		bir profili `srcset`'e yazmak 404 demektir — bu yüzden liste
		süzgeçtir, temenni değil.

		`is_lcp_candidate=True` ise `loading="eager"`, `decoding="sync"` ve
		`fetchpriority="high"` yazılır; aksi hâlde `lazy`/`async`.

		Hiçbir profil üretilebilir değilse `NoProfileAvailable` atılır — boş
		`srcset` yazmak, tarayıcıyı `src`'ye düşürüp ölçüm yapılmış gibi
		görünmesini sağlardı.
		"""
		...

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
		"""Video için manifest üret.

		Poster ZORUNLUDUR: `poster=None` verilirse politikanın otomatik
		poster profili (FR-042) adresinden türetilir. Poster'sız video, pasif
		mobil bütçenin (150 KB) tamamını metadata'ya harcayıp boş kutu
		gösterir.

		`captions_url` boş bırakılabilir ama slot `accessibility.vtt_required`
		= `if_speech` ise çağıran uyarı üretmelidir (FR-125) — sözleşme
		konuşma olup olmadığını bilemez, o yüzden burada zorlamaz.
		"""
		...

	def sizes_attribute(self, slot_key: str, *, context: str = "") -> str:
		"""Slotun `sizes` dizgesi.

		`context` render noktasını ayırır (`pdp`, `listing`, `cart`) çünkü
		aynı slot farklı sayfalarda farklı CSS kutusuna oturuyor
		(docs/reports/03-render-envanteri.md). Tanımsız bağlam boş dizge
		döndürür; `sizes` yazmamak, YANLIŞ `sizes` yazmaktan iyidir.
		"""
		...

	def pick(self, slot_key: str, css_width_px: float, *, dpr: float = 1.0) -> Variant:
		"""Verilen CSS kutusu × DPR için seçilecek varyant.

		Tarayıcının `srcset` seçimini SUNUCUDA taklit eder. İki işi var:
		(1) `<img src>` fallback'i doğru basamaktan seçmek, (2) aşırı-servis
		oranını ölçmek (FR-123) — bugün 13,14 MB / 900 KB = 15× ve bu oranın
		azaldığını kanıtlamak için sunucu tarafında hesaplanabilir olmalı.

		Hedef genişliği KARŞILAYAN en küçük varyant seçilir; hiçbiri
		karşılamıyorsa en büyüğü döner (upscale yerine yetersiz servis —
		FR-028 ile tutarlı).
		"""
		...

	def overshoot(self, slot_key: str, css_width_px: float, *, dpr: float = 1.0) -> float:
		"""Seçilen varyantın hedefe göre fazlalık oranı (`varyant / hedef`).

		Politikadaki `profiles[].max_overshoot` (ürün görselinde 1,85) bu
		sayının tavanıdır; aşılması merdivende basamak eksik demektir.
		Hedef 0 ya da varyant yoksa 0.0 döner — bölme hatası yerine
		"ölçülemedi".
		"""
		...


__all__ = [
	"VARIANT_SEPARATOR",
	"MIME_BY_FORMAT",
	"LOADING_LAZY",
	"LOADING_EAGER",
	"Variant",
	"SourceSet",
	"RenderManifest",
	"DeliveryManifest",
	"mime_for",
	"derivative_key",
]
