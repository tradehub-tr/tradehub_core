"""FAZ 7.1 — Seller Owner rolüne Listing erişimini geri ver (RBAC regresyon fix).

Sorun:
  Yeni RBAC Custom DocPerm modeli (v15_5_1_seed_role_docperms) Listing erişimini
  alt-rollere (Seller Staff = r/w/c, Seller Viewer = r) verdi. Ancak capability
  sistemi DOĞRULANMIŞ satıcılara "Seller Owner" rolünü atıyor ve "Seller Owner"
  Listing'in Custom DocPerm'inde YOK. Frappe'de bir DocType'ta Custom DocPerm
  bulundu mu standart DocPerm tamamen yok sayılır → tüm satıcı sahipleri kendi
  ürünlerini açamaz/düzenleyemez oldu (PermissionError).

Çözüm:
  "Seller Owner" için Listing permlevel-0 read/write/create Custom DocPerm satırı
  ekle. Tenant izolasyonu (permissions.listing_query_conditions +
  permissions.listing_has_permission) korunur → satıcı YALNIZCA kendi ürünlerini
  görür/düzenler. İdempotent.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	if not frappe.db.exists("DocType", "Listing"):
		return {"skipped": "no_listing"}
	if not frappe.db.exists("Role", "Seller Owner"):
		return {"skipped": "no_role"}

	existing = frappe.db.exists(
		"Custom DocPerm", {"parent": "Listing", "role": "Seller Owner", "permlevel": 0}
	)
	if existing:
		cd = frappe.get_doc("Custom DocPerm", existing)
		cd.read = 1
		cd.write = 1
		cd.create = 1
		cd.save(ignore_permissions=True)
		action = "updated"
	else:
		cd = frappe.new_doc("Custom DocPerm")
		cd.parent = "Listing"
		cd.parenttype = "DocType"
		cd.parentfield = "permissions"
		cd.role = "Seller Owner"
		cd.permlevel = 0
		cd.read = 1
		cd.write = 1
		cd.create = 1
		cd.insert(ignore_permissions=True)
		action = "created"

	frappe.clear_cache(doctype="Listing")
	frappe.db.commit()
	return {action: "Seller Owner -> Listing (r/w/c)"}
