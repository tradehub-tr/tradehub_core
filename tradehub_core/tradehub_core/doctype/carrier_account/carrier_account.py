# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Carrier Account — satıcı bazlı kargo taşıyıcı API hesabı (LOG-027/LOG-028).

Her satıcı (Admin Seller Profile) her taşıyıcı (Logistics Provider) için
en fazla bir aktif hesap tutabilir. Secret alanları (api_key, api_secret,
webhook_secret, access_token) Password fieldtype ile saklanır ve onload
sırasında view.carrier_secret capability olmayan kullanıcılara maskelenir.

Tenant izolasyonu: hooks.py doc_events üzerinden
tradehub_core.utils.tenant.enforce_seller_isolation_on_insert (before_insert)
ve validate_seller_isolation_on_save (validate) çift hook ile sağlanır.
Satır-düzeyi liste filtreleme: tradehub_core.logistics.permissions
(carrier_account_query_conditions + carrier_account_has_permission).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class CarrierAccount(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		self._validate_unique_active_account()

	def _validate_unique_active_account(self) -> None:
		"""Aynı seller_profile + carrier için ikinci aktif hesabı engelle."""
		if not self.is_active:
			return

		exists = frappe.db.exists(
			"Carrier Account",
			{
				"seller_profile": self.seller_profile,
				"carrier": self.carrier,
				"is_active": 1,
				"name": ["!=", self.name],
			},
		)
		if exists:
			frappe.throw(
				_("Bu satıcı için {0} taşıyıcısına ait zaten aktif bir hesap var").format(self.carrier)
			)

	def on_update(self) -> None:
		self._sync_default_flag()

	def _sync_default_flag(self) -> None:
		"""is_default=1 ise aynı seller+carrier'daki diğer default kayıtları temizle.

		frappe.db.set_value bilinçli tercih: diğer kayıtların validate/on_update
		zincirini tetiklememek için (get_doc().save() burada sonsuz döngü ve
		gereksiz hook maliyeti yaratırdı). Sadece is_default bayrağı düşürülüyor.
		"""
		if not self.is_default:
			return

		other_defaults = frappe.get_all(
			"Carrier Account",
			filters={
				"seller_profile": self.seller_profile,
				"carrier": self.carrier,
				"is_default": 1,
				"name": ["!=", self.name],
			},
			pluck="name",
		)
		for name in other_defaults:
			frappe.db.set_value("Carrier Account", name, "is_default", 0)

	def onload(self) -> None:
		"""view.carrier_secret capability olmayan kullanıcıya secret'ları maskele."""
		from tradehub_core.logistics.permissions import mask_carrier_account_fields

		mask_carrier_account_fields(self)
