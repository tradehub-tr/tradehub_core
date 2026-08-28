# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from tradehub_core.logistics.constants import MIN_INTEGRATION_LOG_RETENTION_DAYS


class LogisticsSettings(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok (carrier_account emsali)
		self._validate_desi_divisor()
		self._validate_integration_log_retention()

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

	def _validate_integration_log_retention(self) -> None:
		"""Entegrasyon logu saklama süresine ALT SINIR koyar (denetim 2026-08-28).

		`0` (ve boş) "saklama kapalı" anlamındadır — `integration_log_retention.
		get_retention_days` / `purge_expired_integration_logs` sözleşmesi bu;
		korunuyor. `0` dışındaki her değer `MIN_INTEGRATION_LOG_RETENTION_DAYS`
		altına inemez.

		NEDEN: ÖLÇÜLDÜ — Marketplace Admin alanı `1` (hatta `-5`) yapabiliyordu
		ve değer DB'ye yazılıyordu; `1` gün, ertesi günkü saklama koşumunun
		entegrasyon/denetim izini imha etmesi demekti. Silme DocPerm'i
		kaldırıldığı için geriye kalan tek silme yolu saklama işi; o yol da bir
		alt sınıra bağlı olmak zorunda.

		NEGATİF ARTIK REDDEDİLİYOR: saklama işi negatifi "kapalı" sayıyor, ama
		"kapalı"yı zaten `0` ifade ediyor. İki farklı gösterim, alanın yanlışlıkla
		negatif bırakıldığı bir düzenlemeyi "bilinçli kapatma"dan ayırt
		edilemez kılıyordu.
		"""
		value = self.get("integration_log_retention_days")
		if value in (None, ""):
			return

		days = cint(value)
		if days == 0:
			return

		if days < MIN_INTEGRATION_LOG_RETENTION_DAYS:
			frappe.throw(
				_(
					"Entegrasyon logu saklama süresi en az {0} gün olmalıdır"
					" (0 = saklama kapalı); mevcut: {1}"
				).format(MIN_INTEGRATION_LOG_RETENTION_DAYS, value)
			)
