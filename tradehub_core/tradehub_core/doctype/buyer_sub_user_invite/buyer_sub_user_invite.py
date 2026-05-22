# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Buyer Sub User Invite — B2B alıcı çalışan davet kaydı.

Seller Sub User Invite ile aynı pattern; sadece tenant Admin Seller Profile
yerine Organization (buyer_org). Detay: docs/yetki/faz-2/03-faz-2-detayli-plan.md §2.4
"""

import frappe
from frappe import _
from frappe.model.document import Document


class BuyerSubUserInvite(Document):
	def validate(self) -> None:
		self._validate_email()

	def _validate_email(self) -> None:
		if not self.email or "@" not in self.email:
			frappe.throw(_("Geçerli bir e-posta adresi girin."))
		self.email = (self.email or "").strip().lower()

	def on_trash(self) -> None:
		if self.status in ("Accepted", "Expired"):
			frappe.throw(
				_("'{0}' durumundaki davet silinemez (audit için saklanır).").format(self.status),
				frappe.PermissionError,
			)
