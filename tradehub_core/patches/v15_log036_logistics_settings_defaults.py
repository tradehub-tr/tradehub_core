# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-036: Logistics Settings yeni varsayilan alan degerleri (idempotent)."""

from __future__ import annotations

import frappe


def execute() -> None:
	"""Singleton'da bos kalan varsayilan degerleri doldurur; dolu degerlere dokunmaz."""
	# Yeni alanlar henuz migrate edilmemis olabilir
	frappe.reload_doc("tradehub_core", "doctype", "logistics_settings")

	max_attempts = frappe.db.get_single_value("Logistics Settings", "max_delivery_attempts")
	if not max_attempts:  # bos / 0 / None -> varsayilan 3
		frappe.db.set_single_value("Logistics Settings", "max_delivery_attempts", 3)

	return_window = frappe.db.get_single_value("Logistics Settings", "return_window_days")
	if not return_window:  # bos -> varsayilan 15
		frappe.db.set_single_value("Logistics Settings", "return_window_days", 15)

	frappe.db.commit()
