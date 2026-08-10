# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-032: Vehicle Type seed verileri (idempotent)."""

from __future__ import annotations

import frappe

from tradehub_core.logistics.seed import VEHICLE_TYPES


def execute() -> None:
	"""Vehicle Type kayitlarini olusturur (idempotent)."""
	# Yeni DocType henuz migrate edilmemis olabilir
	frappe.reload_doc("tradehub_core", "doctype", "vehicle_type")

	for row in VEHICLE_TYPES:
		vehicle_code = row["code"]
		# Idempotent -- zaten varsa dokunma (autoname field:vehicle_code)
		if frappe.db.exists("Vehicle Type", vehicle_code):
			continue
		doc = frappe.new_doc("Vehicle Type")
		doc.vehicle_name = row["type_name"]
		doc.vehicle_code = vehicle_code
		# Seed type_name degerleri vehicle_category Select secenekleriyle birebir ayni
		doc.vehicle_category = row["type_name"]
		doc.max_weight_kg = row["max_weight_kg"]
		doc.is_active = 1
		doc.insert(ignore_permissions=True)  # Sistem migration'i, kullanici akisi degil

	frappe.db.commit()
