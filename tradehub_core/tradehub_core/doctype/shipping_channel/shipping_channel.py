# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ShippingChannel(Document):
	def before_insert(self) -> None:
		# Frappe v15: set_new_name() validate'ten ÖNCE çalışır — autoname alanı
		# name'e küçük harfle geçmesin diye normalizasyon insert öncesi de yapılır
		if self.channel_code:
			self.channel_code = self.channel_code.strip().upper()

	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		if self.channel_code:
			self.channel_code = self.channel_code.strip().upper()
