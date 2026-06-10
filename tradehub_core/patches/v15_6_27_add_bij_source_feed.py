# Copyright (c) 2026, TradeHub Team and contributors

"""Bulk Import Job'a `source_feed` Link alanini ekle (run-history icin).

`source_feed` core field olarak bulk_import_job.json'a eklendi; `bench migrate`
DocType JSON'unu zaten yukler. Ancak mevcut kurulumlarda DB kolonu olusmamis
olabilir — bu patch DocType'i reload eder ki schema kolonu garanti olusun.
Idempotent: kolon zaten varsa erken doner.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if frappe.db.has_column("Bulk Import Job", "source_feed"):
		return
	# JSON'daki yeni core field'i DB'ye uygula — migrate sirasinda sync_doctype
	# bu reload'u zaten yapar, ama eski kurulumlar icin acikca tetikliyoruz.
	frappe.reload_doc("tradehub_core", "doctype", "bulk_import_job")
	frappe.db.commit()
