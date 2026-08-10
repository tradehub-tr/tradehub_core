# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LogisticsProvider(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.provider_code:
			self.provider_code = self.provider_code.strip().upper()
		if frappe.db.exists(
			"Logistics Provider",
			{"provider_code": self.provider_code, "name": ["!=", self.name]},
		):
			frappe.throw(_("Sağlayıcı kodu {0} zaten kullanılıyor").format(self.provider_code))
