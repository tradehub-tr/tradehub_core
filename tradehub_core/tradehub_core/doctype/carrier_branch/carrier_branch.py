# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CarrierBranch(Document):
	def before_insert(self) -> None:
		# Frappe v15: set_new_name() validate'ten ÖNCE çalışır — autoname alanı
		# name'e küçük harfle geçmesin diye normalizasyon insert öncesi de yapılır
		if self.branch_code:
			self.branch_code = self.branch_code.strip().upper()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.branch_code:
			self.branch_code = self.branch_code.strip().upper()
		if frappe.db.exists(
			"Carrier Branch",
			{"carrier": self.carrier, "branch_code": self.branch_code, "name": ["!=", self.name]},
		):
			frappe.throw(_("Bu taşıyıcı için {0} şube kodu zaten tanımlı").format(self.branch_code))
