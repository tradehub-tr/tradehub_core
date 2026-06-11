# Copyright (c) 2026, TradeHub Team and contributors

"""Bulk Import Job Error'a `field` (Data) ve `severity` (Select) alanlarini ekle.

Hata kayitlari artik hangi sutunun hatali oldugunu (`field`) ve uyari/hata
ayrimini (`severity`) tutuyor. Core field olarak JSON'a eklendi; `bench migrate`
yukler. Mevcut kurulumlar icin DocType reload. Idempotent: kolon varsa erken doner.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if frappe.db.has_column("Bulk Import Job Error", "severity"):
		return
	frappe.reload_doc("tradehub_core", "doctype", "bulk_import_job_error")
	frappe.db.commit()
