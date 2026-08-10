# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ServiceCoverageArea(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.carrier_service:
			service_carrier = frappe.db.get_value("Carrier Service", self.carrier_service, "carrier")
			if service_carrier != self.carrier:
				frappe.throw(_("Seçilen servis {0} taşıyıcısına ait değil").format(self.carrier))
