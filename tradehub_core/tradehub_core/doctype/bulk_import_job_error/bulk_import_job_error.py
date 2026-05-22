# Copyright (c) 2026, TradeHub Team and contributors

import frappe
from frappe import _
from frappe.model.document import Document


class BulkImportJobError(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok
		if not self.error_message:
			frappe.throw(_("Hata mesajı zorunludur"))
