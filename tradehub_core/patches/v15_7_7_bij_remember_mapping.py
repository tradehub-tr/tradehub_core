# Copyright (c) 2026, TradeHub Team and contributors

"""Bulk Import Job'a `remember_mapping` Check alanini ekle.

Onaylanan kolon eslestirmesini satici profili olarak kaydetmek icin kullanilir
(ayni baslikli sonraki dosyalar otomatik eslesir). Core field olarak
bulk_import_job.json'a eklendi; `bench migrate` JSON'u yukler. Mevcut
kurulumlarda DB kolonu olusmamis olabilir — bu patch DocType'i reload eder.
Idempotent: kolon zaten varsa erken doner.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if frappe.db.has_column("Bulk Import Job", "remember_mapping"):
		return
	frappe.reload_doc("tradehub_core", "doctype", "bulk_import_job")
	frappe.db.commit()
