# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LogisticsProvider(Document):
	def before_insert(self) -> None:
		# Frappe v15: set_new_name() validate'ten ÖNCE çalışır — autoname alanı
		# name'e küçük harfle geçmesin diye normalizasyon insert öncesi de yapılır
		if self.provider_code:
			self.provider_code = self.provider_code.strip().upper()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.provider_code:
			self.provider_code = self.provider_code.strip().upper()
		if frappe.db.exists(
			"Logistics Provider",
			{"provider_code": self.provider_code, "name": ["!=", self.name]},
		):
			frappe.throw(_("Sağlayıcı kodu {0} zaten kullanılıyor").format(self.provider_code))
