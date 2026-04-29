# Copyright (c) 2024, TR TradeHub and contributors

import frappe
from frappe.model.document import Document


class HelpdeskTicketTagLink(Document):
	def before_insert(self):
		if not self.tagged_by:
			self.tagged_by = frappe.session.user
		# Aynı ticket'a aynı tag iki kez eklenmesin
		if frappe.db.exists("Helpdesk Ticket Tag Link", {"ticket": self.ticket, "tag": self.tag}):
			frappe.throw("Bu etiket zaten bu talebe eklenmiş.")
