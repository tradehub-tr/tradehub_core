"""Media Migration Batch bütünlük doğrulamaları."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

_TERMINAL = {"completed", "halted", "failed", "rolled_back", "rollback_failed"}


class MediaMigrationBatch(Document):
	def validate(self) -> None:
		for fieldname in (
			"batch_index",
			"total",
			"processed",
			"optimized",
			"skipped",
			"errors",
			"original_bytes",
			"new_bytes",
		):
			if int(self.get(fieldname) or 0) < 0:
				frappe.throw(_("{0} negatif olamaz.").format(fieldname))
		if self.status in _TERMINAL and int(self.processed or 0) != (
			int(self.optimized or 0) + int(self.skipped or 0) + int(self.errors or 0)
		):
			frappe.throw(_("Batch sayaçları işlenen toplamıyla uyuşmuyor."))
		files = self._json_list(self.file_names_json, "file_names_json")
		changed = self._json_list(self.changed_files_json or "[]", "changed_files_json")
		if not set(changed).issubset(set(files)):
			frappe.throw(_("Değişen dosya listesi batch dosyalarının alt kümesi olmalıdır."))

	@staticmethod
	def _json_list(value: str, fieldname: str) -> list[str]:
		try:
			parsed = json.loads(value or "[]")
		except (TypeError, ValueError):
			frappe.throw(_("{0} geçerli JSON olmalıdır.").format(fieldname))
		if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
			frappe.throw(_("{0} metin dizisi olmalıdır.").format(fieldname))
		return parsed
