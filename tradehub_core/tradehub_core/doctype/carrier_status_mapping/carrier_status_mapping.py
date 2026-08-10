# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.logistics.constants import ShipmentStatus


class CarrierStatusMapping(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		self._validate_unique_mapping()
		self._validate_internal_status()

	def _validate_unique_mapping(self) -> None:
		"""Aynı taşıyıcı + durum kodu ikilisi yalnızca bir kez eşlenebilir."""
		exists = frappe.db.exists(
			"Carrier Status Mapping",
			{
				"carrier": self.carrier,
				"carrier_status_code": self.carrier_status_code,
				"name": ["!=", self.name],
			},
		)
		if exists:
			frappe.throw(
				_("{0} taşıyıcısı için {1} durum kodu zaten eşlenmiş").format(
					self.carrier, self.carrier_status_code
				)
			)

	def _validate_internal_status(self) -> None:
		"""internal_status, ShipmentStatus.ALL sabitleriyle uyumlu olmalı."""
		if self.internal_status not in ShipmentStatus.ALL:
			frappe.throw(
				_("Geçersiz dahili durum: {0}. İzin verilen değerler: {1}").format(
					self.internal_status, ", ".join(ShipmentStatus.ALL)
				)
			)
