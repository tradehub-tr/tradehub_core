# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-033: Package Type seed verileri (idempotent)."""

from __future__ import annotations

import frappe

from tradehub_core.logistics.seed import PACKAGE_TYPES


def execute() -> None:
	"""Package Type kayitlarini olusturur (idempotent)."""
	# Yeni DocType henuz migrate edilmemis olabilir
	frappe.reload_doc("tradehub_core", "doctype", "package_type")

	for row in PACKAGE_TYPES:
		package_code = row["code"]
		# Idempotent -- zaten varsa dokunma (autoname field:package_code)
		if frappe.db.exists("Package Type", package_code):
			continue
		doc = frappe.new_doc("Package Type")
		doc.package_name = row["type_name"]
		doc.package_code = package_code
		doc.max_weight_kg = row["max_weight_kg"]
		doc.is_active = 1
		doc.is_default = 1 if package_code == "BOX" else 0
		doc.insert(ignore_permissions=True)  # Sistem migration'i, kullanici akisi degil

	frappe.db.commit()
