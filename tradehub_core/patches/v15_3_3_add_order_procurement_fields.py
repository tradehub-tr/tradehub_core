# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.3 — Order'a procurement custom field'ları ekle.

Yeni field'lar:
  - cost_center: Link → Cost Center
  - procurement_notes: Small Text

Ve Approval Rule'a:
  - cost_center_filter: Small Text

Idempotent: zaten varsa skip.
"""

from __future__ import annotations

import frappe

_ORDER_FIELDS = [
	{
		"dt": "Order",
		"fieldname": "cost_center",
		"label": "Cost Center",
		"fieldtype": "Link",
		"options": "Cost Center",
		"insert_after": "buyer",
		"description": "Hangi cost center'a yüklensin (B2B order'lar için)",
	},
	{
		"dt": "Order",
		"fieldname": "procurement_notes",
		"label": "Procurement Notes",
		"fieldtype": "Small Text",
		"insert_after": "cost_center",
	},
]

_APPROVAL_RULE_FIELDS = [
	{
		"dt": "Approval Rule",
		"fieldname": "cost_center_filter",
		"label": "Cost Center Filter",
		"fieldtype": "Small Text",
		"insert_after": "supplier_filter",
		"description": "Virgülle ayrılmış cost center kodları; boş = tüm cost center'lara",
	},
]


def execute() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	# Doctype'lar var mı?
	for spec in _ORDER_FIELDS:
		if not frappe.db.exists("DocType", spec["dt"]):
			return

	fields_by_doctype: dict[str, list[dict]] = {}
	for spec in _ORDER_FIELDS + _APPROVAL_RULE_FIELDS:
		dt = spec.pop("dt")
		fields_by_doctype.setdefault(dt, []).append(spec)

	create_custom_fields(fields_by_doctype, ignore_validate=True)
	frappe.db.commit()
