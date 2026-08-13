# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Shipment Leg — çok bacaklı sevkiyat bacağı (TUR-105 / LOG-040).

Bilinçli olarak child table DEĞİL, standalone DocType: bacaklar bağımsız
durum güncellemesi alır, Shipment Event kayıtları leg'e link'lenir ve
permission_query_conditions ile satır düzeyi tenant filtrelemesi gerekir.

seller_profile, tenant izolasyonu için Shipment'tan denormalize edilir —
before_insert + validate çift hook konvansiyonu ile hem doldurulur hem
tutarlılığı doğrulanır.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.logistics.constants import LegStatus

# D.4: Planned → In Progress → Arrived → Completed (sıralı);
# Cancelled geçişi ayrıca ele alınır (herhangi bir durumdan iptal edilebilir).
_LEG_TRANSITIONS: dict[str, set[str]] = {
	LegStatus.PLANNED: {LegStatus.IN_PROGRESS},
	LegStatus.IN_PROGRESS: {LegStatus.ARRIVED},
	LegStatus.ARRIVED: {LegStatus.COMPLETED},
	LegStatus.COMPLETED: set(),
	LegStatus.CANCELLED: set(),
}


class ShipmentLeg(Document):
	def before_insert(self) -> None:
		self._set_seller_profile_from_shipment()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok (carrier_account emsali)
		self._validate_seller_profile_matches_shipment()
		self._validate_status_transition()

	# -------------------------------------------------------------------
	# Tenant izolasyonu — before_insert + validate çift hook
	# -------------------------------------------------------------------
	def _set_seller_profile_from_shipment(self) -> None:
		"""seller_profile'ı bağlı Shipment'tan otomatik doldur (denormalize)."""
		if self.shipment and not self.seller_profile:
			self.seller_profile = frappe.db.get_value("Shipment", self.shipment, "seller_profile")

	def _validate_seller_profile_matches_shipment(self) -> None:
		"""seller_profile her zaman bağlı Shipment'ınkiyle aynı olmalı (tamper koruması)."""
		if not self.shipment:
			return

		shipment_seller: str | None = frappe.db.get_value(
			"Shipment", self.shipment, "seller_profile"
		)
		if not self.seller_profile:
			self.seller_profile = shipment_seller
		elif shipment_seller and self.seller_profile != shipment_seller:
			frappe.throw(_("Bacak satıcı profili bağlı sevkiyatın satıcı profiliyle eşleşmiyor."))

	# -------------------------------------------------------------------
	# Durum geçişi (D.4 — basit sıra kuralı)
	# -------------------------------------------------------------------
	def _validate_status_transition(self) -> None:
		"""Planned → In Progress → Arrived → Completed; herhangi bir durumdan → Cancelled."""
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if before is None or before.status == self.status:
			return

		if self.status == LegStatus.CANCELLED:
			return  # D.4: herhangi bir durumdan iptale geçilebilir

		allowed: set[str] = _LEG_TRANSITIONS.get(before.status, set())
		if self.status not in allowed:
			frappe.throw(
				_("Geçersiz bacak durum geçişi: {0} → {1}").format(_(before.status), _(self.status))
			)
