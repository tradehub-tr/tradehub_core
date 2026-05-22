# Copyright (c) 2026, TradeHub Team and contributors

import frappe
from frappe import _
from frappe.model.document import Document

_SELLER_ALLOWED_ACTIONS = {"field_update", "email", "webhook", "reject_row"}
_ADMIN_ROLES = {"System Manager", "Marketplace Admin"}


class ECAActionTemplate(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok
		self._validate_seller_action_scope()

	def _validate_seller_action_scope(self):
		# Custom Script + Create Document yalnızca admin/system roller içindir.
		# Satıcı kullanıcılar bu tipi şablon olarak kaydedemez.
		user = frappe.session.user
		if user == "Administrator":
			return
		roles = set(frappe.get_roles(user))
		if roles & _ADMIN_ROLES:
			return
		if self.action_type not in _SELLER_ALLOWED_ACTIONS:
			frappe.throw(
				_("Bu aksiyon tipi sadece admin/system rolleri için kullanılabilir: {0}").format(
					self.action_type
				)
			)
