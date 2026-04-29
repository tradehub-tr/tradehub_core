# Copyright (c) 2024, TR TradeHub and contributors

import frappe
from frappe.model.document import Document


class HelpdeskTicketTag(Document):
	def validate(self):
		if not (self.tag_name or "").strip():
			frappe.throw("Etiket adı boş olamaz.")
		# normalize: lowercase, no spaces
		self.tag_name = self.tag_name.strip().lower().replace(" ", "-")
