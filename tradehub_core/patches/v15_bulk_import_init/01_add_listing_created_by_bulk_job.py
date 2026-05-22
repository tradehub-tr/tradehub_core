# Copyright (c) 2026, TradeHub Team and contributors

import frappe


def execute():
	"""Add `created_by_bulk_job` field to Listing for cascade tracking."""
	# Frappe v15: has_column ilk arg doctype adı ("Listing"), "tab" prefix otomatik
	if frappe.db.has_column("Listing", "created_by_bulk_job"):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	create_custom_field(
		"Listing",
		{
			"fieldname": "created_by_bulk_job",
			"label": "Created By Bulk Import Job",
			"fieldtype": "Link",
			"options": "Bulk Import Job",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "seller_profile",
		},
	)
