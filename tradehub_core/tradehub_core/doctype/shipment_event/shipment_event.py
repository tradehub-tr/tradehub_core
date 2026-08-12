# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Shipment Event — append-only sevkiyat olay günlüğü (TUR-105 / LOG-041).

Webhook / polling / manuel kaynaklı taşıyıcı olaylarını saklar. G.5/G.6
idempotency stratejisinin 3. katmanı: event_hash unique index'i duplicate
webhook insert'lerini engeller.

APPEND-ONLY: kayıt oluşturulduktan sonra güncellenemez; silme yalnız
System Manager'a (ve Administrator'a) açıktır.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ShipmentEvent(Document):
	def before_insert(self) -> None:
		self._set_seller_profile_from_shipment()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok (carrier_account emsali)
		if not self.is_new():
			frappe.throw(_("Shipment Event kayıtları append-only'dir; güncellenemez."))
		# Tenant izolasyonu — before_insert + validate çift hook konvansiyonu.
		# F4: boş seller_profile doldurulur (before_insert akışı korunur), dolu
		# ama Shipment'la uyuşmayan değer throw eder (spoofing koruması).
		self._validate_seller_profile_matches_shipment()

	def on_trash(self) -> None:
		"""Append-only: System Manager dışında silme yok."""
		user: str = frappe.session.user
		if user == "Administrator":
			return
		if "System Manager" not in frappe.get_roles(user):
			frappe.throw(
				_("Shipment Event kayıtları silinemez (append-only)."),
				frappe.PermissionError,
			)

	def _set_seller_profile_from_shipment(self) -> None:
		"""seller_profile'ı bağlı Shipment'tan otomatik doldur (denormalize)."""
		if self.shipment and not self.seller_profile:
			self.seller_profile = frappe.db.get_value("Shipment", self.shipment, "seller_profile")

	def _validate_seller_profile_matches_shipment(self) -> None:
		"""seller_profile her zaman bağlı Shipment'ınkiyle aynı olmalı (tamper koruması).

		Shipment Leg._validate_seller_profile_matches_shipment emsali (F4):
		boş değer Shipment'tan doldurulur, uyuşmayan değer reddedilir.
		"""
		if not self.shipment:
			return

		shipment_seller: str | None = frappe.db.get_value(
			"Shipment", self.shipment, "seller_profile"
		)
		if not self.seller_profile:
			self.seller_profile = shipment_seller
		elif shipment_seller and self.seller_profile != shipment_seller:
			frappe.throw(_("Olay satıcı profili bağlı sevkiyatın satıcı profiliyle eşleşmiyor."))
