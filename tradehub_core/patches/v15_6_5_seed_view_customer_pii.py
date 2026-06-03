"""Sprint 5 — view.customer_pii capability seed.

CRM Lead, Contact ve CRM Organization kayıtlarındaki müşteri PII
(telefon, e-posta, WhatsApp, doğum tarihi vs.) alanlarına okuma yetkisi.

Tier önerisi: SALES (mağazanın müşteri ilişki yöneticisi — Co-Owner üstü).
Sales Rep henüz fixture'da yok — Sprint 6'da hâlâ dead config; o yüzden grant
matrisi şu an Full Access + Co-Owner + Manager (Management) için açık.

İdempotent.
"""

from __future__ import annotations

import frappe

_CAP_KEY = "view.customer_pii"
_GRANT_PROFILES = (
	"Seller Full Access",
	"Seller Co-Owner",
	"Seller Manager",  # CRM manager rolü de müşteri kontağına ihtiyaç duyabilir
)


def execute() -> dict:
	created_cap = False
	created_grants: list[str] = []

	if not frappe.db.exists("TH Capability Registry", _CAP_KEY):
		doc = frappe.new_doc("TH Capability Registry")
		doc.capability_key = _CAP_KEY
		doc.label = "Müşteri PII Görüntüleme"
		doc.description = (
			"CRM Lead, Contact ve CRM Organization içindeki telefon, e-posta, "
			"WhatsApp gibi müşteri PII alanlarını maskelenmemiş okuma yetkisi."
		)
		doc.module_group = "Görüntüleme"
		doc.default_tier = "SALES"
		doc.is_owner_only = 0
		doc.requires_kyc = 0
		doc.requires_aml = 0
		doc.is_protected = 0
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created_cap = True

	for profile in _GRANT_PROFILES:
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
		g.note = "Seed: Sprint 5 view.customer_pii"
		g.flags.ignore_permissions = True
		g.insert(ignore_permissions=True)
		created_grants.append(profile)

	frappe.db.commit()

	return {
		"capability_created": created_cap,
		"grants_created": created_grants,
	}
