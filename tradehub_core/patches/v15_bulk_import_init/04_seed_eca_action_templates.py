# Copyright (c) 2026, TradeHub Team and contributors

"""Seed örnek ECA Action Template'leri."""

import frappe

SEED_TEMPLATES = [
	{
		"name": "TH Set Status to Draft",
		"action_type": "field_update",
		"description": "Listing.status = 'Draft' yapar",
		"field_updates": '[{"fieldname": "status", "value": "\'Draft\'"}]',
		"rate_limit_per_hour": 1000,
	},
	{
		"name": "TH Set Status to Out of Stock",
		"action_type": "field_update",
		"description": "Listing.status = 'Out of Stock' yapar",
		"field_updates": '[{"fieldname": "status", "value": "\'Out of Stock\'"}]',
		"rate_limit_per_hour": 1000,
	},
	{
		"name": "TH Apply 5% Discount",
		"action_type": "field_update",
		"description": "selling_price = base_price * 0.95",
		"field_updates": '[{"fieldname": "selling_price", "value": "flt(doc[\'base_price\']) * 0.95"}]',
		"rate_limit_per_hour": 1000,
	},
	{
		"name": "TH Reject Row",
		"action_type": "reject_row",
		"description": "Satırı reddet — bulk import context'inde row skip edilir",
		"reject_reason": "ECA kuralı tarafından reddedildi",
		"rate_limit_per_hour": 1000,
	},
]


def execute():
	"""Seed örnek ECA Action Template kayıtları (idempotent)."""
	for spec in SEED_TEMPLATES:
		if frappe.db.exists("ECA Action Template", {"template_name": spec["name"]}):
			continue
		doc = frappe.new_doc("ECA Action Template")
		doc.template_name = spec["name"]
		doc.action_type = spec["action_type"]
		doc.description = spec.get("description", "")
		doc.field_updates = spec.get("field_updates", "")
		doc.reject_reason = spec.get("reject_reason", "")
		doc.rate_limit_per_hour = spec.get("rate_limit_per_hour", 50)
		try:
			doc.insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(f"Seed template {spec['name']} failed: {e}", "v15_bulk_import_init.04")
	frappe.db.commit()
