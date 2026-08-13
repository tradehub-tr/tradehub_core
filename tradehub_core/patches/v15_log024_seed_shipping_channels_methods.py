# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-024: Shipping Channel + Shipping Method seed verileri (idempotent)."""

from __future__ import annotations

import frappe

from tradehub_core.logistics.seed import SHIPPING_CHANNELS

# Seed "code" -> Türkçe aksanlı görünen ad (TEK KAYNAK — seed.py yalnız "code" taşır)
CHANNEL_DISPLAY_NAMES: dict[str, str] = {
	"CARGO": "Kargo",
	"WAREHOUSE": "Ambar",
	"COURIER": "Kurye",
	"SELLER_VEHICLE": "Satıcı Aracı",
	"BUYER_PICKUP": "Alıcı Teslim Alma",
}

# method_name -> (channel_code, shipping_type)
SHIPPING_METHODS: dict[str, tuple[str, str]] = {
	"Kargo": ("CARGO", "Standard"),
	"Ambar": ("WAREHOUSE", "Land"),
	"Kurye": ("COURIER", "Express"),
	"Satıcı Aracı": ("SELLER_VEHICLE", "Land"),
	"Alıcı Teslim Alma": ("BUYER_PICKUP", "Standard"),
}


def execute() -> None:
	"""Shipping Channel ve Shipping Method kayitlarini olusturur (idempotent)."""
	# Yeni DocType henuz migrate edilmemis olabilir
	frappe.reload_doc("tradehub_core", "doctype", "shipping_channel")
	frappe.reload_doc("tradehub_core", "doctype", "shipping_method")

	for row in SHIPPING_CHANNELS:
		channel_code = row["code"]
		# Idempotent -- zaten varsa dokunma (autoname field:channel_code)
		if frappe.db.exists("Shipping Channel", channel_code):
			continue
		doc = frappe.new_doc("Shipping Channel")
		# Gorunen ad CHANNEL_DISPLAY_NAMES'ten -- alan alan atama yapiyoruz
		doc.channel_name = CHANNEL_DISPLAY_NAMES[channel_code]
		doc.channel_code = channel_code
		doc.is_active = 1
		doc.insert(ignore_permissions=True)  # Sistem migration'i, kullanici akisi degil

	for method_name, (channel_code, shipping_type) in SHIPPING_METHODS.items():
		# Idempotent -- zaten varsa dokunma (autoname field:method_name)
		if frappe.db.exists("Shipping Method", method_name):
			continue
		doc = frappe.new_doc("Shipping Method")
		doc.method_name = method_name
		doc.channel = channel_code
		doc.shipping_type = shipping_type
		doc.is_active = 1
		doc.insert(ignore_permissions=True)  # Sistem migration'i, kullanici akisi degil

	frappe.db.commit()
