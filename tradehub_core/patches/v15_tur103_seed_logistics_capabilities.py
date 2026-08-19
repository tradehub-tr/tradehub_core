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
#
# Public: LOG-038 backfill patch'i de bu matrisi kullanır (tek kaynak).
# ---------------------------------------------------------------------------
GRANTS: dict[str, list[str]] = {
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
	# G0/K1 (2026-08-19): `view.logistics_cost` düşürüldü — maliyet asimetrisi
	# kararı; satıcı taşıyıcı maliyetini görmez. Mevcut sitelerde
	# v15_9_21_g0_revoke_seller_cost_capability grant'ı pasifler; buradan
	# düşürmek yeni kurulumun hiç vermemesi için.
	"Seller Full Access": [
		"shipment.create",
		"shipment.write",
		"view.tracking",
	],
}


def seed_capability_grants(grants: dict[str, list[str]]) -> dict:
	"""Verilen matrise göre TH Capability Grant kayıtlarını oluşturur (idempotent).

	Role Profile veya capability DB'de yoksa atlanır — ama **sessizce değil**:
	atlanan her kayıt gerekçesiyle rapora girer, böylece çağıran patch loglayabilir.
	Bu fonksiyon LOG-038 backfill patch'i tarafından da çağrılır.

	Args:
		grants: role_profile adı → capability_key listesi.

	Returns:
		created / skipped_existing / missing_profiles / missing_capabilities raporu.
	"""
	created: list[tuple[str, str]] = []
	skipped_existing: list[tuple[str, str]] = []
	missing_profiles: list[str] = []
	missing_capabilities: set[str] = set()

	for profile_name, cap_keys in grants.items():
		if not frappe.db.exists("Role Profile", profile_name):
			missing_profiles.append(profile_name)
			continue

		for cap_key in cap_keys:
			if not frappe.db.exists("TH Capability Registry", cap_key):
				missing_capabilities.add(cap_key)
				continue

			if frappe.db.get_value(
				"TH Capability Grant",
				{"role_profile": profile_name, "capability": cap_key},
				"name",
			):
				skipped_existing.append((profile_name, cap_key))
				continue

			doc = frappe.new_doc("TH Capability Grant")
			doc.role_profile = profile_name
			doc.capability = cap_key
			doc.granted = 1
			doc.note = "Seed: TUR-103 lojistik modülü"
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			created.append((profile_name, cap_key))

	return {
		"created": created,
		"skipped_existing": skipped_existing,
		"missing_profiles": missing_profiles,
		"missing_capabilities": sorted(missing_capabilities),
	}


def execute() -> dict:
	"""Lojistik capability registry + grant seed."""
	created_caps: list[str] = []
	skipped_caps: list[str] = []

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
	grant_result = seed_capability_grants(GRANTS)

	# Temiz kurulumda lojistik Role Profile'ları bu patch'ten SONRA (LOG-037)
	# oluşur; o yüzden burada eksik kalmaları beklenen bir durumdur ve LOG-038
	# backfill'i tamamlar. Yine de sessiz geçme — görünür olsun.
	if grant_result["missing_profiles"]:
		frappe.log_error(
			f"Grant atlandı, Role Profile yok: {grant_result['missing_profiles']}"
			" — LOG-037/LOG-038 tamamlayacak",
			"v15_tur103_seed_logistics_capabilities",
		)

	frappe.db.commit()

	return {
		"created_capabilities": created_caps,
		"skipped_capabilities": skipped_caps,
		"grants": grant_result,
	}
