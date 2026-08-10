# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ShipmentExceptionCode(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.exception_code:
			self.exception_code = self.exception_code.strip().upper()
