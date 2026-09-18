# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""Medya boru hattı köprüsü — türev (rendition) üretimini tetikler (Dalga A2).

`media/pipeline/` altındaki motor çalışıyor ama ürüne bağlı değildi: yüklenen
bir görsel için TEK çıktı (bugünkü `engine.to_webp`) üretiliyor, `srcset`
basamakları hiç doğmuyordu. Bu modül o motoru `File.after_insert` kancasına
bağlayan **tek** noktadır.

PARALEL HAT — MEVCUT AKIŞ DEĞİŞMEDİ
-----------------------------------
`engine.to_webp`, `transcode.maybe_transcode_on_insert`, `media/states.py` ve
`media/audit.py` kancalarının hiçbirine dokunulmadı; bu kanca onların YANINDA,
en sonda çalışır. Ürettiği türevler için `File` kaydı AÇILMAZ (bkz.
`_write_rendition_file`) — hem envanteri/kotayı şişirmesin hem de `after_insert`
kancası kendi kendini tetikleyip sonsuz döngü kurmasın diye.

KAPSAM VE ETKİNLEŞTİRME
--------------------------------------
1. `pipeline_flags.is_enabled("rendition_on_upload")` — ana şalter + alt bayrak.
   Kapalıysa fonksiyon İLK SATIRDA döner: ne DB okunur, ne kuyruğa iş girer.
   Sistemin bugünkü davranışı birebir aynı kalır.
2. Kapsam daraltması — `transcode.maybe_transcode_on_insert` ile AYNI mantık
   (klasör/private muaf, sahibi satıcıya çözülen ya da bilinen bir slota
   bağlanan dosya), üstüne KVKK kapsam dışı doctype'lar ve `document.attachment`
   slotu (KYB/KYC/kimlik belgeleri) açıkça hariç.
3. `pipeline_flags.is_slot_enabled(slot_key)` — varsayılan `*` tüm slotları
   açar; operatör listeyi daraltabilir veya ana şalteri kapatabilir.

SLOT ÇÖZÜMÜ POLİTİKADAN OKUNUR
------------------------------
(doctype, alan) → `slot_key` haritası kodda SABİT DEĞİL: `media/pipeline/policy/
slots/*.json` dosyalarının `bound_to` blokları okunur. Yeni bir bağlanma noktası
eklemek bu modülü değiştirmez. Daha özel bir slotu olmayan public görseller
`library.image` ile oranları korunarak işlenir.

İŞ AKIŞI
--------
    File.after_insert
      └─ maybe_generate_renditions   (istek thread'i — yalnız karar verir)
           └─ frappe.enqueue(queue="media-image-live", enqueue_after_commit=True)
                └─ _run_rendition_job   (worker)
                     ├─ Media Asset  (bul / oluştur)
                     ├─ Media Version  (bul / oluştur — dedup.version_hash, T-042)
                     ├─ Media Processing Job  (queued → running → success/failed)
                     ├─ Media Profile kayıtları → (genişlik × biçim) matrisi
                     ├─ pipeline.image.render → bayt
                     ├─ diske yaz (dedup.rendition_path — version_hash TAŞIYAN adres)
                     └─ Media Rendition satırları

İKİ AYRI HASH — KARIŞTIRILMASIN (T-042)
---------------------------------------
`content_fingerprint(doc)` (eski adı `version_hash`) KAYNAK dosyanın kimliğidir:
`sha256(içerik)[:32]`, `media/naming.py` kısaltmasıyla birebir. İdempotency
kapısı ve `Media Asset.content_sha256` bunu taşır — dosya ADINDAN okunabildiği
için kanca tarafında içerik okumadan karar verilebilir.

`Media Version.version_hash` ise NORMALIZE MASTER'ın kimliğidir ve üretimi bu
modülde DEĞİL, `pipeline/core/dedup.py::version_hash`'tedir (4 girdi:
source_hash + policy_snapshot + crop_intent + engine_version). Türev adresi
bu hash'i taşır (INV-09): politika/kırpma/motor değişince adres zorunlu
değişir, hiçbiri değişmeden aynı kalır. YALNIZ YENİ üretimler bu adrese yazar;
mevcut dosya adlarına/adreslerine geriye dönük dokunulmaz (backfill ayrı iş).

`_run_rendition_job` HİÇBİR KOŞULDA istisna sızdırmaz: worker'ı patlatan bir
medya işi, kuyruktaki sipariş/ödeme işlerini de bekletir.

ADLANDIRMA SÖZLEŞMESİ (K-2)
---------------------------
`Media Rendition.profile` kolonu **politika profil adını** taşır (`w96`,
`w384`, `og1200x630`) — `Media Profile` docname'ini DEĞİL. `api/
media_manifest.py` bu kolonu olduğu gibi kütüphaneye `available_profiles`
olarak veriyor ve kütüphane onu slot politikasındaki adla karşılaştırıyor;
docname yazılırsa hiçbiri eşleşmez, `NoProfileAvailable` fırlar ve manifest
SESSİZCE boş döner. Docname bu adın slot önekli hâlidir
(`{slot_key}:{policy_profile}`), çünkü `Media Profile.autoname` global tekillik
istiyor ama politika adları slotlar arası çakışıyor (`w128` hem `brand.logo`
hem `seller.logo` politikasında var). Ham ad `Media Profile.policy_profile`
alanındadır; kayıtları `patches/v15_9_23_media_profile_seed.py` tohumlar.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import shutil
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from typing import Any

import frappe
from frappe.utils import get_files_path, now_datetime

from tradehub_core.media import audit, meter, ownership, pipeline_flags, presets, upload_policy
from tradehub_core.media.pipeline.core import queues as media_queues
from tradehub_core.media.rendition_ledger import (
	content_sha256,
	engine_signature,
	file_sha256,
	rendition_key,
)

#: Kullanıcının beklediği görsel işi genel sipariş kuyruğundan ayrıdır.
RQ_QUEUE: str = media_queues.IMAGE_LIVE.name

#: CPU-yoğun video/animasyon işleri görsel ve iş süreçlerini aç bırakmasın.
#: Docker'da bu kuyruğu yalnız tek, kaynak sınırlı worker tüketir (T-075).
RQ_QUEUE_VIDEO: str = media_queues.VIDEO.name

#: Politika backfill'i canlı işleri sıkıştıramaz. Docker topolojisindeki ayrı,
#: tek concurrency'li worker yalnız bu gerçek RQ kuyruğunu dinler.
RQ_QUEUE_BULK: str = media_queues.IMAGE_BULK.name

#: Kuyruk başına süre tavanları tek topolojiden gelir.
QUEUE_TIMEOUT_SECONDS: int = media_queues.VIDEO.timeout_seconds
QUEUE_TIMEOUT_LIVE_SECONDS: int = media_queues.IMAGE_LIVE.timeout_seconds
QUEUE_TIMEOUT_BULK_SECONDS: int = media_queues.IMAGE_BULK.timeout_seconds

#: `Media Processing Job.queue` seçeneği (yükleme anında tetiklenen, kullanıcı
#: bekleyen üretim → "live"). Deneme tavanı bu kuyrukta 3.
JOB_QUEUE: str = media_queues.IMAGE_LIVE.name

JOB_TYPE: str = "rendition"
JOB_QUEUE_BULK: str = RQ_QUEUE_BULK

GEN_READY: str = "ready"
GEN_OMITTED: str = "omitted"
GEN_FAILED: str = "failed"

LAZY_LOCK_TIMEOUT_SECONDS: int = 120
LAZY_LOCK_WAIT_SECONDS: int = 30
ENGINE_OUTPUT_CACHE_SECONDS: int = 7 * 24 * 60 * 60
BULK_STATUS_SECONDS: int = 24 * 60 * 60

ANIMATION_JOB_TYPE: str = "video_from_animation"


@dataclass
class GenerationOutcome:
	"""Tek sürüm üretiminin tamlık künyesi.

	`omitted`, upscale/fayda kapısı nedeniyle kasıtlı olarak manifestten düşen
	basamaklardır ve eksiklik sayılmaz. `failed` sıfır değilken active_version
	asla değişmez; başarılı satırlar aynı transaction geri alınabilir.
	"""

	required: int = 0
	ready: int = 0
	omitted: int = 0
	failed: int = 0
	details: list[str] = field(default_factory=list)
	entries: dict[str, str] = field(default_factory=dict)
	results: list[Any] = field(default_factory=list)

	@property
	def complete(self) -> bool:
		return self.failed == 0 and self.required == self.ready + self.omitted

	@property
	def written(self) -> int:
		return self.ready

	def add(self, status: str, detail: str = "") -> None:
		self.required += 1
		if status == GEN_READY:
			self.ready += 1
		elif status == GEN_OMITTED:
			self.omitted += 1
		else:
			self.failed += 1
		if detail:
			self.details.append(detail)
			self.entries[detail] = status


# ── W7: video hattı sabitleri ────────────────────────────────────────────
#: Ledger ve gerçek RQ kuyruğu aynı adı taşır; operasyon ekranı başka bir ad
#: gösterip işin gerçekte ``long`` kuyruğunda koşması engellenir.
JOB_QUEUE_VIDEO: str = RQ_QUEUE_VIDEO

#: `Media Processing Job.job_type` seçeneklerinden (normalize|rendition|
#: transcode|poster|preview|ai|gc|retention|report) videonun ana işi.
JOB_TYPE_VIDEO: str = "transcode"

#: İş idempotency anahtarının öneki — görseldeki `rendition:` ile çakışmasın.
JOB_KEY_VIDEO: str = "video"

_MEDIA_TYPE_VIDEO: str = "video"

#: Video türev profil adları. Görseldeki gibi politika profili DEĞİL (video
#: slotunun `profiles[]` bloğu poster GÖRSELLERİNİ tanımlar, videoyu değil);
#: sözleşme adları burada sabitlenir ve `api/media_manifest.py` aynı adlarla
#: okur. `dedup.rendition_path` bu adları yol parçası olarak taşır.
VIDEO_PRIMARY_PROFILE: str = "h264"
VIDEO_WEBM_PROFILE: str = "vp9"
VIDEO_POSTER_PROFILE: str = "poster"
VIDEO_HLS_PROFILE: str = "hls"
VIDEO_PREVIEW_PROFILE: str = "preview"

#: HLS paketinin sürüm dizini altındaki alt dizini:
#: `/files/media/{asset}/{version_hash}/hls/master.m3u8`. Tek dosyalık
#: türevler `dedup.rendition_path` düzenindedir; HLS bir dosya AĞACI olduğu
#: için düzen bir alt dizinle GENİŞLETİLİR — kök (`/files/media/{asset}/
#: {version_hash}/…`) aynı kalır, INV-09 (version_hash taşıyan değişmez
#: adres) aynen geçerlidir.
VIDEO_HLS_DIRNAME: str = "hls"

#: Yalnız dosya EKİ olan bağlanmalar slot çözümüne girer. `Long Text` (JSON
#: içine gömülü URL) ve `Data` bağlanmaları `attached_to_field` üretmez.
_ATTACHMENT_FIELDTYPES: frozenset[str] = frozenset({"Attach", "Attach Image"})

#: Bu slot KYB/KYC/kimlik belgelerine bağlı (`document-attachment.json`
#: `bound_to`). Yükleme kancasından ASLA işlenmez: PII belgesinin türevini
#: üretip public dizine yazmak sızıntıdır. `is_private` kontrolü çoğunu zaten
#: eler; bu liste, private işaretlenmeden yüklenmiş bir belge için ikinci settir.
EXCLUDED_SLOTS: frozenset[str] = frozenset({"document.attachment"})

#: `media/naming.py` içerik-adresli adı: sha256'nın ilk 32 hex hanesi.
_HASH_LENGTH: int = 32
_HASHED_NAME_RE = re.compile(r"^[0-9a-f]{32}$")

_MEDIA_TYPE_IMAGE: str = "image"


# --- 1) Kanca: karar mercii --------------------------------------------------


def maybe_generate_renditions(doc: Any, method: str | None = None) -> None:
	"""`File.after_insert` kancası — türev üretimini KOŞULLU olarak kuyruğa alır.

	Bayrak kapalıyken ilk satırda döner; DB'ye tek sorgu bile
	gitmez. Best-effort: burada patlamak dosya yüklemesini asla engellememeli
	(`states.on_file_insert` / `transcode.maybe_transcode_on_insert` ile aynı
	desen).
	"""
	try:
		# KAPI 1 — bayrak. Dalga A'nın tüm güvencesi bu satıra yaslanıyor.
		if not pipeline_flags.is_enabled("rendition_on_upload"):
			return
		# KAPI 2 — deterministik mağaza rollout'u. Canary/%10/%50 aşamasında
		# aynı mağaza bütün web/worker süreçlerinde aynı tarafta kalır.
		if not pipeline_flags.is_store_enabled(ownership.store_of(doc.get("owner"))):
			return

		# KAPI 3 — kapsam.
		slot_key = _resolve_scope(doc)
		if not slot_key:
			# Görsel kapsamına girmeyen dosya VİDEO kapsamında olabilir (W7).
			# Uzantı iki kümeden en çok birine düşer; görsel yolu değişmedi.
			_maybe_enqueue_video(doc)
			return

		# KAPI 4 — slot bazlı açma/kapama (`active_slots` boşken hiçbiri açık değil).
		if not pipeline_flags.is_slot_enabled(slot_key):
			return

		surum_hash = content_fingerprint(doc)
		if not surum_hash:
			return

		# İdempotency: aynı içerik + aynı slot için türev zaten üretilmişse
		# (aynı dosyanın ikinci yüklemesi, yeniden deneme, çift kanca) yeni iş
		# açılmaz. İçerik-adresli adlandırma sayesinde "aynı içerik" güvenilir.
		if _renditions_exist(surum_hash, slot_key, doc=doc):
			return

		# KAPI 5 — dönüşüm kotası (MOGEM-620 §18). Kuyruğa ATMADAN ÖNCE
		# bakılıyor: iş kuyruğa girdikten sonra reddetmek hem worker
		# zamanını harcar hem de kullanıcıya hiçbir yerde görünmeyen bir
		# başarısızlık üretir. Kota tanımsızsa kapı AÇIK (`meter.check`
		# fail-open sözleşmesi — gerekçe orada).
		magaza = ownership.store_of(doc.get("owner"))
		if magaza:
			karar = meter.check(magaza, meter.METRIC_TRANSFORMATIONS, incoming=1)
			if not karar["allowed"]:
				frappe.log_error(
					title="media.pipeline_bridge dönüşüm kotası aşıldı",
					message=f"store={magaza} file={doc.get('file_url')} karar={karar}",
				)
				return

		frappe.enqueue(
			"tradehub_core.media.pipeline_bridge._run_rendition_job",
			queue=RQ_QUEUE,
			timeout=QUEUE_TIMEOUT_LIVE_SECONDS,
			enqueue_after_commit=True,
			file_url=doc.get("file_url"),
			file_name=doc.name,
		)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge maybe_generate_renditions failed",
			message=frappe.get_traceback(),
		)


#: F-33 — kaynak `File` silinince temizlenen bağımlı motor tabloları.
#: Sıra önemli: alt satırlar önce, `Media Asset` en son.
_ASSET_DEPENDENTS: tuple[tuple[str, str], ...] = (
	("Media Usage", "asset"),
	("Media Crop Intent", "asset"),
	("Media Metadata Vault", "asset"),
	("Media Version", "asset"),
	# F-33c — iş defteri. Unutulursa yalnız artık kalmıyor: `_open_job` işi
	# `içerik_hash:slot` anahtarıyla YENİDEN KULLANIYOR; asılı `asset` bağı
	# taşıyan eski satır, aynı içeriğin yeni yüklemesini `LinkValidationError`
	# ile düşürüyor ve yeni dosya sessizce türevsiz kalıyor. Ölçüldü:
	# canlı DB'de 44/185 iş satırı silinmiş varlığa bağlı.
	("Media Processing Job", "asset"),
)


def cleanup_on_file_trash(doc: Any, method: str | None = None) -> None:
	"""`File.on_trash` — silinen orijinalin motor kayıtlarını ve türevlerini kaldır.

	Ölçüldü (2026-08-29): `trash.purge_expired` File'ı kalıcı siliyor ama
	HİÇBİR kod `Media Asset` / `Media Version` / `Media Rendition` satırlarını
	ve türev DOSYALARINI silmiyordu. Her silinen ürün görseli 1 varlık +
	~16 türev dosyası bırakıyordu; test ortamında 36 yetim varlık birikti.

	İki zarar:
	  1. Depolama — türev dosyaları hiçbir GC'nin kapsamında değil.
	  2. **Yanlış idempotency.** `_renditions_exist` yetim varlığı görüp aynı
	     içeriğin yeni yüklemesine "zaten üretildi" diyor (F-33a ile birlikte
	     kapatıldı).

	Türevler SİLİNMİYOR, çöp kapısından geçiriliyor (`trash.move_to_trash(...,
	rendition=)`): denetimli, legal hold'a saygılı, `purge_after` dolana kadar
	geri alınabilir. Kalıcı silmeyi bakım işi (`retention.purge_soft_deleted_
	renditions`) yapar — o iş legal hold'u SON KEZ kontrol eder. Varlık ve
	alt satırları ise kalıcı siliniyor: orijinal gitti, mezar taşı tutmanın
	tüketicisi yok ve tutulan satır `_renditions_exist`i yanıltıyor.

	Legal hold'daki varlığa DOKUNULMAZ; yalnız denetime yazılır. Hold bir
	saklama kararıdır ve File'ın silinmesi o kararı düşürmez — tersine, hold
	altında bir File'ın silinebilmiş olması denetimde görünmesi gereken şeydir.

	Best-effort: burada patlamak File silme işlemini engellememeli.
	"""
	try:
		ad = getattr(doc, "name", None)
		if not ad or not frappe.db.exists("DocType", "Media Asset"):
			return
		varliklar = frappe.get_all(
			"Media Asset",
			filters={"source_file": ad},
			fields=["name", "legal_hold", "slot_key"],
		)
		if not varliklar:
			return
		from tradehub_core.media import trash as trash_mod

		file_url = getattr(doc, "file_url", "") or ""
		for v in varliklar:
			if v.get("legal_hold"):
				audit.log_media_event(
					action=audit.ACTION_TRASH,
					file_url=file_url,
					allowed=False,
					reason="legal_hold_asset_orphaned_by_file_delete",
					context={"asset": v["name"], "slot_key": v.get("slot_key")},
				)
				continue
			for r in frappe.get_all(
				"Media Rendition",
				filters={"asset": v["name"], "state": ["!=", "purged"]},
				fields=["name", "file_url"],
			):
				try:
					trash_mod.move_to_trash(r["file_url"], rendition=r["name"], reason="source_file_deleted")
				except Exception:
					frappe.log_error(
						title="media.pipeline_bridge türev çöpe taşınamadı",
						message=f"{r['name']}: {frappe.get_traceback()}",
					)
			for dt, alan in _ASSET_DEPENDENTS:
				if not frappe.db.exists("DocType", dt):
					continue
				for satir in frappe.get_all(dt, filters={alan: v["name"]}, pluck="name"):
					frappe.delete_doc(dt, satir, ignore_permissions=True, force=True, delete_permanently=True)
			# `Media Rendition.asset` bağı bilerek askıda kalıyor: purge işi
			# satırı `trash_path` üzerinden bulur, `asset`e yalnız legal hold
			# için bakar ve kayıt yoksa "tutulu değil" der.
			frappe.delete_doc(
				"Media Asset", v["name"], ignore_permissions=True, force=True, delete_permanently=True
			)
			audit.log_media_event(
				action=audit.ACTION_TRASH,
				file_url=file_url,
				reason="engine_records_cascaded_on_file_delete",
				context={"asset": v["name"], "slot_key": v.get("slot_key")},
			)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge cleanup_on_file_trash failed",
			message=frappe.get_traceback(),
		)


@frappe.whitelist()
def sweep_orphaned_assets(dry_run: bool = True, limit: int = 5000) -> dict:
	"""Kaynak `File`'ı artık olmayan varlıkları raporla / temizle — F-33'ün ikizi.

	`cleanup_on_file_trash` kancası BUNDAN SONRAKİ birikimi önlüyor; bu
	süpürücü kanca yokken oluşmuş yığın içindir (ölçüldü 2026-08-29: 36 yetim
	varlık, 27'si `ready` durumda türevleriyle birlikte). Aynı temizlik
	yolundan geçer — türevler çöp kapısına, satırlar kalıcı — ve legal hold'a
	aynı şekilde saygı duyar.

	**Yetim** = `source_file` dolu ama o adda `File` yok. `source_file` boş
	sistem varlıkları (bayrak/politika üretimi) yetim SAYILMAZ; onlara
	dokunulmaz.

	`dry_run=True` (varsayılan) hiçbir şey silmez.
	"""
	dry_run = bool(dry_run) if not isinstance(dry_run, str) else dry_run.lower() not in ("0", "false")
	frappe.only_for("System Manager")
	yetimler = frappe.db.sql(
		"""select a.name, a.source_file, a.slot_key, a.state, a.legal_hold
		   from `tabMedia Asset` a
		   where ifnull(a.source_file, '') != ''
		     and not exists (select 1 from `tabFile` f where f.name = a.source_file)
		   order by a.creation asc
		   limit %s""",
		(int(limit),),
		as_dict=True,
	)
	tutulan = [y for y in yetimler if y.get("legal_hold")]
	aday = [y for y in yetimler if not y.get("legal_hold")]
	silinen = 0
	if not dry_run:
		for y in aday:
			cleanup_on_file_trash(frappe._dict(name=y["source_file"], file_url=""))
			silinen += 1
		frappe.db.commit()
	return {
		"orphans": len(yetimler),
		"held": len(tutulan),
		"deleted": silinen,
		"dry_run": dry_run,
		"samples": [
			{"asset": y["name"], "slot_key": y["slot_key"], "state": y["state"]} for y in yetimler[:10]
		],
	}


def _resolve_scope(doc: Any) -> str | None:
	"""Dosya yeni hattın kapsamında mı; kapsamdaysa `slot_key`, değilse `None`.

	Daraltma `transcode.maybe_transcode_on_insert` ile AYNI omurgayı izler —
	oradan farkı yalnız medya türü (video değil, görsel) ve slot şartı:

	  - Geri yükleme bayrağı (`th_skip_transcode`) varsa dokunulmaz: `media/
	    restore.py` dosyayı yedekteki hâliyle diske yazıyor, üstüne iş açmak
	    az önce geri yüklenen içeriği yeniden işlemeye kalkardı.
	  - Klasör ve `is_private=1` muaf — chat ekleri, KYB/KYC belgeleri PRIVATE
	    yükleniyor, bu yüzden zaten kapsam dışı.
	  - Yalnız görsel uzantıları (`upload_policy.EXTENSIONS`).
	  - KVKK kapsam dışı doctype'lar (`presets.EXCLUDED_DOCTYPES`) muaf.
	  - Slot politikadan veya kullanımdan çözülür. Kullanılmayan public
	    kütüphane görselleri library.image ile oranları korunarak işlenir.
	  - Sahibi bir satıcıya çözülüyor OLABİLİR ama şart değil: slotun kendisi
	    zaten "bu dosya ürün/mağaza/marka görselidir" diyor (transcode'daki
	    "satıcı VEYA Listing eki" şartının slot karşılığı budur).
	  - İçeriğin HASSAS BİR İKİZİ varsa (aynı `content_hash` private ya da
	    hassas doctype'lı başka bir kayıtta) üretim YOK — optimize akışıyla
	    aynı kural, aynı gerekçe kodu (`sensitive_content_twin`, rapor 69 §7.2).
	"""
	if getattr(getattr(doc, "flags", None), "th_skip_transcode", False):
		return None

	if doc.get("is_folder") or doc.get("is_private"):
		return None

	uzanti = os.path.splitext(doc.get("file_name") or "")[1].lower()
	if upload_policy.EXTENSIONS.get(uzanti) != upload_policy.KIND_IMAGE:
		return None

	attached_doctype = doc.get("attached_to_doctype") or ""
	if attached_doctype in presets.EXCLUDED_DOCTYPES:
		return None

	slot_key = resolve_slot_key(attached_doctype, doc.get("attached_to_field"))
	if not slot_key and not attached_doctype:
		# K-3: toplu içe aktarımla gelen görsellerde `attached_to_*` NULL
		# (ölçüldü: 3.152 ürün görselinin 1.909'u) — ağırlığın çoğunu taşıyan
		# galeri tam olarak orada. Metadata YOKKEN slot ilişkiden çözülür.
		# Bilinen doctype'ın slotu belirsizse oran dayatmadan library.image
		# kullanılır. Hassas belgeler aşağıdaki ters referans kapısından geçmez.
		slot_key = _slot_from_reference(doc.get("file_url"))
	if not slot_key and str(doc.get("file_url") or "").startswith("/files/"):
		from tradehub_core.media.access_level import _is_protected_pii

		if not _is_protected_pii(doc, doc.file_url):
			slot_key = "library.image"
	if not slot_key or slot_key in EXCLUDED_SLOTS:
		return None

	# EN SON hassas-ikiz kontrolü (rapor 69 §7.2): kapsam DIŞI dosyalar için
	# fazladan sorgu koşmasın — buraya yalnız slotu çözülmüş adaylar gelir.
	if _sensitive_twin_blocked(doc):
		return None

	return slot_key


def _sensitive_twin_blocked(doc: Any) -> bool:
	"""İçeriğin hassas bir İKİZİ varsa üretim engellenir (rapor 69 §7.2).

	Ölçülen sapma: optimize akışı (`runner._assert_in_scope`) aynı `content_hash`i
	private ya da hassas doctype'lı BAŞKA bir `File` kaydında görünce içeriği
	`sensitive_content_twin` gerekçesiyle REDDEDİYOR; bu köprü ise yalnız SEÇİLEN
	kaydın `is_private`/`attached_to`suna baktığı için aynı içeriğin herkese açık
	türevlerini üretti (W3-B koşusunda 10 public türev). İki akış aynı içerik için
	zıt karar veremez — kontrolün tek kaynağı `runner._has_sensitive_twin`, burada
	kopyası YAZILMADI (audit.py ve trash.py de aynı fonksiyonu kullanıyor).

	Optimize akışından tek fark: `frappe.throw` YOK. Bu kanca best-effort'tur
	(yükleme kırılmaz, worker istisna sızdırmaz); davranış "sessizce kapsam dışı"
	+ optimize akışıyla AYNI denetim kaydı (`ACTION_SCOPE_DENIED`,
	`sensitive_content_twin`, `sensitive=True` — URL denetime yazılmaz, sızmasın).
	`commit=False`: kanca `File` insert transaction'ının içinde koşar; worker
	tarafında da RQ işi sonunda zaten commit'lenir.

	`content_hash` boşsa kontrol atlanır — optimize akışıyla aynı sınır
	(`runner._assert_in_scope` da yalnız doluysa soruyor).
	"""
	content_hash = doc.get("content_hash")
	if not content_hash:
		return False

	from tradehub_core.media.runner import _has_sensitive_twin

	if not _has_sensitive_twin(content_hash):
		return False

	audit.log_media_event(
		action=audit.ACTION_SCOPE_DENIED,
		file_url=doc.get("file_url") or "",
		allowed=False,
		reason="sensitive_content_twin",
		sensitive=True,
		commit=False,
	)
	return True


#: `attached_to_*` boşken slotun okunacağı (doctype, alan, slot) üçlüleri.
#: Kaynak `product-image.json` `bound_to` bloğu: `Listing.primary_image` ve
#: galeri alt tablosu `Listing Image.image` — GERÇEK child doctype adı, tahmin
#: değil (`Listing.listing_images` alanının `options` değeri).
_REFERENCE_LOOKUPS: tuple[tuple[str, str, str], ...] = (
	("Listing", "primary_image", "product.image"),
	("Listing Image", "image", "product.image"),
)


def _slot_from_reference(file_url: str | None) -> str | None:
	"""`attached_to_*` boşken slotu İLİŞKİDEN çözer; bulunamazsa `None`.

	Yalnız `_resolve_scope` içinden, yalnız metadata yokken çağrılır. Her
	arama TEK eşitlik sorgusudur ve ilk eşleşmede kısa devre yapar; ikisi de
	aynı slota bağlandığı için ikinci sorgu çoğu zaman hiç koşmaz.

	Bulunamazsa çağıran public kütüphane görseli olarak değerlendirebilir.

	NOT (ölçüldü): `tabListing.primary_image` ve `tabListing Image.image`
	kolonları `text` tipinde ve İNDEKSSİZ — MariaDB TEXT kolonu prefix
	uzunluğu olmadan indekslenemez. Bugünkü boyutta (2.735 + 1.628 satır) tam
	tarama kabul edilebilir; indeks eklemek DocType şeması değişikliğidir ve
	bu görevin kapsamı dışında bırakıldı.
	"""
	if not file_url:
		return None
	for doctype, alan, slot_key in _REFERENCE_LOOKUPS:
		try:
			# Sistem işi: kanca oturumsuz çalışır, `get_list` burada
			# kullanıcının göremediği bir ilanı "yok" sayardı.
			if frappe.db.get_value(doctype, {alan: file_url}, "name"):
				return slot_key
		except Exception:
			frappe.log_error(
				title="media.pipeline_bridge ilişkiden slot çözülemedi",
				message=f"{doctype}.{alan} = {file_url}\n\n{frappe.get_traceback()}",
			)
			return None
	return None


def resolve_slot_key(attached_to_doctype: str | None, attached_to_field: str | None) -> str | None:
	"""(doctype, alan) → `slot_key`. Çözülemezse `None`.

	Alan adı boş gelebiliyor (Frappe yükleyicisi `attached_to_field`'i yalnız
	istemci gönderdiğinde yazar). O durumda doctype tek bir slota bağlanıyorsa
	o slot kullanılır; iki slota birden aday olan doctype'ta (ör. `Admin Seller
	Profile` → `logo` VE `banner_image`) TAHMİN YAPILMAZ, `None` döner. Yanlış
	slot, yanlış oran ve yanlış kırpma demektir.
	"""
	if not attached_to_doctype:
		return None

	tam, tekil = _slot_bindings()
	alan = (attached_to_field or "").strip()
	if alan:
		return tam.get((attached_to_doctype, alan))
	return tekil.get(attached_to_doctype)


@lru_cache(maxsize=1)
def _slot_bindings() -> tuple[dict[tuple[str, str], str], dict[str, str]]:
	"""Slot politikalarının `bound_to` bloklarından iki harita üretir.

	Dönüş: `((doctype, alan) → slot, doctype → slot)`. İkincisi yalnız TEK
	slota bağlanan doctype'ları içerir. Politika dosyası okunamazsa boş harita
	döner — kapsam çözülemez, kanca sessizce no-op olur (fail-safe).
	"""
	tam: dict[tuple[str, str], str] = {}
	doctype_slotlari: dict[str, set[str]] = {}
	try:
		from tradehub_core.media.pipeline.image import render

		for slot_key in render.slot_keys():
			if slot_key in EXCLUDED_SLOTS:
				continue
			politika = render.load_slot_policy(slot_key)
			for baglanma in politika.get("bound_to") or ():
				if baglanma.get("fieldtype") not in _ATTACHMENT_FIELDTYPES:
					continue
				doctype = (baglanma.get("doctype") or "").strip()
				alan = (baglanma.get("field") or "").strip()
				if not doctype or not alan:
					continue
				tam.setdefault((doctype, alan), slot_key)
				doctype_slotlari.setdefault(doctype, set()).add(slot_key)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge slot haritası okunamadı",
			message=frappe.get_traceback(),
		)
		return ({}, {})

	tekil = {dt: next(iter(slotlar)) for dt, slotlar in doctype_slotlari.items() if len(slotlar) == 1}
	return (tam, tekil)


def content_fingerprint(doc: Any) -> str | None:
	"""KAYNAK dosyanın parmak izi — `media/naming.py` ile AYNI kısaltma.

	Bu bir `Media Version.version_hash` DEĞİLDİR (o `pipeline/core/dedup.py::
	version_hash`'ten, 4 girdiyle üretilir — bkz. modül başlığı). Buradaki
	değer içerik kimliğidir: idempotency kapısı ve `Media Asset.content_sha256`
	bunu taşır.

	Yeni yüklemelerin disk adı zaten `sha256(içerik)[:32]` (içerik-adresli
	adlandırma, TUR-141/130); bu durumda hash adından okunur, dosya yeniden
	OKUNMAZ. Adı bu desene uymayan (eski ya da dışarıdan taşınmış) dosyalarda
	içerik okunup aynı kısaltma hesaplanır — iki yol aynı değeri üretmeli,
	aksi hâlde idempotency kontrolü kendi kendini yanıltır.
	"""
	ad = os.path.basename(doc.get("file_url") or "")
	govde = os.path.splitext(ad)[0].lower()
	if _HASHED_NAME_RE.match(govde):
		return govde

	try:
		icerik = doc.get_content()
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge içerik okunamadı",
			message=f"{doc.get('file_url')}\n\n{frappe.get_traceback()}",
		)
		return None
	if isinstance(icerik, str):
		icerik = icerik.encode()
	if not icerik:
		return None
	return hashlib.sha256(icerik).hexdigest()[:_HASH_LENGTH]


#: GERİYE UYUMLULUK — fonksiyonun eski adı. Ölçüldü (2026-08-20, grep): dış
#: çağıran yalnız `tests/test_pipeline_bridge.py`; kırmamak için takma ad
#: duruyor. Bu ad YANILTICIYDI: döndürdüğü şey içerik kimliği, sürüm kimliği
#: değil. Sürüm kimliği `pipeline/core/dedup.py::version_hash`'ten gelir.
version_hash = content_fingerprint


def _contract_value(value: Any, *names: str) -> Any:
	"""Classifier sözleşmesini object/dict sürümleri arasında uyumlu oku."""
	for name in names:
		if isinstance(value, dict) and name in value:
			return value.get(name)
		if hasattr(value, name):
			return getattr(value, name)
	return None


def _animation_route(content: bytes, decision: Any = None) -> dict[str, str] | None:
	"""Animasyonu T-062 video-route sözleşmesine çevir; eski classifier'a uyumlu.

	Yeni sözleşmede `target_pipeline/job_type`, ara sürümde `route_to_video`,
	eski sürümde yalnız `klass=animation` bulunabilir. Hiçbiri yoksa Pillow'un
	frame sayısı kesin geri dönüş kapısıdır.
	"""
	try:
		from tradehub_core.media.pipeline.image import classify as classify_mod

		karar = decision or classify_mod.classify(content)
		hedef = str(_contract_value(karar, "target_pipeline", "pipeline") or "")
		is_tipi = str(_contract_value(karar, "job_type") or "")
		sinif = str(_contract_value(karar, "klass", "class_name", "classification") or "")
		video_mu = bool(_contract_value(karar, "route_to_video"))
		if hedef == "video" or video_mu or sinif == "animation":
			return {"job_type": is_tipi or ANIMATION_JOB_TYPE, "class": sinif or "animation"}
	except Exception:
		pass

	try:
		from PIL import Image

		with Image.open(io.BytesIO(content)) as im:
			if bool(getattr(im, "is_animated", False)) or int(getattr(im, "n_frames", 1)) > 1:
				return {"job_type": ANIMATION_JOB_TYPE, "class": "animation"}
	except Exception:
		pass
	return None


def _prepare_image_master(
	content: bytes,
	slot_key: str,
	*,
	classification: Any = None,
	filename: str = "",
) -> Any:
	"""T-061/T-062 production köprüsü: kaynak → sınıflandırılmış Version master.

	Slot politikası geometri/metadata tavanlarını; ``image.master`` ise Faz 2
	format karar tablosunu uygular. Dönen master, sürüm künyesi, crop hesabı,
	lazy kontrolü, rendition encode'u ve kalite raporunun ORTAK girdisidir.
	"""
	from tradehub_core.media.pipeline.image import master as master_mod
	from tradehub_core.media.pipeline.image import render

	return master_mod.make_master(
		content,
		render.load_slot_policy(slot_key),
		filename=filename,
		classification=classification,
	)


def _animated_video_slot(image_slot: str) -> str | None:
	"""Görsel slotunun animasyon teslim kardeşini politika ağacından bul."""
	from tradehub_core.media.pipeline.image import render

	adaylar: list[str] = []
	if image_slot.endswith(".image"):
		adaylar.append(f"{image_slot[:-6]}.video")
	if image_slot.endswith("_image"):
		adaylar.append(f"{image_slot[:-6]}_video")
	if image_slot == "company.cover_image":
		adaylar.append("company.cover_video")
	for aday in dict.fromkeys(adaylar):
		try:
			if render.load_slot_policy(aday).get("video"):
				return aday
		except Exception:
			continue
	return None


def _engine_output_match(content: bytes) -> dict[str, Any] | None:
	"""Persistent ledger ile exact engine output'u tanı (heuristic yok).

	Ana yol indeksli ``output_sha256`` sorgusudur ve tarihsel sürüm satırlarını
	de kapsar. Redis yalnız docname hızlandırmasıdır; kanıt daima DB'deki hash +
	engine_signature çiftidir. Legacy satırların disk fallback'i bir kez
	doğrulanınca aynı persistent deftere yükseltilir.
	"""
	sha = content_sha256(content)
	cache_key = f"media:engine-output:{sha}"
	try:
		cached_name = frappe.cache().get_value(cache_key, expires=True)
		if isinstance(cached_name, bytes):
			cached_name = cached_name.decode("utf-8", "replace")
		if cached_name:
			cached = frappe.db.get_value(
				"Media Rendition",
				str(cached_name),
				[
					"name",
					"asset",
					"version_hash",
					"profile",
					"width",
					"format",
					"file_url",
					"output_sha256",
					"engine_signature",
				],
				as_dict=True,
			)
			if cached and cached.output_sha256 == sha and _engine_ledger_valid(dict(cached), sha):
				return {**dict(cached), "sha256": sha, "cached": True}
	except Exception:
		pass

	ledger_rows = frappe.get_all(
		"Media Rendition",
		filters={"output_sha256": sha},
		fields=[
			"name",
			"asset",
			"version_hash",
			"profile",
			"width",
			"format",
			"file_url",
			"output_sha256",
			"engine_signature",
		],
		limit_page_length=0,
	)
	for row in ledger_rows:
		if not _engine_ledger_valid(dict(row), sha):
			continue
		try:
			frappe.cache().set_value(cache_key, row["name"], expires_in_sec=ENGINE_OUTPUT_CACHE_SECONDS)
		except Exception:
			pass
		return {**dict(row), "sha256": sha, "cached": False}

	for row in frappe.get_all(
		"Media Rendition",
		filters={"bytes": len(content)},
		fields=[
			"name",
			"asset",
			"version_hash",
			"profile",
			"width",
			"format",
			"file_url",
			"output_sha256",
			"engine_signature",
		],
		# Aynı bayt boyunda 100'den fazla türev olabilir. Varsayılan/sabit bir
		# sayfa sınırı hedefi defterin dışında bırakıp aynı motor çıktısını tekrar
		# encode ettirirdi; idempotency kanıtı için bütün adaylar tam hash'lenir.
		limit_page_length=0,
	):
		yol = _media_disk_path(row.get("file_url") or "")
		if not yol or not os.path.isfile(yol):
			continue
		if file_sha256(yol) != sha:
			continue
		engine_version = frappe.db.get_value("Media Version", row.get("version_hash"), "engine_version")
		signature = engine_signature(
			engine_version=str(engine_version or "legacy"),
			version_hash=str(row.get("version_hash") or ""),
			profile=str(row.get("profile") or ""),
			width=int(row.get("width") or 0),
			fmt=str(row.get("format") or ""),
			output_sha256=sha,
		)
		frappe.db.set_value(
			"Media Rendition",
			row["name"],
			{"output_sha256": sha, "engine_signature": signature},
			update_modified=False,
		)
		try:
			frappe.cache().set_value(cache_key, row["name"], expires_in_sec=ENGINE_OUTPUT_CACHE_SECONDS)
		except Exception:
			pass
		return {
			**dict(row),
			"sha256": sha,
			"output_sha256": sha,
			"engine_signature": signature,
			"cached": False,
		}
	return None


def _engine_ledger_valid(row: dict[str, Any], output_hash: str) -> bool:
	"""Recompute the deterministic signature; a merely non-empty field is not proof."""
	signature = str(row.get("engine_signature") or "")
	if len(signature) != 64 or str(row.get("output_sha256") or "") != output_hash:
		return False
	engine_version = frappe.db.get_value("Media Version", row.get("version_hash"), "engine_version")
	expected = engine_signature(
		engine_version=str(engine_version or "legacy"),
		version_hash=str(row.get("version_hash") or ""),
		profile=str(row.get("profile") or ""),
		width=int(row.get("width") or 0),
		fmt=str(row.get("format") or ""),
		output_sha256=output_hash,
	)
	return hmac.compare_digest(signature, expected)


def _reevaluate_engine_output_policy(match: dict[str, Any], slot_key: str) -> bool:
	"""Re-evaluate current policy without creating an Asset or encoding bytes.

	The report job is the durable audit record: success means the historical
	output coordinate still belongs to the current slot policy; a mismatch is
	recorded explicitly, but neither case feeds lossy output back to an encoder.
	"""
	sha = str(match.get("output_sha256") or match.get("sha256") or "")
	job_name = _open_job(
		str(match["asset"]),
		sha,
		slot_key,
		job_type="report",
		queue=JOB_QUEUE,
		key_prefix="engine-output-policy",
	)
	profile = str(match.get("profile") or "")
	width = int(match.get("width") or 0)
	fmt = str(match.get("format") or "").lower()
	compatible = any(
		str(candidate.policy_profile or "") == profile
		and width in {int(value) for value in candidate.get_widths()}
		and fmt in {str(value).lower() for value in candidate.get_formats()}
		for candidate in _profiles_for_slot(slot_key)
	)
	_finish_job(job_name, "success" if compatible else "failed", None if compatible else "policy_mismatch")
	frappe.db.commit()
	return compatible


def _renditions_exist(surum_hash: str, slot_key: str, *, doc: Any = None) -> bool:
	"""Bu içerik + slot için üretilmiş bir türev zaten var mı?"""
	# Sistem işi: oturum yetkisinden bağımsızdır; dosya verildiğinde aynı
	# satıcının varlığı aranır. Başka mağazanın türevi bu dosyayı atlatamaz.
	filters: dict[str, Any] = {"content_sha256": surum_hash, "slot_key": slot_key}
	if doc is not None:
		store = ownership.store_of(doc.get("owner"))
		filters["owner_seller"] = store if store else ["in", ["", None]]
	assetler = frappe.get_all(
		"Media Asset",
		filters=filters,
		pluck="name",
	)
	if not assetler:
		return False
	# F-33a — çöpe taşınmış (`state=purged`) türev "var" DEĞİLDİR. Süzgeç
	# yokken, silinmiş bir görselin aynısı yeniden yüklendiğinde bu kapı eski
	# purged satırları görüp "zaten üretildi" diyor ve yeni yükleme SESSİZCE
	# türevsiz kalıyordu — F-31 ile aynı sınıf: bir artık, taze bir dosyanın
	# kaderini belirliyor.
	return bool(
		frappe.get_all(
			"Media Rendition",
			filters={"asset": ["in", assetler], "state": ["!=", "purged"]},
			limit=1,
			pluck="name",
		)
	)


# --- 2) Worker: üretim -------------------------------------------------------


def _run_rendition_job(
	file_url: str, force: bool = False, file_name: str | None = None, *, backfill: bool = False
) -> None:
	"""Worker tarafı — türev matrisini üretir, diske yazar, kayıtları açar.

	İstisna SIZDIRMAZ. Hata hâlinde `Media Processing Job` `failed` olur,
	`frappe.log_error` yazılır ve fonksiyon sessizce döner.
	"""
	job_name: str | None = None
	baslangic = time.perf_counter()
	try:
		name = file_name or frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not name:
			# Kuyruğa alındıktan sonra dosya silinmiş olabilir.
			return
		doc = frappe.get_doc("File", name)
		if doc.file_url != file_url:
			return

		# Bayrak kuyrukta beklerken kapatılmış olabilir — worker da sorar.
		if not pipeline_flags.is_enabled("rendition_on_upload"):
			return
		if not pipeline_flags.is_store_enabled(ownership.store_of(doc.get("owner"))):
			return

		slot_key = _resolve_scope(doc)
		if not slot_key or not pipeline_flags.is_slot_enabled(slot_key):
			return

		parmak_izi = content_fingerprint(doc)
		if not parmak_izi:
			return
		# Kontrollü backfill politika değişikliğinde (mesela JPEG fallback
		# eklendiğinde) mevcut eski merdiveni yeni version_hash ile yeniden
		# üretmelidir. Upload yolu varsayılan `force=False` ile aynı idempotency
		# kapısını korur.
		if not force and _renditions_exist(parmak_izi, slot_key, doc=doc):
			return

		kaynak = doc.get_content()
		if isinstance(kaynak, str):
			kaynak = kaynak.encode()
		if not kaynak:
			return

		from tradehub_core.media.pipeline.image import classify as classify_mod

		siniflandirma = classify_mod.classify(kaynak, filename=str(doc.file_name or ""))
		# T-062 sözleşmesi geç gelmiş olsa da köprü alan adlarına sıkı bağlı
		# değildir: object/dict + klass/route/job_type biçimlerini kabul eder,
		# son çare olarak Pillow frame sayısını ölçer. Animasyon hiçbir zaman
		# görsel render'a girip ilk kareye düzleştirilmez.
		animasyon = _animation_route(kaynak, siniflandirma)
		if animasyon:
			video_slot = _animated_video_slot(slot_key)
			if video_slot:
				frappe.enqueue(
					"tradehub_core.media.pipeline_bridge._run_animation_job",
					queue=RQ_QUEUE_VIDEO,
					timeout=media_queues.VIDEO.timeout_seconds,
					enqueue_after_commit=True,
					job_id=(
						f"media-animation::{hashlib.sha1(f'{file_url}|{video_slot}'.encode()).hexdigest()}"
					),
					deduplicate=True,
					file_url=file_url,
					slot_override=video_slot,
				)
			return

		# T-064 / INV-06: tam bayt daha önce Media Rendition olarak yazıldıysa
		# bu bir master değildir. Politika kaydı hâlâ değerlendirilir ama kayıplı
		# encode asla ikinci kez uygulanmaz.
		if match := _engine_output_match(kaynak):
			_reevaluate_engine_output_policy(match, slot_key)
			return

		asset = _ensure_asset(doc, slot_key, parmak_izi)
		# §18 — dönüşüm sayacı. Kuyruğa alma kapısı (KAPI 5) kotayı ÖNCEDEN
		# soruyor; sayaç ise işin GERÇEKTEN yapıldığı yerde artıyor. İkisini
		# aynı yere koymak, kuyrukta bekleyip sonra düşen işleri de saymak
		# olurdu — kullanıcı üretilmemiş türev için kotasından ödeme yapardı.
		# Sürüm geçişinin eski fotoğrafları işlemesi satıcının yeni yükleme
		# kotasını tüketmez; kullanıcının başlattığı dönüşümler sayılır.
		if not backfill:
			meter.record(ownership.store_of(doc.get("owner")), meter.METRIC_TRANSFORMATIONS, 1)
		# Public türevler EXIF/GPS'i politika gereği siler; gerekli kaynak
		# metadata'sı silinmeden önce şifreli, yetki-sınırlı kasada tutulur.
		from tradehub_core.media import exif_vault

		exif_vault.retain(asset, kaynak)
		job_name = _open_job(
			asset.name,
			parmak_izi,
			slot_key,
			queue=JOB_QUEUE_BULK if backfill else JOB_QUEUE,
			key_prefix=f"{'backfill' if backfill else 'rendition'}:{asset.name}",
		)
		prepared = _prepare_image_master(
			kaynak,
			slot_key,
			classification=siniflandirma,
			filename=str(doc.file_name or ""),
		)
		if not prepared.ok:
			aktif = frappe.db.get_value("Media Asset", asset.name, "active_version")
			frappe.db.set_value("Media Asset", asset.name, "state", "ready" if aktif else "failed")
			reason = str(prepared.reason or "normalize_failed")
			_record_generation_failure(reason, time.perf_counter() - baslangic)
			_finish_job(job_name, "failed", error_code=reason)
			frappe.db.commit()
			return
		master_bytes = prepared.content
		# T-042: sürüm kimliği KÜTÜPHANEDEN (dedup.version_hash, 4 girdi) gelir
		# ve türev adresleri onu taşır. Yalnız YENİ üretimler — mevcut türev
		# kayıtlarının adresine dokunulmaz.
		# Politika geçişi satıcının yayındaki kırpma/odak kararını korur.
		crop_intent = (
			_version_crop_intent(asset.active_version) if backfill and asset.active_version else None
		)
		surum = _ensure_version(asset, slot_key, kaynak, crop_intent=crop_intent, prepared=prepared)

		frappe.db.savepoint("image_rendition_generation")
		sonuc = _generate(
			master_bytes,
			asset,
			slot_key,
			surum.version_hash,
			crop_intent=crop_intent,
			generation="eager",
			classification=prepared.classification,
		)

		if sonuc.complete:
			frappe.db.set_value("Media Asset", asset.name, "state", "ready")
			_record_generation_report(
				kaynak,
				asset,
				surum.version_hash,
				sonuc,
				trigger="backfill" if backfill else "upload",
				rendering_source=master_bytes,
				normalized=prepared.normalized,
				classification=prepared.classification,
				crop_intent=crop_intent,
			)
			_finish_job(job_name, "success")
			if backfill:
				_promote_complete_version(asset.name, surum.version_hash)
			else:
				_promote_initial_version(asset.name, surum.version_hash)
		else:
			# Okuyucu transaction boyunca eski satırları görür. Başarısız yeni
			# matrisin tek bir satırı bile commit edilmez; eski aktif sürüm kalır.
			frappe.db.rollback(save_point="image_rendition_generation")
			aktif = frappe.db.get_value("Media Asset", asset.name, "active_version")
			frappe.db.set_value("Media Asset", asset.name, "state", "ready" if aktif else "failed")
			_record_generation_failure(
				"incomplete_rendition_matrix",
				time.perf_counter() - baslangic,
			)
			_finish_job(job_name, "failed", error_code="incomplete_rendition_matrix")
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		frappe.db.rollback()
		_record_generation_failure(type(exc).__name__, time.perf_counter() - baslangic)
		if job_name:
			_finish_job(job_name, "failed", error_code=type(exc).__name__)
			frappe.db.commit()
		frappe.log_error(
			title="media.pipeline_bridge rendition job failed",
			message=f"{file_url}\n\n{frappe.get_traceback()}",
		)


def enqueue_catalog_backfill(limit: int = 100) -> dict[str, int]:
	"""Eksik katalog görsellerini kontrollü bir batch olarak `long` kuyruğa at.

	Aynı URL için RQ `job_id` deterministiktir; operatör butona tekrar bassa
	kuyrukta aynı iş çoğalmaz. `force=True`, eski politika sürümündeki
	asset'lerin güncel AVIF/WebP/JPEG merdivenine yükselmesini sağlar.
	"""
	if not pipeline_flags.is_enabled("rendition_on_upload"):
		return {"queued": 0, "remaining": 0, "reason": "pipeline_disabled"}
	if not pipeline_flags.is_slot_enabled("product.image"):
		return {"queued": 0, "remaining": 0, "reason": "slot_disabled"}

	tavan = max(1, min(500, int(limit or 100)))
	adaylar = _catalog_backfill_candidates(limit=tavan)
	secili = adaylar[:tavan]
	for url in secili:
		job_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()  # noqa: S324 -- kimlik, kripto değil
		frappe.enqueue(
			"tradehub_core.media.pipeline_bridge._run_rendition_job",
			queue=RQ_QUEUE_BULK,
			timeout=QUEUE_TIMEOUT_BULK_SECONDS,
			enqueue_after_commit=False,
			job_id=f"media-rendition-backfill::{job_hash}",
			deduplicate=True,
			file_url=url,
			force=True,
		)
	durum = rendition_backfill_status()
	return {
		"queued": len(secili),
		"remaining": durum["missing"],
		"has_more": durum["missing"] > len(secili),
	}


def _catalog_backfill_candidates(limit: int = 101) -> list[str]:
	"""Hazır merdiveni (ready asset + en az bir türev) olmayan vitrin görselleri.

	JPEG şartı BİLEREK yok: fallback formatı sınıfa göre değişir — grafik/
	şeffaf sınıfı lossless WEBP+PNG zinciri alır, JPEG plana hiç girmez
	(ölçüm 2026-08-26: 232 ready asset JPEG'siz; jpeg-şartlı sorgu bunları
	sonsuza dek aday sayıp backfill'i platoya oturttu).

	NOT EXISTS eşlemesi iki koldan: `source_file` VE içerik hash'i
	(`content_sha256` = hash-adlı dosyanın gövde adı). Yalnız `source_file`
	ile eşlemek, aynı içeriğin başka bir `File` satırından açılmış asset'ini
	görmüyor ve adres sonsuza dek aday kalıyordu (ölçüm 2026-08-26: backfill
	2.748 adayda platoya oturdu; teslimat tarafı `_mukerrer_dosya_koprusu`
	ile zaten içerikten eşliyor — burada da aynı kimlik kullanılmalı).
	"""
	return [
		r["file_url"]
		for r in frappe.db.sql(
			"""
			SELECT DISTINCT f.file_url
			FROM `tabFile` f
			JOIN (
				SELECT primary_image AS file_url FROM `tabListing`
				WHERE storefront_visible=1 AND primary_image LIKE '/files/%%'
				UNION
				SELECT li.image AS file_url FROM `tabListing Image` li
				JOIN `tabListing` l ON l.name=li.parent
				WHERE l.storefront_visible=1 AND li.image LIKE '/files/%%'
			) catalog ON catalog.file_url=f.file_url
			WHERE NOT EXISTS (
				SELECT 1 FROM `tabMedia Asset` a
				JOIN `tabMedia Rendition` r ON r.asset=a.name
				WHERE (a.source_file=f.name
				       OR a.content_sha256=SUBSTRING_INDEX(SUBSTRING_INDEX(f.file_url,'/',-1),'.',1))
				  AND a.slot_key='product.image'
				  AND a.state='ready'
			)
			ORDER BY f.modified DESC
			LIMIT %(limit)s
			""",
			{"limit": max(1, min(501, int(limit or 101)))},
			as_dict=True,
		)
	]


def rendition_backfill_status() -> dict[str, int]:
	"""Katalog merdiveni ve iş kuyruğunun tek, ucuz operasyonel özeti."""
	total = int(
		frappe.db.sql(
			"""
			SELECT COUNT(DISTINCT f.name)
			FROM `tabFile` f
			JOIN (
				SELECT primary_image AS file_url FROM `tabListing`
				 WHERE storefront_visible=1 AND primary_image LIKE '/files/%%'
				UNION
				SELECT li.image FROM `tabListing Image` li
				 JOIN `tabListing` l ON l.name=li.parent
				 WHERE l.storefront_visible=1 AND li.image LIKE '/files/%%'
			) catalog ON catalog.file_url=f.file_url
			"""
		)[0][0]
		or 0
	)
	missing = int(
		frappe.db.sql(
			"""
			SELECT COUNT(*) FROM (
				SELECT DISTINCT f.name
				FROM `tabFile` f
				JOIN (
					SELECT primary_image AS file_url FROM `tabListing`
					 WHERE storefront_visible=1 AND primary_image LIKE '/files/%%'
					UNION
					SELECT li.image FROM `tabListing Image` li
					 JOIN `tabListing` l ON l.name=li.parent
					 WHERE l.storefront_visible=1 AND li.image LIKE '/files/%%'
				) catalog ON catalog.file_url=f.file_url
				WHERE NOT EXISTS (
					SELECT 1 FROM `tabMedia Asset` a
					JOIN `tabMedia Rendition` r ON r.asset=a.name
					WHERE (a.source_file=f.name
					       OR a.content_sha256=SUBSTRING_INDEX(SUBSTRING_INDEX(f.file_url,'/',-1),'.',1))
					  AND a.slot_key='product.image'
					  AND a.state='ready'
				)
			) missing_catalog
			"""
		)[0][0]
		or 0
	)
	jobs = {
		str(row[0]): int(row[1])
		for row in frappe.db.sql(
			"""SELECT status, COUNT(*) FROM `tabMedia Processing Job`
			WHERE job_type='rendition' GROUP BY status"""
		)
	}
	try:
		from frappe.utils.background_jobs import get_queue

		queue_depth = int(get_queue(RQ_QUEUE).count)
	except Exception:
		queue_depth = 0
	return {
		"total": total,
		"ready": max(0, total - missing),
		"missing": missing,
		"queue_depth": queue_depth,
		"success": jobs.get("success", 0),
		"failed": jobs.get("failed", 0),
		"running": jobs.get("running", 0),
		"queued_jobs": jobs.get("queued", 0),
	}


def retry_failed_renditions(limit: int = 50) -> dict[str, int]:
	"""Başarısız görsel işlerinin kaynaklarını kontrollü yeniden kuyruğa al."""
	tavan = max(1, min(200, int(limit or 50)))
	urls = frappe.db.sql(
		"""
		SELECT DISTINCT f.file_url
		FROM `tabMedia Processing Job` j
		JOIN `tabMedia Asset` a ON a.name=j.asset
		JOIN `tabFile` f ON f.name=a.source_file
		WHERE j.job_type='rendition' AND j.status='failed'
		  AND f.file_url IS NOT NULL AND f.file_url != ''
		ORDER BY j.modified DESC LIMIT %(limit)s
		""",
		{"limit": tavan},
	)
	queued = 0
	for (url,) in urls:
		job_hash = hashlib.sha1(str(url).encode("utf-8")).hexdigest()  # noqa: S324
		frappe.enqueue(
			"tradehub_core.media.pipeline_bridge._run_rendition_job",
			queue=RQ_QUEUE_BULK,
			timeout=QUEUE_TIMEOUT_BULK_SECONDS,
			enqueue_after_commit=False,
			job_id=f"media-rendition-retry::{job_hash}",
			deduplicate=True,
			file_url=url,
			force=True,
		)
		queued += 1
	return {"queued": queued}


def _bulk_status_key(token: str) -> str:
	return f"media:policy-reprocess:{token}:status"


def _bulk_cancel_key(token: str) -> str:
	return f"media:policy-reprocess:{token}:cancel"


def _set_bulk_status(token: str, **values: Any) -> dict[str, Any]:
	durum = policy_reprocess_status(token)
	durum.update(values)
	frappe.cache().set_value(
		_bulk_status_key(token),
		json.dumps(durum, sort_keys=True),
		expires_in_sec=BULK_STATUS_SECONDS,
	)
	return durum


def policy_reprocess_status(token: str) -> dict[str, Any]:
	ham = frappe.cache().get_value(_bulk_status_key(str(token)), expires=True)
	if not ham:
		return {"token": str(token), "status": "unknown", "processed": 0, "failed": 0}
	if isinstance(ham, bytes):
		ham = ham.decode("utf-8", "replace")
	try:
		return json.loads(ham) if isinstance(ham, str) else dict(ham)
	except Exception:
		return {"token": str(token), "status": "unknown", "processed": 0, "failed": 0}


def enqueue_policy_reprocess(
	asset_names: Iterable[str] | None = None,
	*,
	limit: int = 500,
	rate_per_minute: int = 30,
) -> dict[str, Any]:
	"""Her asset'i ayrı düşük-öncelikli işe, hız planıyla kuyruğa al.

	Tek bir long worker içinde ``sleep`` edilmez. İlk asset hemen, sonrakiler
	``60/rate`` aralıklarıyla RQ scheduled registry'ye yazılır; ayrı
	``media-image-bulk`` worker'ı canlı kullanıcı işlerini tüketmez.
	"""
	if asset_names is None:
		adlar = frappe.get_all(
			"Media Asset",
			filters={"media_type": "image", "state": "ready"},
			order_by="modified asc",
			limit_page_length=max(1, min(5000, int(limit or 500))),
			pluck="name",
		)
	else:
		adlar = list(dict.fromkeys(str(name) for name in asset_names if name))
		adlar = adlar[: max(1, min(5000, int(limit or 500)))]
	token = frappe.generate_hash(length=24)
	_set_bulk_status(
		token,
		status="queued" if adlar else "completed",
		total=len(adlar),
		processed=0,
		failed=0,
		cancelled=False,
	)
	rate = max(1, min(600, int(rate_per_minute or 30)))
	for index, asset_name in enumerate(adlar):
		_enqueue_scheduled_policy_item(
			token,
			asset_name,
			index=index,
			delay_seconds=index * (60.0 / rate),
		)
	return {"token": token, "queued": len(adlar), "queue": JOB_QUEUE_BULK}


def cancel_policy_reprocess(token: str) -> dict[str, Any]:
	"""Koşan asset tamamlanınca ve planlı işler başlamadan önce iptal et."""
	frappe.cache().set_value(_bulk_cancel_key(str(token)), "1", expires_in_sec=BULK_STATUS_SECONDS)
	return _set_bulk_status(str(token), status="cancelling", cancelled=True)


def _enqueue_scheduled_policy_item(
	token: str,
	asset_name: str,
	*,
	index: int,
	delay_seconds: float,
) -> Any:
	"""One asset → one RQ job; delayed jobs retain Frappe site/user context."""
	method = "tradehub_core.media.pipeline_bridge._run_policy_reprocess_item"
	job_id = f"media-policy-reprocess::{token}::{index}"
	if delay_seconds <= 0:
		return frappe.enqueue(
			method,
			queue=RQ_QUEUE_BULK,
			timeout=QUEUE_TIMEOUT_BULK_SECONDS,
			enqueue_after_commit=False,
			job_id=job_id,
			deduplicate=True,
			token=token,
			asset_name=asset_name,
		)

	# frappe.enqueue has no enqueue_at/enqueue_in parameter. Build the same
	# execute_job envelope it uses, then place that envelope in RQ's scheduled
	# registry. The dedicated bulk worker promotes due jobs without occupying a
	# Python worker process while waiting.
	from frappe.utils.background_jobs import (  # noqa: PLC0415
		RQ_JOB_FAILURE_TTL,
		RQ_RESULTS_TTL,
		create_job_id,
		execute_job,
		get_queue,
	)

	queue_args = {
		"site": frappe.local.site,
		"user": getattr(frappe.session, "user", None),
		"method": method,
		"event": None,
		"job_name": method,
		"is_async": True,
		"kwargs": {"token": token, "asset_name": asset_name},
	}
	return get_queue(RQ_QUEUE_BULK).enqueue_in(
		timedelta(seconds=float(delay_seconds)),
		execute_job,
		kwargs=queue_args,
		timeout=QUEUE_TIMEOUT_BULK_SECONDS,
		failure_ttl=frappe.conf.get("rq_job_failure_ttl") or RQ_JOB_FAILURE_TTL,
		result_ttl=frappe.conf.get("rq_results_ttl") or RQ_RESULTS_TTL,
		job_id=create_job_id(job_id),
	)


def _run_policy_reprocess_batch(
	token: str,
	asset_names: Iterable[str],
	rate_per_minute: int = 30,
) -> None:
	"""Legacy queued batch'i bloklamadan atomik işlere dağıtan dispatcher.

	Eski sürümden kuyrukta kalmış batch payload'ları güvenle devam etsin diye
	public isim korunur; yeni enqueue yolu doğrudan item'ları planlar.
	"""
	adlar = list(dict.fromkeys(str(name) for name in asset_names if name))
	rate = max(1, min(600, int(rate_per_minute or 30)))
	_set_bulk_status(token, status="queued", total=len(adlar))
	for index, asset_name in enumerate(adlar):
		_enqueue_scheduled_policy_item(
			token,
			asset_name,
			index=index,
			delay_seconds=index * (60.0 / rate),
		)


def _run_policy_reprocess_item(token: str, asset_name: str) -> None:
	"""Run exactly one asset, with cancel checks on both sides of the work."""
	if frappe.cache().get_value(_bulk_cancel_key(token), expires=True):
		_set_bulk_status(token, status="cancelled", cancelled=True)
		return
	_set_bulk_status(token, status="running")
	baslangic = time.perf_counter()
	failed = False
	error_code = ""
	try:
		failed = not _run_policy_reprocess_asset(asset_name)
		if failed:
			error_code = "reprocess_failed"
	except Exception as exc:
		frappe.db.rollback()
		_record_generation_failure(type(exc).__name__, time.perf_counter() - baslangic)
		failed = True
		error_code = type(exc).__name__
		frappe.log_error(
			title="media.pipeline_bridge policy reprocess failed",
			message=f"{asset_name}\n\n{frappe.get_traceback()}",
		)
	_update_bulk_after_item(
		token,
		failed=failed,
		asset_name=asset_name if failed else "",
		error_code=error_code,
	)


def _update_bulk_after_item(
	token: str,
	*,
	failed: bool,
	asset_name: str = "",
	error_code: str = "",
) -> dict[str, Any]:
	"""Atomically increment shared counters for independently scheduled jobs."""
	lock = frappe.cache().lock(
		f"media:policy-reprocess:{token}:status-lock",
		timeout=30,
		blocking_timeout=10,
	)
	with lock:
		status = policy_reprocess_status(token)
		processed = int(status.get("processed") or 0) + 1
		failed_count = int(status.get("failed") or 0) + int(failed)
		failures = list(status.get("failures") or [])
		if failed and asset_name:
			failures.append({"asset": asset_name, "error_code": error_code or "reprocess_failed"})
		cancelled = bool(frappe.cache().get_value(_bulk_cancel_key(token), expires=True))
		final = processed >= int(status.get("total") or 0)
		return _set_bulk_status(
			token,
			processed=processed,
			failed=failed_count,
			failures=failures,
			cancelled=cancelled,
			status="cancelled" if cancelled else "completed" if final else "running",
		)


def _run_policy_reprocess_asset(asset_name: str) -> bool:
	"""Tek asset'in politika sürümünü tam üret, sonra atomik promote et."""
	baslangic = time.perf_counter()
	if not frappe.db.exists("Media Asset", asset_name):
		return False
	asset = frappe.get_doc("Media Asset", asset_name)
	if asset.media_type != "image" or not asset.source_file:
		return False
	if not frappe.db.exists("File", asset.source_file):
		return False
	source_doc = frappe.get_doc("File", asset.source_file)
	kaynak = source_doc.get_content()
	if isinstance(kaynak, str):
		kaynak = kaynak.encode()
	if not kaynak:
		return False
	intent = (
		frappe.get_doc("Media Crop Intent", asset.name)
		if frappe.db.exists("Media Crop Intent", asset.name)
		else _version_crop_intent(asset.active_version)
		if asset.active_version
		else None
	)
	prepared = _prepare_image_master(
		kaynak,
		asset.slot_key,
		filename=str(source_doc.file_name or ""),
	)
	if not prepared.ok:
		reason = str(prepared.reason or "normalize_failed")
		job_name = _open_job(
			asset.name,
			content_sha256(kaynak),
			asset.slot_key,
			queue=JOB_QUEUE_BULK,
			key_prefix="policy-reprocess",
		)
		_record_generation_failure(reason, time.perf_counter() - baslangic)
		_finish_job(job_name, "failed", error_code=reason)
		frappe.db.commit()
		return False
	master_bytes = prepared.content
	surum = _ensure_version(asset, asset.slot_key, kaynak, crop_intent=intent, prepared=prepared)
	job_name = _open_job(
		asset.name,
		surum.version_hash,
		asset.slot_key,
		queue=JOB_QUEUE_BULK,
		key_prefix="policy-reprocess",
	)
	frappe.db.savepoint("image_policy_reprocess")
	# Eski lazy satırlar tarihsel sürüm defterinin parçasıdır; silinmez. Yeni
	# version_hash altında satır bulunmadığı için ilk manifest isteği yalnız yeni
	# sürümün lazy basamaklarını üretir.
	sonuc = _generate(
		master_bytes,
		asset,
		asset.slot_key,
		surum.version_hash,
		crop_intent=intent,
		generation="eager",
		classification=prepared.classification,
	)
	if not sonuc.complete:
		frappe.db.rollback(save_point="image_policy_reprocess")
		_record_generation_failure(
			"incomplete_policy_matrix",
			time.perf_counter() - baslangic,
		)
		_finish_job(job_name, "failed", error_code="incomplete_rendition_matrix")
		frappe.db.commit()
		return False
	frappe.db.set_value("Media Asset", asset.name, "state", "ready")
	_record_generation_report(
		kaynak,
		asset,
		surum.version_hash,
		sonuc,
		crop_intent=intent,
		trigger="policy_reprocess",
		rendering_source=master_bytes,
		normalized=prepared.normalized,
		classification=prepared.classification,
	)
	_finish_job(job_name, "success")
	_promote_complete_version(asset.name, surum.version_hash)
	frappe.db.commit()
	return True


def maybe_reprocess_after_crop(asset_name: str) -> None:
	"""`save_intent` sonrası köprü — türevlerin YENİ kadrajla yeniden üretimini kuyruğa alır.

	Best-effort: kuyruk hatası niyet kaydını geri almaz (çağıran yutar-loglar).
	Bayrak/slot kapıları worker'da TEKRAR sorulur; burada sorulmaları yalnız
	kapalı hatta kuyruğa boş iş sokmamak için.
	"""
	if not pipeline_flags.is_enabled("rendition_on_upload"):
		return
	varlik = frappe.db.get_value("Media Asset", asset_name, ["slot_key", "media_type"], as_dict=True)
	slot_key = varlik.get("slot_key") if varlik else None
	if not slot_key or not pipeline_flags.is_slot_enabled(str(slot_key)):
		return
	frappe.enqueue(
		"tradehub_core.media.pipeline_bridge._run_crop_reprocess_job",
		queue=RQ_QUEUE_VIDEO if str(varlik.get("media_type") or "") == _MEDIA_TYPE_VIDEO else RQ_QUEUE,
		timeout=(
			media_queues.VIDEO.timeout_seconds
			if str(varlik.get("media_type") or "") == _MEDIA_TYPE_VIDEO
			else media_queues.IMAGE_LIVE.timeout_seconds
		),
		enqueue_after_commit=True,
		# Uygula'ya art arda basılırsa kuyrukta TEK iş kalsın (deduplicate
		# yalnız henüz koşmamış işe bakar; koşan işten sonra gelen kayıt
		# yeni iş açar — son kadraj daima kazanır).
		job_id=f"media-crop-reprocess::{asset_name}",
		deduplicate=True,
		asset_name=asset_name,
	)


def _run_crop_reprocess_job(asset_name: str) -> None:
	"""Worker — kayıtlı kırpma niyetiyle türev matrisini YENİDEN üretir (T-041 zinciri).

	`_run_rendition_job`un kardeşi; farkları:
	  · Girdi `File` değil `Media Asset` — kaynak `asset.source_file`'dan okunur.
	  · `_renditions_exist` SORULMAZ: işin varlık sebebi mevcut türevleri
	    değiştirmek.
	  · Sürüm hash'ine kırpma niyeti GİRER (`_ensure_version`); aynı niyetle
	    ikinci koşum aynı hash'i üretir ve disk-atlama (T-064) encode'ları
	    sıfırlar — iş idempotent.
	İstisna SIZDIRMAZ (worker sözleşmesi `_run_rendition_job` ile aynı).
	"""
	job_name: str | None = None
	baslangic = time.perf_counter()
	try:
		if not frappe.db.exists("Media Asset", asset_name):
			return
		if not pipeline_flags.is_enabled("rendition_on_upload"):
			return
		asset = frappe.get_doc("Media Asset", asset_name)
		slot_key = asset.slot_key
		if not slot_key or not pipeline_flags.is_slot_enabled(slot_key):
			return
		# Niyet adı = asset adı (`autoname: field:asset`). Niyet silinmişse
		# yapılacak iş yok — niyetsiz üretim yükleme hattının işi.
		if not frappe.db.exists("Media Crop Intent", asset_name):
			return
		intent = frappe.get_doc("Media Crop Intent", asset_name)
		if asset.media_type == _MEDIA_TYPE_VIDEO:
			_run_video_crop_reprocess_job(asset, intent)
			return

		if not asset.source_file or not frappe.db.exists("File", asset.source_file):
			return
		source_doc = frappe.get_doc("File", asset.source_file)
		kaynak = source_doc.get_content()
		if isinstance(kaynak, str):
			kaynak = kaynak.encode()
		if not kaynak:
			return

		prepared = _prepare_image_master(
			kaynak,
			slot_key,
			filename=str(source_doc.file_name or ""),
		)
		if not prepared.ok:
			reason = str(prepared.reason or "normalize_failed")
			job_name = _open_job(
				asset.name,
				content_sha256(kaynak),
				slot_key,
				key_prefix="crop-reprocess",
			)
			_record_generation_failure(reason, time.perf_counter() - baslangic)
			_finish_job(job_name, "failed", error_code=reason)
			frappe.db.commit()
			return
		master_bytes = prepared.content
		active_engine = (
			frappe.db.get_value("Media Version", asset.active_version, "engine_version")
			if asset.active_version
			else None
		)
		if active_engine and str(active_engine) != _engine_version():
			# Eski motorun pikselleri yeni normalize master sürümüne taşınamaz;
			# crop niyeti yalnız bazı profilleri değiştirse bile tüm eager matris
			# yeniden üretilmelidir.
			etkilenen = tuple(
				dict.fromkeys(str(profile.policy_profile) for profile in _profiles_for_slot(slot_key))
			)
		else:
			etkilenen = _affected_crop_profiles(master_bytes, asset, slot_key, intent)
		surum = _ensure_version(asset, slot_key, kaynak, crop_intent=intent, prepared=prepared)
		job_name = _open_job(asset.name, surum.version_hash, slot_key, key_prefix="crop-reprocess")
		frappe.db.savepoint("image_crop_reprocess")
		devredildi = _carry_forward_renditions(
			asset.name,
			surum.version_hash,
			excluded_profiles=etkilenen,
		)
		sonuc = _generate(
			master_bytes,
			asset,
			slot_key,
			surum.version_hash,
			crop_intent=intent,
			generation="eager",
			profile_names=etkilenen,
			classification=prepared.classification,
		)

		if sonuc.complete and devredildi:
			frappe.db.set_value("Media Asset", asset.name, "state", "ready")
			_record_generation_report(
				kaynak,
				asset,
				surum.version_hash,
				sonuc,
				crop_intent=intent,
				trigger="crop_reprocess",
				rendering_source=master_bytes,
				normalized=prepared.normalized,
				classification=prepared.classification,
			)
			_finish_job(job_name, "success")
			_promote_complete_version(asset.name, surum.version_hash)
		else:
			frappe.db.rollback(save_point="image_crop_reprocess")
			# Yeni türev yazılamadı; ESKİ kadrajlı satırlar/aktif sürüm transaction
			# rollback'iyle bütünüyle yerinde kalır.
			_record_generation_failure(
				"incomplete_crop_matrix",
				time.perf_counter() - baslangic,
			)
			_finish_job(job_name, "failed", error_code="incomplete_rendition_matrix")
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		frappe.db.rollback()
		_record_generation_failure(type(exc).__name__, time.perf_counter() - baslangic)
		if job_name:
			_finish_job(job_name, "failed", error_code=type(exc).__name__)
			frappe.db.commit()
		frappe.log_error(
			title="media.pipeline_bridge crop reprocess failed",
			message=f"{asset_name}\n\n{frappe.get_traceback()}",
		)


def _run_video_crop_reprocess_job(asset: Any, intent: Any) -> None:
	"""Video poster merdivenini kayıtlı crop intent ile yeni sürüme geçir.

	Video bytes ve HLS de aynı içerik-adresli sürüm köküne yeniden hazırlanır;
	poster profilleri görsel motorundan crop intent ile geçer. Tüm satırlar
	hazır olmadan ``active_version`` değişmez.
	"""
	job_name: str | None = None
	savepoint_open = False
	try:
		if not asset.source_file or not frappe.db.exists("File", asset.source_file):
			return
		source_doc = frappe.get_doc("File", asset.source_file)
		src_yolu = _media_disk_path(str(source_doc.file_url or ""))
		if not os.path.isfile(src_yolu):
			return

		from tradehub_core.media.pipeline.core import dedup
		from tradehub_core.media.pipeline.video import probe as video_probe
		from tradehub_core.media.pipeline.video import validation as video_validation

		facts = video_probe.probe(src_yolu)
		dogrulama = video_validation.validate(asset.slot_key, facts)
		karar = dogrulama.processing
		if dogrulama.rejected:
			raise ValueError(dogrulama.code or "video_rejected")
		with open(src_yolu, "rb") as f:
			source_hash = dedup.stream_sha256(f).sha256
		politika = _video_policy_snapshot(asset.slot_key)
		surum_hash = dedup.version_hash(
			source_hash,
			politika,
			intent,
			_video_engine_version(),
		)
		if str(asset.active_version or "") == surum_hash and _video_poster_matrix_exists(
			asset.name,
			surum_hash,
			asset.slot_key,
		):
			return

		job_name = _open_job(
			asset.name,
			surum_hash,
			asset.slot_key,
			job_type="poster",
			queue=JOB_QUEUE_VIDEO,
			key_prefix="video-crop-reprocess",
		)
		frappe.db.savepoint("video_crop_reprocess")
		savepoint_open = True
		uretildi = _produce_video_outputs(
			src_yolu,
			facts,
			karar,
			asset,
			asset.slot_key,
			crop_intent=intent,
		)
		if not _video_poster_matrix_exists(asset.name, uretildi, asset.slot_key):
			raise ValueError("video_poster_crop_matrix_incomplete")
		frappe.db.set_value("Media Asset", asset.name, "state", "ready")
		_finish_job(job_name, "success")
		_promote_complete_version(asset.name, uretildi)
		frappe.db.commit()
	except Exception as exc:
		if savepoint_open:
			frappe.db.rollback(save_point="video_crop_reprocess")
		else:
			frappe.db.rollback()
		if job_name:
			_finish_job(job_name, "failed", error_code=type(exc).__name__)
			frappe.db.commit()
		raise


def _video_poster_matrix_exists(asset_name: str, version_hash: str, slot_key: str) -> bool:
	"""Crop niyetinin gerçekten en az bir teslim posterine uygulandığını kanıtla.

	Ham ``poster`` karesi crop niyetinden geçmez; yalnız görsel merdivenindeki
	politika profilleri geçer. Bu nedenle salt ham poster satırı yeni sürümü
	promote etmek için yeterli değildir. No-upscale nedeniyle büyük basamaklar
	omit edilebildiğinden bütün profiller yerine en az bir teslim basamağı aranır.
	"""
	if not frappe.db.exists(
		"Media Rendition",
		{"asset": asset_name, "version_hash": version_hash, "profile": VIDEO_POSTER_PROFILE},
	):
		return False
	poster_profiles = tuple(
		dict.fromkeys(str(profile.policy_profile) for profile in _profiles_for_slot(slot_key))
	)
	if not poster_profiles:
		return False
	return bool(
		frappe.get_all(
			"Media Rendition",
			filters={
				"asset": asset_name,
				"version_hash": version_hash,
				"profile": ["in", poster_profiles],
			},
			pluck="name",
			limit=1,
		)
	)


def _version_crop_intent(version_hash: str) -> Any:
	ham = frappe.db.get_value("Media Version", version_hash, "crop_intent_snapshot")
	if not ham:
		return None
	try:
		return frappe.parse_json(ham)
	except Exception:
		return json.loads(ham)


def _format_plan(profil: Any, classification: Any = None) -> tuple[tuple[str, Any], ...]:
	"""Profil biçimlerini T-062 sınıf zinciri ve kalite kipiyle birleştir.

	Profil hangi genişliklerde hangi modern formatların sunulacağını belirler;
	sınıflandırıcı ise bunların kayıplı/kayıpsız kodlanacağını ve güvenli geri
	dönüş sırasını belirler. Zincirle profil kesişmiyorsa (ör. ortamda yalnız PNG
	kodlayıcı kaldıysa) sınıflandırıcının ilk güvenli adımı kullanılır.
	"""
	if classification is None:
		return tuple(
			(
				str(fmt).lower(),
				int(profil.quality_target) if profil.quality_target not in (None, "") else None,
			)
			for fmt in profil.get_formats()
		)
	chain = tuple(getattr(classification, "chain", ()) or ())
	if not chain:
		return ()
	configured = {str(fmt).lower() for fmt in profil.get_formats()}
	selected = [step for step in chain if str(step.fmt).lower() in configured]
	if not selected:
		selected = [chain[0]]
	return tuple((str(step.fmt).lower(), step.quality_target) for step in selected)


def _missing_lazy_profiles(
	asset: Any,
	version_hash: str,
	kaynak: bytes,
	requested_profiles: Iterable[str] | None = None,
	*,
	classification: Any = None,
) -> tuple[str, ...]:
	"""DB/disk pozitif cache + omission marker üzerinden eksik lazy profiller."""
	from tradehub_core.media.pipeline.image import render

	istenen = None if requested_profiles is None else {str(p) for p in requested_profiles}
	profiller = [
		p
		for p in _profiles_for_slot(asset.slot_key)
		if str(p.generation or "eager") == "lazy" and (istenen is None or str(p.policy_profile) in istenen)
	]
	if not profiller:
		return ()
	hazir, _icc, _notlar = render.prepare_source(kaynak)
	intent = _version_crop_intent(version_hash)
	mevcut: set[tuple[str, int, str]] = set()
	for row in frappe.get_all(
		"Media Rendition",
		filters={"asset": asset.name, "version_hash": version_hash, "generation": "lazy"},
		fields=["profile", "width", "format", "file_url"],
		limit_page_length=0,
	):
		url = row.get("file_url") or ""
		if os.path.isfile(_media_disk_path(url)):
			mevcut.add(
				(str(row.get("profile") or ""), int(row.get("width") or 0), str(row.get("format") or ""))
			)

	eksik: list[str] = []
	for profil in profiller:
		for genislik in profil.get_widths():
			for bicim, quality_target in _format_plan(profil, classification):
				anahtar = (str(profil.policy_profile), int(genislik), str(bicim))
				spec = render.RenditionProfile(
					slot_key=asset.slot_key,
					name=str(profil.policy_profile),
					width=int(genislik),
					formats=(str(bicim),),
					fit=profil.fit or render.FIT_CONTAIN,
					target_ratio=profil.aspect_ratio or "",
					encoder_quality=(((str(bicim), quality_target),) if quality_target is not None else ()),
				)
				if not render.profile_is_eligible(hazir.size, spec, intent):
					continue
				if anahtar in mevcut or _rendition_was_omitted(
					asset.name,
					version_hash,
					anahtar[0],
					anahtar[1],
					anahtar[2],
				):
					continue
				eksik.append(str(profil.policy_profile))
	return tuple(dict.fromkeys(eksik))


def ensure_lazy_renditions(
	asset_name: str,
	requested_profiles: Iterable[str] | None = None,
	*,
	blocking_timeout: int = LAZY_LOCK_WAIT_SECONDS,
) -> dict[str, Any]:
	"""İlk teslim isteğinde lazy türevleri senkron, persistent ve singleflight üret.

	Manifest katmanı bu fonksiyonu varlığı okumadan hemen önce çağırabilir.
	İlk çağıran Redis distributed lock altında üretir; takipçiler kilidi bekler,
	sonra DB/disk cache'i yeniden okuyup encode etmeden döner.
	"""
	if not frappe.db.exists("Media Asset", asset_name):
		return {"status": "missing_asset", "generated": 0}
	asset = frappe.get_doc("Media Asset", asset_name)
	if not pipeline_flags.is_enabled("rendition_on_upload") or not pipeline_flags.is_slot_enabled(
		str(asset.slot_key or "")
	):
		return {"status": "disabled", "generated": 0}
	if not pipeline_flags.is_store_enabled(asset.owner_seller):
		return {"status": "rollout_disabled", "generated": 0}
	if asset.media_type != _MEDIA_TYPE_IMAGE or asset.state != "ready":
		return {"status": "not_ready", "generated": 0}
	version_hash = asset.active_version or frappe.db.get_value(
		"Media Version", {"asset": asset.name, "is_active": 1}, "name"
	)
	if not version_hash or not asset.source_file or not frappe.db.exists("File", asset.source_file):
		return {"status": "not_ready", "generated": 0}
	source_doc = frappe.get_doc("File", asset.source_file)
	# Görsel köprüsü bugün public türev köküne yazar. Özel kaynağı bu yola
	# sokmak, signed-url isteği sırasında içeriği public'e kopyalamak olurdu.
	if int(source_doc.is_private or 0):
		return {"status": "private_source", "generated": 0}
	kaynak = source_doc.get_content()
	if isinstance(kaynak, str):
		kaynak = kaynak.encode()
	if not kaynak:
		return {"status": "missing_source", "generated": 0}
	version_engine = frappe.db.get_value("Media Version", version_hash, "engine_version")
	if isinstance(version_engine, str) and version_engine and version_engine != _engine_version():
		# Eski motor sürümünün immutable version_hash kökü altına yeni motor
		# pikseli yazılamaz. Politika reprocess yeni sürümü kurmalıdır.
		return {"status": "stale_version", "generated": 0, "version": version_hash}
	prepared = _prepare_image_master(
		kaynak,
		asset.slot_key,
		filename=str(source_doc.file_name or ""),
	)
	if not prepared.ok:
		reason = str(prepared.reason or "normalize_failed")
		_record_generation_failure(reason, 0.0)
		return {
			"status": "failed",
			"generated": 0,
			"version": version_hash,
			"reason": reason,
		}
	master_bytes = prepared.content

	eksik = _missing_lazy_profiles(
		asset,
		version_hash,
		master_bytes,
		requested_profiles,
		classification=prepared.classification,
	)
	if not eksik:
		return {"status": "cached", "generated": 0, "version": version_hash}

	try:
		lock = frappe.cache.lock(
			f"media:lazy:{asset.name}:{version_hash}",
			timeout=LAZY_LOCK_TIMEOUT_SECONDS,
			blocking=True,
			blocking_timeout=max(0, int(blocking_timeout)),
		)
		if not lock.acquire():
			return {"status": "pending", "generated": 0, "version": version_hash}
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge lazy lock failed",
			message=f"{asset.name} / {version_hash}\n\n{frappe.get_traceback()}",
		)
		return {"status": "lock_unavailable", "generated": 0, "version": version_hash}

	try:
		eksik = _missing_lazy_profiles(
			asset,
			version_hash,
			master_bytes,
			requested_profiles,
			classification=prepared.classification,
		)
		if not eksik:
			return {"status": "cached", "generated": 0, "version": version_hash}
		frappe.db.savepoint("image_lazy_generation")
		baslangic = time.perf_counter()
		intent = _version_crop_intent(version_hash)
		try:
			sonuc = _generate(
				master_bytes,
				asset,
				asset.slot_key,
				version_hash,
				crop_intent=intent,
				generation="lazy",
				profile_names=eksik,
				classification=prepared.classification,
			)
		except Exception as exc:
			frappe.db.rollback(save_point="image_lazy_generation")
			_record_generation_failure(type(exc).__name__, time.perf_counter() - baslangic)
			frappe.log_error(
				title="media.pipeline_bridge lazy generation failed",
				message=f"{asset.name} / {version_hash}\n\n{frappe.get_traceback()}",
			)
			return {
				"status": "failed",
				"generated": 0,
				"version": version_hash,
				"failures": 1,
			}
		if not sonuc.complete:
			frappe.db.rollback(save_point="image_lazy_generation")
			_record_generation_failure(
				"incomplete_lazy_matrix",
				time.perf_counter() - baslangic,
			)
			return {
				"status": "failed",
				"generated": 0,
				"version": version_hash,
				"failures": sonuc.failed,
			}
		_record_generation_report(
			kaynak,
			asset,
			version_hash,
			sonuc,
			crop_intent=intent,
			trigger="lazy_first_request",
			rendering_source=master_bytes,
			normalized=prepared.normalized,
			classification=prepared.classification,
		)
		frappe.db.commit()
		return {
			"status": "generated",
			"generated": sonuc.ready,
			"omitted": sonuc.omitted,
			"version": version_hash,
		}
	finally:
		try:
			lock.release()
		except Exception:
			pass


def _ensure_asset(doc: Any, slot_key: str, surum_hash: str, media_type: str = _MEDIA_TYPE_IMAGE) -> Any:
	"""Bu (satıcı, slot, içerik) üçlüsü için Media Asset'i bulur ya da açar."""
	owner_seller = ownership.store_of(doc.get("owner"))
	# Sistem işi — worker'ın oturumu yok; satıcı izolasyonu kaydın kendi
	# `owner_seller` kolonunda taşınıyor (bkz. permissions.media_asset_*).
	filtreler: dict[str, Any] = {"content_sha256": surum_hash, "slot_key": slot_key}
	# Sahipsiz (platform/yönetim) yükleme: kolon NULL ya da boş metin olabilir;
	# ikisini de aynı kayıt saymazsak her işte yeni bir Asset açılırdı.
	filtreler["owner_seller"] = owner_seller if owner_seller else ["in", ["", None]]
	mevcut = frappe.get_all("Media Asset", filters=filtreler, limit=1, pluck="name")
	if mevcut:
		asset = frappe.get_doc("Media Asset", mevcut[0])
		asset.state = "processing"
		asset.save(ignore_permissions=True)
		return asset

	asset = frappe.get_doc(
		{
			"doctype": "Media Asset",
			"slot_key": slot_key,
			"media_type": media_type,
			"state": "processing",
			"owner_seller": owner_seller,
			"source_file": doc.name,
			"content_sha256": surum_hash,
		}
	)
	asset.insert(ignore_permissions=True)
	return asset


def _engine_version() -> str:
	"""Normalize master + rendition motorunun sürüm kimliği.

	Sınıflandırma/normalize sözleşmesi de türev pikselini değiştirdiği için
	yalnız Pillow sürümünü taşımak yeterli değildir. Master motoru değişince bu
	değer, dolayısıyla TÜM version_hash'ler ve türev adresleri zorunlu değişir
	(INV-09).
	"""
	import PIL  # noqa: PLC0415 — Pillow yalnız worker yolunda gerekiyor

	from tradehub_core.media.pipeline.image import master as master_mod
	from tradehub_core.media.pipeline.image import render as render_mod

	return (
		f"pillow-{PIL.__version__}+master-{master_mod.MASTER_ENGINE_VERSION}"
		f"+render-{render_mod.ENGINE_VERSION}"
	)


def _prepared_version_fields(prepared: Any) -> dict[str, Any]:
	"""Normalize master'ın gerçek künyesini ``Media Version`` alanlarına çevir.

	LQIP/baskın renk master baytından çıkarılır. Alanlar insert payload'ında
	hazır olduğu için controller kaynak dosyayı yeniden zenginleştirmez; böylece
	Version künyesi ile rendition girdisi aynı normalize master'ı anlatır.
	"""
	if not prepared or not prepared.ok or not prepared.normalized:
		return {}
	normalized = prepared.normalized
	classification = prepared.classification
	fields: dict[str, Any] = {
		"width": int(normalized.width or 0),
		"height": int(normalized.height or 0),
		"dpi": int(round(float(normalized.dpi[0]))) if normalized.dpi else 0,
		"colorspace": str(normalized.colorspace or "sRGB")[:32],
		"has_alpha": 1 if normalized.has_alpha else 0,
		"classification": str(classification.klass or ""),
		"classification_confidence": str(classification.confidence or "")[:8],
		"format_chain": frappe.as_json([step.to_dict() for step in classification.chain]),
	}
	try:
		from tradehub_core.media.pipeline.image import enrich as enrich_mod

		enrichment = enrich_mod.enrich(prepared.content)
		if enrichment.ok:
			fields.update(
				{
					"lqip": enrichment.lqip,
					"lqip_data_uri": enrichment.lqip_data_uri,
					"dominant_color": enrichment.dominant_color,
				}
			)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge normalized master enrichment failed",
			message=frappe.get_traceback(),
		)
	return fields


def _ensure_version(
	asset: Any,
	slot_key: str,
	kaynak: bytes,
	crop_intent: Any = None,
	*,
	prepared: Any = None,
) -> Any:
	"""Bu üretimin `Media Version` kaydını bulur ya da açar (T-042).

	Hash HESAPLANMAZ, kütüphaneye DEVREDİLİR: `dedup.version_hash(source_hash,
	policy_snapshot, crop_intent, engine_version)`. Girdiler kayda AYNEN yazılır
	ki hash sonradan yeniden hesaplanıp doğrulanabilsin.

	`source_hash` içeriğin TAM 64 haneli SHA-256'sıdır (`dedup.stream_sha256`);
	`Media Asset.content_sha256`'daki 32 haneli kısaltma DEĞİL — kısaltma
	`_require_hex`'ten geçemez ve iki kimliğin karışması tam da bu görevin
	kapattığı açıktı.

	Kırpma niyeti (W9+): yükleme yolunda `None` gelir; kırpma-yeniden-üretim
	yolunda (`_run_crop_reprocess_job`) `Media Crop Intent` belgesi gelir ve
	hash'e girer — "niyet yok" ile "boş niyet" farklı hash alır
	(`dedup.normalize_crop_intent`).

	Yarış: `version_hash` UNIQUE + autoname. İki worker aynı anda gelirse
	`dedup.idempotent_create` kazananın kaydını döndürür (INV-06).
	"""
	from tradehub_core.media.pipeline.core import dedup
	from tradehub_core.media.pipeline.image import render

	source_hash = dedup.stream_sha256(kaynak).sha256
	politika = render.load_slot_policy(slot_key)
	motor = _engine_version()
	surum_hash = dedup.version_hash(source_hash, politika, crop_intent, motor)
	# Eski varlığın kimliği korunur. Yeni varlık kendi sürümünü alır: aynı
	# fotoğraf iki mağazada varsa global hash ilk mağazanın sürümünü döndürüp
	# ikincisinin promote adımını reddediyordu.
	legacy_asset = frappe.db.get_value("Media Version", surum_hash, "asset")
	if legacy_asset != asset.name:
		surum_hash = dedup.version_hash(source_hash, politika, crop_intent, motor, asset_key=asset.name)
	version_fields = _prepared_version_fields(prepared)

	def _bul(anahtar: str) -> Any:
		ad = frappe.db.get_value("Media Version", {"version_hash": anahtar}, "name")
		return frappe.get_doc("Media Version", ad) if ad else None

	def _olustur() -> Any:
		doc = frappe.get_doc(
			{
				"doctype": "Media Version",
				"asset": asset.name,
				"version_hash": surum_hash,
				"source_hash": source_hash,
				"policy_snapshot": frappe.as_json(politika),
				"crop_intent_snapshot": (
					frappe.as_json(dedup.normalize_crop_intent(crop_intent))
					if crop_intent is not None
					else None
				),
				"engine_version": motor,
				"created_at": now_datetime(),
				# `is_active` 0 kalır: "hangi sürüm yayında" bir MODERASYON
				# kararıdır (bkz. media_version.json sapma 2), üretim değil.
				"is_active": 0,
				**version_fields,
			}
		)
		if prepared is not None:
			# Enrichment zaten normalize master'dan hesaplandı. Nadir bir LQIP
			# hatasında controller'ın orijinal kaynağı okuyup sınıf/master
			# künyesini farklı bayttan doldurmasına izin verme.
			doc.flags.skip_source_enrichment = True
		# Sistem işi: worker oturumsuz; `asset` permlevel-1 alanı ancak böyle yazılır.
		doc.insert(ignore_permissions=True)
		return doc

	def _catisma(exc: BaseException) -> bool:
		# Aynı ad (autoname=field:version_hash) → DuplicateEntryError;
		# unique kolon ihlali → UniqueValidationError. İkisi de aynı yarış.
		return isinstance(exc, frappe.DuplicateEntryError | frappe.UniqueValidationError)

	kayit, _yeni = dedup.idempotent_create(surum_hash, _olustur, _bul, _catisma)
	return kayit


def _promote_initial_version(asset_name: str, version_hash: str) -> None:
	"""İlk `ready` geçişinde üretilen sürümü yayına al — YALNIZ ilk yayında.

	`_ensure_version`/`_ensure_video_version` sürümü `is_active=0` ile açar:
	"hangi sürüm yayında" bir MODERASYON kararıdır (media_version.json sapma 2),
	üretim değil. Ama İLK yayında moderasyon yoktur — üretilen tek sürüm yayına
	alınmazsa varlık `ready` olur ama `active_version` boş kalır ve okuma yolu
	`is_active/creation` fallback'ine düşerek "en yeniyi" gösterir (tam da bu
	görevin kapattığı maskeleme).

	Bu yüzden geçiş YALNIZ `active_version` boşken yapılır: yeniden işleme
	(reprocess) senaryosunda `active_version` zaten doludur ve hangi yeni sürümün
	yayına alınacağı yine moderasyona bırakılır — bu kanca ona DOKUNMAZ. Böylece
	mevcut mantık bozulmaz, yalnız "hiç yazılmıyordu" boşluğu kapanır.

	commit=False: köprü job'ın sonunda kendi `frappe.db.commit()`'ini atar;
	geçiş o commit ile aynı transaction'da kalıcı olur.
	"""
	if frappe.db.get_value("Media Asset", asset_name, "active_version"):
		return
	from tradehub_core.tradehub_core.doctype.media_version.media_version import promote_version

	promote_version(asset_name, version_hash, commit=False)


def _promote_complete_version(asset_name: str, version_hash: str) -> None:
	"""Tam üretilmiş yeniden-işleme sürümünü, eskisi varken de atomik geçir.

	Çağıran tüm zorunlu çıktıların dosyalarını yazmış ve rendition satırlarını
	ayni transaction içinde hazırlamış olmalıdır. `promote_version` üç aktiflik
	yazısını commit etmez; satır geçişiyle tek committe görünür olur.
	"""
	from tradehub_core.tradehub_core.doctype.media_version.media_version import promote_version

	promote_version(asset_name, version_hash, commit=False)


def _open_job(
	asset_name: str,
	surum_hash: str,
	slot_key: str,
	*,
	job_type: str = JOB_TYPE,
	queue: str = JOB_QUEUE,
	key_prefix: str | None = None,
) -> str:
	"""İş kaydını açar (ya da aynı anahtarlı kaydı yeniden kullanır).

	Varsayılanlar görsel hattınınki — W7 video hattı `job_type/queue/key_prefix`
	verir; anahtar öneki `job_type`tan AYRI, çünkü video işi `transcode` tipini
	taşıyor ama görseldeki `rendition:` anahtarlarıyla çakışmamalı.
	"""
	anahtar = f"{key_prefix or job_type}:{surum_hash}:{slot_key}"
	mevcut = frappe.db.get_value("Media Processing Job", {"idempotency_key": anahtar}, "name")
	if mevcut:
		job = frappe.get_doc("Media Processing Job", mevcut)
		# F-33c — kaydın varlığı silinmişse (kanca yokken oluşmuş yığın) bağı
		# yeni varlığa çevir; aksi hâlde `save` bağ doğrulamasında düşer ve
		# aynı içerik bir daha hiç işlenemez.
		if job.asset != asset_name and not frappe.db.exists("Media Asset", job.asset):
			job.asset = asset_name
		# Tavan aşılırsa controller `validate` içinde reddeder; sayaç tavanda durur.
		job.attempt = min(int(job.attempt or 0) + 1, job.max_attempts())
		job.status = "running"
		job.started_at = now_datetime()
		job.finished_at = None
		job.error_code = None
		job.save(ignore_permissions=True)
		return job.name

	job = frappe.get_doc(
		{
			"doctype": "Media Processing Job",
			"asset": asset_name,
			"job_type": job_type,
			"queue": queue,
			"status": "running",
			"attempt": 1,
			"idempotency_key": anahtar,
			"started_at": now_datetime(),
		}
	)
	job.insert(ignore_permissions=True)
	return job.name


def _finish_job(job_name: str, status: str, error_code: str | None = None) -> None:
	"""İşi kapatır. Kapatma hatası asıl işi gölgelememeli — yalnız loglanır."""
	try:
		job = frappe.get_doc("Media Processing Job", job_name)
		job.status = status
		job.finished_at = now_datetime()
		if error_code:
			# Controller: başarısız iş hata kodu olmadan kapatılamaz.
			job.error_code = error_code[:140]
		job.save(ignore_permissions=True)
		# T-092: olay yalnız bir GEÇERSİZLEŞTİRME sinyalidir; asset/dosya/store
		# kimliği yayınlanmaz. İstemci sinyal gelince kendi yetki-süzgeçli liste
		# ucunu yeniden okur. `after_commit` yarım transaction durumunu göstermez.
		frappe.publish_realtime(
			"media_processing_status",
			{"doctype": "Media Processing Job", "status": status},
			after_commit=True,
		)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge iş kaydı kapatılamadı",
			message=f"{job_name} → {status}\n\n{frappe.get_traceback()}",
		)


def _report_results_for_version(
	kaynak: bytes,
	asset: Any,
	version_hash: str,
	crop_intent: Any,
	new_results: Iterable[Any],
) -> list[Any]:
	"""Yayınlanacak sürümün TÜM çıktılarını kalite raporu sonuçlarına çevir.

	Yeni encode sonuçları tam künyeleriyle korunur. Crop carry-forward, disk
	cache-hit ve lazy genişletme yollarında encode edilmeyen mevcut dosyalar ise
	DB'deki ölçülmüş kalite/bayt değerleriyle temsil edilir; böylece raporun
	`output_bytes` alanı yalnız bu koşuda encode edilenleri değil sürümün bütün
	rendition toplamını taşır.
	"""
	from tradehub_core.media.pipeline.image import render

	yeni = {(r.profile.name, int(r.width), str(r.format).lower()): r for r in new_results}
	profiller = _profile_specs(render, asset, _profiles_for_slot(asset.slot_key))
	spec_gore = {(p.name, int(p.width)): p for p in profiller}
	hazir = render.prepare_source(kaynak)[0]
	sinif = next((str(r.content_class) for r in yeni.values() if r.content_class), "")
	if not sinif:
		sinif = str(frappe.db.get_value("Media Version", version_hash, "classification") or "")
	if not sinif:
		try:
			from tradehub_core.media.pipeline.quality import ssim as ssim_mod

			sinif = ssim_mod.guess_content_class(hazir)
		except Exception:
			sinif = "photo"
	try:
		hedef = render.resolve_target_ssim(asset.slot_key, sinif)
	except Exception:
		hedef = 0.0

	satirlar = frappe.get_all(
		"Media Rendition",
		filters={"asset": asset.name, "version_hash": version_hash},
		fields=["profile", "width", "height", "format", "file_url", "quality", "ssim"],
		order_by="width asc, format asc",
		limit_page_length=0,
	)
	cikti: list[Any] = []
	for row in satirlar:
		url = str(row.get("file_url") or "")
		anahtar = (
			str(row.get("profile") or ""),
			int(row.get("width") or 0),
			str(row.get("format") or "").lower(),
		)
		if anahtar in yeni:
			cikti.append(yeni[anahtar])
			continue
		try:
			with open(_media_disk_path(url), "rb") as handle:
				content = handle.read()
		except OSError:
			continue
		spec = spec_gore.get(anahtar[:2]) or render.RenditionProfile(
			slot_key=asset.slot_key,
			name=anahtar[0],
			width=anahtar[1],
			formats=(anahtar[2],),
		)
		try:
			geometri = render.plan_geometry(hazir.size, spec, crop_intent)
		except Exception:
			boyut = (int(row.get("width") or 0), int(row.get("height") or 0))
			geometri = render.GeometryPlan(
				source_size=(int(hazir.width), int(hazir.height)),
				crop_box=(0, 0, int(hazir.width), int(hazir.height)),
				inner_size=boyut,
				canvas_size=boyut,
				paste_at=(0, 0),
				scale=1.0,
				upscale_blocked=False,
				crop_method="persistent",
				padded=False,
			)
		quality = row.get("quality")
		cikti.append(
			render.RenditionResult(
				slot_key=asset.slot_key,
				profile=spec,
				format=anahtar[2],
				content=content,
				width=anahtar[1],
				height=int(row.get("height") or 0),
				quality=int(quality) if quality not in (None, "") else None,
				ssim=float(row.get("ssim") or 0.0),
				ssim_target=float(hedef or 0.0),
				content_class=sinif,
				geometry=geometri,
				encodes=0,
				elapsed_ms=0.0,
				source_bytes=len(kaynak),
				notes=("persistent_rendition",),
				ssim_backend="stored",
			)
		)
	return cikti


def _record_generation_report(
	kaynak: bytes,
	asset: Any,
	version_hash: str,
	sonuc: GenerationOutcome,
	*,
	crop_intent: Any = None,
	trigger: str = "upload",
	rendering_source: bytes | None = None,
	normalized: Any = None,
	classification: Any = None,
) -> None:
	"""Başarılı üretimi kalıcı kalite raporu + Prometheus'a best-effort bağla."""
	try:
		from tradehub_core.media.pipeline.image import report

		render_source = rendering_source or kaynak
		raporda = _report_results_for_version(
			render_source,
			asset,
			version_hash,
			crop_intent,
			sonuc.results,
		)
		rapor = report.build_report(
			kaynak,
			raporda,
			slot_key=asset.slot_key,
			asset_id=asset.name,
			version_id=version_hash,
			extra={
				"trigger": trigger,
				"normalized": normalized,
				"classification": (
					classification.to_dict()
					if classification is not None and hasattr(classification, "to_dict")
					else classification
				),
				"generation": {
					"required": sonuc.required,
					"ready": sonuc.ready,
					"omitted": sonuc.omitted,
					"entries": dict(sonuc.entries),
				},
			},
		)
		if _quality_report_table_ready():
			report.persist_report(rapor)
		report.record_report_metrics(rapor)
	except Exception:
		# Telemetri ana üretimin başarı/atomiklik kararını değiştiremez. Hata
		# görünürdür ama türev transaction'ı yürümeye devam eder.
		frappe.log_error(
			title="media.pipeline_bridge quality report failed",
			message=f"{asset.name} / {version_hash}\n\n{frappe.get_traceback()}",
		)


def _quality_report_table_ready() -> bool:
	"""Patch/migrate tamamlanmamış düğümde ana üretimi rapor tablosuna bağlama."""
	return bool(
		frappe.db.exists("DocType", "Media Quality Report") and frappe.db.table_exists("Media Quality Report")
	)


def _record_generation_failure(reason: str, duration_s: float) -> None:
	"""Rapor üretilemeyen işin düşük kardinaliteli hata metriğini best-effort yaz."""
	try:
		from tradehub_core.media.pipeline.image import report

		report.record_job_failure(reason=reason, duration_s=max(0.0, duration_s))
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge quality failure metric failed",
			message=f"{reason}\n\n{frappe.get_traceback()}",
		)


def _generate(
	kaynak: bytes,
	asset: Any,
	slot_key: str,
	surum_hash: str,
	crop_intent: Any = None,
	*,
	generation: str | None = None,
	profile_names: Iterable[str] | None = None,
	classification: Any = None,
) -> GenerationOutcome:
	"""Profil matrisini üretir ve atomik yayın için tamlık künyesi döner.

	`surum_hash`: `Media Version.version_hash` (64 hex) — türev adresleri bunu
	taşır (INV-09). İçerik `_run_rendition_job`'da BİR kez okunur ve buraya
	bayt olarak gelir; sürüm hash'i için ikinci bir okuma yapılmaz.
	"""
	from tradehub_core.media.pipeline.image import render

	tum_profiller = _profiles_for_slot(slot_key)
	profiller = [p for p in tum_profiller if generation is None or str(p.generation or "eager") == generation]
	if profile_names is not None:
		adlar = {str(name) for name in profile_names}
		profiller = [p for p in profiller if str(p.policy_profile) in adlar]
	sonuc = GenerationOutcome()
	if not profiller:
		# Kayıtları `patches/v15_9_23_media_profile_seed.py` politika
		# dosyalarından tohumluyor. Burası boşsa ya patch koşmamıştır ya da
		# operatör slotun tüm profillerini kapatmıştır — ikisi de sessiz
		# kalmamalı, çünkü dışarıdan "hat çalışıyor ama türev yok" görünür.
		if not tum_profiller and profile_names is None:
			frappe.log_error(
				title="media.pipeline_bridge profil yok",
				message=f"{slot_key} için etkin Media Profile kaydı bulunamadı.",
			)
			sonuc.add(GEN_FAILED, "no_enabled_profile")
		return sonuc

	tavan = pipeline_flags.max_renditions_per_asset()
	uretilenler: set[tuple[str, int, str]] = set()
	format_plans = {profil.name: _format_plan(profil, classification) for profil in profiller}
	if profiller and not any(format_plans.values()):
		sonuc.add(GEN_FAILED, "no_supported_format_chain")
		return sonuc
	matris_boyutu = sum(len(profil.get_widths()) * len(format_plans[profil.name]) for profil in profiller)
	# AVIF tek biçim olduğundan aynı büyük matris artık 17 basamaktır.
	hizli_kalite = matris_boyutu >= 17

	# Kaynak bir kez hazırlanır: eligibility, disk atlama ve bütün formatların
	# render çağrısı aynı EXIF/crop uzayını paylaşır.
	try:
		hazir, icc, hazirlik_notlari = render.prepare_source(kaynak)
		kaynak_boyut: tuple[int, int] = (int(hazir.width), int(hazir.height))
	except Exception:
		sonuc.add(GEN_FAILED, "source_prepare_failed")
		return sonuc
	hazirlanmis = (hazir, icc, hazirlik_notlari)
	tuval_onbellegi: dict[tuple, tuple] = {}

	# T-064/W8 — mevcut-türev atlama ön koşulu. Türev adresleri deterministik
	# (INV-09: aynı version_hash → aynı adres → aynı bayt); sürüm dizini diskte
	# DURUYORSA bu üretim daha önce koşmuş demektir ve `_render_one` her basamağı
	# encode'suz doğrulayıp atlayabilir. Beklenen çıktı genişliğini hesaplamak
	# için kaynağın HAZIRLANMIŞ (EXIF döndürülmüş) boyutu gerekir — bir kez
	# burada çözülür, dizin diskte yoksa hiç çözülmez (sıcak yol bedava kalır).
	# ÖLÇÜLDÜ (bu depo, 1200px JPEG, product.image): DB satırları silinip disk
	# dosyaları dururken ikinci koşum 48 encode yapıyordu — W6-B'nin videoda
	# bulduğu "yol-determinizmi var ama her koşum yeniden kodluyor" açığının
	# görüntü karşılığı. Bu kontrol o 48'i 0'a indirir.
	surum_kok = os.path.join(get_files_path(is_private=0), "media", asset.name, surum_hash)
	disk_kontrolu = os.path.isdir(surum_kok)

	for profil in profiller:
		for genislik in profil.get_widths():
			for bicim, quality_target in format_plans[profil.name]:
				if sonuc.required >= tavan:
					# Tavan bir güvenlik freni: bozuk bir profil kaydı tek
					# görselden yüzlerce dosya üretmesin. Ancak bu eksik matris
					# yayına alınamaz; sessiz kısmi başarı değildir.
					sonuc.add(GEN_FAILED, "rendition_limit")
					continue
				durum = _render_one(
					render,
					kaynak,
					asset,
					surum_hash,
					profil,
					genislik,
					bicim,
					uretilenler,
					kaynak_boyut if disk_kontrolu else None,
					crop_intent,
					prepared=hazirlanmis,
					canvas_cache=tuval_onbellegi,
					result_sink=sonuc.results,
					fast_quality=hizli_kalite,
					quality_target=quality_target,
					content_class=(
						str(getattr(classification, "klass", "") or "")
						if classification is not None
						else None
					),
				)
				detay = f"{profil.policy_profile}/{genislik}/{bicim}"
				sonuc.add(durum, detay)
				if durum == GEN_OMITTED:
					_mark_rendition_omitted(
						asset.name,
						surum_hash,
						str(profil.policy_profile),
						int(genislik),
						str(bicim),
					)
	# En küçük basamaktan da küçük kaynak boş kalmasın. Yalnız ilk eager
	# üretimde, büyütmeden tek AVIF üret; diğer basamaklar omitted kalır.
	if generation == "eager" and sonuc.ready == 0 and sonuc.failed == 0 and crop_intent is None:
		profil = min(profiller, key=lambda p: min(p.get_widths()))
		native_width = min(kaynak_boyut)
		if native_width < min(profil.get_widths()):
			for bicim, quality_target in format_plans[profil.name]:
				durum = _render_one(
					render,
					kaynak,
					asset,
					surum_hash,
					profil,
					native_width,
					bicim,
					uretilenler,
					kaynak_boyut if disk_kontrolu else None,
					prepared=hazirlanmis,
					canvas_cache=tuval_onbellegi,
					result_sink=sonuc.results,
					quality_target=quality_target,
				)
				sonuc.add(durum, f"{profil.policy_profile}/{native_width}/{bicim}")
	return sonuc


def _profiles_for_slot(slot_key: str) -> list[Any]:
	"""Slotun etkin Media Profile kayıtları."""
	# Sistem işi: worker oturumsuz çalışır, profil kayıtları satıcıya ait değil.
	adlar = frappe.get_all(
		"Media Profile",
		filters={"slot_key": slot_key, "enabled": 1},
		order_by="profile_key asc",
		pluck="name",
	)
	profiller = [frappe.get_doc("Media Profile", ad) for ad in adlar]
	# Basamaklar SAYISAL artan sırada işlenmeli. `profile_key asc` alfabetik:
	# `…:w1280` < `…:w192` < `…:w1920` < `…:w96`. Sıra iki yerde belirleyici —
	# D-1 mükerrer kapısında hangi basamağın kaydı tutulduğunda (küçük
	# basamak kazanmalı) ve `max_renditions_per_asset` tavanı kestiğinde
	# (önce küçükler üretilmeli, srcset'in alt basamakları kritik).
	profiller.sort(key=lambda p: (min(p.get_widths() or [0]), p.name))
	return profiller


def _profile_specs(render: Any, asset: Any, profiles: Iterable[Any]) -> tuple[Any, ...]:
	"""DB Media Profile kayıtlarını saf render profil geometrisine çevir."""
	sonuc: list[Any] = []
	for profil in profiles:
		for genislik in profil.get_widths():
			kaliteler = tuple(
				(bicim, int(profil.quality_target)) for bicim in profil.get_formats() if profil.quality_target
			)
			sonuc.append(
				render.RenditionProfile(
					slot_key=asset.slot_key,
					name=str(profil.policy_profile),
					width=int(genislik),
					formats=tuple(profil.get_formats()),
					fit=profil.fit or render.FIT_CONTAIN,
					target_ratio=profil.aspect_ratio or "",
					encoder_quality=kaliteler,
				)
			)
	return tuple(sonuc)


def _affected_crop_profiles(
	kaynak: bytes,
	asset: Any,
	slot_key: str,
	new_intent: Any,
) -> tuple[str, ...]:
	"""Aktif sürümden yeni niyete pikseli değişen politika profil adları."""
	from tradehub_core.media.pipeline.image import render, reprocess

	profiller = _profiles_for_slot(slot_key)
	aktif = frappe.db.get_value("Media Asset", asset.name, "active_version")
	if not aktif:
		return tuple(dict.fromkeys(str(p.policy_profile) for p in profiller))
	eski_ham = frappe.db.get_value("Media Version", aktif, "crop_intent_snapshot")
	try:
		eski = frappe.parse_json(eski_ham) if eski_ham else None
	except Exception:
		eski = json.loads(eski_ham) if eski_ham else None
	hazir, _icc, _notlar = render.prepare_source(kaynak)
	return tuple(
		dict.fromkeys(
			reprocess.affected_profile_names(
				(int(hazir.width), int(hazir.height)),
				_profile_specs(render, asset, profiller),
				eski,
				new_intent,
			)
		)
	)


def _carry_forward_renditions(
	asset_name: str,
	version_hash: str,
	*,
	excluded_profiles: Iterable[str] = (),
) -> bool:
	"""Değişmeyen türevleri encode etmeden yeni immutable sürüm köküne taşı.

	Kaynak dosya/satır silinmez; hard-link mümkün değilse kopya alınır ve hedef
	sürüm için YENİ satır açılır. Eşzamanlı okuyucu promote commit'ine kadar eski
	active_version satırlarını, sonra yalnız yeni sürüm satırlarını görür.
	"""
	from tradehub_core.media.pipeline.core import dedup
	from tradehub_core.media.pipeline.image import render

	haric = {str(name) for name in excluded_profiles}
	aktif = str(frappe.db.get_value("Media Asset", asset_name, "active_version") or "")
	if not aktif:
		return True
	rows = frappe.get_all(
		"Media Rendition",
		filters={"asset": asset_name, "version_hash": aktif, "state": ["!=", "purged"]},
		fields=[
			"name",
			"profile",
			"width",
			"height",
			"format",
			"file_url",
			"bytes",
			"quality",
			"ssim",
			"generation",
			"benefit_gate_passed",
			"output_sha256",
		],
		limit_page_length=0,
	)
	try:
		for row in rows:
			if str(row.get("profile") or "") in haric:
				continue
			kaynak_url = row.get("file_url") or ""
			kaynak_yol = _media_disk_path(kaynak_url)
			if not kaynak_yol or not os.path.isfile(kaynak_yol):
				return False
			uzanti = render.EXTENSION.get(
				str(row.get("format") or "").lower(),
				f".{str(row.get('format') or '').lower()}",
			).lstrip(".")
			yeni_url = dedup.rendition_path(
				asset_name,
				version_hash,
				str(row.get("profile") or ""),
				int(row.get("width") or 0),
				uzanti,
			)
			yeni_yol = _media_disk_path(yeni_url)
			if os.path.abspath(kaynak_yol) != os.path.abspath(yeni_yol):
				os.makedirs(os.path.dirname(yeni_yol), exist_ok=True)
				if not os.path.isfile(yeni_yol):
					gecici = f"{yeni_yol}.tmp-{os.getpid()}-{frappe.generate_hash(length=8)}"
					try:
						os.link(kaynak_yol, gecici)
					except OSError:
						shutil.copy2(kaynak_yol, gecici)
					os.replace(gecici, yeni_yol)
			output_hash = str(row.get("output_sha256") or "") or file_sha256(yeni_yol)
			ledger = _rendition_ledger_fields(
				version_hash,
				str(row.get("profile") or ""),
				int(row.get("width") or 0),
				str(row.get("format") or ""),
				output_hash=output_hash,
			)
			anahtar = rendition_key(
				asset_name,
				version_hash,
				str(row.get("profile") or ""),
				int(row.get("width") or 0),
				str(row.get("format") or ""),
			)
			if frappe.db.exists("Media Rendition", {"rendition_key": anahtar}):
				continue
			frappe.get_doc(
				{
					"doctype": "Media Rendition",
					"asset": asset_name,
					**ledger,
					"profile": row.get("profile"),
					"width": int(row.get("width") or 0),
					"height": int(row.get("height") or 0),
					"format": row.get("format"),
					"file_url": yeni_url,
					"storage_backend": "local",
					"generation": row.get("generation") or "eager",
					"bytes": int(row.get("bytes") or 0),
					"quality": int(row.get("quality") or 0),
					"ssim": float(row.get("ssim") or 0.0),
					"benefit_gate_passed": int(row.get("benefit_gate_passed") or 0),
				}
			).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge rendition carry-forward failed",
			message=f"{asset_name} / {version_hash}\n\n{frappe.get_traceback()}",
		)
		return False
	return True


def _rendition_ledger_fields(
	version_hash: str,
	profile: str,
	width: int,
	fmt: str,
	*,
	content: bytes | None = None,
	output_hash: str | None = None,
	engine_version: str | None = None,
) -> dict[str, str]:
	"""Build the persistent exact-output ledger columns for one rendition."""
	if not output_hash and content is None:
		raise ValueError("rendition ledger requires exact content or output_hash")
	sha = str(output_hash or "") or content_sha256(content or b"")
	motor = (
		engine_version or frappe.db.get_value("Media Version", version_hash, "engine_version") or "unknown"
	)
	return {
		"version_hash": version_hash,
		"output_sha256": sha,
		"engine_signature": engine_signature(
			engine_version=str(motor),
			version_hash=version_hash,
			profile=profile,
			width=width,
			fmt=fmt,
			output_sha256=sha,
		),
	}


def _render_one(
	render: Any,
	kaynak: bytes,
	asset: Any,
	surum_hash: str,
	profil: Any,
	genislik: int,
	bicim: str,
	uretilenler: set[tuple[str, int, str]],
	kaynak_boyut: tuple[int, int] | None = None,
	crop_intent: Any = None,
	*,
	prepared: tuple | None = None,
	canvas_cache: dict[tuple, tuple] | None = None,
	result_sink: list[Any] | None = None,
	fast_quality: bool = False,
	quality_target: Any = None,
	content_class: str | None = None,
) -> str:
	"""Tek matris satırını üret; `ready|omitted|failed` döndür.

	`render.render()` yerine `render.render_rendition()` çağrılıyor: ikisi aynı
	modülün aynı yolu, ama `render()` yalnız BAYT döndürüyor ve fayda kapısı
	(INV-05) düştüğünde kaynağın kendisini "türev" diye geri veriyor. Künye
	olmadan bu iki durum ayırt edilemez ve kaynağın kopyası `.webp` adıyla
	diske yazılırdı. `render_rendition` aynı üretimi künyesiyle döner.

	`uretilenler` bu Asset için ŞU ANA KADAR yazılmış tekil
	(profil, genişlik, biçim) satırlarını taşır.

	`kaynak_boyut` (T-064/W8): kaynağın HAZIRLANMIŞ boyutu — verilirse ve bu
	türev diskte zaten duruyorsa encode ATLANIR (aşağıda `_skip_from_disk`).
	"""
	try:
		profile_spec = render.RenditionProfile(
			slot_key=asset.slot_key,
			# Künye adı POLİTİKA profil adından türer, docname'den değil:
			# `crop.resolve_crop` kırpma geçersiz kılmalarını `profile_key`
			# ile eşleştiriyor ve orada da politika adı bekleniyor.
			name=str(profil.policy_profile),
			width=int(genislik),
			formats=(bicim,),
			fit=profil.fit or render.FIT_CONTAIN,
			target_ratio=profil.aspect_ratio or "",
			encoder_quality=(
				((bicim, quality_target),)
				if quality_target is not None
				else ((bicim, int(profil.quality_target)),)
				if profil.quality_target
				else ()
			),
		)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge türev üretilemedi",
			message=f"{asset.name} / {profil.name} / w{genislik} / {bicim}\n\n{frappe.get_traceback()}",
		)
		return GEN_FAILED

	hazir = prepared[0] if prepared is not None else render.prepare_source(kaynak)[0]
	try:
		plan = render.plan_geometry(hazir.size, profile_spec, crop_intent)
	except Exception:
		return GEN_FAILED
	if int(profile_spec.width) > int(plan.crop_box[2]) or plan.upscale_blocked:
		# INV-01: clamp ederek aynı genişlikte ikinci bir sahte basamak üretme.
		return GEN_OMITTED

	matris_anahtari = (
		str(profil.policy_profile or ""),
		int(genislik),
		str(bicim).lower(),
	)
	if matris_anahtari in uretilenler:
		return GEN_OMITTED
	if _rendition_was_omitted(
		asset.name,
		surum_hash,
		matris_anahtari[0],
		matris_anahtari[1],
		matris_anahtari[2],
	):
		return GEN_OMITTED

	# T-064/W8 — mevcut-türev atlama: version_hash aynı + dosya diskte +
	# bayt tutuyor → encode ATLA. Best-effort: kontrolün kendisi patlarsa
	# üretim yolu değişmeden koşar (yanlış atlama yok, yalnız kaçan atlama var).
	if kaynak_boyut:
		try:
			atlama = _skip_from_disk(
				render,
				asset,
				surum_hash,
				profil,
				bicim,
				profile_spec,
				kaynak_boyut,
				crop_intent,
			)
		except Exception:
			atlama = None
		if atlama is not None:
			if atlama["found"]:
				if not atlama["row_exists"]:
					# Disk gerçeklerinden kayıt tazele. `quality`/`ssim` diskteki
					# baytlardan okunamaz — 0 yazılır (üretim yolundaki "int değilse
					# 0" kuralıyla aynı boşluk değeri; sayı UYDURULMAZ).
					frappe.get_doc(
						{
							"doctype": "Media Rendition",
							"asset": asset.name,
							**_rendition_ledger_fields(
								surum_hash,
								str(profil.policy_profile or ""),
								int(atlama["width"]),
								bicim,
								output_hash=str(atlama["output_sha256"]),
							),
							"profile": profil.policy_profile,
							"width": atlama["width"],
							"height": atlama["height"],
							"format": bicim,
							"file_url": atlama["file_url"],
							"storage_backend": "local",
							"generation": profil.generation or "eager",
							"state": "ready",
							"bytes": atlama["bytes"],
							"quality": 0,
							"ssim": 0.0,
							"benefit_gate_passed": 1,
						}
					).insert(ignore_permissions=True)
				uretilenler.add(matris_anahtari)
				return GEN_READY
			# atlama["found"] değil: diskte yok — normal üretim yoluna düş.

	try:
		# Kırpma niyeti: yükleme yolunda None (politikanın varsayılan
		# penceresi), kırpma-yeniden-üretim yolunda kayıtlı niyet —
		# `crop.resolve_crop` zinciri (elle pencere > odak > öneri > merkez).
		if canvas_cache is None:
			canvas_cache = {}
		tuval_anahtari = (plan, profile_spec.pad_color or render.DEFAULT_PAD_COLOR)
		if tuval_anahtari not in canvas_cache:
			canvas, tuval_notlari = render.build_canvas(hazir, profile_spec, plan)
			canvas_cache[tuval_anahtari] = (plan, canvas, tuval_notlari)
		sonuc = render.render_rendition(
			kaynak,
			profile_spec,
			crop_intent,
			content_class=content_class,
			_prepared=prepared,
			_canvas=canvas_cache[tuval_anahtari],
			_fast_quality=fast_quality,
			# Tek teslim biçimi isteniyor: küçük bir kaynakta AVIF daha büyük
			# olsa da orijinale dönülmez. Tasarruf raporu gerçek baytı gösterir.
			require_format=bicim == "avif",
			allow_passthrough=bicim != "avif",
			**({"quality_range": (100, 100)} if quality_target == 100 else {}),
		)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge türev üretilemedi",
			message=f"{asset.name} / {profil.name} / w{genislik} / {bicim}\n\n{frappe.get_traceback()}",
		)
		return GEN_FAILED

	if sonuc.passthrough:
		# Fayda kapısı düştü: çıktı kaynaktan küçük değil. Kaynağın kopyasını
		# türev diye saklamak iki kat yer kaplar, sayfayı hızlandırmaz.
		return GEN_OMITTED
	if result_sink is not None:
		result_sink.append(sonuc)

	file_url = _write_rendition_file(
		asset.name, surum_hash, profil.policy_profile, int(sonuc.width or 0), sonuc.format, sonuc.content
	)
	ledger = _rendition_ledger_fields(
		surum_hash,
		str(profil.policy_profile or ""),
		int(sonuc.width or 0),
		str(sonuc.format or ""),
		content=sonuc.content,
	)
	# Aynı sürüm koordinatı idempotent upsert edilir; farklı sürüm yeni tarihsel
	# row açar. Böylece crop/policy geçişi eski ledger kanıtını yok etmez.
	anahtar = rendition_key(
		asset.name,
		surum_hash,
		str(profil.policy_profile or ""),
		int(sonuc.width or 0),
		str(sonuc.format or ""),
	)
	mevcut_ad = frappe.db.get_value("Media Rendition", {"rendition_key": anahtar}, "name")
	if mevcut_ad:
		frappe.db.set_value(
			"Media Rendition",
			mevcut_ad,
			{
				**ledger,
				"height": sonuc.height,
				"file_url": file_url,
				"bytes": sonuc.size_bytes,
				"quality": sonuc.quality if isinstance(sonuc.quality, int) else 0,
				"ssim": sonuc.ssim or 0.0,
				"benefit_gate_passed": 1,
				"generated_at": now_datetime(),
				"state": "ready",
				"purged_at": None,
				"purge_after": None,
				"trash_path": None,
				"purge_reason": None,
			},
		)
		uretilenler.add(matris_anahtari)
		return GEN_READY
	frappe.get_doc(
		{
			"doctype": "Media Rendition",
			"asset": asset.name,
			**ledger,
			# K-2: buraya POLİTİKA profil adı (`w384`) yazılır, `Media Profile`
			# docname'i (`product.image:w384`) DEĞİL. `api/media_manifest.py`
			# bu kolonu `available_profiles` olarak kütüphaneye veriyor ve
			# kütüphane onu slot politikasındaki adla karşılaştırıyor;
			# eşleşmezse `NoProfileAvailable` → manifest sessizce boş döner.
			# Alan şemada `Data`: taşıdığı değer bir docname değil, sözleşme
			# adıdır ve slotlar arası tekil DEĞİLDİR (`w128` iki slotta birden
			# var), yani `Link` olarak ifade edilemez.
			"profile": profil.policy_profile,
			"width": sonuc.width,
			"height": sonuc.height,
			"format": sonuc.format,
			"file_url": file_url,
			"storage_backend": "local",
			"generation": profil.generation or "eager",
			"state": "ready",
			"bytes": sonuc.size_bytes,
			"quality": sonuc.quality if isinstance(sonuc.quality, int) else 0,
			"ssim": sonuc.ssim or 0.0,
			"benefit_gate_passed": 1,
		}
	).insert(ignore_permissions=True)
	uretilenler.add(matris_anahtari)
	return GEN_READY


def _skip_from_disk(
	render: Any,
	asset: Any,
	surum_hash: str,
	profil: Any,
	bicim: str,
	profile_spec: Any,
	kaynak_boyut: tuple[int, int],
	crop_intent: Any = None,
) -> dict[str, Any] | None:
	"""Bu türevin PLANLANAN künyesi + diskte hazır olup olmadığı; plan kurulamazsa `None`.

	T-064/W8 mevcut-türev atlaması. Dayanağı INV-09: türev adresi
	`version_hash` taşır ve `version_hash` = f(kaynak, politika, kırpma, motor).
	Aynı adreste bir dosya varsa o dosya KESİNLİKLE bu üretimin daha önceki
	çıktısıdır — determinizm garantisi `tests/test_render_regression.py`'de
	kilitli. Ölçülen açık: DB satırları silinip disk dosyaları dururken
	(yetim disk, DB geri yüklemesi) `_run_rendition_job` 48 encode'un 48'ini
	yeniden yapıyordu; W6-B'nin videoda bulduğu desenle aynı.

	Beklenen çıktı genişliği encode'suz hesaplanır: `render.plan_geometry`
	saf aritmetiktir ve `render_rendition`'ın kullandığı fonksiyonun KENDİSİDİR
	(kopyası değil) — upscale kırpması dahil aynı genişliği verir. Genişlik
	dosya bulunamasa da döner: D-1 mükerrer kapısı encode'dan ÖNCE sorulabilsin.

	`found=True` için "bayt tutuyor" iki kademede sorulur:
	  - `Media Rendition` satırı VARSA satırdaki `bytes` disktekiyle
	    karşılaştırılır; tutmuyorsa dosya şüphelidir, `found=False` (yeniden üretim).
	  - Satır yoksa dosyanın gerçekten açıldığı doğrulanır (`render._verify`,
	    üretim yolundaki decode kapısının aynısı); açılamıyorsa `found=False`.
	"""
	from tradehub_core.media.pipeline.core import dedup

	plan = render.plan_geometry(kaynak_boyut, profile_spec, crop_intent)
	genislik_gercek, yukseklik = plan.canvas_size
	uzanti = render.EXTENSION.get(bicim, f".{bicim}").lstrip(".")
	url = dedup.rendition_path(asset.name, surum_hash, profil.policy_profile, int(genislik_gercek), uzanti)
	kunye: dict[str, Any] = {
		"file_url": url,
		"width": int(genislik_gercek),
		"height": int(yukseklik),
		"bytes": 0,
		"row_exists": False,
		"found": False,
	}

	yol = _media_disk_path(url)
	if not os.path.isfile(yol):
		_restore_purged_rendition(
			asset.name,
			surum_hash,
			str(profil.policy_profile or ""),
			int(genislik_gercek),
			bicim,
			url,
			yol,
		)
	if not os.path.isfile(yol):
		return kunye
	boyut = os.path.getsize(yol)
	if boyut <= 0:
		return kunye

	# Sistem işi: worker oturumsuz; türev kayıtları satıcı verisi değil.
	kayit = frappe.get_all(
		"Media Rendition",
		filters={
			"asset": asset.name,
			"version_hash": surum_hash,
			"file_url": url,
			"state": ["!=", "purged"],
		},
		fields=["name", "bytes", "output_sha256", "engine_signature"],
		limit=1,
	)
	if kayit:
		if int(kayit[0].get("bytes") or 0) != boyut:
			return kunye  # kayıt ile disk ayrışmış — güvenilir değil, yeniden üret
	else:
		with open(yol, "rb") as f:
			veri = f.read()
		if not render._verify(veri):
			return kunye  # diskte duran şey açılmıyor — yeniden üret

	output_hash = str(kayit[0].get("output_sha256") or "") if kayit else ""
	if not output_hash:
		output_hash = file_sha256(yol)
	if kayit and (not kayit[0].get("output_sha256") or not kayit[0].get("engine_signature")):
		frappe.db.set_value(
			"Media Rendition",
			kayit[0]["name"],
			_rendition_ledger_fields(
				surum_hash,
				str(profil.policy_profile or ""),
				int(genislik_gercek),
				bicim,
				output_hash=output_hash,
			),
			update_modified=False,
		)
	kunye.update(
		{
			"bytes": int(boyut),
			"output_sha256": output_hash,
			"row_exists": bool(kayit),
			"found": True,
		}
	)
	return kunye


def _restore_purged_rendition(
	asset_name: str,
	version_hash: str,
	profile: str,
	width: int,
	fmt: str,
	file_url: str,
	target_path: str,
) -> bool:
	"""Grace penceresindeki soft-delete çıktısını ilk istekte atomik geri al."""
	key = rendition_key(asset_name, version_hash, profile, width, fmt)
	row = frappe.db.get_value(
		"Media Rendition",
		{"rendition_key": key, "state": "purged"},
		["name", "trash_path"],
		as_dict=True,
	)
	if not row or not row.get("trash_path"):
		return False
	site_root = os.path.realpath(frappe.get_site_path())
	trash_root = os.path.realpath(frappe.get_site_path("private", "media_rendition_trash"))
	trash_path = os.path.realpath(os.path.join(site_root, str(row.get("trash_path"))))
	if not trash_path.startswith(trash_root + os.sep) or not os.path.isfile(trash_path):
		return False
	os.makedirs(os.path.dirname(target_path), exist_ok=True)
	os.replace(trash_path, target_path)
	try:
		frappe.db.set_value(
			"Media Rendition",
			row.get("name"),
			{
				"state": "ready",
				"benefit_gate_passed": 1,
				"purged_at": None,
				"purge_after": None,
				"trash_path": None,
				"purge_reason": None,
				"last_access_at": now_datetime(),
			},
			update_modified=False,
		)
	except Exception:
		os.replace(target_path, trash_path)
		raise
	return True


def _omission_marker_path(
	asset_name: str,
	version_hash: str,
	profile: str,
	width: int,
	fmt: str,
) -> str:
	anahtar = f"{profile}|{int(width)}|{fmt.lower()}"
	ozet = hashlib.sha256(anahtar.encode("utf-8")).hexdigest()
	return os.path.join(
		get_files_path(is_private=0),
		"media",
		asset_name,
		version_hash,
		".omitted",
		f"{ozet}.json",
	)


def _mark_rendition_omitted(
	asset_name: str,
	version_hash: str,
	profile: str,
	width: int,
	fmt: str,
) -> None:
	"""Negatif cache: kasıtlı omission ilk istekte tekrar encode edilmesin."""
	yol = _omission_marker_path(asset_name, version_hash, profile, width, fmt)
	os.makedirs(os.path.dirname(yol), exist_ok=True)
	gecici = f"{yol}.tmp-{os.getpid()}-{frappe.generate_hash(length=8)}"
	with open(gecici, "w", encoding="utf-8") as handle:
		json.dump({"profile": profile, "width": int(width), "format": fmt.lower()}, handle)
	os.replace(gecici, yol)


def _rendition_was_omitted(
	asset_name: str,
	version_hash: str,
	profile: str,
	width: int,
	fmt: str,
) -> bool:
	return os.path.isfile(_omission_marker_path(asset_name, version_hash, profile, width, fmt))


def _write_rendition_file(
	asset_name: str,
	surum_hash: str,
	profil_adi: str,
	genislik: int,
	bicim: str,
	content: bytes,
) -> str:
	"""Türevi diske yazar ve `file_url`'ünü döner.

	Adlandırma İCAT EDİLMEZ: adres `pipeline/core/dedup.py::rendition_path`'ten
	gelir — `/files/media/{asset}/{version_hash}/{profil}-{genişlik}.{uzantı}`
	(T-042, INV-09). Adres `version_hash` taşıdığı için içerik değişmeden URL
	değişmez, içerik/politika/motor değişince URL zorunlu değişir; bu yüzden
	`Cache-Control: immutable` güvenlidir ve CDN purge hiç gerekmez. Aynı türev
	iki kez üretilirse aynı adrese yazılır (idempotent).

	YALNIZ YENİ üretimler bu düzene yazar. Eski üretimlerin shard'lı adresleri
	(`/files/{xx}/{sha[:32]}.webp`) diskte ve `Media Rendition.file_url`'de
	olduğu gibi durur — manifest URL'leri veritabanından okuduğu için iki düzen
	yan yana yaşayabilir (bkz. `api/media_manifest.py`); taşıma ayrı bir iştir.

	`File` kaydı AÇILMAZ. İki sebep: (1) türevler satıcının medya envanterinde
	ve depolama kotasında görünmemeli — bunlar sistemin ürettiği kopyalar,
	kullanıcının yüklediği dosyalar değil (`presets.ARCHIVE_DIRNAME` arşivi de
	aynı gerekçeyle File kaydı açmıyor); (2) `File.after_insert` kancası
	kendi kendini tetikleyip sonsuz döngü kurardı.
	"""
	from tradehub_core.media.pipeline.core import dedup
	from tradehub_core.media.pipeline.image import render

	uzanti = render.EXTENSION.get(bicim, f".{bicim}").lstrip(".")
	url = dedup.rendition_path(asset_name, surum_hash, profil_adi, genislik, uzanti)
	# `/files/` öneki `get_files_path(is_private=0)`'ın kendisi; kalan parça
	# `media/{asset}/{version_hash}/...` alt dizinidir.
	yol = os.path.join(get_files_path(is_private=0), url.removeprefix("/files/"))
	os.makedirs(os.path.dirname(yol), exist_ok=True)
	# Okuyucu final URL'yi ya eski TAM içerikle ya yeni TAM içerikle görmeli;
	# kısmen yazılmış bir rendition asla görünür olmamalı. Temp dosya aynı
	# dizindedir, dolayısıyla `os.replace` aynı filesystem üzerinde atomiktir.
	gecici = f"{yol}.tmp-{os.getpid()}-{frappe.generate_hash(length=8)}"
	try:
		with open(gecici, "wb") as f:
			f.write(content)
		os.replace(gecici, yol)
	finally:
		try:
			os.unlink(gecici)
		except FileNotFoundError:
			pass
	return url


# --- 3) W7: VIDEO hattı ------------------------------------------------------
#
# Görsel hattının video karşılığı — AYNI üç kat kapı, AYNI kayıt zinciri
# (Media Asset → Media Version → Media Processing Job → Media Rendition),
# AYNI kanonik adres kökü (`/files/media/{asset}/{version_hash}/…`, INV-09).
#
# AYRI BİR BAYRAK AÇILMADI (bilinçli): video da yükleme anında tetiklenen bir
# üretimdir; `rendition_on_upload` üretim şalteri + `is_slot_enabled
# ("product.video")` slot şalteri operatöre zaten iki kademeli kontrol verir.
# `active_slots`tan `product.video` silmek video hattını TEK BAŞINA kapatır.
#
# NEDEN AYRI DOCTYPE DEĞİL: `Media Asset.media_type` zaten `video` seçeneğini,
# `Media Rendition.format` zaten `mp4/webm` seçeneklerini taşıyor — şema video
# için TASARLANMIŞ, yalnız üretim ucu yoktu (rapor 81 §8.2). Yeni bir DocType
# açmak manifest/öksüz-tarama/panel envanteri gibi mevcut tüm okuyucuları
# ikinci bir zincire bakmaya zorlardı. Eklenenler: `format` enum'una `m3u8`
# (HLS master türevi) ve `Media Version.duration_s`.


def _maybe_enqueue_video(doc: Any) -> None:
	"""Video türev üretimini KOŞULLU olarak kuyruğa alır (W7).

	Yalnız `maybe_generate_renditions` içinden, KAPI 1 (bayrak) sorulmuş
	olarak çağrılır. Görsel yoluyla aynı sıra: kapsam → slot şalteri →
	idempotency → enqueue.
	"""
	slot_key = _resolve_video_scope(doc)
	if not slot_key:
		return
	if not pipeline_flags.is_slot_enabled(slot_key):
		return

	parmak_izi = content_fingerprint(doc)
	if not parmak_izi:
		return
	if _renditions_exist(parmak_izi, slot_key):
		return

	frappe.enqueue(
		"tradehub_core.media.pipeline_bridge._run_video_job",
		queue=RQ_QUEUE_VIDEO,
		timeout=media_queues.VIDEO.timeout_seconds,
		enqueue_after_commit=True,
		file_url=doc.get("file_url"),
	)


def _resolve_video_scope(doc: Any) -> str | None:
	"""Dosya VİDEO hattının kapsamında mı; kapsamdaysa `slot_key`, değilse `None`.

	`_resolve_scope` ile aynı omurga; farklar:
	  - Uzantı kümesi `upload_policy.KIND_VIDEO`.
	  - Slot haritası video bloğu taşıyan politikalardan kurulur ve `bound_to`
	    girdileri `Data` alanlarıdır (panel `upload_file` çıktısını string
	    yazıyor) — `Attach` şartı yok.
	  - `attached_to_*` boşken slot İLİŞKİDEN çözülür (K-3'ün video karşılığı).
	    Ölçüldü (2026-08-20 DEV): 4 gerçek ürün videosunun 4'ünde de
	    `attached_to_doctype` NULL; slotu taşıyan tek bağ `Listing.video_url`.
	"""
	if getattr(getattr(doc, "flags", None), "th_skip_transcode", False):
		return None

	if doc.get("is_folder") or doc.get("is_private"):
		return None

	uzanti = os.path.splitext(doc.get("file_name") or doc.get("file_url") or "")[1].lower()
	if upload_policy.EXTENSIONS.get(uzanti) != upload_policy.KIND_VIDEO:
		return None

	attached_doctype = doc.get("attached_to_doctype") or ""
	if attached_doctype in presets.EXCLUDED_DOCTYPES:
		return None

	tam, tekil, referanslar = _video_slot_bindings()
	alan = (doc.get("attached_to_field") or "").strip()
	if attached_doctype:
		# Bilinen bir doctype'a bağlıyken slot çözülemiyorsa dosya gerçekten
		# kapsam dışıdır — görsel yolundaki gerekçeyle aynı.
		slot_key = tam.get((attached_doctype, alan)) if alan else tekil.get(attached_doctype)
	else:
		slot_key = _video_slot_from_reference(doc.get("file_url"), referanslar)
	if not slot_key or slot_key in EXCLUDED_SLOTS:
		return None

	if _sensitive_twin_blocked(doc):
		return None

	return slot_key


@lru_cache(maxsize=1)
def _video_slot_bindings() -> tuple[
	dict[tuple[str, str], str], dict[str, str], tuple[tuple[str, str, str], ...]
]:
	"""VİDEO slotlarının `bound_to` bloklarından üç harita üretir.

	Dönüş: `((doctype, alan) → slot, doctype → slot, (doctype, alan, slot)
	ilişki-arama listesi)`. Video slotu = politikasında `video` bloğu olan
	slot (`product.video`, `company.cover_video`); kodda slot adı SABİT DEĞİL.
	Politika okunamazsa boş harita döner (fail-safe, görsel yoluyla aynı).
	"""
	tam: dict[tuple[str, str], str] = {}
	doctype_slotlari: dict[str, set[str]] = {}
	referanslar: list[tuple[str, str, str]] = []
	try:
		from tradehub_core.media.pipeline.image import render

		for slot_key in render.slot_keys():
			if slot_key in EXCLUDED_SLOTS:
				continue
			politika = render.load_slot_policy(slot_key)
			if not politika.get("video"):
				continue
			for baglanma in politika.get("bound_to") or ():
				doctype = (baglanma.get("doctype") or "").strip()
				alan = (baglanma.get("field") or "").strip()
				if not doctype or not alan:
					continue
				tam.setdefault((doctype, alan), slot_key)
				doctype_slotlari.setdefault(doctype, set()).add(slot_key)
				referanslar.append((doctype, alan, slot_key))
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge video slot haritası okunamadı",
			message=frappe.get_traceback(),
		)
		return ({}, {}, ())

	tekil = {dt: next(iter(slotlar)) for dt, slotlar in doctype_slotlari.items() if len(slotlar) == 1}
	return (tam, tekil, tuple(referanslar))


def _video_slot_from_reference(
	file_url: str | None, referanslar: tuple[tuple[str, str, str], ...]
) -> str | None:
	"""`attached_to_*` boşken video slotunu İLİŞKİDEN çözer (K-3 muadili)."""
	if not file_url:
		return None
	for doctype, alan, slot_key in referanslar:
		try:
			if frappe.db.get_value(doctype, {alan: file_url}, "name"):
				return slot_key
		except Exception:
			frappe.log_error(
				title="media.pipeline_bridge video ilişkiden slot çözülemedi",
				message=f"{doctype}.{alan} = {file_url}\n\n{frappe.get_traceback()}",
			)
			return None
	return None


def _media_disk_path(url: str) -> str:
	"""`/files/...` adresinin public disk yolu (`_write_rendition_file` düzeni)."""
	return os.path.join(get_files_path(is_private=0), url.removeprefix("/files/"))


@lru_cache(maxsize=1)
def _video_engine_version() -> str:
	"""`Media Version.engine_version` girdisi — 'ffmpeg-n8.1.2…' biçiminde.

	Görseldeki `pillow-…` ile aynı rol: motor (imaj) değişince version_hash,
	dolayısıyla TÜM video türev adresleri zorunlu değişir (INV-09).
	"""
	import subprocess

	try:
		ilk = (
			subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
			.stdout.decode("utf-8", "replace")
			.splitlines()[0]
		)
		m = re.search(r"ffmpeg version (\S+)", ilk)
		if m:
			return f"ffmpeg-{m.group(1)}"
	except Exception:
		pass
	# Sürüm okunamadıysa sabit bir değer: hash'i BOŞ string ile üretmek, iki
	# farklı imajı aynı sürüm saymaktır.
	return "ffmpeg-unknown"


def _video_policy_snapshot(slot_key: str) -> dict[str, Any]:
	"""`Media Version.policy_snapshot` girdisi — pikseli/baytı etkileyen İKİ katman.

	Görselde tek katman (slot politikası) yeter; videoda kodlama parametreleri
	`video_decision.json`'dadır. İkisi birden hash'e girer: karar tablosu
	(CRF, tavanlar, merdiven) değişince adres de değişmeli.
	"""
	from tradehub_core.media.pipeline.image import render
	from tradehub_core.media.pipeline.video.decision import default_table

	return {"slot_policy": render.load_slot_policy(slot_key), "video_decision": dict(default_table().raw)}


def _animation_engine_version() -> str:
	"""GIF video dönüşüm kodu + ffmpeg imajının tek sürüm kimliği."""
	from tradehub_core.media.pipeline.video import animation

	return f"{_video_engine_version()}+animation-{animation.ANIMATION_ENGINE_VERSION}"


def _animation_policy_snapshot(slot_key: str, spec: Any) -> dict[str, Any]:
	"""Animasyon çıktısının bütün piksel/bayt parametrelerini hash girdisine al."""
	from dataclasses import asdict

	from tradehub_core.media.pipeline.image import render

	return {"slot_policy": render.load_slot_policy(slot_key), "animation": asdict(spec)}


def _run_animation_job(file_url: str, *, slot_override: str) -> None:
	"""Animated GIF'i gerçek MP4/H.264 + WebM/VP9 + PNG postere yayınla.

	Normal video karar tablosundaki boyut-fayda kapısı burada kullanılmaz: küçük
	GIF'in video çıktısı daha büyük olsa bile animasyonu kaybetmeden teslim edilir.
	Üç dosya doğrulanmadan hiçbir rendition satırı açılmaz.
	"""
	job_name: str | None = None
	staged: list[str] = []
	try:
		name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not name:
			return
		doc = frappe.get_doc("File", name)
		if not pipeline_flags.is_enabled("rendition_on_upload"):
			return
		if not pipeline_flags.is_store_enabled(ownership.store_of(doc.get("owner"))):
			return
		parmak_izi = content_fingerprint(doc)
		if not parmak_izi or _renditions_exist(parmak_izi, slot_override):
			return
		src_yolu = _media_disk_path(str(doc.file_url or ""))
		if not os.path.isfile(src_yolu):
			return
		kaynak = doc.get_content()
		if isinstance(kaynak, str):
			kaynak = kaynak.encode()
		if not kaynak:
			return

		from tradehub_core.media.pipeline.core import dedup
		from tradehub_core.media.pipeline.video import animation
		from tradehub_core.media.pipeline.video import probe as video_probe

		spec = animation.AnimationSpec()
		politika = _animation_policy_snapshot(slot_override, spec)
		motor = _animation_engine_version()
		source_hash = dedup.stream_sha256(io.BytesIO(kaynak)).sha256
		surum_hash = dedup.version_hash(source_hash, politika, None, motor)
		asset = _ensure_asset(doc, slot_override, parmak_izi, media_type=_MEDIA_TYPE_VIDEO)
		job_name = _open_job(
			asset.name,
			surum_hash,
			slot_override,
			job_type=ANIMATION_JOB_TYPE,
			queue=JOB_QUEUE_VIDEO,
			key_prefix=ANIMATION_JOB_TYPE,
		)

		version_root = os.path.dirname(
			_media_disk_path(dedup.rendition_path(asset.name, surum_hash, VIDEO_PRIMARY_PROFILE, 2, "mp4"))
		)
		os.makedirs(version_root, exist_ok=True)
		stage_id = frappe.generate_hash(length=10)
		staged = [
			os.path.join(version_root, f".animation-{stage_id}.part.mp4"),
			os.path.join(version_root, f".animation-{stage_id}.part.webm"),
			os.path.join(version_root, f".animation-{stage_id}.part.png"),
		]
		converted = animation.convert(src_yolu, *staged, spec=spec)
		if not converted.ok:
			frappe.db.set_value("Media Asset", asset.name, "state", "failed")
			_finish_job(job_name, "failed", error_code=converted.reason or "animation_conversion_failed")
			frappe.db.commit()
			return

		profiles = (VIDEO_PRIMARY_PROFILE, VIDEO_WEBM_PROFILE, VIDEO_POSTER_PROFILE)
		final_paths: dict[str, str] = {}
		for output, profile in zip(converted.outputs, profiles, strict=True):
			fmt = str(output.container).lower()
			url = dedup.rendition_path(asset.name, surum_hash, profile, int(output.width), fmt)
			dst = _media_disk_path(url)
			os.makedirs(os.path.dirname(dst), exist_ok=True)
			os.replace(output.path, dst)
			final_paths[profile] = dst
			_insert_video_rendition(
				asset.name,
				surum_hash=surum_hash,
				profil=profile,
				genislik=int(output.width),
				yukseklik=int(output.height),
				bicim=fmt,
				file_url=url,
				bayt=int(output.size_bytes),
				quality=(spec.h264_crf if profile == VIDEO_PRIMARY_PROFILE else spec.vp9_crf)
				if profile != VIDEO_POSTER_PROFILE
				else 0,
				engine_version=motor,
			)

		facts = video_probe.probe(final_paths[VIDEO_PRIMARY_PROFILE])
		if not facts.measured:
			raise ValueError("animation_primary_probe_failed")
		_ensure_video_version(
			asset,
			surum_hash,
			source_hash,
			politika,
			facts,
			final_paths.get(VIDEO_POSTER_PROFILE),
			engine_version=motor,
			classification="animation",
			classification_confidence="exact",
			# Classifier sözleşmesinde animation'ın GÖRSEL zinciri bilerek
			# boştur; gerçek video hedefleri rendition satırlarında taşınır.
			format_chain=[],
		)
		frappe.db.set_value("Media Asset", asset.name, "state", "ready")
		_finish_job(job_name, "success")
		_promote_initial_version(asset.name, surum_hash)
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001 — worker sözleşmesi: istisna sızdırma
		frappe.db.rollback()
		if job_name:
			_finish_job(job_name, "failed", error_code=type(exc).__name__)
			frappe.db.commit()
		frappe.log_error(
			title="media.pipeline_bridge animation job failed",
			message=f"{file_url}\n\n{frappe.get_traceback()}",
		)
	finally:
		for path in staged:
			try:
				os.unlink(path)
			except FileNotFoundError:
				pass


def _run_video_job(
	file_url: str,
	*,
	slot_override: str | None = None,
	key_prefix: str | None = None,
) -> None:
	"""Worker tarafı (W7) — kararı uygular, türevleri üretir, kayıtları açar.

	Görseldeki `_run_rendition_job` ile aynı sözleşme: istisna SIZDIRMAZ,
	hata hâlinde iş kaydı `failed` olur ve fonksiyon sessizce döner.
	"""
	job_name: str | None = None
	source_name: str | None = None
	try:
		name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not name:
			return
		doc = frappe.get_doc("File", name)
		source_name = doc.name

		if not pipeline_flags.is_enabled("rendition_on_upload"):
			return
		if not pipeline_flags.is_store_enabled(ownership.store_of(doc.get("owner"))):
			return
		slot_key = slot_override or _resolve_video_scope(doc)
		if not slot_key:
			return
		# Animasyon görsel slotunun kapılarından geçip buraya gelir; hedef video
		# slotunun ayrıca açık olmasını istemek aynı dosyayı iki bayrakla
		# koşullandırırdı. Normal video yüklemesi kendi slot bayrağını korur.
		if slot_override is None and not pipeline_flags.is_slot_enabled(slot_key):
			return
		parmak_izi = content_fingerprint(doc)
		if not parmak_izi:
			return
		if _renditions_exist(parmak_izi, slot_key):
			return

		src_yolu = _media_disk_path(doc.get("file_url") or "")
		if not os.path.exists(src_yolu):
			return

		from tradehub_core.media.pipeline.video import probe as video_probe
		from tradehub_core.media.pipeline.video import validation as video_validation

		facts = video_probe.probe(src_yolu)
		dogrulama = video_validation.validate(slot_key, facts)
		karar = dogrulama.processing

		asset = _ensure_asset(doc, slot_key, parmak_izi, media_type=_MEDIA_TYPE_VIDEO)
		job_name = _open_job(
			asset.name,
			parmak_izi,
			slot_key,
			job_type=JOB_TYPE_VIDEO,
			queue=JOB_QUEUE_VIDEO,
			key_prefix=key_prefix or JOB_KEY_VIDEO,
		)
		frappe.db.set_value("File", doc.name, "th_media_video_status", "processing", update_modified=False)

		if dogrulama.rejected:
			# Karar bir HATA değil: motor bu dosyayı işlemiyor (bozuk künye,
			# 4K üstü, 15 dk üstü…) ya da slotun süre/geometri kapısı
			# dosyayı kabul etmiyor. Varlık `rejected` + kodla kapanır.
			frappe.db.set_value(
				"Media Asset",
				asset.name,
				{
					"state": "rejected",
					"rejection_code": (dogrulama.code or "video_rejected")[:140],
					"rejection_note": dogrulama.reason or "",
				},
			)
			frappe.db.set_value("File", doc.name, "th_media_video_status", "failed", update_modified=False)
			_finish_job(job_name, "failed", error_code=dogrulama.code or "video_rejected")
			frappe.db.commit()
			return

		surum_hash = _produce_video_outputs(src_yolu, facts, karar, asset, slot_key)

		frappe.db.set_value("Media Asset", asset.name, "state", "ready")
		frappe.db.set_value("File", doc.name, "th_media_video_status", "ready", update_modified=False)
		_finish_job(job_name, "success")
		if surum_hash:
			_promote_initial_version(asset.name, surum_hash)
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		frappe.db.rollback()
		if source_name:
			frappe.db.set_value("File", source_name, "th_media_video_status", "failed", update_modified=False)
		if job_name:
			_finish_job(job_name, "failed", error_code=type(exc).__name__)
		if source_name or job_name:
			frappe.db.commit()
		frappe.log_error(
			title="media.pipeline_bridge video job failed",
			message=f"{file_url}\n\n{frappe.get_traceback()}",
		)


def _produce_video_outputs(
	src_yolu: str,
	facts: Any,
	karar: Any,
	asset: Any,
	slot_key: str,
	*,
	crop_intent: Any = None,
) -> str:
	"""Karar → birincil dosya → poster → HLS → Media Version. Sıra anlamlı.

	Birincil ÖNCE: poster ve HLS, teslim edilecek dosyadan (kapıları geçen
	çıktı ya da passthrough kaynak) üretilir — kapıdan düşen bir çıktının
	posteri olmaz. Media Version EN SONDA açılır ki `lqip` poster baytlarından
	doldurulabilsin (görselde kaynak baytlardan doluyordu; video baytını
	Pillow açamaz).

	Açılan sürümün `version_hash`ini döndürür — çağıran ilk `ready` geçişinde
	onu yayına alır (`_promote_initial_version`).
	"""
	from tradehub_core.media.pipeline.core import dedup

	with open(src_yolu, "rb") as f:
		source_hash = dedup.stream_sha256(f).sha256
	politika = _video_policy_snapshot(slot_key)
	surum_hash = dedup.version_hash(source_hash, politika, crop_intent, _video_engine_version())

	teslim_yolu, teslim_facts = _produce_video_primary(src_yolu, facts, karar, asset.name, surum_hash)
	poster_yolu = _produce_video_poster(
		teslim_yolu,
		teslim_facts,
		asset.name,
		surum_hash,
		slot_key=slot_key,
		crop_intent=crop_intent,
	)
	_produce_video_preview(teslim_yolu, teslim_facts, asset.name, surum_hash)
	_produce_video_hls(teslim_yolu, teslim_facts, asset.name, surum_hash)

	_ensure_video_version(
		asset,
		surum_hash,
		source_hash,
		politika,
		teslim_facts,
		poster_yolu,
		crop_intent=crop_intent,
	)
	return surum_hash


def _produce_video_primary(
	src_yolu: str, facts: Any, karar: Any, asset_name: str, surum_hash: str
) -> tuple[str, Any]:
	"""REMUX/TRANSCODE çıktısını üretir ve kaydeder; teslim edilecek dosyayı döner.

	PASSTHROUGH (ya da kapılardan düşen TRANSCODE) yeni dosya YAZMAZ: teslim
	kaynak dosyanın kendisidir ve `Media Rendition` satırı açılmaz — satır
	üretilmiş dosyanın künyesidir, kaynağın takma adı değil.
	"""
	from tradehub_core.media.pipeline.core import dedup
	from tradehub_core.media.pipeline.video import probe as video_probe
	from tradehub_core.media.pipeline.video import transcode as video_transcode
	from tradehub_core.media.pipeline.video.decision import ACTION_REMUX

	if not karar.writes_new_file:
		return (src_yolu, facts)

	spec = video_transcode.H264Spec.from_table()
	# REMUX akış kopyalar (ölçü değişmez); TRANSCODE 1280 tavanına iner.
	genislik = int(facts.width or 0)
	if karar.action != ACTION_REMUX:
		genislik = min(genislik or spec.max_width, spec.max_width)
	genislik = max(genislik, 2)

	url = dedup.rendition_path(asset_name, surum_hash, VIDEO_PRIMARY_PROFILE, genislik, "mp4")
	dst = _media_disk_path(url)
	os.makedirs(os.path.dirname(dst), exist_ok=True)

	sonuc = video_transcode.apply_decision(src_yolu, dst, karar, facts=facts)
	if not (sonuc.accepted and sonuc.out_path):
		# Fayda/kalite kapısından düştü ve REMUX'a geri çekilme de uygulanmadı:
		# kaynak teslim edilir. Bu bir hata değil, ölçülmüş bir karardır —
		# gerekçesi sonuç notlarında; iş kaydı success kapanır.
		return (src_yolu, facts)

	cikti_facts = video_probe.probe(sonuc.out_path)
	gercek_g = int(cikti_facts.width or 0) if cikti_facts.measured else 0
	if gercek_g and gercek_g != genislik:
		# Adres GERÇEĞİ söylemeli: geri çekilme (REMUX) kaynak ölçüsünü korur,
		# ad transcode tavanıyla açılmıştı. Dosya bir kez, doğru ada taşınır.
		yeni_url = dedup.rendition_path(asset_name, surum_hash, VIDEO_PRIMARY_PROFILE, gercek_g, "mp4")
		yeni_dst = _media_disk_path(yeni_url)
		os.replace(dst, yeni_dst)
		url, dst = yeni_url, yeni_dst
		genislik = gercek_g

	kunye = cikti_facts if cikti_facts.measured else facts
	_insert_video_rendition(
		asset_name,
		surum_hash=surum_hash,
		profil=VIDEO_PRIMARY_PROFILE,
		genislik=genislik,
		yukseklik=int(kunye.height or 0),
		bicim="mp4",
		file_url=url,
		bayt=sonuc.out_bytes or 0,
		quality=int(spec.crf) if karar.action != ACTION_REMUX and not sonuc.fallback_from else 0,
	)
	return (dst, kunye)


def _produce_video_poster(
	teslim_yolu: str,
	teslim_facts: Any,
	asset_name: str,
	surum_hash: str,
	*,
	slot_key: str,
	crop_intent: Any = None,
) -> str | None:
	"""Posteri üretir, GERÇEK ölçüsüyle adlandırır ve kaydeder.

	Best-effort: poster üretimi düşerse (parlaklık kapısı iki pencerede de
	tutmadı, ffmpeg hatası) video teslimi SÜRMELİ — poster bir zenginleştirme,
	ön koşul değil. Hata loglanır, `None` döner.
	"""
	from tradehub_core.media.pipeline.core import dedup
	from tradehub_core.media.pipeline.video import poster as video_poster

	try:
		# Geçici ad sürüm dizininde: `os.replace` aynı dosya sisteminde kalsın.
		dizin = os.path.dirname(
			_media_disk_path(dedup.rendition_path(asset_name, surum_hash, VIDEO_POSTER_PROFILE, 2, "webp"))
		)
		os.makedirs(dizin, exist_ok=True)
		gecici = os.path.join(dizin, ".poster.part.webp")
		r = video_poster.make_poster(teslim_yolu, gecici, facts=teslim_facts)

		from PIL import Image  # noqa: PLC0415 — yalnız worker yolunda

		with Image.open(gecici) as im:
			g, y = im.size
		url = dedup.rendition_path(asset_name, surum_hash, VIDEO_POSTER_PROFILE, int(g), "webp")
		os.replace(gecici, _media_disk_path(url))

		_insert_video_rendition(
			asset_name,
			surum_hash=surum_hash,
			profil=VIDEO_POSTER_PROFILE,
			genislik=int(g),
			yukseklik=int(y),
			bicim="webp",
			file_url=url,
			bayt=r.size_bytes,
			quality=int(r.quality or 0),
		)
		poster_yolu = _media_disk_path(url)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge video poster üretilemedi",
			message=f"{asset_name} / {teslim_yolu}\n\n{frappe.get_traceback()}",
		)
		return None

	# Slotun ``profiles[]`` matrisi video değil POSTER görselidir. Aynı kareyi
	# görsel motorundan geçirerek crop intent, cover/contain geometrisi, AVIF
	# zinciri ve küçük thumbnail basamakları tek kanonik yoldan uygulanır.
	try:
		from tradehub_core.media.pipeline.image import render

		with open(poster_yolu, "rb") as f:
			poster_baytlari = f.read()
		sonuclar = render.render_ladder(
			poster_baytlari,
			slot_key,
			crop_intent,
			per_format=True,
		)
		for sonuc in sonuclar:
			if sonuc.passthrough or not sonuc.content:
				continue
			file_url = _write_rendition_file(
				asset_name,
				surum_hash,
				sonuc.profile.name,
				int(sonuc.width),
				sonuc.format,
				sonuc.content,
			)
			_insert_video_rendition(
				asset_name,
				surum_hash=surum_hash,
				profil=sonuc.profile.name,
				genislik=int(sonuc.width),
				yukseklik=int(sonuc.height),
				bicim=sonuc.format,
				file_url=file_url,
				bayt=sonuc.size_bytes,
				quality=int(sonuc.quality) if isinstance(sonuc.quality, int) else 0,
			)
	except Exception:
		# Ana poster hazırdır; profil merdiveni zenginleştirmesinin hatası videoyu
		# ve güvenli fallback posteri düşürmez, fakat sessiz de kalmaz.
		frappe.log_error(
			title="media.pipeline_bridge video poster merdiveni üretilemedi",
			message=f"{asset_name} / {slot_key}\n\n{frappe.get_traceback()}",
		)
	return poster_yolu


def _produce_video_preview(
	teslim_yolu: str, teslim_facts: Any, asset_name: str, surum_hash: str
) -> str | None:
	"""Hareketli önizleme klibini (3-6 sn, sessiz, ≤1 MB) üretir ve kaydeder.

	Rapor 84 §8.1'in kapattığı boşluk: motor (`poster.make_preview_clip`)
	hazırdı ama üretim yolu çağırmıyordu. Poster gibi BEST-EFFORT: klip bir
	zenginleştirme, teslim ön koşulu değil — hata loglanır, `None` döner.

	Bayt kapısı motorun kendisinde (CRF 28→32→36 + süre 6→4→3 merdiveni);
	merdiven tükenip 1 MB görev kapısı yine de aşılırsa (`within_task_gate`
	False) dosya SİLİNİR ve `Media Rendition` satırı AÇILMAZ — satır yalnız
	teslim edilebilir dosyanın künyesidir (h264/HLS kapılarıyla aynı sözleşme).
	Politika hedefi (400 KB) aşılıp görev kapısı tutuyorsa klip TESLİM edilir;
	motorun notu sonuçta zaten duruyor.
	"""
	from tradehub_core.media.pipeline.core import dedup
	from tradehub_core.media.pipeline.video import poster as video_poster
	from tradehub_core.media.pipeline.video import probe as video_probe

	try:
		spec = video_poster.PreviewClipSpec.from_table()
		# Geçici ad sürüm dizininde: `os.replace` aynı dosya sisteminde kalsın
		# (posterle aynı gerekçe). Gerçek ad, ÇIKTININ ölçülen genişliğiyle
		# açılır — klip ölçeği yönelime duyarlı (`preview_scale_filter`),
		# spec.width dikey kaynakta yalan söylerdi.
		dizin = os.path.dirname(
			_media_disk_path(
				dedup.rendition_path(asset_name, surum_hash, VIDEO_PREVIEW_PROFILE, 2, spec.container)
			)
		)
		os.makedirs(dizin, exist_ok=True)
		gecici = os.path.join(dizin, f".preview.part.{spec.container}")
		r = video_poster.make_preview_clip(teslim_yolu, gecici, spec=spec, facts=teslim_facts)
		if not r.within_task_gate:
			if os.path.exists(gecici):
				os.remove(gecici)
			frappe.log_error(
				title="media.pipeline_bridge video önizleme kapıdan düştü",
				message=f"{asset_name}: {r.size_bytes} B > {spec.max_bytes} B\n{r.notes}",
			)
			return None

		kunye = video_probe.probe(gecici)
		genislik = max(int(kunye.width or 0) if kunye.measured else int(spec.width), 2)
		url = dedup.rendition_path(asset_name, surum_hash, VIDEO_PREVIEW_PROFILE, genislik, spec.container)
		os.replace(gecici, _media_disk_path(url))

		_insert_video_rendition(
			asset_name,
			surum_hash=surum_hash,
			profil=VIDEO_PREVIEW_PROFILE,
			genislik=genislik,
			yukseklik=int(kunye.height or 0) if kunye.measured else 0,
			bicim=spec.container,
			file_url=url,
			bayt=r.size_bytes,
			quality=int(r.crf or 0),
		)
		return url
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge video önizleme üretilemedi",
			message=f"{asset_name} / {teslim_yolu}\n\n{frappe.get_traceback()}",
		)
		return None


def _produce_video_hls(teslim_yolu: str, teslim_facts: Any, asset_name: str, surum_hash: str) -> str | None:
	"""Gerekliyse HLS paketini üretir, BASAMAK KAPISINI uygular ve kaydeder.

	`enforce_rung_benefit_gate` (W7): kaynaktan büyük basamak master
	playlist'ten çıkarılır ve silinir; hiçbir basamak kalmazsa paket ilan
	edilmez ve `Media Rendition` satırı AÇILMAZ — teslim progresif mp4'te kalır.
	"""
	from tradehub_core.media.pipeline.core import dedup
	from tradehub_core.media.pipeline.video import hls as video_hls

	try:
		bayt = os.path.getsize(teslim_yolu)
	except OSError:
		return None
	gereklilik = video_hls.hls_required(teslim_facts, rendition_bytes=bayt)
	if not gereklilik.required:
		return None

	dizin_url = f"{dedup.RENDITION_ROOT}/{asset_name}/{surum_hash}/{VIDEO_HLS_DIRNAME}"
	out_dir = _media_disk_path(dizin_url)
	try:
		sonuc = video_hls.make_hls(teslim_yolu, out_dir, facts=teslim_facts)
		sonuc = video_hls.enforce_rung_benefit_gate(sonuc)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge video HLS üretilemedi",
			message=f"{asset_name} / {teslim_yolu}\n\n{frappe.get_traceback()}",
		)
		return None

	yayinda = sonuc.published_variants
	if not sonuc.master_path or not yayinda:
		return None

	tepe = max(yayinda, key=lambda v: v.bitrate_kbps)
	master_url = f"{dizin_url}/{video_hls.MASTER_PLAYLIST_NAME}"
	_insert_video_rendition(
		asset_name,
		surum_hash=surum_hash,
		profil=VIDEO_HLS_PROFILE,
		genislik=int(tepe.width or 2),
		yukseklik=int(tepe.height or 0),
		bicim="m3u8",
		file_url=master_url,
		bayt=sonuc.published_bytes,
	)
	return master_url


def _insert_video_rendition(
	asset_name: str,
	*,
	surum_hash: str,
	profil: str,
	genislik: int,
	yukseklik: int,
	bicim: str,
	file_url: str,
	bayt: int,
	quality: int = 0,
	engine_version: str | None = None,
) -> None:
	"""Video türev satırı. `benefit_gate_passed=1`: kapıdan düşen türev diske
	hiç yazılmadığı için satırı da yoktur (görselden fark — orada düşen türev
	kayda geçer; videoda düşen çıktı `os.replace` öncesi silinir)."""
	anahtar = rendition_key(asset_name, surum_hash, profil, genislik, bicim)
	if frappe.db.exists("Media Rendition", {"rendition_key": anahtar}):
		return
	yol = _media_disk_path(file_url)
	if not yol or not os.path.isfile(yol):
		raise FileNotFoundError(f"video rendition ledger file missing: {file_url}")
	output_hash = file_sha256(yol)
	doc = frappe.get_doc(
		{
			"doctype": "Media Rendition",
			"asset": asset_name,
			**_rendition_ledger_fields(
				surum_hash,
				profil,
				genislik,
				bicim,
				output_hash=output_hash,
				engine_version=engine_version or _video_engine_version(),
			),
			"profile": profil,
			"width": genislik,
			"height": yukseklik,
			"format": bicim,
			"file_url": file_url,
			"storage_backend": "local",
			"generation": "eager",
			"bytes": int(bayt or 0),
			"quality": quality,
			"ssim": 0.0,
			"benefit_gate_passed": 1,
		}
	)
	# Video output rows are prepared before Media Version so poster enrichment
	# can be included in that version. The whole transaction rolls back on
	# version failure; ignore only this transient Link ordering, not validation.
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)


def _poster_enrichment(poster_yolu: str | None) -> dict[str, Any]:
	"""Poster baytlarından LQIP/baskın renk — `Media Version` ön izleme alanları.

	Video baytını Pillow açamaz; sürümün `_enrich_from_source` kancası video
	kaynağında boşa koşup log kirletirdi. Poster tam da "videonun ilk anlamlı
	karesi" olduğu için LQIP'in DOĞRU kaynağı odur (`MediaVideo.vue` `lqip`
	prop'u posterin inişine kadarki yüzeyi boyar).
	"""
	if not poster_yolu:
		return {}
	try:
		from tradehub_core.media.pipeline.image import enrich as enrich_mod

		with open(poster_yolu, "rb") as f:
			kunye = enrich_mod.enrich(f.read())
		if kunye.ok:
			return {
				"lqip": kunye.lqip,
				"lqip_data_uri": kunye.lqip_data_uri,
				"dominant_color": kunye.dominant_color,
			}
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge poster LQIP üretilemedi",
			message=f"{poster_yolu}\n\n{frappe.get_traceback()}",
		)
	return {}


def _ensure_video_version(
	asset: Any,
	surum_hash: str,
	source_hash: str,
	politika: dict[str, Any],
	teslim_facts: Any,
	poster_yolu: str | None,
	*,
	engine_version: str | None = None,
	classification: str = "",
	classification_confidence: str = "",
	format_chain: list[dict[str, Any]] | None = None,
	crop_intent: Any = None,
) -> Any:
	"""Videonun `Media Version` kaydı (T-042'nin video karşılığı).

	Görseldeki `_ensure_version` ile aynı yarış sözleşmesi (`idempotent_create`).
	Geometri + süre TESLİM EDİLEN dosyanındır (manifest CLS/aspect-ratio bunu
	okur); `lqip` poster baytlarından dolar.
	"""
	from tradehub_core.media.pipeline.core import dedup

	motor = engine_version or _video_engine_version()

	def _bul(anahtar: str) -> Any:
		ad = frappe.db.get_value("Media Version", {"version_hash": anahtar}, "name")
		return frappe.get_doc("Media Version", ad) if ad else None

	def _olustur() -> Any:
		doc = frappe.get_doc(
			{
				"doctype": "Media Version",
				"asset": asset.name,
				"version_hash": surum_hash,
				"source_hash": source_hash,
				"policy_snapshot": frappe.as_json(politika),
				"crop_intent_snapshot": (
					frappe.as_json(dedup.normalize_crop_intent(crop_intent))
					if crop_intent is not None
					else None
				),
				"engine_version": motor,
				"created_at": now_datetime(),
				"is_active": 0,
				"width": int(teslim_facts.width or 0),
				"height": int(teslim_facts.height or 0),
				"duration_s": round(float(teslim_facts.duration_s or 0.0), 3),
				"classification": classification or None,
				"classification_confidence": classification_confidence or None,
				"format_chain": frappe.as_json(format_chain) if format_chain is not None else None,
				**_poster_enrichment(poster_yolu),
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def _catisma(exc: BaseException) -> bool:
		return isinstance(exc, frappe.DuplicateEntryError | frappe.UniqueValidationError)

	kayit, _yeni = dedup.idempotent_create(surum_hash, _olustur, _bul, _catisma)
	return kayit
