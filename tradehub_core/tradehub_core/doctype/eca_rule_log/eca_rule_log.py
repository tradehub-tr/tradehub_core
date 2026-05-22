# Copyright (c) 2026, TradeHub Team and contributors

import frappe
from frappe import _
from frappe.model.document import Document

_VALID_STATUSES = {"success", "condition_false", "action_failed", "error"}


class ECARuleLog(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok
		if self.status and self.status not in _VALID_STATUSES:
			frappe.throw(_("Geçersiz log durumu: {0}").format(self.status))
