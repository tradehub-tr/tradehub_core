# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Authorization Decision Log — immutable yetki karar kaydı.

Bu doctype yalnızca `tradehub_core.audit.log.log_decision()` üzerinden yazılır.
Manuel insert/edit/delete YASAK — controller fırlatır.

Detay: docs/yetki/03-doctype-sablonlari.md §6
"""

import frappe
from frappe import _
from frappe.model.document import Document


class AuthorizationDecisionLog(Document):
	def validate(self) -> None:
		# Sadece audit helper'dan yazılabilir
		if not self.flags.get("audit_write"):
			frappe.throw(
				_("Authorization Decision Log doğrudan yazılamaz. tradehub_core.audit.log_decision kullanın."),
				frappe.PermissionError,
			)

	def before_update_after_submit(self) -> None:
		"""Kaydedildikten sonra değiştirilemez."""
		frappe.throw(
			_("Authorization Decision Log immutable — değiştirilemez."), frappe.PermissionError
		)

	def on_change(self) -> None:
		"""Mevcut kaydın değiştirilmesini engelle.

		Frappe before_save herhangi bir field değişikliğinde çağrılır.
		Yeni doc'lar OK (validate'te audit_write flag kontrolü), ama mevcut
		doc'un edit'i yasak.
		"""
		if self.has_value_changed("decision") or self.has_value_changed("action") or self.has_value_changed("actor"):
			# Modified-after-creation — yasak
			if not self.is_new() and not self.flags.get("audit_write"):
				frappe.throw(
					_("Authorization Decision Log immutable — değiştirilemez."), frappe.PermissionError
				)

	def on_trash(self) -> None:
		"""Silme yasak — sadece scheduled archive job (audit_archive flag)."""
		if not self.flags.get("audit_archive"):
			frappe.throw(
				_("Authorization Decision Log silinemez — retention için scheduled arşiv yapılır."),
				frappe.PermissionError,
			)
