# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Subscription Payment — havale/EFT tabanlı abonelik ödeme talebi.

Ödeme gateway'i yok; satıcı paket seçince `pending` bir kayıt oluşur, banka
bilgileri + referans kodu gösterilir. Satıcı havale yapar, admin panelden
`confirmed` yapınca abonelik aktive edilir (bkz. api/v1/subscription_payment).
"""

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SubscriptionPayment(Document):
	def before_insert(self) -> None:
		if not self.requested_at:
			self.requested_at = now_datetime()
		if not self.reference_code:
			self.reference_code = self._generate_reference_code()

	def _generate_reference_code(self) -> str:
		"""Banka açıklamasına yazılacak, insan-okunur eşleştirme kodu.

		Format: ISTOC-<store>-<5hex>  (ör. ISTOC-SEL-00002-A1B2C)
		"""
		suffix = frappe.generate_hash(length=5).upper()
		return f"ISTOC-{self.store}-{suffix}"
