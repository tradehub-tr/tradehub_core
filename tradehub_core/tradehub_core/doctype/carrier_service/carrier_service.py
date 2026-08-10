# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CarrierService(Document):
	def before_insert(self) -> None:
		# Frappe v15: set_new_name() validate'ten ÖNCE çalışır — autoname alanı
		# name'e küçük harfle geçmesin diye normalizasyon insert öncesi de yapılır
		if self.service_code:
			self.service_code = self.service_code.strip().upper()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.service_code:
			self.service_code = self.service_code.strip().upper()
		if (
			self.estimated_days_min
			and self.estimated_days_max
			and self.estimated_days_max < self.estimated_days_min
		):
			frappe.throw(_("Maksimum tahmini gün, minimum tahmini günden küçük olamaz"))
