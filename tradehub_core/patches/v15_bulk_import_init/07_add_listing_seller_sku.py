# Copyright (c) 2026, TradeHub Team and contributors

import frappe


def execute():
	"""Add `seller_sku` field to Listing for bulk-import + seller-provided stock code."""
	if frappe.db.has_column("Listing", "seller_sku"):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	create_custom_field(
		"Listing",
		{
			"fieldname": "seller_sku",
			"label": "Satıcı Stok Kodu",
			"fieldtype": "Data",
			"length": 140,
			"insert_after": "listing_code",
			"search_index": 1,
			"in_standard_filter": 1,
			"in_list_view": 1,
			"description": "Satıcının xlsx/CSV yüklemesinde verdiği iç stok kodu. listing_code sistem ID'sinden farklıdır.",
		},
	)
