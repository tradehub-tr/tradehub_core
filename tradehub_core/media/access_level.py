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
Private yapmak serbest.

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
from frappe.core.doctype.file.utils import check_path_safety
from frappe.utils import get_files_path

from tradehub_core.media import audit, presets, refs

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

	if not make_private and file_doc.attached_to_doctype in presets.EXCLUDED_DOCTYPES:
		audit.log_media_event(
			action=audit.ACTION_SCOPE_DENIED,
			file_url=url,
			allowed=False,
			reason="excluded_doctype_public",
			sensitive=True,
			context={"operation": "set_access_level", "attached_to_doctype": file_doc.attached_to_doctype},
		)
		frappe.throw(_("Bu belge herkese açık yapılamaz (KVKK/PII)."))

	currently_private = bool(file_doc.is_private)
	if currently_private == make_private:
		return {"file_url": url, "changed": False, "is_private": currently_private, "refs_updated": 0}

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

	audit.log_media_event(
		action=audit.ACTION_LEVEL_CHANGED,
		file_url=new_url,
		context={
			"old_url": url,
			"old_private": currently_private,
			"new_private": make_private,
			"refs_updated": ref_result["total"],
		},
	)

	return {
		"file_url": new_url,
		"changed": True,
		"is_private": make_private,
		"refs_updated": ref_result["total"],
	}
