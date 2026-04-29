# Copyright (c) 2024, TR TradeHub and contributors

import json

import frappe
from frappe.model.document import Document


class HelpdeskSavedFilter(Document):
	def before_insert(self):
		if not self.owner_user:
			self.owner_user = frappe.session.user

	def validate(self):
		if not (self.label or "").strip():
			frappe.throw("Görünüm adı boş olamaz.")
		if self.filters_json:
			try:
				json.loads(self.filters_json)
			except (TypeError, ValueError):
				frappe.throw("Filtre JSON geçersiz.")
