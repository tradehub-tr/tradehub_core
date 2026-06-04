"""Sprint 6 — TH Capability Grant matrix seed.

Sorun:
  Capability → Role Profile grant'ları `seller_capabilities.py`'da _TIER_*
  Python frozenset'lerinde. Süper admin Manager'a `view.bank_info` veremiyor.
  Bu patch tier set'lerini gezerek Role Profile × Capability grant kayıtları
  üretir.

Mantık:
  - SELLER_CAPABILITIES her (cap, tier_set) → tier_set içindeki her role_profile
    için TH Capability Grant insert
  - _OWNER_ONLY_CAPABILITIES için "Seller Full Access" (owner) tek grant yarat
    (sub-user profile'lar için grant yok — runtime'da is_owner_only kapısı kontrol eder)
  - Plan-bağımlı capability'ler için grant aynen verilir; resolver çalışma
    anında subscription_plan.capability_flags ile ikinci kapıyı geçer

Role Profile adı seçimi:
  Tier set elementleri zaten role_profile_name string'leri (Seller Full Access,
  Seller Co-Owner, ...). Role Profile DocType'ında bu kayıtlar mevcut olmalı
  (role_profile.json fixture seed sonrası).

İdempotent: (role_profile, capability) çifti varsa atla.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	from tradehub_core.utils import seller_capabilities as sc

	created: list[tuple[str, str]] = []
	skipped: list[tuple[str, str]] = []
	skipped_missing_profile: set[str] = set()
	skipped_missing_capability: set[str] = set()

	# 1) Normal capability'ler için tier set'lerini gez
	for cap_key, (tier_set, _plan_feature) in sc.SELLER_CAPABILITIES.items():
		if not frappe.db.exists("TH Capability Registry", cap_key):
			skipped_missing_capability.add(cap_key)
			continue

		for profile_name in tier_set:
			if not frappe.db.exists("Role Profile", profile_name):
				skipped_missing_profile.add(profile_name)
				continue

			existing = frappe.db.get_value(
				"TH Capability Grant",
				{"role_profile": profile_name, "capability": cap_key},
				"name",
			)
			if existing:
				skipped.append((profile_name, cap_key))
				continue

			doc = frappe.new_doc("TH Capability Grant")
			doc.role_profile = profile_name
			doc.capability = cap_key
			doc.granted = 1
			doc.note = "Seed: Sprint 6 tier matrisi"
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			created.append((profile_name, cap_key))

	# 2) Owner-only capability'ler — sadece "Seller Full Access" alır
	owner_profile = "Seller Full Access"
	if frappe.db.exists("Role Profile", owner_profile):
		for cap_key in sc._OWNER_ONLY_CAPABILITIES:
			if not frappe.db.exists("TH Capability Registry", cap_key):
				skipped_missing_capability.add(cap_key)
				continue

			existing = frappe.db.get_value(
				"TH Capability Grant",
				{"role_profile": owner_profile, "capability": cap_key},
				"name",
			)
			if existing:
				skipped.append((owner_profile, cap_key))
				continue

			doc = frappe.new_doc("TH Capability Grant")
			doc.role_profile = owner_profile
			doc.capability = cap_key
			doc.granted = 1
			doc.note = "Seed: Sprint 6 — Owner-only kapı"
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			created.append((owner_profile, cap_key))
	else:
		skipped_missing_profile.add(owner_profile)

	frappe.db.commit()

	return {
		"created_count": len(created),
		"skipped_existing_count": len(skipped),
		"missing_profiles": list(skipped_missing_profile),
		"missing_capabilities": list(skipped_missing_capability),
		"total_grants_in_db": frappe.db.count("TH Capability Grant"),
	}
