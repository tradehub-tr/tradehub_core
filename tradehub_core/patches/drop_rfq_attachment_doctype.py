"""Remove the RFQ Attachment child doctype.

The Frappe File doctype already records the link between an uploaded file
and its parent RFQ (attached_to_doctype/attached_to_name), so the custom
RFQ Attachment child table was a redundant copy that risked diverging.

This patch drops the doctype and its underlying table. Files themselves
are untouched — they live as File records.

Idempotent.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "RFQ Attachment"):
		print("[drop_rfq_attachment_doctype] doctype already absent — skip")
		return

	# Drop any child rows first (table is empty if rfq.json no longer references it,
	# but child rows can persist if migrate hasn't been re-run on this DB).
	try:
		frappe.db.sql("DROP TABLE IF EXISTS `tabRFQ Attachment`")
	except Exception as e:
		print(f"[drop_rfq_attachment_doctype] WARN: could not drop table: {e}")

	frappe.delete_doc("DocType", "RFQ Attachment", force=1, ignore_missing=True)
	frappe.db.commit()
	print("[drop_rfq_attachment_doctype] removed RFQ Attachment doctype")
