# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""T-066 kalıcı varlık/aylık kalite raporu doğrulamaları."""

from __future__ import annotations

from calendar import monthrange

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

REPORT_ASSET = "asset"
REPORT_MONTHLY = "monthly"


class MediaQualityReport(Document):
	"""Ölçülen değerleri saklar; türetilen tasarruf alanları elle değiştirilemez."""

	def validate(self) -> None:
		if hasattr(super(), "validate"):
			super().validate()
		self.report_type = (self.report_type or REPORT_ASSET).strip().lower()
		if self.report_type not in {REPORT_ASSET, REPORT_MONTHLY}:
			frappe.throw(_("Bilinmeyen kalite raporu türü: {0}").format(self.report_type))
		self._validate_non_negative()
		if self.report_type == REPORT_ASSET:
			self._validate_asset_report()
		else:
			self._validate_monthly_report()

	def _validate_non_negative(self) -> None:
		for fieldname in (
			"input_bytes",
			"output_bytes",
			"processed_assets",
			"total_job_count",
			"failure_count",
		):
			value = self.get(fieldname)
			if value is not None and int(value or 0) < 0:
				frappe.throw(_("{0} negatif olamaz.").format(self.meta.get_label(fieldname)))

	def _validate_asset_report(self) -> None:
		if not self.asset:
			frappe.throw(_("Asset kalite raporunda varlık zorunludur."))
		input_bytes = int(self.input_bytes or 0)
		output_bytes = int(self.output_bytes or 0)
		self.saved_bytes = input_bytes - output_bytes
		self.saving_ratio = (self.saved_bytes / input_bytes) if input_bytes else None
		self.period_key = None
		self.period_start = None
		self.period_end = None

	def _validate_monthly_report(self) -> None:
		if not self.period_start or not self.period_end:
			frappe.throw(_("Aylık kalite raporunda dönem başlangıcı ve bitişi zorunludur."))
		if getdate(self.period_end) < getdate(self.period_start):
			frappe.throw(_("Dönem bitişi başlangıçtan önce olamaz."))
		period_start = getdate(self.period_start)
		period_end = getdate(self.period_end)
		if (
			period_start.day != 1
			or period_end.month != period_start.month
			or period_end.year != period_start.year
			or period_end.day != monthrange(period_start.year, period_start.month)[1]
		):
			frappe.throw(_("Aylık rapor tek bir takvim ayını kapsamalıdır."))
		self.period_key = period_start.strftime("%Y-%m")
		total_job_count = int(self.total_job_count or 0)
		failure_count = int(self.failure_count or 0)
		if failure_count > total_job_count:
			frappe.throw(_("Hatalı iş sayısı terminal iş sayısını aşamaz."))
		# Hata oranı kullanıcı girdisi değildir. Asset raporu sayısından bağımsız,
		# dönemin terminal normalize/rendition işlerinden yeniden türetilir.
		self.failure_rate = failure_count / total_job_count if total_job_count else 0
		self.asset = None
		self.version = None


__all__ = ["REPORT_ASSET", "REPORT_MONTHLY", "MediaQualityReport"]
