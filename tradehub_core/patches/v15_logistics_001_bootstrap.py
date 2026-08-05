# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-102: Lojistik modul bootstrap -- Logistics Settings singleton olustur."""

from __future__ import annotations

import frappe


def execute() -> None:
	"""Logistics Settings singleton kaydini olusturur (idempotent)."""
	# Idempotent -- zaten varsa dokunma
	if frappe.db.exists("Logistics Settings"):
		return

	doc = frappe.new_doc("Logistics Settings")
	doc.logistics_enabled = 0
	doc.auto_tracking_enabled = 0
	doc.tracking_poll_interval_minutes = 60
	doc.sla_breach_notify_hours = 48
	doc.default_currency = "TRY"
	doc.shipment_naming_series = "SHP-.YYYY.-.#####"
	doc.feature_flags = frappe.as_json({
		"carrier_api_enabled": False,
		"multi_carrier_enabled": False,
		"shipping_zone_pricing_enabled": False,
		"auto_tracking_enabled": False,
		"split_shipment_enabled": False,
		"multi_leg_enabled": False,
		"cost_estimation_enabled": False,
		"webhook_notifications_enabled": False,
		"return_flow_enabled": False,
		"seller_delivery_enabled": False,
		"buyer_pickup_enabled": False,
		"warehouse_transfer_enabled": False,
	})
	doc.insert(ignore_permissions=True)  # Bootstrap: sistem kurulumu, kullanici akisi degil
	frappe.db.commit()
