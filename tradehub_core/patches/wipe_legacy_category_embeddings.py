"""Wipe legacy dense Category Embedding vectors after Phase 1 sparse refactor.

The embedding format changed from `[float, float, …]` (dense list) to
`{ngram: weight}` (sparse dict). Legacy rows deserialize to {} under the
new code and silently produce zero similarity, polluting Complementary
fallback results until they're rebuilt.

This patch wipes all rows so the after_migrate bootstrap (or the next
weekly_long scheduler tick) re-embeds them in the new format. Idempotent
on re-runs — a second execute is a no-op once the table is empty.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Category Embedding"):
		return
	n = frappe.db.count("Category Embedding")
	if not n:
		return
	frappe.db.sql("DELETE FROM `tabCategory Embedding`")
	frappe.db.commit()
