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

# D.4: Planned → In Progress → Arrived → Completed (sıralı).
# P1-5: Cancelled geçişi terminal-olmayan her durumdan yapılabilir; Completed
# TERMİNALDİR — Completed → Cancelled kapalıdır (tamamlanmış bacak iptal edilemez).
_LEG_TRANSITIONS: dict[str, set[str]] = {
	LegStatus.PLANNED: {LegStatus.IN_PROGRESS, LegStatus.CANCELLED},
	LegStatus.IN_PROGRESS: {LegStatus.ARRIVED, LegStatus.CANCELLED},
	LegStatus.ARRIVED: {LegStatus.COMPLETED, LegStatus.CANCELLED},
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
		self._validate_leg_sequence_unique()

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
		"""Planned → In Progress → Arrived → Completed; terminal olmayanlardan → Cancelled.

		P1-5: Completed terminaldir (Cancelled dahil hiçbir geçiş yok) ve yeni
		bacak yalnız Planned durumuyla doğabilir — farklı bir status ile insert
		durum sırasını baypas ederdi. Boş status kabul edilir: JSON default'u
		Planned atar.
		"""
		if self.is_new():
			if self.status and self.status != LegStatus.PLANNED:
				frappe.throw(
					_("Yeni sevkiyat bacağı yalnız Planned durumuyla oluşturulabilir; mevcut: {0}").format(
						_(self.status)
					)
				)
			return

		before = self.get_doc_before_save()
		if before is None or before.status == self.status:
			return

		allowed: set[str] = _LEG_TRANSITIONS.get(before.status, set())
		if self.status not in allowed:
			frappe.throw(
				_("Geçersiz bacak durum geçişi: {0} → {1}").format(_(before.status), _(self.status))
			)

	def _validate_leg_sequence_unique(self) -> None:
		"""P1-5: aynı Shipment içinde leg_sequence tekil olmalı.

		Duplicate sıra numarası rota sıralamasını belirsizleştirir; kendi
		kaydı (name) hariç tutularak update senaryosu yanlış pozitife düşmez.
		"""
		if not self.shipment or self.leg_sequence is None:
			return

		duplicate = frappe.db.exists(
			"Shipment Leg",
			{
				"shipment": self.shipment,
				"leg_sequence": self.leg_sequence,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_("Bacak sırası {0} bu sevkiyatta zaten kullanılmış; leg_sequence tekil olmalıdır.").format(
					self.leg_sequence
				)
			)
