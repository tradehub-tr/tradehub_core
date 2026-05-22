# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Seller Sub User Invite — satıcının çalışan davet kaydı.

Akış:
  1. Mağaza Sahibi (Owner/Co-Owner) `invite_sub_user` API'sını çağırır
  2. Raw token üretilir (secrets.token_urlsafe), SHA-256 hash DB'ye yazılır,
     raw token sadece e-postada gönderilir
  3. expires_at = now() + 7 gün
  4. status = Pending
  5. Email ile davet linki: /accept-invite?token=<raw>
  6. Hedef kullanıcı linke tıklar → accept_invite API → User + role profile + tenant set
  7. status = Accepted, created_user link set

Detay: docs/yetki/01-karar-dosyasi.md §5, §6.1
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SellerSubUserInvite(Document):
	def validate(self) -> None:
		self._validate_email()

	def _validate_email(self) -> None:
		"""E-posta formatı (basit kontrol — Frappe options=Email zaten validate eder)."""
		if not self.email or "@" not in self.email:
			frappe.throw(_("Geçerli bir e-posta adresi girin."))
		self.email = (self.email or "").strip().lower()

	def on_trash(self) -> None:
		"""Pending davet silinebilir; Accepted/Expired silinemez (audit için)."""
		if self.status in ("Accepted", "Expired"):
			frappe.throw(
				_("'{0}' durumundaki davet silinemez (audit için saklanır).").format(self.status),
				frappe.PermissionError,
			)
