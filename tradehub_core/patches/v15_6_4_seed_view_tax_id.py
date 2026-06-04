"""Sprint 4 — view.tax_id capability'sini ekle.

Sorun:
  Sprint 4 backend serializer maskeleme adımında KYB Verification ve
  Admin Seller Profile içindeki `tax_id` field'ı için ayrı bir capability
  gerekiyor. Mevcut listede yok.

Seed:
  - capability_key = "view.tax_id"
  - label = "Vergi Kimliği Görüntüleme"
  - module_group = "Görüntüleme"
  - default_tier = "COOWNER"  (banka bilgisi gibi)
  - requires_kyc = 0
  - Seller Full Access + Seller Co-Owner için grant

İdempotent.
"""

from __future__ import annotations

import frappe

_CAP_KEY = "view.tax_id"


def execute() -> dict:
	created_cap = False
	created_grants: list[str] = []

	# 1) Registry'de yoksa yarat
	if not frappe.db.exists("TH Capability Registry", _CAP_KEY):
		doc = frappe.new_doc("TH Capability Registry")
		doc.capability_key = _CAP_KEY
		doc.label = "Vergi Kimliği Görüntüleme"
		doc.description = (
			"KYB Verification ve Admin Seller Profile içindeki tax_id (vergi/TCKN) "
			"alanını maskelenmemiş okuma yetkisi. Banka bilgisi gibi yüksek hassasiyetli."
		)
		doc.module_group = "Görüntüleme"
		doc.default_tier = "COOWNER"
		doc.is_owner_only = 0
		doc.requires_kyc = 0
		doc.requires_aml = 0
		doc.is_protected = 0
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created_cap = True

	# 2) Grant matrisi — Full Access + Co-Owner
	for profile in ("Seller Full Access", "Seller Co-Owner"):
		if not frappe.db.exists("Role Profile", profile):
			continue
		if frappe.db.exists(
			"TH Capability Grant",
			{"role_profile": profile, "capability": _CAP_KEY},
		):
			continue
		g = frappe.new_doc("TH Capability Grant")
		g.role_profile = profile
		g.capability = _CAP_KEY
		g.granted = 1
		g.note = "Seed: Sprint 4 view.tax_id"
		g.flags.ignore_permissions = True
		g.insert(ignore_permissions=True)
		created_grants.append(profile)

	frappe.db.commit()

	return {
		"capability_created": created_cap,
		"grants_created": created_grants,
	}
