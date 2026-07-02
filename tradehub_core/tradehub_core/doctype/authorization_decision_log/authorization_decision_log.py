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
				_(
					"Authorization Decision Log doğrudan yazılamaz. tradehub_core.audit.log_decision kullanın."
				),
				frappe.PermissionError,
			)

	def before_insert(self) -> None:
		"""#F1 — Tamper-evident hash-chain: bu kaydın entry_hash'ini, içeriği +
		bir önceki kaydın entry_hash'i üzerinden hesapla."""
		from tradehub_core.audit.log import adl_entry_hash

		last = frappe.get_all(
			"Authorization Decision Log",
			fields=["entry_hash"],
			order_by="creation desc, name desc",
			limit=1,
		)
		self.prev_hash = (last[0].entry_hash if last else None) or "GENESIS"
		self.entry_hash = adl_entry_hash(self, self.prev_hash)

	def before_update_after_submit(self) -> None:
		"""Kaydedildikten sonra değiştirilemez."""
		frappe.throw(_("Authorization Decision Log immutable — değiştirilemez."), frappe.PermissionError)

	def on_change(self) -> None:
		"""#F1 — Kayıt oluşturulduktan sonra HİÇBİR alanı değiştirilemez (tam
		immutability). Yalnız insert (in_insert) ve retention arşiv (audit_archive)
		istisnadır; her diğer update yasak."""
		if self.flags.get("in_insert") or self.flags.get("audit_archive"):
			return
		frappe.throw(
			_("Authorization Decision Log immutable — hiçbir alanı değiştirilemez."),
			frappe.PermissionError,
		)

	def on_trash(self) -> None:
		"""Silme yasak — sadece scheduled archive job (audit_archive flag)."""
		if not self.flags.get("audit_archive"):
			frappe.throw(
				_("Authorization Decision Log silinemez — retention için scheduled arşiv yapılır."),
				frappe.PermissionError,
			)
