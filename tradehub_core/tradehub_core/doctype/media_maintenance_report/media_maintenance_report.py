# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Retention/tiering bakım koşumlarının değiştirilemez kanıt kaydı."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


IMMUTABLE_FIELDS = frozenset(
	{
		"job_type",
		"policy_hash",
		"dry_run",
		"status",
		"generated_at",
		"expires_at",
		"scanned",
		"candidates",
		"deleted",
		"demoted",
		"blocked",
		"failed",
		"bytes_candidate",
		"bytes_freed",
		"report_json",
		"error",
	}
)


class MediaMaintenanceReport(Document):
	def validate(self) -> None:
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		changed = [field for field in IMMUTABLE_FIELDS if before.get(field) != self.get(field)]
		if changed:
			frappe.throw(
				_("Bakım raporunun kanıt alanları değiştirilemez: {0}").format(", ".join(changed))
			)
		if before.approval_status in {"consumed", "rejected"} and (
			before.approval_status != self.approval_status
		):
			frappe.throw(_("Sonlandırılmış bakım raporu yeniden açılamaz."))
