# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Role Change Log — immutable rol değişiklik kaydı.

Detay: docs/yetki/03-doctype-sablonlari.md §7
"""

import frappe
from frappe import _
from frappe.model.document import Document


class RoleChangeLog(Document):
	def validate(self) -> None:
		if not self.flags.get("audit_write"):
			frappe.throw(
				_("Role Change Log doğrudan yazılamaz. tradehub_core.audit.log_role_change kullanın."),
				frappe.PermissionError,
			)

	def on_trash(self) -> None:
		if not self.flags.get("audit_archive"):
			frappe.throw(
				_("Role Change Log silinemez — retention için scheduled arşiv yapılır."),
				frappe.PermissionError,
			)
