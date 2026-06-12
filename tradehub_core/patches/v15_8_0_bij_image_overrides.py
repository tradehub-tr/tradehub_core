# Copyright (c) 2026, TradeHub Team and contributors

"""Bulk Import Job'a `image_overrides` (Long Text) alanini ekle.

'Gorseller' adiminda kullanicinin yaptigi yetim klasor -> SKU/yoksay manuel
atamalari JSON olarak burada tutulur; runner gorsel eslestirmede uygular. Core
field olarak JSON'a eklendi; `bench migrate` yukler. Idempotent: kolon varsa doner.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if frappe.db.has_column("Bulk Import Job", "image_overrides"):
		return
	frappe.reload_doc("tradehub_core", "doctype", "bulk_import_job")
	frappe.db.commit()
