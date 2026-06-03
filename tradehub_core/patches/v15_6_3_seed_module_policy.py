"""Sprint 6 — TH Module Policy seed.

navigation.js `requires:[...]` etiketlerini DB politikalarına çevirir.

Default davranış: TH Module Policy kaydı YOKSA modül tüm rollere visible
(allowlist değil, denylist mantığı — geriye-uyumluluk için).

Seed mantığı:
  - spec["requires"] = ["owner_or_co", "admin"] gibi etiketler →
    REQUIRES_TAG_MAP'ten Role Profile listesine çevrilir
  - `admin` tag'i platform admin demek (System Manager / Marketplace Admin) →
    Frappe rolüyle çözülür, Module Policy gerekmez (zaten resolver bypass eder)
  - "İzin verilen" profile listesinin DIŞINDA kalan tüm Seller/Buyer
    profile'lar için `mode=hidden` kaydı yaratılır

Örnek:
  requires: ["owner_or_co", "admin"]
  → İzinli: Seller Full Access, Seller Co-Owner, (platform admin zaten geçer)
  → Hidden: Seller Manager, Seller Operations, Seller Finance Staff,
            (buyer profile'lar zaten farklı section'da)

İdempotent: (module, role_profile) çifti varsa atla.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	from tradehub_core.setup.module_navigation_spec import (
		ALL_BUYER_PROFILES,
		ALL_SELLER_PROFILES,
		REQUIRES_TAG_MAP,
		get_all_modules,
	)

	created: list[tuple[str, str]] = []
	skipped: list[tuple[str, str]] = []
	skipped_missing_profile: set[str] = set()

	for spec in get_all_modules():
		requires = spec.get("requires") or []
		if not requires:
			# Etiket yok → varsayılan visible (Policy kaydı gereksiz)
			continue

		module_key = spec["key"]
		if not frappe.db.exists("TH Module Registry", module_key):
			continue

		# Tag listesini Role Profile listesine çöz
		allowed_profiles: set[str] = set()
		for tag in requires:
			if tag == "admin":
				# "admin" → platform admin (System Manager/Marketplace Admin);
				# Role Profile değil Frappe rolü ile bypass edilir; policy
				# tablosuna kayıt gerekmiyor.
				continue
			mapped = REQUIRES_TAG_MAP.get(tag)
			if mapped:
				allowed_profiles.update(mapped)
			elif frappe.db.exists("Role Profile", tag):
				# Tag doğrudan Role Profile adı (örn. "Buyer Approver L1")
				allowed_profiles.add(tag)

		# Panel'a göre relevant profile evreni
		panel = spec["panel"]
		if panel == "seller":
			candidate_profiles = ALL_SELLER_PROFILES
		elif panel == "admin":
			# Admin panel sub-user'ları yok; satıcı + buyer hepsini kapsa
			candidate_profiles = ALL_SELLER_PROFILES + ALL_BUYER_PROFILES
		else:
			candidate_profiles = ALL_SELLER_PROFILES + ALL_BUYER_PROFILES

		# Allowed dışında kalan profile'lar için hidden kaydı yarat
		for profile in candidate_profiles:
			if profile in allowed_profiles:
				continue
			if not frappe.db.exists("Role Profile", profile):
				skipped_missing_profile.add(profile)
				continue
			if frappe.db.exists("TH Module Policy", {"module": module_key, "role_profile": profile}):
				skipped.append((module_key, profile))
				continue

			doc = frappe.new_doc("TH Module Policy")
			doc.module = module_key
			doc.role_profile = profile
			doc.mode = "hidden"
			doc.note = f"Seed: Sprint 6 — requires={requires}"
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			created.append((module_key, profile))

	frappe.db.commit()

	return {
		"created_count": len(created),
		"skipped_existing_count": len(skipped),
		"missing_profiles": list(skipped_missing_profile),
		"total_policies_in_db": frappe.db.count("TH Module Policy"),
	}
