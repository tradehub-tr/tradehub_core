"""TUR-103 — Lojistik modülü capability seed.

8 TH Capability Registry kaydı + TH Capability Grant kayıtları oluşturur.

Capability'ler:
  - shipment.create         → Sevkiyat oluşturma
  - shipment.write          → Sevkiyat düzenleme
  - shipment.cancel         → Sevkiyat iptal
  - shipment.split          → Sevkiyat bölme
  - view.logistics_cost     → Lojistik maliyet görüntüleme
  - view.tracking           → Kargo takip bilgisi görüntüleme
  - carrier_credential.manage → Kargo entegrasyon yönetimi
  - view.carrier_secret     → Kargo API anahtarı görüntüleme

Grant matrisi:
  - Logistics Manager:           tüm 8 capability
  - Logistics Operator:          shipment.create, shipment.write, view.tracking
  - Carrier Integration Manager: carrier_credential.manage, view.carrier_secret,
                                 view.tracking
  - Seller Full Access:          shipment.create, shipment.write, view.tracking,
                                 view.logistics_cost

İdempotent: var olan kayıtların değişmemiş field'larına dokunmaz.
"""

from __future__ import annotations

import frappe

# ---------------------------------------------------------------------------
# Capability tanımları: (key, label, module_group, default_tier, is_owner_only)
# ---------------------------------------------------------------------------
_CAPABILITIES: list[tuple[str, str, str, str, int]] = [
	("shipment.create", "Sevkiyat Oluşturma", "Lojistik", "OPERATIONS", 0),
	("shipment.write", "Sevkiyat Düzenleme", "Lojistik", "OPERATIONS", 0),
	("shipment.cancel", "Sevkiyat İptal", "Lojistik", "MANAGEMENT", 0),
	("shipment.split", "Sevkiyat Bölme", "Lojistik", "MANAGEMENT", 0),
	("view.logistics_cost", "Lojistik Maliyet Görüntüleme", "Lojistik", "FINANCE", 0),
	("view.tracking", "Kargo Takip Bilgisi Görüntüleme", "Lojistik", "OPERATIONS", 0),
	("carrier_credential.manage", "Kargo Entegrasyon Yönetimi", "Lojistik", "MANAGEMENT", 0),
	("view.carrier_secret", "Kargo API Anahtarı Görüntüleme", "Lojistik", "MANAGEMENT", 0),
]

# ---------------------------------------------------------------------------
# Grant matrisi: role_profile → capability_key listesi
# ---------------------------------------------------------------------------
_GRANTS: dict[str, list[str]] = {
	"Logistics Manager": [
		"shipment.create",
		"shipment.write",
		"shipment.cancel",
		"shipment.split",
		"view.logistics_cost",
		"view.tracking",
		"carrier_credential.manage",
		"view.carrier_secret",
	],
	"Logistics Operator": [
		"shipment.create",
		"shipment.write",
		"view.tracking",
	],
	"Carrier Integration Manager": [
		"carrier_credential.manage",
		"view.carrier_secret",
		"view.tracking",
	],
	"Seller Full Access": [
		"shipment.create",
		"shipment.write",
		"view.tracking",
		"view.logistics_cost",
	],
}


def execute() -> dict:
	"""Lojistik capability registry + grant seed."""
	created_caps: list[str] = []
	skipped_caps: list[str] = []
	created_grants: list[tuple[str, str]] = []
	skipped_grants: list[tuple[str, str]] = []

	# 1) TH Capability Registry kayıtları
	for cap_key, label, module_group, default_tier, is_owner_only in _CAPABILITIES:
		if frappe.db.exists("TH Capability Registry", cap_key):
			skipped_caps.append(cap_key)
			continue

		doc = frappe.new_doc("TH Capability Registry")
		doc.capability_key = cap_key
		doc.label = label
		doc.module_group = module_group
		doc.default_tier = default_tier
		doc.is_owner_only = is_owner_only
		doc.requires_kyc = 0
		doc.requires_aml = 0
		doc.is_protected = 0
		doc.is_active = 1
		doc.plan_feature_flag = ""
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created_caps.append(cap_key)

	# 2) TH Capability Grant kayıtları
	for profile_name, cap_keys in _GRANTS.items():
		if not frappe.db.exists("Role Profile", profile_name):
			continue

		for cap_key in cap_keys:
			if not frappe.db.exists("TH Capability Registry", cap_key):
				continue

			existing = frappe.db.get_value(
				"TH Capability Grant",
				{"role_profile": profile_name, "capability": cap_key},
				"name",
			)
			if existing:
				skipped_grants.append((profile_name, cap_key))
				continue

			doc = frappe.new_doc("TH Capability Grant")
			doc.role_profile = profile_name
			doc.capability = cap_key
			doc.granted = 1
			doc.note = "Seed: TUR-103 lojistik modülü"
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			created_grants.append((profile_name, cap_key))

	frappe.db.commit()

	return {
		"created_capabilities": created_caps,
		"skipped_capabilities": skipped_caps,
		"created_grants": created_grants,
		"skipped_grants": skipped_grants,
	}
