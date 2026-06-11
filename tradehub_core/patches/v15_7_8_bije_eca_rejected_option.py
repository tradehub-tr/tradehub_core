# Copyright (c) 2026, TradeHub Team and contributors

"""Bulk Import Job Error.error_type Select'ine `eca_rejected` secenegini ekle.

ECA reject_row aksiyonu artik satiri gercekten skip ediyor ve bu tiple
raporlaniyor. Select option degisikligi DocType JSON'a eklendi; `bench migrate`
JSON'u yukler. Bu patch DocType'i reload eder ki mevcut kurulumlar da yeni
option'i tanisin. Idempotent: option zaten varsa erken doner.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	meta_options = frappe.db.get_value(
		"DocField",
		{"parent": "Bulk Import Job Error", "fieldname": "error_type"},
		"options",
	)
	if meta_options and "eca_rejected" in meta_options:
		return
	frappe.reload_doc("tradehub_core", "doctype", "bulk_import_job_error")
	frappe.db.commit()
