# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.logistics.constants import ShipmentStatus


class CarrierStatusMapping(Document):
	def before_insert(self) -> None:
		# Frappe v15: set_new_name() validate'ten ÖNCE çalışır; autoname
		# format:{carrier}-{carrier_status_code} olduğu için boşluk temizliği
		# insert öncesi de yapılmalı, yoksa " YK01 " ayrı bir kayıt adı üretir.
		self._normalize_status_code()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		self._normalize_status_code()
		self._validate_unique_mapping()
		self._validate_internal_status()

	def _normalize_status_code(self) -> None:
		"""Taşıyıcı durum kodundaki baş/son boşlukları temizler.

		Büyük/küçük harf DEĞİŞTİRİLMEZ — kod taşıyıcının API yanıtıyla birebir
		eşleşmek zorunda ve bazı taşıyıcılar case-sensitive kod döndürüyor.
		"""
		if self.carrier_status_code:
			self.carrier_status_code = self.carrier_status_code.strip()

	def _validate_unique_mapping(self) -> None:
		"""Aynı taşıyıcı + durum kodu ikilisi yalnızca bir kez eşlenebilir.

		DB seviyesinde `autoname: format:{carrier}-{carrier_status_code}` de aynı
		garantiyi veriyor (yarış koşuluna karşı). Buradaki kontrol kullanıcıya
		anlaşılır hata mesajı göstermek için duruyor.
		"""
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
