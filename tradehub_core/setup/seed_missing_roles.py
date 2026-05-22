"""HOTFIX — Eksik rolleri seed et (Seller Co-Owner, Seller Admin).

Fixture'lar bazen migrate sırasında sync olmuyor; bu helper idempotent
şekilde eksik rolleri oluşturur.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	created = []
	skipped = []
	for role in ["Seller Co-Owner", "Seller Admin"]:
		if frappe.db.exists("Role", role):
			skipped.append(role)
			continue
		doc = frappe.new_doc("Role")
		doc.role_name = role
		doc.desk_access = 0
		doc.is_custom = 1
		doc.insert(ignore_permissions=True)
		created.append(role)
	frappe.db.commit()
	return {"created": created, "skipped": skipped}
