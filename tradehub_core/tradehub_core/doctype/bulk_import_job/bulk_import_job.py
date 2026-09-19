# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

_ALLOWED_FILE_FORMATS = {"xlsx", "csv", "xml", "json"}  # json: Ürün API paketi (MOGEM-665)
_ALLOWED_UPDATE_MODES = {"insert_only", "upsert"}


class BulkImportJob(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok
		self._resolve_seller_profile_from_session()
		self._validate_enums()

	def _resolve_seller_profile_from_session(self):
		# Satıcı UI'dan job açtığında seller_profile boş gelirse session user
		# üzerinden Admin Seller Profile'ı bul. System Manager için boşsa hata.
		if self.seller_profile:
			return
		user = frappe.session.user
		seller = frappe.db.get_value("Admin Seller Profile", {"owner": user}, "name")
		if not seller:
			frappe.throw(_("Satıcı profili bulunamadı, lütfen seller_profile alanını doldurun"))
		self.seller_profile = seller

	def _validate_enums(self):
		if self.update_mode and self.update_mode not in _ALLOWED_UPDATE_MODES:
			frappe.throw(_("Geçersiz güncelleme modu: {0}").format(self.update_mode))
		if self.file_format and self.file_format not in _ALLOWED_FILE_FORMATS:
			frappe.throw(_("Geçersiz dosya formatı: {0}").format(self.file_format))
