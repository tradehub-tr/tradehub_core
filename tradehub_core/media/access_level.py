"""Medya erişim-seviyesi toggle — public ↔ private (TUR-126 §4).

Bir medyanın erişim seviyesi bugüne kadar yüklemede sabitleniyordu. Süper-admin
artık yanlış yüklenen bir belgeyi private'a alabilir ya da bir tanıtım
görselini public yapabilir. Üç parça tek işlemde birleşiyor:

  1. **Fiziksel taşıma** — `private/files/<ab>/` ↔ `public/files/<ab>/`,
     shard + dosya adı korunur (bkz. `media/naming.py` içerik-hash isimlendirme).
  2. **`File` güncelleme** — `file_url` prefix'i + `is_private` bayrağı.
  3. **Referans güncelleme** — `media/refs.py`'ın bulma altyapısı üzerine:
     dosyayı gösteren tüm satırlar (`Listing.primary_image` vb.) yeni URL'e
     çevrilir, yoksa kırık görsel kalır.

**KYB/KYC koruması (kritik):** `presets.EXCLUDED_DOCTYPES`'e bağlı bir dosya
ASLA public yapılamaz — PII sızıntısı koruması, rol seviyesiyle de aşılamaz.
Private yapmak serbest. Bu kontrol İKİ bağımsız yoldan yapılır (`_is_protected_
pii`): `attached_to_doctype` DOĞRUDAN set edilmişse, YA DA dosya `presets.
EXCLUDED_MEDIA_FIELDS` haritasındaki bir alanda (`Seller Application.
identity_document` vb.) TERS REFERANS olarak duruyorsa — ikincisi olmadan
canlı DB'de 146 kimlik/PII belgesi (`attached_to_doctype` boş) korumayı
atlayıp public yapılabiliyordu (TUR-126 §4 review round 1 CRITICAL bulgusu).

**Atomiklik:** disk taşıması DB yazımlarından ÖNCE yapılır (tek atomik
`os.replace`), sonra `File` + referans güncellemeleri aynı transaction'da
yazılır. Sonraki adım (DB yazımı) patlarsa disk taşıması GERİ ALINIR —
aksi hâlde dosya yeni konumda, `File.file_url` eski konumu gösteriyor olurdu
(kırık referans). Trash akışının (`trash.py`) tersi sıra: orada disk hatası
DB'yi etkilemesin diye önce DB yazılıyor; burada disk adımının kendisi geri
alınabilir tek adım olduğu için önce o yapılıp hata durumunda elle geri
alınıyor.
"""

from __future__ import annotations

import os

import frappe
from frappe import _
from frappe.utils import get_files_path

from tradehub_core.media import audit, presets, refs
from tradehub_core.media.path_safety import check_path_safety

PUBLIC_PREFIX = "/files/"
PRIVATE_PREFIX = "/private/files/"


def _relative(url: str) -> str:
	"""URL'i prefix'siz, göreli disk yoluna çevirir (`ab/hash.ext`).

	Path traversal ve tanınmayan prefix burada reddedilir — `_disk_path` ikinci
	bir savunma katmanı olarak `check_path_safety` ile aynı kontrolü tekrar yapar.
	"""
	clean = (url or "").split("?")[0]
	if not clean or ".." in clean:
		frappe.throw(_("Geçersiz dosya yolu: {0}").format(url))
	if clean.startswith(PRIVATE_PREFIX):
		return clean[len(PRIVATE_PREFIX) :]
	if clean.startswith(PUBLIC_PREFIX):
		return clean[len(PUBLIC_PREFIX) :]
	frappe.throw(_("Desteklenmeyen dosya yolu: {0}").format(url))


def _disk_path(is_private: bool, relative: str) -> str:
	root = os.path.realpath(get_files_path(is_private=is_private))
	target = os.path.realpath(os.path.join(root, relative))
	if not check_path_safety(base_path=root, requested_path=target):
		frappe.throw(_("Dosya yolu kök dizinin dışında: {0}").format(relative))
	return target


def _is_protected_pii(file_doc, url: str) -> bool:
	"""Dosya `presets.EXCLUDED_DOCTYPES` kapsamında mı — İKİ bağımsız yoldan.

	1. `attached_to_doctype` doğrudan set edilmiş (yaygın yükleme yolu —
	   Frappe'nin standart Attach alanı akışı bunu otomatik doldurur).
	2. **TERS REFERANS** (TUR-126 §4 review round 1 CRITICAL bulgusu): bazı
	   hassas belgeler `attached_to_doctype` set edilmeden yükleniyor,
	   yalnız `presets.EXCLUDED_MEDIA_FIELDS` haritasındaki bir alanda Data/
	   Attach string'i olarak duruyor. Canlı DB'de doğrulandı:
	   `Seller Application.identity_document` 144 dosya, `Seller
	   Certification.document` 2 dosya — ikisi de `attached_to_doctype` BOŞ.
	   (1) tek başına bu 146 kimlik/PII belgesini (TC kimlik taraması
	   dahil) kaçırıp public yapılmasına izin veriyordu.
	"""
	if file_doc.attached_to_doctype in presets.EXCLUDED_DOCTYPES:
		return True
	for doctype, fields in presets.EXCLUDED_MEDIA_FIELDS.items():
		for field in fields:
			if frappe.db.exists(doctype, {field: url}):
				return True
	return False


def set_level(file_url: str, *, make_private: bool) -> dict:
	"""Bir dosyanın erişim seviyesini değiştir.

	Args:
	    file_url: `File.file_url` — `/files/...` ya da `/private/files/...`.
	    make_private: Hedef seviye. `True` → private, `False` → public.

	Returns:
	    `{"file_url", "changed", "is_private", "refs_updated"}`

	Zaten hedef seviyedeyse hiçbir şeye dokunulmadan `changed=False` döner
	(idempotent). KYB/KYC vb. kapsam dışı doctype'a bağlı dosya public
	yapılmak istenirse `frappe.throw` — bu kontrol `force` benzeri hiçbir
	parametreyle aşılamaz.
	"""
	url = (file_url or "").strip()
	if not url:
		frappe.throw(_("Dosya URL'i zorunlu."))

	file_doc = frappe.get_doc("File", {"file_url": url})

	if not make_private and _is_protected_pii(file_doc, url):
		audit.log_media_event(
			action=audit.ACTION_SCOPE_DENIED,
			file_url=url,
			allowed=False,
			reason="excluded_doctype_public",
			sensitive=True,
			context={"operation": "set_access_level"},
		)
		frappe.throw(_("Bu belge herkese açık yapılamaz (KVKK/PII)."))

	currently_private = bool(file_doc.is_private)
	if currently_private == make_private:
		return {"file_url": url, "changed": False, "is_private": currently_private, "refs_updated": 0}

	# Tarama akışı dosyayı fiziksel olarak taşıyabiliyor (TUR-125): bekletme
	# (`media_scan_hold`) ve karantina (`media_quarantine`) canlı ağacın DIŞINDA.
	# Bu kapı olmadan aşağıdaki `isfile` kontrolü "diskte bulunamadı" diyordu —
	# dosya var, yalnız başka kökte; mesaj yanıltıcıydı ve iki mekanizma aynı
	# dosyayı taşımak için yarışırdı (TUR-125 × TUR-296 dersi). Tarama bitip
	# dosya yerine dönene (ya da karantinadan çıkarılana) kadar seviye değişmez.
	from tradehub_core.media import av

	if av.in_quarantine(url) or av.in_hold(url):
		audit.log_media_event(
			action=audit.ACTION_LEVEL_CHANGED,
			file_url=url,
			allowed=False,
			reason="av_state_blocks_move",
			sensitive=True,
			context={"operation": "set_access_level"},
		)
		frappe.throw(
			_(
				"Dosya karantinada ya da tarama bekliyor; erişim seviyesi güvenlik "
				"akışı bitmeden değiştirilemez."
			)
		)

	relative = _relative(url)
	old_path = _disk_path(currently_private, relative)
	new_path = _disk_path(make_private, relative)

	if not os.path.isfile(old_path):
		frappe.throw(_("Dosya diskte bulunamadı: {0}").format(url))

	new_prefix = PRIVATE_PREFIX if make_private else PUBLIC_PREFIX
	new_url = new_prefix + relative

	frappe.create_folder(os.path.dirname(new_path))

	# Disk taşıması tek atomik adım (`os.replace`) — DB yazımlarından önce
	# yapılır ki bir sonraki adım patlarsa geri alınacak tek şey bu olsun.
	os.replace(old_path, new_path)

	try:
		frappe.db.set_value(
			"File",
			{"file_url": url},
			{"file_url": new_url, "is_private": int(make_private)},
			update_modified=False,
		)
		ref_result = refs.retarget(url, new_url)
	except Exception:
		frappe.db.rollback()
		try:
			os.replace(new_path, old_path)
		except Exception:
			frappe.log_error(
				title=f"Access level disk revert failed for {url}",
				message=frappe.get_traceback(with_context=True),
			)
		frappe.log_error(
			title=f"Access level change failed for {url}", message=frappe.get_traceback(with_context=True)
		)
		raise

	frappe.db.commit()

	# Bir geçiş her zaman kaynakta ya da hedefte bir private durumu içerir
	# (idempotent kontrolü ikisinin FARKLI olmasını zaten garanti ediyor) —
	# denetim kaydı bu yüzden hassas işaretlenir. `log_media_event` `file_url`
	# parametresini otomatik maskeler (object_name → masked:<fingerprint>),
	# ama yalnız context'teki SABİT üç anahtarı ("file_name"/"file_url"/
	# "attached_to_doctype") siler — bizim eklediğimiz özel anahtar
	# ("old_url" gibi) silinmeyip ham yolu context'ten geri sızdırırdı. Bu
	# yüzden hassas durumda ham yol hiç context'e konmaz, yalnız parmak izi.
	sensitive = currently_private or make_private
	context: dict = {
		"old_private": currently_private,
		"new_private": make_private,
		"refs_updated": ref_result["total"],
		"refs_skipped": len(ref_result["skipped"]),
	}
	if sensitive:
		context["old_url_fp"] = audit.fingerprint(url)
	else:
		context["old_url"] = url

	audit.log_media_event(
		action=audit.ACTION_LEVEL_CHANGED,
		file_url=new_url,
		sensitive=sensitive,
		context=context,
	)

	return {
		"file_url": new_url,
		"changed": True,
		"is_private": make_private,
		"refs_updated": ref_result["total"],
		# Operatör kırık-referans riskinden haberdar olsun: `retarget`'ın
		# atladığı (gömülü JSON, sipariş geçmişi) satırlar API cevabında da
		# görünür — yalnız audit'te kaybolmasınlar diye değil, çağıranın
		# kendisi de görsün diye (bkz. review round 1 Important #2).
		"refs_skipped": len(ref_result["skipped"]),
		"refs_skipped_detail": ref_result["skipped"][:10],
	}
