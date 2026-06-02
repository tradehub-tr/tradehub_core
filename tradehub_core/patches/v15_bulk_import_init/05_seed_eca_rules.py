# Copyright (c) 2026, TradeHub Team and contributors

"""Seed örnek ECA Rule'lar (Platform scope, default disabled)."""

import frappe

SEED_RULES = [
	{
		"name": "TH Resimsiz Ürünleri Draft'a Düşür",
		"reference_doctype": "Listing",
		"event": "before_save",
		"context_filter": "bulk_import",
		"rule_scope": "Platform",
		"owner_role": "System Manager",
		"priority": 1100,
		"condition": "not doc.get('primary_image')",
		"action_type": "field_update",
		"action_template": "TH Set Status to Draft",
		"enabled": 0,  # Default DISABLED — admin manuel açar
	},
	{
		"name": "TH Stok Sıfır - Out of Stock",
		"reference_doctype": "Listing",
		"event": "before_save",
		"context_filter": "bulk_import",
		"rule_scope": "Platform",
		"owner_role": "System Manager",
		"priority": 1200,
		"condition": "cint(doc.get('stock_qty')) == 0",
		"action_type": "field_update",
		"action_template": "TH Set Status to Out of Stock",
		"enabled": 0,
	},
]


def execute():
	"""Seed örnek ECA Rule kayıtları (idempotent, default disabled)."""
	for spec in SEED_RULES:
		# action_template var mı? Yoksa rule oluşturma — bağımlılık eksik demektir.
		template_name = spec.get("action_template")
		if template_name and not frappe.db.exists("ECA Action Template", template_name):
			frappe.log_error(
				f"Action template missing: {template_name}",
				"v15_bulk_import_init.05",
			)
			continue
		if frappe.db.exists("ECA Rule", {"rule_name": spec["name"]}):
			continue
		doc = frappe.new_doc("ECA Rule")
		doc.rule_name = spec["name"]
		doc.enabled = spec.get("enabled", 0)
		doc.reference_doctype = spec["reference_doctype"]
		doc.event = spec["event"]
		doc.context_filter = spec.get("context_filter", "")
		doc.rule_scope = spec["rule_scope"]
		doc.owner_role = spec["owner_role"]
		doc.priority = spec["priority"]
		doc.condition = spec["condition"]
		doc.action_type = spec["action_type"]
		doc.action_template = template_name or ""
		try:
			doc.insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(f"Seed rule {spec['name']} failed: {e}", "v15_bulk_import_init.05")
	frappe.db.commit()
