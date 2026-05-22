# Copyright (c) 2026, TradeHub Team and contributors

import frappe
from frappe import _
from frappe.model.document import Document

_ALLOWED_FORMATS = {"xlsx", "csv", "xml"}


class SellerTemplateProfile(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok
		if not self.seller:
			frappe.throw(_("Satıcı (seller) alanı zorunludur"))
		if not self.fingerprint:
			frappe.throw(_("Fingerprint alanı zorunludur"))
		if self.source_format and self.source_format not in _ALLOWED_FORMATS:
			frappe.throw(_("Geçersiz kaynak format: {0}").format(self.source_format))
