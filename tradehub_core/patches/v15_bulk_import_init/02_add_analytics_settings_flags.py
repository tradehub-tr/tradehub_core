# Copyright (c) 2026, TradeHub Team and contributors

import frappe


def execute():
	"""Analytics Settings'e ECA + email flag'lerini ekle."""
	# Analytics Settings doctype yoksa atla (graceful)
	if not frappe.db.exists("DocType", "Analytics Settings"):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	if not frappe.db.has_column("Analytics Settings", "enable_eca_rules"):
		create_custom_field(
			"Analytics Settings",
			{
				"fieldname": "enable_eca_rules",
				"label": "ECA Kural Motoru Aktif",
				"fieldtype": "Check",
				"default": 1,
			},
		)
	if not frappe.db.has_column("Analytics Settings", "enable_failure_emails"):
		create_custom_field(
			"Analytics Settings",
			{
				"fieldname": "enable_failure_emails",
				"label": "Bulk Import Failure E-postaları Aktif",
				"fieldtype": "Check",
				"default": 0,
				"description": "Job_failed olayında satıcı + admin'e mail. Default OFF.",
			},
		)
