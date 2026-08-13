# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class LogisticsSettings(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok (carrier_account emsali)
		self._validate_desi_divisor()

	def _validate_desi_divisor(self) -> None:
		"""P1-6c: default_desi_divisor boş değilse pozitif olmalı.

		Boş/0 değer "ayarlanmamış" sayılır (get_desi_divisor kendi
		DEFAULT_DESI_DIVISOR fallback'ine düşer); negatif değer desi
		hesabını bozacağından reddedilir.
		"""
		value = self.get("default_desi_divisor")
		if value in (None, 0, ""):
			return

		if cint(value) <= 0:
			frappe.throw(
				_("Varsayılan desi böleni pozitif bir sayı olmalıdır; mevcut: {0}").format(value)
			)
