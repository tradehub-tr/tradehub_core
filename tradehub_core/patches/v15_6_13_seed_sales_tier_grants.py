"""Sprint 6 — Sales Rep tier'ı için eksik Capability Grant seed.

`v15_6_1_seed_capability_grant.py` çalıştığında _TIER_SALES tanımlı olmasına
rağmen iki nokta eksikti:
  1. `_TIER_ROLE_FALLBACK` dict'inde _TIER_SALES kayıt edilmemişti — runtime
     fallback Sales tier'ı tanımıyordu (Python sabit yolu).
  2. Seller Sales Rep profili Capability Grant tablosuna **hiç seed
     edilmemiş** — DB-driven yolda Sales kayıt yok.

Sonuç: Sales tier capability'leri (view.customer_full vb.) kimsenin
listesinde yoktu.

Bu patch _TIER_SALES set'indeki Role Profile'lara (Seller Sales Rep dahil)
Sales tier'a düşen capability'leri (örn. view.customer_full) grant eder.
İdempotent: var olan (role_profile, capability) çifti varsa atlanır.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	from tradehub_core.utils import seller_capabilities as sc

	# _TIER_SALES içindeki capability'leri bul
	sales_caps = [
		cap for cap, (tier_set, _flag) in sc.SELLER_CAPABILITIES.items() if tier_set is sc._TIER_SALES
	]
	if not sales_caps:
		return {"created": 0, "note": "no Sales tier caps found"}

	created: list[tuple[str, str]] = []
	skipped_existing = 0
	skipped_missing_profile: set[str] = set()
	skipped_missing_capability: set[str] = set()

	for cap_key in sales_caps:
		if not frappe.db.exists("TH Capability Registry", cap_key):
			skipped_missing_capability.add(cap_key)
			continue
		for profile_name in sc._TIER_SALES:
			if not frappe.db.exists("Role Profile", profile_name):
				skipped_missing_profile.add(profile_name)
				continue
			existing = frappe.db.get_value(
				"TH Capability Grant",
				{"role_profile": profile_name, "capability": cap_key},
				"name",
			)
			if existing:
				skipped_existing += 1
				continue
			doc = frappe.new_doc("TH Capability Grant")
			doc.role_profile = profile_name
			doc.capability = cap_key
			doc.granted = 1
			doc.note = "Sales tier seed (v15_6_13)"
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			created.append((profile_name, cap_key))

	frappe.db.commit()

	from tradehub_core.utils.permission_resolver import flush_all_cache

	flush_all_cache()

	return {
		"created_count": len(created),
		"created": created,
		"skipped_existing": skipped_existing,
		"skipped_missing_profile": sorted(skipped_missing_profile),
		"skipped_missing_capability": sorted(skipped_missing_capability),
	}
