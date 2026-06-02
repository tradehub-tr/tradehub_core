# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.5 — User'a `temporary_role_until` custom field ekle.

Idempotent: zaten varsa skip.
"""

from __future__ import annotations

import frappe

_FIELDS = [
	{
		"dt": "User",
		"fieldname": "temporary_role_until",
		"label": "Temporary Role Expires At",
		"fieldtype": "Datetime",
		"insert_after": "role_profile_name",
		"description": "Geçici rol bu tarihte otomatik kaldırılır",
		"read_only": 1,
	},
]


def execute() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	fields_by_doctype: dict[str, list[dict]] = {}
	for spec in _FIELDS:
		dt = spec.pop("dt")
		fields_by_doctype.setdefault(dt, []).append(spec)

	create_custom_fields(fields_by_doctype, ignore_validate=True)
	frappe.db.commit()
