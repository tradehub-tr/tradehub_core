"""MOGEM-570 kalıcı migration run/batch şeması ve checkpoint benzersizliği."""

from __future__ import annotations

import frappe


def _has_index(table: str, index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			f"SHOW INDEX FROM `{table}` WHERE Key_name = %s",  # nosec B608 — sabit tablo
			(index_name,),
		)
	)


def execute() -> None:
	# Patch schema sync sırası farklı kurulumlarda da güvenli olsun.
	frappe.reload_doc("tradehub_core", "doctype", "media_migration_batch")
	frappe.reload_doc("tradehub_core", "doctype", "media_migration_run")

	# Controller aynı parent içindeki tekrarları yakalayabilir; DB constraint ise
	# iki eşzamanlı enqueue'nun aynı checkpoint'i üretmesini kesin olarak önler.
	if not _has_index("tabMedia Migration Batch", "uniq_media_migration_batch"):
		frappe.db.sql(
			"""ALTER TABLE `tabMedia Migration Batch`
			ADD UNIQUE INDEX `uniq_media_migration_batch` (`parent`, `batch_index`)"""
		)
