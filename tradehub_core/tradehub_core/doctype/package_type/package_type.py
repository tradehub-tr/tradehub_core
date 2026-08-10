# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PackageType(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.package_code:
			self.package_code = self.package_code.strip().upper()

	def on_update(self) -> None:
		if self.is_default:
			self._unset_other_defaults()

	def _unset_other_defaults(self) -> None:
		"""Tek default garantisi: bu kayıt default işaretlendiyse diğerlerini sıfırla.

		Bilinçli olarak frappe.db.set_value kullanılıyor — diğer kayıtların
		validate zincirini tetiklememek için (doc.save yerine doğrudan DB yazımı).
		"""
		others = frappe.get_all(
			"Package Type",
			filters={"is_default": 1, "name": ["!=", self.name]},
			pluck="name",
		)
		for name in others:
			frappe.db.set_value("Package Type", name, "is_default", 0)
