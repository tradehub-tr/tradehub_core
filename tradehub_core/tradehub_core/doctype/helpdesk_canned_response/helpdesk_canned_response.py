# Copyright (c) 2024, TR TradeHub and contributors

import frappe
from frappe.model.document import Document


class HelpdeskCannedResponse(Document):
	def validate(self):
		if self.scope == "team" and not self.created_by_team:
			frappe.throw("scope=team ise bir Ekip seçmelisiniz.")
		if not (self.content or "").strip():
			frappe.throw("Mesaj içeriği boş olamaz.")
