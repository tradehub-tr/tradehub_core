"""FAZ 5.3 — Authorization Anomaly Alert'e `buyer_org` custom field.

D10: Mevcut `tenant` field'ı Admin Seller Profile (seller-side). Buyer-side
anomaliler (örn. cross-org Order create, over_budget) için organizasyon
scope yok → buyer-side alarmlar dashboard'da düzgün ataşelenmiyordu.

Bu patch ADL'deki v15_5_2 pattern'ini takip eder.

İdempotent.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> dict:
	if not frappe.db.exists("DocType", "Authorization Anomaly Alert"):
		return {"skipped": "doctype_missing"}

	custom_fields = {
		"Authorization Anomaly Alert": [
			{
				"fieldname": "buyer_org",
				"label": "Buyer Organization",
				"fieldtype": "Link",
				"options": "CRM Organization",
				"insert_after": "tenant",
				"description": (
					"Buyer-side anomalies (cross-org Order, over_budget) için "
					"organizasyon scope'u. Anomaly detector evidence log'undan "
					"buyer_org propagate eder."
				),
				"read_only": 1,
				"in_standard_filter": 1,
				"search_index": 1,
			}
		]
	}

	create_custom_fields(custom_fields, update=True)
	frappe.db.commit()
	return {"created": "buyer_org"}
