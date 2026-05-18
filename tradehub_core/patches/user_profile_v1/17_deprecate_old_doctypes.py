"""Patch 17: Buyer Profile + Seller Profile DocType'larını hidden + read_only yap.
90 gün sonra Sprint 4 Patch 18'de DROP TABLE."""

import frappe


def execute():
	for dt in ("Buyer Profile", "Seller Profile"):
		if not frappe.db.exists("DocType", dt):
			continue

		# Property Setter ile hidden + read_only (idempotent)
		for prop_name, value, prop_type in (
			("hidden", "1", "Check"),
			("read_only", "1", "Check"),
		):
			ps_name = f"{dt}-main-{prop_name}"
			if not frappe.db.exists("Property Setter", ps_name):
				ps = frappe.get_doc(
					{
						"doctype": "Property Setter",
						"name": ps_name,
						"doctype_or_field": "DocType",
						"doc_type": dt,
						"property": prop_name,
						"value": value,
						"property_type": prop_type,
					}
				)
				ps.flags.ignore_permissions = True
				ps.flags.ignore_links = True
				ps.flags.ignore_validate = True
				ps.insert(ignore_permissions=True)
			else:
				frappe.db.set_value("Property Setter", ps_name, "value", value)

	frappe.db.commit()
	frappe.clear_cache()
