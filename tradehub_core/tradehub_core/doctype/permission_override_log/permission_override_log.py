# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Permission Override Log — immutable manuel override kaydı.

`ignore_permissions=True` veya admin bypass kullanıldığında çağrılır.
justification ZORUNLU alan — kullanıcı gerekçe yazmak zorunda.

Detay: docs/yetki/03-doctype-sablonlari.md §8
"""

import frappe
from frappe import _
from frappe.model.document import Document


class PermissionOverrideLog(Document):
	def validate(self) -> None:
		if not self.flags.get("audit_write"):
			frappe.throw(
				_(
					"Permission Override Log doğrudan yazılamaz. "
					"tradehub_core.audit.log_override kullanın."
				),
				frappe.PermissionError,
			)
		if not (self.justification or "").strip():
			frappe.throw(_("Permission Override Log: justification (gerekçe) zorunludur."))

	def on_trash(self) -> None:
		if not self.flags.get("audit_archive"):
			frappe.throw(
				_("Permission Override Log silinemez — retention için scheduled arşiv yapılır."),
				frappe.PermissionError,
			)
