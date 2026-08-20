"""Dosya ↔ klasör bağı (T-094).

**Neden `tabFile`'a custom field DEĞİL, ayrı bağlantı kaydı — ölçülen üç sebep:**

  1. Aynı adres birden çok mağazaya ait olabiliyor (ölçüm: 30 adres iki
     mağazada, bkz. `media/ownership.py`). Klasör mağazanın kendi düzenidir;
     `tabFile.th_media_folder` gibi tek bir alan, iki mağazanın aynı dosyayı
     FARKLI klasörlere koymasını temsil edemezdi.
  2. Sahiplik yalnız "kim yükledi" değil "kim kullanıyor" ile de kurulur
     (`ownership.owners_of`). Kullanım yoluyla sahip olunan dosyanın `File`
     satırı BAŞKA mağazanın kullanıcısına aittir; custom field'a yazmak ya o
     satırı kirletir ya da (metadata modülündeki gibi yalnız kendi satırına
     yazınca) hiçbir satır bulunamaz ve taşıma sessizce kaybolurdu.
  3. Türev dosyalar `File` kaydı açmıyor (MEDYA-DEPOLAMA-STANDARDI.md §3.2 ve
     mimari not); `tabFile` şemasına bağlanan her özellik bu dosyalar için
     baştan çalışmaz. Bağı `file_url` üzerinden ayrı tabloda tutmak `File`
     satırının varlığına yaslanmaz.

  Ek kazanç: custom field patch'i ve migrate koordinasyonu gerekmez.

**Benzersizlik (store, file_url) — bir dosya, bir mağazada, en çok bir
klasörde.** DB kısıtı yerine `validate` + taşıma ucundaki sil-sonra-yaz
akışıyla korunur: `file_url` 500 karaktere kadar çıkabildiği için birleşik
benzersiz indeks utf8mb4'te indeks boyu sınırına dayanırdı.

İzolasyon `Media Folder` ile aynı iki katman: uç-içi mağaza karşılaştırması +
aşağıdaki hook fonksiyonları (hooks.py kaydı raporda).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

_ADMIN_ROLES: tuple[str, ...] = ("System Manager", "Marketplace Admin")


class MediaFolderItem(Document):
	def validate(self) -> None:
		self.file_url = (self.file_url or "").split("?")[0].strip()
		if not self.file_url:
			frappe.throw(_("Dosya adresi boş olamaz."))
		klasor_magazasi = frappe.db.get_value("Media Folder", self.folder, "store")
		if not klasor_magazasi:
			frappe.throw(_("Klasör bulunamadı."), frappe.DoesNotExistError)
		if klasor_magazasi != self.store:
			# "bulunamadı": başka mağazanın klasör kimliğini doğrulamamak için
			# (ownership.assert_owns ile aynı ilke).
			frappe.throw(_("Klasör bulunamadı."), frappe.DoesNotExistError)
		if frappe.db.exists(
			"Media Folder Item",
			{"store": self.store, "file_url": self.file_url, "name": ["!=", self.name]},
		):
			frappe.throw(
				_("Dosya zaten bir klasörde. Taşıma ucu eski bağı silmeden yazmış."),
				frappe.DuplicateEntryError,
			)


def get_permission_query_conditions(user: str | None = None) -> str:
	"""hooks.py kaydı (raporda):

	    "Media Folder Item": "tradehub_core.tradehub_core.doctype.media_folder_item.media_folder_item.get_permission_query_conditions"
	"""
	from tradehub_core.media import ownership

	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"
	roller = frappe.get_roles(user)
	if any(r in roller for r in _ADMIN_ROLES):
		return ""
	store = ownership.store_of(user)
	if not store:
		return "1=0"
	return f"`tabMedia Folder Item`.`store` = {frappe.db.escape(store)}"


def has_permission(doc, user: str | None = None, permission_type: str = "") -> bool:
	"""hooks.py kaydı (raporda):

	    "Media Folder Item": "tradehub_core.tradehub_core.doctype.media_folder_item.media_folder_item.has_permission"
	"""
	from tradehub_core.media import ownership

	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	roller = frappe.get_roles(user)
	if any(r in roller for r in _ADMIN_ROLES):
		return True
	store = ownership.store_of(user)
	return bool(store) and getattr(doc, "store", None) == store
