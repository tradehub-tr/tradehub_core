# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-025: Logistics Provider seed verileri (idempotent)."""

from __future__ import annotations

import frappe

from tradehub_core.logistics.seed import LOGISTICS_PROVIDERS

# Seed ulke kodu -> DocType country alanindaki gorunen ad
COUNTRY_NAMES: dict[str, str] = {
	"TR": "Türkiye",
	"US": "ABD",
	"DE": "Almanya",
}


def execute() -> None:
	"""Logistics Provider kayitlarini olusturur (idempotent)."""
	# Yeni DocType henuz migrate edilmemis olabilir
	frappe.reload_doc("tradehub_core", "doctype", "logistics_provider")

	for row in LOGISTICS_PROVIDERS:
		provider_code = row["code"]
		# Idempotent -- zaten varsa dokunma (autoname field:provider_code)
		if frappe.db.exists("Logistics Provider", provider_code):
			continue
		doc = frappe.new_doc("Logistics Provider")
		doc.provider_name = row["provider_name"]
		doc.provider_code = provider_code
		doc.country = COUNTRY_NAMES[row["country"]]
		doc.provider_type = "Kargo"
		doc.integration_type = "Manual"
		doc.is_active = 1
		doc.insert(ignore_permissions=True)  # Sistem migration'i, kullanici akisi degil

	frappe.db.commit()
