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

ÜÇ KAT KAPI (hepsi fail-safe "kapalı")
--------------------------------------
1. `pipeline_flags.is_enabled("rendition_on_upload")` — ana şalter + alt bayrak.
   Kapalıysa fonksiyon İLK SATIRDA döner: ne DB okunur, ne kuyruğa iş girer.
   Sistemin bugünkü davranışı birebir aynı kalır.
2. Kapsam daraltması — `transcode.maybe_transcode_on_insert` ile AYNI mantık
   (klasör/private muaf, sahibi satıcıya çözülen ya da bilinen bir slota
   bağlanan dosya), üstüne KVKK kapsam dışı doctype'lar ve `document.attachment`
   slotu (KYB/KYC/kimlik belgeleri) açıkça hariç.
3. `pipeline_flags.is_slot_enabled(slot_key)` — `active_slots` boşken hiçbir
   slot açık değildir; operatör açtığı slotu tek tek yazar.

SLOT ÇÖZÜMÜ POLİTİKADAN OKUNUR
------------------------------
(doctype, alan) → `slot_key` haritası kodda SABİT DEĞİL: `media/pipeline/policy/
slots/*.json` dosyalarının `bound_to` blokları okunur. Yeni bir bağlanma noktası
eklemek bu modülü değiştirmez. Çözülemeyen (ya da iki slota birden aday olan)
dosya sessizce kapsam dışıdır.

İŞ AKIŞI
--------
    File.after_insert
      └─ maybe_generate_renditions   (istek thread'i — yalnız karar verir)
           └─ frappe.enqueue(queue="long", enqueue_after_commit=True)
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
import os
import re
from functools import lru_cache
from typing import Any

import frappe
from frappe.utils import get_files_path, now_datetime

from tradehub_core.media import audit, ownership, pipeline_flags, presets, upload_policy

#: Gerçek RQ kuyruğu. Bu kurulumda `default/short/long` var; `media-image-*`
#: kuyrukları Faz 3 tasarımında tanımlı ama HENÜZ AÇILMADI. İş kaydındaki
#: `queue` alanı (JOB_QUEUE) tasarım adını, bu sabit taşıyıcı kuyruğu tutar.
RQ_QUEUE: str = "long"

#: `transcode.QUEUE_TIMEOUT_SECONDS` ile aynı değer — aynı worker, aynı tavan.
QUEUE_TIMEOUT_SECONDS: int = 1800

#: `Media Processing Job.queue` seçeneği (yükleme anında tetiklenen, kullanıcı
#: bekleyen üretim → "live"). Deneme tavanı bu kuyrukta 3.
JOB_QUEUE: str = "media-image-live"

JOB_TYPE: str = "rendition"

# ── W7: video hattı sabitleri ────────────────────────────────────────────
#: Video işi de aynı gerçek RQ kuyruğuna (`long`) girer; `Media Processing
#: Job.queue` alanına ise Faz 3 tasarım adı yazılır (görseldeki JOB_QUEUE
#: deseniyle birebir aynı ayrım).
JOB_QUEUE_VIDEO: str = "media-video"

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

	Bayrak kapalıyken (varsayılan) ilk satırda döner; DB'ye tek sorgu bile
	gitmez. Best-effort: burada patlamak dosya yüklemesini asla engellememeli
	(`states.on_file_insert` / `transcode.maybe_transcode_on_insert` ile aynı
	desen).
	"""
	try:
		# KAPI 1 — bayrak. Dalga A'nın tüm güvencesi bu satıra yaslanıyor.
		if not pipeline_flags.is_enabled("rendition_on_upload"):
			return

		# KAPI 2 — kapsam.
		slot_key = _resolve_scope(doc)
		if not slot_key:
			# Görsel kapsamına girmeyen dosya VİDEO kapsamında olabilir (W7).
			# Uzantı iki kümeden en çok birine düşer; görsel yolu değişmedi.
			_maybe_enqueue_video(doc)
			return

		# KAPI 3 — slot bazlı açma/kapama (`active_slots` boşken hiçbiri açık değil).
		if not pipeline_flags.is_slot_enabled(slot_key):
			return

		surum_hash = content_fingerprint(doc)
		if not surum_hash:
			return

		# İdempotency: aynı içerik + aynı slot için türev zaten üretilmişse
		# (aynı dosyanın ikinci yüklemesi, yeniden deneme, çift kanca) yeni iş
		# açılmaz. İçerik-adresli adlandırma sayesinde "aynı içerik" güvenilir.
		if _renditions_exist(surum_hash, slot_key):
			return

		frappe.enqueue(
			"tradehub_core.media.pipeline_bridge._run_rendition_job",
			queue=RQ_QUEUE,
			timeout=QUEUE_TIMEOUT_SECONDS,
			enqueue_after_commit=True,
			file_url=doc.get("file_url"),
		)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge maybe_generate_renditions failed",
			message=frappe.get_traceback(),
		)


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
	  - Slot politikadan çözülebilmeli ve `EXCLUDED_SLOTS` içinde olmamalı.
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
		# `attached_doctype` DOLUYSA bu yol koşmaz: bilinen bir doctype'a
		# bağlıyken slot çözülemiyorsa (ör. `Sales Order`) bu dosya gerçekten
		# kapsam dışıdır; ilişkiye bakmak yanlış slota atamak olurdu.
		slot_key = _slot_from_reference(doc.get("file_url"))
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

	Bulunamazsa BUGÜNKÜ davranış korunur: dosya sessizce kapsam dışı kalır,
	kimseye hata dönmez.

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


def _renditions_exist(surum_hash: str, slot_key: str) -> bool:
	"""Bu içerik + slot için üretilmiş bir türev zaten var mı?"""
	# Sistem işi: kanca oturum yetkisinden bağımsız çalışır ve satıcı
	# izolasyonu Asset'in `owner_seller` kolonundan değil, içerik hash'inden
	# sorulduğu için `get_all` bilinçli (`get_list` burada kullanıcının
	# göremediği bir Asset'i "yok" sayıp aynı işi ikinci kez açardı).
	assetler = frappe.get_all(
		"Media Asset",
		filters={"content_sha256": surum_hash, "slot_key": slot_key},
		pluck="name",
	)
	if not assetler:
		return False
	return bool(
		frappe.get_all(
			"Media Rendition",
			filters={"asset": ["in", assetler]},
			limit=1,
			pluck="name",
		)
	)


# --- 2) Worker: üretim -------------------------------------------------------


def _run_rendition_job(file_url: str) -> None:
	"""Worker tarafı — türev matrisini üretir, diske yazar, kayıtları açar.

	İstisna SIZDIRMAZ. Hata hâlinde `Media Processing Job` `failed` olur,
	`frappe.log_error` yazılır ve fonksiyon sessizce döner.
	"""
	job_name: str | None = None
	try:
		name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not name:
			# Kuyruğa alındıktan sonra dosya silinmiş olabilir.
			return
		doc = frappe.get_doc("File", name)

		# Bayrak kuyrukta beklerken kapatılmış olabilir — worker da sorar.
		if not pipeline_flags.is_enabled("rendition_on_upload"):
			return

		slot_key = _resolve_scope(doc)
		if not slot_key or not pipeline_flags.is_slot_enabled(slot_key):
			return

		parmak_izi = content_fingerprint(doc)
		if not parmak_izi:
			return
		if _renditions_exist(parmak_izi, slot_key):
			return

		kaynak = doc.get_content()
		if isinstance(kaynak, str):
			kaynak = kaynak.encode()
		if not kaynak:
			return

		asset = _ensure_asset(doc, slot_key, parmak_izi)
		# T-042: sürüm kimliği KÜTÜPHANEDEN (dedup.version_hash, 4 girdi) gelir
		# ve türev adresleri onu taşır. Yalnız YENİ üretimler — mevcut türev
		# kayıtlarının adresine dokunulmaz.
		surum = _ensure_version(asset, slot_key, kaynak)
		job_name = _open_job(asset.name, parmak_izi, slot_key)

		uretilen = _generate(kaynak, asset, slot_key, surum.version_hash)

		frappe.db.set_value("Media Asset", asset.name, "state", "ready" if uretilen else "failed")
		if uretilen:
			_finish_job(job_name, "success")
			_promote_initial_version(asset.name, surum.version_hash)
		else:
			_finish_job(job_name, "failed", error_code="no_rendition")
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		frappe.db.rollback()
		if job_name:
			_finish_job(job_name, "failed", error_code=type(exc).__name__)
			frappe.db.commit()
		frappe.log_error(
			title="media.pipeline_bridge rendition job failed",
			message=f"{file_url}\n\n{frappe.get_traceback()}",
		)


def maybe_reprocess_after_crop(asset_name: str) -> None:
	"""`save_intent` sonrası köprü — türevlerin YENİ kadrajla yeniden üretimini kuyruğa alır.

	Best-effort: kuyruk hatası niyet kaydını geri almaz (çağıran yutar-loglar).
	Bayrak/slot kapıları worker'da TEKRAR sorulur; burada sorulmaları yalnız
	kapalı hatta kuyruğa boş iş sokmamak için.
	"""
	if not pipeline_flags.is_enabled("rendition_on_upload"):
		return
	slot_key = frappe.db.get_value("Media Asset", asset_name, "slot_key")
	if not slot_key or not pipeline_flags.is_slot_enabled(str(slot_key)):
		return
	frappe.enqueue(
		"tradehub_core.media.pipeline_bridge._run_crop_reprocess_job",
		queue=RQ_QUEUE,
		timeout=QUEUE_TIMEOUT_SECONDS,
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

		if not asset.source_file or not frappe.db.exists("File", asset.source_file):
			return
		kaynak = frappe.get_doc("File", asset.source_file).get_content()
		if isinstance(kaynak, str):
			kaynak = kaynak.encode()
		if not kaynak:
			return

		surum = _ensure_version(asset, slot_key, kaynak, crop_intent=intent)
		job_name = _open_job(asset.name, surum.version_hash, slot_key, key_prefix="crop-reprocess")

		uretilen = _generate(kaynak, asset, slot_key, surum.version_hash, crop_intent=intent)

		if uretilen:
			frappe.db.set_value("Media Asset", asset.name, "state", "ready")
			_finish_job(job_name, "success")
		else:
			# Yeni türev yazılamadı; ESKİ kadrajlı türevler yerinde duruyor —
			# varlık durumu düşürülmez, yalnız iş kaydı sebeple kapanır.
			_finish_job(job_name, "failed", error_code="no_rendition")
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		frappe.db.rollback()
		if job_name:
			_finish_job(job_name, "failed", error_code=type(exc).__name__)
			frappe.db.commit()
		frappe.log_error(
			title="media.pipeline_bridge crop reprocess failed",
			message=f"{asset_name}\n\n{frappe.get_traceback()}",
		)


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
	"""`Media Version.engine_version` girdisi — 'pillow-11.3.0' biçiminde.

	Motor değişirse (pyvips'e geçiş) bu değer, dolayısıyla TÜM version_hash'ler
	ve türev adresleri zorunlu değişir (INV-09). Ölçülen karar: Pillow'da
	kalındı (`docs/reports/05-kutuphane-benchmark.md`).
	"""
	import PIL  # noqa: PLC0415 — Pillow yalnız worker yolunda gerekiyor

	return f"pillow-{PIL.__version__}"


def _ensure_version(asset: Any, slot_key: str, kaynak: bytes, crop_intent: Any = None) -> Any:
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
			}
		)
		# Sistem işi: worker oturumsuz; `asset` permlevel-1 alanı ancak böyle yazılır.
		doc.insert(ignore_permissions=True)
		return doc

	def _catisma(exc: BaseException) -> bool:
		# Aynı ad (autoname=field:version_hash) → DuplicateEntryError;
		# unique kolon ihlali → UniqueValidationError. İkisi de aynı yarış.
		return isinstance(exc, (frappe.DuplicateEntryError, frappe.UniqueValidationError))

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
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge iş kaydı kapatılamadı",
			message=f"{job_name} → {status}\n\n{frappe.get_traceback()}",
		)


def _generate(
	kaynak: bytes, asset: Any, slot_key: str, surum_hash: str, crop_intent: Any = None
) -> int:
	"""Profil matrisini üretir; yazılan türev sayısını döner.

	`surum_hash`: `Media Version.version_hash` (64 hex) — türev adresleri bunu
	taşır (INV-09). İçerik `_run_rendition_job`'da BİR kez okunur ve buraya
	bayt olarak gelir; sürüm hash'i için ikinci bir okuma yapılmaz.
	"""
	from tradehub_core.media.pipeline.image import render

	profiller = _profiles_for_slot(slot_key)
	if not profiller:
		# Kayıtları `patches/v15_9_23_media_profile_seed.py` politika
		# dosyalarından tohumluyor. Burası boşsa ya patch koşmamıştır ya da
		# operatör slotun tüm profillerini kapatmıştır — ikisi de sessiz
		# kalmamalı, çünkü dışarıdan "hat çalışıyor ama türev yok" görünür.
		frappe.log_error(
			title="media.pipeline_bridge profil yok",
			message=f"{slot_key} için etkin Media Profile kaydı bulunamadı.",
		)
		return 0

	tavan = pipeline_flags.max_renditions_per_asset()
	yazilan = 0
	# D-1: motor BÜYÜTME yapmaz — kaynaktan geniş her basamak kaynağın kendi
	# genişliğine kırpılır. 1080 px'lik bir kaynakta `w1280` ve `w1920`
	# basamaklarının ikisi de 1080 px AVIF üretir ve `rendition_key` profil
	# adını taşıdığı için iki AYRI kayıt açılır (doğrulanmış kanıt:
	# `994prleaac|w1280|1080|avif` ve `…|w1920|1080|avif`, `file_url` birebir
	# aynı). Fayda kapısı (`sonuc.passthrough`) bunların yalnız bir kısmını
	# eliyor. Ölçüt üretilen türevin GERÇEK (genişlik, biçim) ikilisidir:
	# aynı ikili için ikinci kayıt açılmaz.
	uretilenler: set[tuple[int, str]] = set()

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
	kaynak_boyut: tuple[int, int] | None = None
	surum_kok = os.path.join(get_files_path(is_private=0), "media", asset.name, surum_hash)
	if os.path.isdir(surum_kok):
		try:
			hazir, _icc, _notlar = render.prepare_source(kaynak)
			kaynak_boyut = (int(hazir.width), int(hazir.height))
		except Exception:
			# Atlama kontrolü best-effort: boyut çözülemezse üretim yolu
			# değişmeden koşar (yeniden encode pahalı ama DOĞRU sonuç verir).
			kaynak_boyut = None

	for profil in profiller:
		for genislik in profil.get_widths():
			for bicim in profil.get_formats():
				if yazilan >= tavan:
					# Tavan bir güvenlik freni: bozuk bir profil kaydı tek
					# görselden yüzlerce dosya üretmesin.
					return yazilan
				if _render_one(
					render,
					kaynak,
					asset,
					surum_hash,
					profil,
					genislik,
					bicim,
					uretilenler,
					kaynak_boyut,
					crop_intent,
				):
					yazilan += 1
	return yazilan


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


def _render_one(
	render: Any,
	kaynak: bytes,
	asset: Any,
	surum_hash: str,
	profil: Any,
	genislik: int,
	bicim: str,
	uretilenler: set[tuple[int, str]],
	kaynak_boyut: tuple[int, int] | None = None,
	crop_intent: Any = None,
) -> bool:
	"""Tek (genişlik × biçim) türevini üretip kaydeder. Yazıldıysa True.

	`render.render()` yerine `render.render_rendition()` çağrılıyor: ikisi aynı
	modülün aynı yolu, ama `render()` yalnız BAYT döndürüyor ve fayda kapısı
	(INV-05) düştüğünde kaynağın kendisini "türev" diye geri veriyor. Künye
	olmadan bu iki durum ayırt edilemez ve kaynağın kopyası `.webp` adıyla
	diske yazılırdı. `render_rendition` aynı üretimi künyesiyle döner.

	`uretilenler` bu Asset için ŞU ANA KADAR yazılmış (genişlik, biçim)
	ikililerini taşır; D-1 mükerrer kapısı buradan sorulur.

	`kaynak_boyut` (T-064/W8): kaynağın HAZIRLANMIŞ boyutu — verilirse ve bu
	türev diskte zaten duruyorsa encode ATLANIR (aşağıda `_skip_from_disk`).
	"""
	try:
		profile_spec = render.RenditionProfile(
			slot_key=asset.slot_key,
			# Künye adı POLİTİKA profil adından türer, docname'den değil:
			# `crop.resolve_crop` kırpma geçersiz kılmalarını `profile_key`
			# ile eşleştiriyor ve orada da politika adı bekleniyor.
			name=f"{profil.policy_profile}_w{genislik}",
			width=int(genislik),
			formats=(bicim,),
			fit=profil.fit or render.FIT_CONTAIN,
			target_ratio=profil.aspect_ratio or "",
			encoder_quality=((bicim, int(profil.quality_target)),) if profil.quality_target else (),
		)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge türev üretilemedi",
			message=f"{asset.name} / {profil.name} / w{genislik} / {bicim}\n\n{frappe.get_traceback()}",
		)
		return False

	# T-064/W8 — mevcut-türev atlama: version_hash aynı + dosya diskte +
	# bayt tutuyor → encode ATLA. Best-effort: kontrolün kendisi patlarsa
	# üretim yolu değişmeden koşar (yanlış atlama yok, yalnız kaçan atlama var).
	if kaynak_boyut:
		try:
			atlama = _skip_from_disk(render, asset, surum_hash, profil, bicim, profile_spec, kaynak_boyut)
		except Exception:
			atlama = None
		if atlama is not None:
			olcu = (atlama["width"], bicim)
			if olcu in uretilenler:
				# D-1 ÖN-kapısı: planlanan (genişlik, biçim) bu koşuda zaten
				# üretildi/atlandı. Planlanan genişlik = gerçek genişlik (aynı
				# `plan_geometry`), yani encode SONRASI D-1 kapısının vereceği
				# kararın aynısı encode'suz verilir. ÖLÇÜLDÜ: bu satır olmadan
				# mükerrer basamaklar (w1280/w1920 → 1200px) yeniden kodlanıyordu
				# (senaryo B'de 8 artık encode).
				return False
			if atlama["found"]:
				if not atlama["row_exists"]:
					# Disk gerçeklerinden kayıt tazele. `quality`/`ssim` diskteki
					# baytlardan okunamaz — 0 yazılır (üretim yolundaki "int değilse
					# 0" kuralıyla aynı boşluk değeri; sayı UYDURULMAZ).
					frappe.get_doc(
						{
							"doctype": "Media Rendition",
							"asset": asset.name,
							"profile": profil.policy_profile,
							"width": atlama["width"],
							"height": atlama["height"],
							"format": bicim,
							"file_url": atlama["file_url"],
							"storage_backend": "local",
							"generation": profil.generation or "eager",
							"bytes": atlama["bytes"],
							"quality": 0,
							"ssim": 0.0,
							"benefit_gate_passed": 1,
						}
					).insert(ignore_permissions=True)
				uretilenler.add(olcu)
				return True
			# atlama["found"] değil: diskte yok — normal üretim yoluna düş.

	try:
		# Kırpma niyeti: yükleme yolunda None (politikanın varsayılan
		# penceresi), kırpma-yeniden-üretim yolunda kayıtlı niyet —
		# `crop.resolve_crop` zinciri (elle pencere > odak > öneri > merkez).
		sonuc = render.render_rendition(kaynak, profile_spec, crop_intent)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge türev üretilemedi",
			message=f"{asset.name} / {profil.name} / w{genislik} / {bicim}\n\n{frappe.get_traceback()}",
		)
		return False

	if sonuc.passthrough:
		# Fayda kapısı düştü: çıktı kaynaktan küçük değil. Kaynağın kopyasını
		# türev diye saklamak iki kat yer kaplar, sayfayı hızlandırmaz.
		return False

	olcu = (int(sonuc.width or 0), (sonuc.format or "").lower())
	if olcu in uretilenler:
		# D-1: kaynaktan geniş bir basamak, daha küçük bir basamakla BİREBİR
		# aynı çıktıyı üretti. İkinci kayıt aynı dosyayı ikinci kez gösterir,
		# srcset'e iki özdeş basamak yazar ve envanteri şişirir.
		return False

	file_url = _write_rendition_file(
		asset.name, surum_hash, profil.policy_profile, int(sonuc.width or 0), sonuc.format, sonuc.content
	)
	# W9+ upsert: (asset, profil, genişlik, biçim) dörtlüsü UNIQUE
	# (`rendition_key`). Kırpma-yeniden-üretiminde satır zaten vardır — yeni
	# sürümün dosyası MEVCUT satırın adresine yazılır, ikinci satır açılmaz.
	# Vitrin srcset'i bu satırlardan çıktığı için adres güncellemesi teslimatı
	# yeni kadraja çevirir; eski sürümün dosyaları diskte kalır (geri dönüş
	# ucuz, moderasyon sürüm kaydından izlenebilir).
	anahtar = "|".join(
		(asset.name, profil.policy_profile or "", str(int(sonuc.width or 0)), sonuc.format or "")
	)
	mevcut_ad = frappe.db.get_value("Media Rendition", {"rendition_key": anahtar}, "name")
	if mevcut_ad:
		frappe.db.set_value(
			"Media Rendition",
			mevcut_ad,
			{
				"height": sonuc.height,
				"file_url": file_url,
				"bytes": sonuc.size_bytes,
				"quality": sonuc.quality if isinstance(sonuc.quality, int) else 0,
				"ssim": sonuc.ssim or 0.0,
				"benefit_gate_passed": 1,
				"generated_at": now_datetime(),
			},
		)
		uretilenler.add(olcu)
		return True
	frappe.get_doc(
		{
			"doctype": "Media Rendition",
			"asset": asset.name,
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
			"bytes": sonuc.size_bytes,
			"quality": sonuc.quality if isinstance(sonuc.quality, int) else 0,
			"ssim": sonuc.ssim or 0.0,
			"benefit_gate_passed": 1,
		}
	).insert(ignore_permissions=True)
	uretilenler.add(olcu)
	return True


def _skip_from_disk(
	render: Any,
	asset: Any,
	surum_hash: str,
	profil: Any,
	bicim: str,
	profile_spec: Any,
	kaynak_boyut: tuple[int, int],
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

	plan = render.plan_geometry(kaynak_boyut, profile_spec, None)
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
		return kunye
	boyut = os.path.getsize(yol)
	if boyut <= 0:
		return kunye

	# Sistem işi: worker oturumsuz; türev kayıtları satıcı verisi değil.
	kayit = frappe.get_all(
		"Media Rendition",
		filters={"asset": asset.name, "file_url": url},
		fields=["name", "bytes"],
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

	kunye.update({"bytes": int(boyut), "row_exists": bool(kayit), "found": True})
	return kunye


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
	with open(yol, "wb") as f:
		f.write(content)
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
		queue=RQ_QUEUE,
		timeout=QUEUE_TIMEOUT_SECONDS,
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


def _run_video_job(file_url: str) -> None:
	"""Worker tarafı (W7) — kararı uygular, türevleri üretir, kayıtları açar.

	Görseldeki `_run_rendition_job` ile aynı sözleşme: istisna SIZDIRMAZ,
	hata hâlinde iş kaydı `failed` olur ve fonksiyon sessizce döner.
	"""
	job_name: str | None = None
	try:
		name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not name:
			return
		doc = frappe.get_doc("File", name)

		if not pipeline_flags.is_enabled("rendition_on_upload"):
			return
		slot_key = _resolve_video_scope(doc)
		if not slot_key or not pipeline_flags.is_slot_enabled(slot_key):
			return
		parmak_izi = content_fingerprint(doc)
		if not parmak_izi:
			return
		if _renditions_exist(parmak_izi, slot_key):
			return

		src_yolu = _media_disk_path(doc.get("file_url") or "")
		if not os.path.exists(src_yolu):
			return

		from tradehub_core.media.pipeline.video import decision as video_decision
		from tradehub_core.media.pipeline.video import probe as video_probe

		facts = video_probe.probe(src_yolu)
		karar = video_decision.decide(facts)

		asset = _ensure_asset(doc, slot_key, parmak_izi, media_type=_MEDIA_TYPE_VIDEO)
		job_name = _open_job(
			asset.name,
			parmak_izi,
			slot_key,
			job_type=JOB_TYPE_VIDEO,
			queue=JOB_QUEUE_VIDEO,
			key_prefix=JOB_KEY_VIDEO,
		)

		if karar.rejected:
			# Karar bir HATA değil: motor bu dosyayı işlemiyor (bozuk künye,
			# 4K üstü, 15 dk üstü…). Varlık `rejected` + kodla kapanır.
			frappe.db.set_value(
				"Media Asset",
				asset.name,
				{
					"state": "rejected",
					"rejection_code": (karar.code or "video_rejected")[:140],
					"rejection_note": karar.reason or "",
				},
			)
			_finish_job(job_name, "failed", error_code=karar.code or "video_rejected")
			frappe.db.commit()
			return

		surum_hash = _produce_video_outputs(src_yolu, facts, karar, asset, slot_key)

		frappe.db.set_value("Media Asset", asset.name, "state", "ready")
		_finish_job(job_name, "success")
		if surum_hash:
			_promote_initial_version(asset.name, surum_hash)
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001 — worker hiçbir koşulda kuyruğu patlatmamalı
		frappe.db.rollback()
		if job_name:
			_finish_job(job_name, "failed", error_code=type(exc).__name__)
			frappe.db.commit()
		frappe.log_error(
			title="media.pipeline_bridge video job failed",
			message=f"{file_url}\n\n{frappe.get_traceback()}",
		)


def _produce_video_outputs(
	src_yolu: str, facts: Any, karar: Any, asset: Any, slot_key: str
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
	surum_hash = dedup.version_hash(source_hash, politika, None, _video_engine_version())

	teslim_yolu, teslim_facts = _produce_video_primary(src_yolu, facts, karar, asset.name, surum_hash)
	poster_yolu = _produce_video_poster(teslim_yolu, teslim_facts, asset.name, surum_hash)
	_produce_video_preview(teslim_yolu, teslim_facts, asset.name, surum_hash)
	_produce_video_hls(teslim_yolu, teslim_facts, asset.name, surum_hash)

	_ensure_video_version(asset, surum_hash, source_hash, politika, teslim_facts, poster_yolu)
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
	teslim_yolu: str, teslim_facts: Any, asset_name: str, surum_hash: str
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
		dizin = os.path.dirname(_media_disk_path(
			dedup.rendition_path(asset_name, surum_hash, VIDEO_POSTER_PROFILE, 2, "webp")
		))
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
			profil=VIDEO_POSTER_PROFILE,
			genislik=int(g),
			yukseklik=int(y),
			bicim="webp",
			file_url=url,
			bayt=r.size_bytes,
			quality=int(r.quality or 0),
		)
		return _media_disk_path(url)
	except Exception:
		frappe.log_error(
			title="media.pipeline_bridge video poster üretilemedi",
			message=f"{asset_name} / {teslim_yolu}\n\n{frappe.get_traceback()}",
		)
		return None


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
		dizin = os.path.dirname(_media_disk_path(
			dedup.rendition_path(asset_name, surum_hash, VIDEO_PREVIEW_PROFILE, 2, spec.container)
		))
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
		url = dedup.rendition_path(
			asset_name, surum_hash, VIDEO_PREVIEW_PROFILE, genislik, spec.container
		)
		os.replace(gecici, _media_disk_path(url))

		_insert_video_rendition(
			asset_name,
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


def _produce_video_hls(
	teslim_yolu: str, teslim_facts: Any, asset_name: str, surum_hash: str
) -> str | None:
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
	profil: str,
	genislik: int,
	yukseklik: int,
	bicim: str,
	file_url: str,
	bayt: int,
	quality: int = 0,
) -> None:
	"""Video türev satırı. `benefit_gate_passed=1`: kapıdan düşen türev diske
	hiç yazılmadığı için satırı da yoktur (görselden fark — orada düşen türev
	kayda geçer; videoda düşen çıktı `os.replace` öncesi silinir)."""
	frappe.get_doc(
		{
			"doctype": "Media Rendition",
			"asset": asset_name,
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
	).insert(ignore_permissions=True)


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
) -> Any:
	"""Videonun `Media Version` kaydı (T-042'nin video karşılığı).

	Görseldeki `_ensure_version` ile aynı yarış sözleşmesi (`idempotent_create`).
	Geometri + süre TESLİM EDİLEN dosyanındır (manifest CLS/aspect-ratio bunu
	okur); `lqip` poster baytlarından dolar.
	"""
	from tradehub_core.media.pipeline.core import dedup

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
				"crop_intent_snapshot": None,
				"engine_version": _video_engine_version(),
				"created_at": now_datetime(),
				"is_active": 0,
				"width": int(teslim_facts.width or 0),
				"height": int(teslim_facts.height or 0),
				"duration_s": round(float(teslim_facts.duration_s or 0.0), 3),
				**_poster_enrichment(poster_yolu),
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def _catisma(exc: BaseException) -> bool:
		return isinstance(exc, (frappe.DuplicateEntryError, frappe.UniqueValidationError))

	kayit, _yeni = dedup.idempotent_create(surum_hash, _olustur, _bul, _catisma)
	return kayit
