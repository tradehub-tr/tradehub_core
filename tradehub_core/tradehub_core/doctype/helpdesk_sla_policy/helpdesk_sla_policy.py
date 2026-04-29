# Copyright (c) 2024, TR TradeHub and contributors

import frappe
from frappe.model.document import Document


class HelpdeskSLAPolicy(Document):
	def validate(self):
		if self.first_response_minutes is not None and self.first_response_minutes < 1:
			frappe.throw("İlk yanıt süresi en az 1 dakika olmalı.")
		if self.resolution_minutes is not None and self.resolution_minutes < 1:
			frappe.throw("Çözüm süresi en az 1 dakika olmalı.")
		if (
			self.first_response_minutes
			and self.resolution_minutes
			and self.resolution_minutes < self.first_response_minutes
		):
			frappe.throw("Çözüm süresi, ilk yanıt süresinden küçük olamaz.")
