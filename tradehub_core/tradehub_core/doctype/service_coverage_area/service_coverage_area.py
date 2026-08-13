# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.patches.normalize_address_provinces_diacritics import ASCII_TO_DIACRITIC


class ServiceCoverageArea(Document):
	def before_insert(self) -> None:
		# Frappe v15: set_new_name() validate'ten ÖNCE çalışır. autoname
		# format:{carrier}-{carrier_service}-{city}-{district} olduğu için
		# normalizasyon insert öncesi de yapılmalı — yoksa "Istanbul" ve
		# "İstanbul" iki ayrı kayıt adı üretir ve benzersizlik kısıtı delinir.
		self._normalize_area()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		self._normalize_area()
		self._validate_service_belongs_to_carrier()

	def _normalize_area(self) -> None:
		"""İl/ilçe değerlerini projenin kanonik biçimine çevirir.

		Kanonik biçim **diakritikli Türkçe**dir ("İstanbul", "Şanlıurfa") —
		storefront ve admin-panel il listeleri bu biçimi kullanıyor ve ilçe
		lookup'ı exact-match çalışıyor. Eşleme tablosu
		`patches/normalize_address_provinces_diacritics` içinde; burada
		kopyalanmıyor ki iki kaynak sürüklenmesin.
		"""
		if self.city:
			city = self.city.strip()
			self.city = ASCII_TO_DIACRITIC.get(city, city)
		if self.district:
			self.district = self.district.strip()

	def _validate_service_belongs_to_carrier(self) -> None:
		if not self.carrier_service:
			return
		service_carrier = frappe.db.get_value("Carrier Service", self.carrier_service, "carrier")
		if service_carrier != self.carrier:
			frappe.throw(_("Seçilen servis {0} taşıyıcısına ait değil").format(self.carrier))
