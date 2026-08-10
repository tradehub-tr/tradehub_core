# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class VehicleType(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.vehicle_code:
			self.vehicle_code = self.vehicle_code.strip().upper()
