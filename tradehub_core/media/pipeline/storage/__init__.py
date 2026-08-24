"""T-055 — Depolama fabrikası: ayardan adaptör kurar, DÜŞÜŞÜ raporlar.

NE YAPAR
--------
Dört kip var ve dördü de aynı `StorageAdapter` sözleşmesini uygular:

    local    yerel disk (bugünkü üretim davranışı)          `local.LocalDiskStorage`
    s3       yalnız nesne deposu                            `s3.S3Storage`
    mirror   yerel BİRİNCİL + S3 asenkron ikincil           `mirror.MirrorStorage`
    tiered   sıcak yerel + N gün sonra soğuk S3             `tiered.TieredStorage`

Ayar kaynağı iki biçimde okunabilir:

  * `StorageSettings.from_mapping` — `site_config.json` deseni (`s3_enabled`,
    `s3_bucket`, …). `s3.S3Config.from_mapping` ile AYNI anahtar adları.
  * `StorageSettings.from_doctype` — `doctype_specs/media_storage_settings.json`
    alan adları (`backend`, `s3_endpoint`, `s3_access_key`, …). İki ad şeması
    var çünkü ayarın nerede duracağı henüz KARARLAŞMADI (`retention.schema.json`
    `configurability.source` alanı da aynı belirsizliği taşıyor); fabrika
    ikisini de kabul ederek kararı geciktirir, kod ikiye bölünmez.

SESSİZ DÜŞÜŞ YOK (görev şartı)
------------------------------
`s3_enabled=0` iken `mirror`/`tiered`/`s3` istenirse fabrika **yerel depoya
düşer** ama bunu gizlemez: `StoragePlan.mode` gerçekte kurulan kipi,
`requested_mode` istenen kipi, `downgraded_from` düşüşün nereden olduğunu ve
`reasons` düşüşün SEBEPLERİNİ taşır (`s3_enabled=0`, `boto3 kurulu değil`,
`s3_bucket boş`). Çağıran `plan.degraded` ile tek `if` yazarak uyarı basabilir.

Alternatif — S3 yoksa hata atmak — üretimde tek bir yanlış ayarın bütün medya
yolunu durdurması demekti. Bugün S3 hiç yok (`docs/standards/retention.md`
§5.3, ölçüldü) ve yerel disk çalışan tek gerçek; fabrikanın varsayılan
davranışı o gerçeği KIRMAMAK, ama üstünü de örtmemek.

BU MODÜL `boto3` İMPORT ETMEZ
-----------------------------
`storage.s3` modülü import edilir (o da boto3'ü import etmez, yalnız
`find_spec` ile bakar). Yani `import tradehub_core.media.pipeline.storage` boto3 kurulu
olmayan bir makinede sorunsuz çalışır ve hiçbir S3 istemcisi kurulmaz.

İMZALAYICI
----------
Private kapsamda `url_for()` imza ister. Fabrika sırayla bakar: açıkça verilen
`secret` → `MEDIA_ENGINE_SIGNING_KEY` → frappe (`FrappeSignedUrl`). Hiçbiri
yoksa **rastgele anahtar üretilmez** (`delivery/signed.default_signer`
gerekçesi): imzalayıcı `None` kalır, plana `no_signer` sebebi yazılır ve
private `url_for()` çağrısı `StorageError` atar. Sessizce imzasız URL
döndürmek, private dosyayı korunuyor sanmak demekti.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from tradehub_core.media.pipeline.contracts.errors import StorageError
from tradehub_core.media.pipeline.contracts.storage import StorageAdapter
from tradehub_core.media.pipeline.delivery import signed as signed_urls
from tradehub_core.media.pipeline.storage.local import LocalDiskStorage, from_site_path
from tradehub_core.media.pipeline.storage.mirror import (
	FrappeEnqueueMirrorQueue,
	InlineMirrorQueue,
	MirrorStorage,
	ThreadMirrorQueue,
)
from tradehub_core.media.pipeline.storage.s3 import S3Config, S3Storage, boto3_available
from tradehub_core.media.pipeline.storage.tiered import DEFAULT_AGE_DAYS, TieredStorage

IMPLEMENTED: bool = True

MODE_LOCAL: str = "local"
MODE_S3: str = "s3"
MODE_S3_PRIMARY: str = "s3_primary"
MODE_MIRROR: str = "mirror"
MODE_TIERED: str = "tiered"
MODES: Tuple[str, ...] = (MODE_LOCAL, MODE_S3, MODE_MIRROR, MODE_TIERED)

#: S3 gerektiren kipler. Bu kümedeki bir kip S3 kullanılamazken istenirse
#: `local`'e düşer.
S3_MODES: Tuple[str, ...] = (MODE_S3, MODE_MIRROR, MODE_TIERED)


def normalize_mode(value: Any) -> str:
	"""Ayar ekranının ``s3_primary`` adını iç sözleşmedeki ``s3``e çevir."""
	mode = str(value or MODE_LOCAL).strip().lower()
	if mode == MODE_S3_PRIMARY:
		return MODE_S3
	return mode if mode in MODES else MODE_LOCAL

QUEUE_THREAD: str = "thread"
QUEUE_INLINE: str = "inline"
QUEUE_FRAPPE: str = "frappe"

#: `FrappeEnqueueMirrorQueue`'nun çağıracağı uç. Bu paket frappe yolunu
#: bilmez; `api/` katmanı bu adı taşıyan bir fonksiyon sağlamak zorunda.
DEFAULT_MIRROR_METHOD: str = "tradehub_core.api.media_mirror.run_mirror_task"


@dataclass(frozen=True)
class StorageSettings:
	"""Depolama ayarı — tek yerde, düz veri.

	`site_path` verilirse public/private kökleri ondan türetilir
	(`<site>/public/files`, `<site>/private/files`). Açıkça `public_root` /
	`private_root` verilirse onlar kazanır: test ve migrasyon betikleri site
	dizini olmadan çalışabilmeli.
	"""

	mode: str = MODE_LOCAL
	site_path: str = ""
	public_root: str = ""
	private_root: str = ""
	local_root: str = ""
	local_free_space_alarm_bytes: int = 0
	local_max_usage_bytes: int = 0
	s3: S3Config = field(default_factory=S3Config)
	tier_age_days: int = DEFAULT_AGE_DAYS
	signing_secret: str = ""
	signed_url_ttl_seconds: int = 0
	fsync: bool = True
	mirror_queue: str = QUEUE_THREAD
	mirror_method: str = DEFAULT_MIRROR_METHOD
	read_repair: bool = True

	def roots(self) -> Tuple[str, str]:
		"""(public_root, private_root). İkisi de çözülemezse `StorageError`."""
		if self.public_root and self.private_root:
			return (self.public_root, self.private_root)
		if self.local_root:
			return (
				os.path.join(self.local_root, "public"),
				os.path.join(self.local_root, "private"),
			)
		if self.site_path:
			return (
				os.path.join(self.site_path, "public", "files"),
				os.path.join(self.site_path, "private", "files"),
			)
		raise StorageError(
			"Yerel depo kökü çözülemedi: `site_path` ya da `public_root`+`private_root` verin.",
			detay={"reason": "no_roots"},
			retryable=False,
		)

	@classmethod
	def from_mapping(cls, conf: Mapping[str, Any]) -> "StorageSettings":
		"""`site_config.json` deseni: `media_storage_mode`, `s3_*`, …"""
		kip = normalize_mode(conf.get("media_storage_mode", MODE_LOCAL))
		return cls(
			mode=kip,
			site_path=str(conf.get("media_site_path", "") or ""),
			public_root=str(conf.get("media_public_root", "") or ""),
			private_root=str(conf.get("media_private_root", "") or ""),
			local_root=str(conf.get("media_local_root", "") or ""),
			local_free_space_alarm_bytes=max(
				0, int(conf.get("media_local_free_space_alarm_gb", 0) or 0) * 1024**3
			),
			local_max_usage_bytes=max(
				0, int(conf.get("media_local_max_usage_gb", 0) or 0) * 1024**3
			),
			s3=S3Config.from_mapping(conf),
			tier_age_days=int(conf.get("media_tier_age_days", DEFAULT_AGE_DAYS) or DEFAULT_AGE_DAYS),
			signing_secret=str(conf.get("media_signing_key", "") or ""),
			signed_url_ttl_seconds=int(conf.get("media_signed_url_ttl_seconds", 0) or 0),
			mirror_queue=str(conf.get("media_mirror_queue", QUEUE_THREAD) or QUEUE_THREAD),
			mirror_method=str(conf.get("media_mirror_method", DEFAULT_MIRROR_METHOD) or DEFAULT_MIRROR_METHOD),
		)

	@classmethod
	def from_doctype(cls, doc: Mapping[str, Any], *, site_path: str = "") -> "StorageSettings":
		"""Resmî T-051 alanlarını oku; eski alanlar yalnız geçiş fallback'idir."""
		kip = normalize_mode(doc.get("storage_mode") or doc.get("backend") or MODE_LOCAL)
		storage_class = str(doc.get("s3_storage_class") or "STANDARD")
		storage_class = {
			"INFREQUENT": "STANDARD_IA",
			"COLD": "GLACIER_IR",
			"ARCHIVE": "DEEP_ARCHIVE",
		}.get(storage_class, storage_class)
		s3_konf = S3Config(
			enabled=(
				bool(int(doc.get("s3_enabled", 0) or 0))
				if "s3_enabled" in doc
				else kip in S3_MODES
			),
			bucket=str(doc.get("s3_bucket", "") or ""),
			region=str(doc.get("s3_region", "") or ""),
			endpoint_url=str(doc.get("s3_endpoint_url") or doc.get("s3_endpoint") or ""),
			prefix=str(doc.get("s3_prefix") or "media").strip("/"),
			access_key_id=str(doc.get("s3_access_key_id") or doc.get("s3_access_key") or ""),
			secret_access_key=str(
				doc.get("s3_secret_access_key") or doc.get("s3_secret_key") or ""
			),
			storage_class=storage_class,
			server_side_encryption=str(doc.get("s3_server_side_encryption") or "none"),
			multipart_threshold_bytes=max(
				5 * 1024 * 1024,
				int(doc.get("s3_multipart_threshold_mb", 64) or 64) * 1024 * 1024,
			),
			max_concurrency=max(1, int(doc.get("s3_max_concurrency", 4) or 4)),
			addressing_style="path" if bool(doc.get("s3_path_style")) else "auto",
			public_base_url=(
				str(doc.get("cdn_base_url") or "").rstrip("/")
				if (
					bool(doc.get("cdn_enabled"))
					if "cdn_enabled" in doc
					else bool(doc.get("cdn_base_url"))
				)
				else ""
			),
		)
		return cls(
			mode=kip,
			site_path=site_path,
			local_root=str(doc.get("local_root") or ""),
			local_free_space_alarm_bytes=max(
				0, int(doc.get("local_free_space_alarm_gb", 50) or 0) * 1024**3
			),
			local_max_usage_bytes=max(
				0, int(doc.get("local_max_usage_gb", 0) or 0) * 1024**3
			),
			s3=s3_konf,
			tier_age_days=max(
				1,
				int(doc.get("original_local_days", DEFAULT_AGE_DAYS) or DEFAULT_AGE_DAYS),
			),
			signing_secret=str(doc.get("cdn_signing_key") or ""),
			signed_url_ttl_seconds=int(
				doc.get("cdn_signed_ttl_seconds") or doc.get("signed_url_ttl_seconds") or 0
			),
			mirror_queue=QUEUE_FRAPPE,
		)


@dataclass(frozen=True)
class StoragePlan:
	"""Kurulan depo + nasıl kurulduğunun künyesi.

	`adapter` doğrudan kullanılabilir. `mode != requested_mode` ise bir düşüş
	yaşanmıştır ve `reasons` sebebi söyler — çağıran bunu log'a/denetime
	yazmalıdır, yutmamalıdır.
	"""

	adapter: StorageAdapter
	mode: str
	requested_mode: str
	downgraded_from: str = ""
	reasons: Tuple[str, ...] = ()
	signer_available: bool = False

	@property
	def degraded(self) -> bool:
		return self.mode != self.requested_mode

	def to_dict(self) -> Dict[str, Any]:
		return {
			"mode": self.mode,
			"requested_mode": self.requested_mode,
			"degraded": self.degraded,
			"downgraded_from": self.downgraded_from,
			"reasons": list(self.reasons),
			"signer_available": self.signer_available,
			"backend": type(self.adapter).__name__,
		}


def _build_signer(
	settings: StorageSettings, signer: Optional[signed_urls.UrlSigner]
) -> Tuple[Optional[signed_urls.UrlSigner], Tuple[str, ...]]:
	"""İmzalayıcıyı çöz. Bulunamazsa `None` + sebep — rastgele anahtar YOK."""
	if signer is not None:
		return signer, ()
	kwargs: Dict[str, Any] = {}
	if settings.signed_url_ttl_seconds:
		kwargs["default_ttl"] = settings.signed_url_ttl_seconds
	try:
		return signed_urls.default_signer(secret=settings.signing_secret or None, **kwargs), ()
	except signed_urls.SignedUrlError as hata:
		return None, (f"no_signer:{hata.detay.get('reason', 'unknown')}",)


def _build_local(
	settings: StorageSettings,
	signer: Optional[signed_urls.UrlSigner],
	alarm: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> LocalDiskStorage:
	kwargs = {
		"signer": signer,
		"fsync": settings.fsync,
		"free_space_alarm_bytes": settings.local_free_space_alarm_bytes,
		"max_usage_bytes": settings.local_max_usage_bytes,
		"alarm": alarm,
	}
	if settings.public_root and settings.private_root:
		return LocalDiskStorage(settings.public_root, settings.private_root, **kwargs)
	if settings.local_root:
		public_root, private_root = settings.roots()
		return LocalDiskStorage(public_root, private_root, **kwargs)
	if settings.site_path:
		return from_site_path(settings.site_path, **kwargs)
	# `roots()` anlamlı hatayı zaten üretiyor.
	public_root, private_root = settings.roots()
	return LocalDiskStorage(public_root, private_root, **kwargs)


def _mirror_queue_factory(settings: StorageSettings) -> Callable[[Any], Any]:
	"""Ayar adından kuyruk fabrikası. Bilinmeyen ad `thread`'e düşer."""
	ad = (settings.mirror_queue or QUEUE_THREAD).strip().lower()
	if ad == QUEUE_INLINE:
		return InlineMirrorQueue
	if ad == QUEUE_FRAPPE:
		return lambda worker: FrappeEnqueueMirrorQueue(settings.mirror_method)
	return ThreadMirrorQueue


def build_storage(
	settings: StorageSettings,
	*,
	signer: Optional[signed_urls.UrlSigner] = None,
	s3_client_factory: Optional[Callable[[], Any]] = None,
	queue_factory: Optional[Callable[[Any], Any]] = None,
	alarm: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> StoragePlan:
	"""Ayardan depo kur. S3 kullanılamıyorsa `local`'e DÜŞER ve raporlar.

	Args:
	    settings: Depolama ayarı.
	    signer: Hazır imzalayıcı. `None` ise `delivery/signed.default_signer`.
	    s3_client_factory: S3 istemcisi üreten çağrılabilir (test için sahte
	        istemci). Verilirse `boto3` kurulu olma şartı DÜŞER — sahte
	        istemci gerçek boto3'ün yerine geçer.
	    queue_factory: Ayna kuyruğu fabrikası; `None` ise ayardan seçilir.

	Returns:
	    `StoragePlan` — kurulan adaptör + düşüş künyesi.
	"""
	istenen = normalize_mode(settings.mode)

	imzalayici, imza_sebep = _build_signer(settings, signer)
	sebepler = list(imza_sebep)

	if istenen == MODE_LOCAL:
		return StoragePlan(
			adapter=_build_local(settings, imzalayici, alarm),
			mode=MODE_LOCAL,
			requested_mode=MODE_LOCAL,
			reasons=tuple(sebepler),
			signer_available=imzalayici is not None,
		)

	# S3 gerektiren kipler: önce kullanılabilirlik ölçülür.
	engeller = list(settings.s3.problems())
	if s3_client_factory is not None:
		# Sahte/enjekte istemci varken `boto3 kurulu değil` engeli düşer;
		# diğer engeller (kapalı bayrak, bucket yok) AYNEN geçerli kalır.
		engeller = [e for e in engeller if "boto3" not in e]
	if engeller:
		sebepler.extend(engeller)
		return StoragePlan(
			adapter=_build_local(settings, imzalayici, alarm),
			mode=MODE_LOCAL,
			requested_mode=istenen,
			downgraded_from=istenen,
			reasons=tuple(sebepler),
			signer_available=imzalayici is not None,
		)

	s3_depo = S3Storage(
		settings.s3,
		client_factory=s3_client_factory,
		signer=imzalayici,
		alarm=alarm,
	)

	if istenen == MODE_S3:
		return StoragePlan(
			adapter=s3_depo,
			mode=MODE_S3,
			requested_mode=MODE_S3,
			reasons=tuple(sebepler),
			signer_available=imzalayici is not None,
		)

	yerel = _build_local(settings, imzalayici, alarm)

	if istenen == MODE_MIRROR:
		fabrika = queue_factory if queue_factory is not None else _mirror_queue_factory(settings)
		return StoragePlan(
			adapter=MirrorStorage(
				yerel,
				s3_depo,
				queue_factory=fabrika,
				read_repair=settings.read_repair,
				alarm=alarm,
			),
			mode=MODE_MIRROR,
			requested_mode=MODE_MIRROR,
			reasons=tuple(sebepler),
			signer_available=imzalayici is not None,
		)

	return StoragePlan(
		adapter=TieredStorage(yerel, s3_depo, age_days=settings.tier_age_days),
		mode=MODE_TIERED,
		requested_mode=MODE_TIERED,
		reasons=tuple(sebepler),
		signer_available=imzalayici is not None,
	)


def build_from_mapping(conf: Mapping[str, Any], **kwargs: Any) -> StoragePlan:
	"""`site_config.json` benzeri sözlükten doğrudan kur."""
	return build_storage(StorageSettings.from_mapping(conf), **kwargs)


def local_storage(site_path: str, **kwargs: Any) -> LocalDiskStorage:
	"""Kısayol: yalnız yerel disk. Fabrikayı kurmadan tek satırda depo."""
	imzalayici = kwargs.pop("signer", None)
	if imzalayici is None:
		try:
			imzalayici = signed_urls.default_signer()
		except signed_urls.SignedUrlError:
			imzalayici = None
	return from_site_path(site_path, signer=imzalayici, **kwargs)


def with_mode(settings: StorageSettings, mode: str) -> StorageSettings:
	"""Ayarın kipini değiştirilmiş kopyasını üret (dataclass dondurulmuş)."""
	return replace(settings, mode=mode)


__all__ = [
	"IMPLEMENTED",
	"MODE_LOCAL",
	"MODE_S3",
	"MODE_S3_PRIMARY",
	"MODE_MIRROR",
	"MODE_TIERED",
	"MODES",
	"S3_MODES",
	"normalize_mode",
	"QUEUE_THREAD",
	"QUEUE_INLINE",
	"QUEUE_FRAPPE",
	"DEFAULT_MIRROR_METHOD",
	"StorageSettings",
	"StoragePlan",
	"build_storage",
	"build_from_mapping",
	"local_storage",
	"with_mode",
	"boto3_available",
	"LocalDiskStorage",
	"S3Config",
	"S3Storage",
	"MirrorStorage",
	"TieredStorage",
]
