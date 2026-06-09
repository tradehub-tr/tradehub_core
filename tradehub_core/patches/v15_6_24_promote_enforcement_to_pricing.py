"""Gerçek enforce edilen özellikleri Paket İçeriği (pricing) matrisine taşı.

Sorun: capability_flags/quota_limits ile gerçekten enforce edilen 28 özellik
(feature.pim.*, feature.store.*, feature.functional.*, feature.b2b.*, feature.crm.module,
feature.analytics.*, feature.api.webhook, feature.role.custom_creation, quota.max_*)
Feature Catalog'da display_category'siz olduğu için admin "Paket İçeriği" matrisinde
ve storefront karşılaştırma tablosunda görünmüyordu. Bu patch onlara display_category +
value_type atar ve her plan için Pricing Plan Feature hücresini plan'ın gerçek
capability_flags/quota_limits değerinden türetir (Pro'da CRM açıksa hücre de ✓).

Kapsam dışı: 11 rol-atama özelliği (feature.role.profile.*) — müşteriye/pakete
gösterilmesi anlamsız, sadece Yetenekler sekmesinde kalır.

Idempotent: display_category set_value upsert; plan hücreleri feature_key ile eşlenir,
varsa güncellenir yoksa eklenir. Enforcement (capability_flags/quota_limits) DEĞİŞMEZ —
bu yalnızca display katmanını (pricing_features child table) besler.
"""

from __future__ import annotations

import json

import frappe

from tradehub_core.api.v1.feature_catalog import _legacy_cell_type
from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

# (feature_key, display_category, value_type, display_order)
# Mevcut 24 pricing özelliğinin display_order'larıyla çakışmamak için yüksek başlatılır.
PROMOTE = [
	# ── Komisyon & Limitler (quota) ──────────────────────────
	("quota.max_products", "Komisyon & Limitler", "quota", 40),
	("quota.max_sub_users", "Komisyon & Limitler", "quota", 50),
	("quota.max_co_owners", "Komisyon & Limitler", "quota", 60),
	("quota.max_regions", "Komisyon & Limitler", "quota", 70),
	("quota.max_orders_per_month", "Komisyon & Limitler", "quota", 80),
	("quota.api_rate_limit", "Komisyon & Limitler", "quota", 90),
	# ── Vitrin & Mağaza (boolean) ────────────────────────────
	("feature.store.basic_storefront", "Vitrin & Mağaza", "boolean", 100),
	("feature.store.custom_theme", "Vitrin & Mağaza", "boolean", 110),
	("feature.store.custom_domain", "Vitrin & Mağaza", "boolean", 120),
	("feature.store.multi_language", "Vitrin & Mağaza", "boolean", 130),
	("feature.pim.basic_product", "Vitrin & Mağaza", "boolean", 140),
	("feature.pim.multi_variant", "Vitrin & Mağaza", "boolean", 150),
	("feature.pim.attribute_set", "Vitrin & Mağaza", "boolean", 160),
	("feature.pim.product_family", "Vitrin & Mağaza", "boolean", 170),
	("feature.pim.bulk_import", "Vitrin & Mağaza", "boolean", 180),
	# ── B2B Ticaret Modülleri (boolean) ──────────────────────
	("feature.functional.rfq", "B2B Ticaret Modülleri", "boolean", 100),
	("feature.functional.approval_chain", "B2B Ticaret Modülleri", "boolean", 110),
	("feature.functional.cargo_integration", "B2B Ticaret Modülleri", "boolean", 120),
	("feature.functional.commission_report", "B2B Ticaret Modülleri", "boolean", 130),
	("feature.b2b.approved_vendor_list", "B2B Ticaret Modülleri", "boolean", 140),
	("feature.b2b.cost_center", "B2B Ticaret Modülleri", "boolean", 150),
	("feature.b2b.organization_hierarchy", "B2B Ticaret Modülleri", "boolean", 160),
	("feature.crm.module", "B2B Ticaret Modülleri", "boolean", 170),
	# ── Destek & Kurumsal (boolean) ──────────────────────────
	("feature.analytics.basic", "Destek & Kurumsal", "boolean", 100),
	("feature.analytics.advanced", "Destek & Kurumsal", "boolean", 110),
	("feature.analytics.export", "Destek & Kurumsal", "boolean", 120),
	("feature.api.webhook", "Destek & Kurumsal", "boolean", 130),
	("feature.role.custom_creation", "Destek & Kurumsal", "boolean", 140),
]


def _derive_cell(key: str, value_type: str, caps: dict, quotas: dict) -> tuple[bool, str]:
	"""Plan'ın capability/quota değerinden hücre (is_included, text_value) türet."""
	if value_type == "quota":
		raw = quotas.get(key)
		if raw is None or raw == 0:
			return False, ""
		if raw == -1:
			return True, "Sınırsız"
		return True, str(raw)
	# boolean (capability)
	return bool(caps.get(key)), ""


def execute():
	# 1) Feature Catalog: display_category + value_type + display_order ata (display_name korunur)
	for key, cat, vtype, order in PROMOTE:
		if not frappe.db.exists("Feature Catalog", key):
			continue
		frappe.db.set_value(
			"Feature Catalog",
			key,
			{"display_category": cat, "value_type": vtype, "display_order": order},
			update_modified=False,
		)

	# 2) Her plan için pricing_features hücrelerini plan'ın gerçek değerinden türet
	plans = frappe.get_all("Subscription Plan", pluck="name")
	for name in plans:
		doc = frappe.get_doc("Subscription Plan", name)
		caps = json.loads(doc.capability_flags or "{}")
		quotas = json.loads(doc.quota_limits or "{}")
		existing = {r.feature_key: r for r in doc.pricing_features if r.feature_key}
		changed = False

		for key, _cat, vtype, _order in PROMOTE:
			if not frappe.db.exists("Feature Catalog", key):
				continue
			legacy = _legacy_cell_type(vtype)
			is_inc, tv = _derive_cell(key, vtype, caps, quotas)
			row = existing.get(key)
			if row:
				if (
					row.value_type != legacy
					or int(bool(row.is_included)) != int(is_inc)
					or (row.text_value or "") != tv
				):
					row.value_type = legacy
					row.is_included = 1 if is_inc else 0
					row.text_value = tv
					changed = True
			else:
				doc.append(
					"pricing_features",
					{
						"feature_key": key,
						"value_type": legacy,
						"is_included": 1 if is_inc else 0,
						"text_value": tv,
						"show_on_card": 0,
					},
				)
				changed = True

		if changed:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
	invalidate_pricing_cache()
