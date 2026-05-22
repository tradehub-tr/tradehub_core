"""FAZ 5.2 — Authorization Decision Log'a `buyer_org` custom field ekle.

Mevcut `tenant` field'ı Admin Seller Profile link'i (seller-side). Buyer-side
audit logları için organizasyon scope'u yoktu → Buyer Finance kullanıcısı kendi
şirketinin tüm audit kayıtlarını göremiyordu, sadece actor=self kayıtları.

Bu patch:
  1. ADL'ye `buyer_org` (Link → CRM Organization) custom field'ı ekler
  2. Mevcut kayıtlara backfill yapmaz — geriye dönük buyer-side log'lar
     sadece actor üzerinden çağrılır (alternatif filter)

İdempotent.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> dict:
	if not frappe.db.exists("DocType", "Authorization Decision Log"):
		return {"skipped": "doctype_missing"}

	custom_fields = {
		"Authorization Decision Log": [
			{
				"fieldname": "buyer_org",
				"label": "Buyer Organization",
				"fieldtype": "Link",
				"options": "CRM Organization",
				"insert_after": "tenant",
				"description": (
					"Buyer-side tenant. Set during log_decision when actor "
					"belongs to a buyer organization. Used by "
					"authorization_decision_log_query_conditions to scope buyer "
					"users to their organization's audit trail."
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
