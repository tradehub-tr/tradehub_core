"""Sprint 6 — Seller Sales Rep Role Profile + Sales tier grants.

`_TIER_SALES` Python sabit'inde `Seller Sales Rep` listelenmiş ama Role
Profile fixture'larında hiç yaratılmamış. Sonuç: v15_6_13 patch'i Sales
grant'ları verirken bu profile için "missing" diye skip ediyordu.

Bu patch:
  1. Eksikse "Seller Sales Rep" Role Profile'ı yaratır (Has Role:
     Seller Sales + Seller Staff + Seller Viewer)
  2. _TIER_SALES capability'lerini (view.customer_full vb.) Sales Rep
     profile'a grant olarak ekler

Idempotent.
"""

from __future__ import annotations

import frappe

_SALES_REP_ROLES = ["Seller Sales", "Seller Staff", "Seller Viewer"]


def execute() -> dict:
	from tradehub_core.utils import seller_capabilities as sc

	created_profile = False
	created_grants = 0
	skipped_existing = 0
	skipped_missing_role: set[str] = set()

	# 1) Role Profile yarat
	profile_name = "Seller Sales Rep"
	if not frappe.db.exists("Role Profile", profile_name):
		# Atanacak roller mevcut mu kontrol et
		for role in _SALES_REP_ROLES:
			if not frappe.db.exists("Role", role):
				skipped_missing_role.add(role)

		doc = frappe.new_doc("Role Profile")
		doc.role_profile = profile_name
		for role in _SALES_REP_ROLES:
			if role not in skipped_missing_role:
				doc.append("roles", {"role": role})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created_profile = True

	# 2) Sales tier capability'lerini grant et
	sales_caps = [
		cap for cap, (tier_set, _flag) in sc.SELLER_CAPABILITIES.items() if tier_set is sc._TIER_SALES
	]
	for cap_key in sales_caps:
		if not frappe.db.exists("TH Capability Registry", cap_key):
			continue
		existing = frappe.db.get_value(
			"TH Capability Grant",
			{"role_profile": profile_name, "capability": cap_key},
			"name",
		)
		if existing:
			skipped_existing += 1
			continue
		gd = frappe.new_doc("TH Capability Grant")
		gd.role_profile = profile_name
		gd.capability = cap_key
		gd.granted = 1
		gd.note = "Sales Rep seed (v15_6_14)"
		gd.flags.ignore_permissions = True
		gd.insert(ignore_permissions=True)
		created_grants += 1

	frappe.db.commit()

	from tradehub_core.utils.permission_resolver import flush_all_cache

	flush_all_cache()

	return {
		"created_profile": created_profile,
		"created_grants": created_grants,
		"skipped_existing": skipped_existing,
		"skipped_missing_role": sorted(skipped_missing_role),
	}
