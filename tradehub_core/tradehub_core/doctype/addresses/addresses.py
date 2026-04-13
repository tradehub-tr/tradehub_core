"""
Addresses — polimorfik adres DocType'ı.

Hem Buyer (user tabanlı) hem Seller (seller_profile tabanlı) adreslerini tutar.
Ayrım `kind` field'ı ile yapılır.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class Addresses(Document):
	def validate(self):
		self._validate_owner_by_kind()

	def _validate_owner_by_kind(self):
		"""kind'e göre user/seller exclusive zorunluluk."""
		if self.kind == "Buyer":
			if not self.user:
				frappe.throw(_("Buyer adresi için 'user' alanı zorunludur."))
			# Buyer scope'unda seller bilgisi taşımamalı
			self.seller = None
		elif self.kind == "Seller":
			if not self.seller:
				frappe.throw(_("Seller adresi için 'seller' alanı zorunludur."))
			# Seller kaydında user alanını otomatik Seller Profile'ın user'ı ile doldur
			# (permission / if_owner için gerekebilir)
			if not self.user:
				profile_user = frappe.db.get_value("Seller Profile", self.seller, "user")
				if profile_user:
					self.user = profile_user
		else:
			frappe.throw(_("Geçersiz adres türü: {0}").format(self.kind))
