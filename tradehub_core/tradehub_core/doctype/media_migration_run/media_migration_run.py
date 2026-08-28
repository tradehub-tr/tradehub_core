"""Kalıcı medya migration koşumu ve durum doğrulamaları."""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

PLAN_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {
	"planned",
	"queued",
	"running",
	"paused",
	"halted",
	"stopping",
	"stopped",
	"completed",
	"validating",
	"validated",
	"validation_failed",
	"rolling_back",
	"rolled_back",
	"rollback_failed",
	"failed",
}


class MediaMigrationRun(Document):
	def before_insert(self) -> None:
		if not self.requested_by:
			self.requested_by = frappe.session.user

	def validate(self) -> None:
		if self.status not in _STATUSES:
			frappe.throw(_("Geçersiz migration durumu: {0}").format(self.status))
		if int(self.plan_schema_version or 0) != PLAN_SCHEMA_VERSION:
			frappe.throw(_("Desteklenmeyen migration plan sürümü: {0}").format(self.plan_schema_version))
		if not _SHA256.fullmatch((self.plan_digest or "").strip()):
			frappe.throw(_("Plan özeti 64 karakterlik SHA-256 olmalıdır."))
		batch_size = int(self.batch_size or 0)
		if not 1 <= batch_size <= 2000:
			frappe.throw(_("Batch boyutu 1 ile 2000 arasında olmalıdır."))
		for fieldname in (
			"total_files",
			"total_batches",
			"next_batch_index",
			"rollback_batch_index",
			"processed",
			"optimized",
			"skipped",
			"errors",
			"original_bytes",
			"new_bytes",
			"notifications_sent",
			"notifications_skipped",
		):
			if int(self.get(fieldname) or 0) < 0:
				frappe.throw(_("{0} negatif olamaz.").format(fieldname))
		if not int(self.dry_run or 0) and not self.approved_dry_run:
			frappe.throw(_("Gerçek koşum için doğrulanmış kuru koşum zorunludur."))
