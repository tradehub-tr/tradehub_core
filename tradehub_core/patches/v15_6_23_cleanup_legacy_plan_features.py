"""Faz F — Storefront per-kart liste temizliği.

İki sorun:
1. Pre-Faz-J seed'den kalan **orphan** Pricing Plan Feature satırları (feature_key
   NULL ya da Feature Catalog'da olmayan eski key'ler — "Vitrin (TR dili)",
   "feature.rfq_module" vb.) hâlâ duruyor ve storefront per-kart listesini
   kirletiyor.
2. show_on_card bazı planlarda hiç set edilmemiş (FREE/STARTER=0). Bu yüzden
   storefront cardFeatures fallback'i devreye girip TÜM satırları (orphan dahil)
   gösteriyor.

Bu patch:
- Orphan satırları siler (yalnız gerçek Feature Catalog feature'larına bağlı
  satırlar kalır).
- show_on_card'ı tutarlı uygular: boolean feature'lar + üretici rozeti → 1,
  diğerleri → 0 (her planda).

Idempotent.
"""

from __future__ import annotations

import frappe

_BADGE_KEY = "feature.storefront.manufacturer_badge_tier"


def execute() -> None:
	# Yalnız storefront feature seti (display_category set) — pricing_features
	# yalnız bunları taşımalı. Backend capability'leri capability_flags JSON'da.
	storefront = frappe.get_all(
		"Feature Catalog",
		filters={"display_category": ["is", "set"]},
		fields=["feature_key", "value_type"],
	)
	catalog_keys = {r["feature_key"] for r in storefront}
	value_type_by_key = {r["feature_key"]: (r.get("value_type") or "boolean") for r in storefront}

	# 1) Orphan satırları sil (feature_key NULL veya katalogda yok)
	all_rows = frappe.get_all(
		"Pricing Plan Feature",
		filters={"parenttype": "Subscription Plan"},
		fields=["name", "feature_key"],
	)
	orphan_names = [
		r["name"] for r in all_rows if not r.get("feature_key") or r["feature_key"] not in catalog_keys
	]
	if orphan_names:
		frappe.db.delete("Pricing Plan Feature", {"name": ["in", orphan_names]})

	# 2) show_on_card'ı politikaya göre yeniden uygula (boolean + rozet → 1)
	remaining = frappe.get_all(
		"Pricing Plan Feature",
		filters={"parenttype": "Subscription Plan"},
		fields=["name", "feature_key"],
	)
	for r in remaining:
		key = r["feature_key"]
		on_card = 1 if (value_type_by_key.get(key) == "boolean" or key == _BADGE_KEY) else 0
		frappe.db.set_value("Pricing Plan Feature", r["name"], "show_on_card", on_card)

	frappe.db.commit()

	try:
		from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

		invalidate_pricing_cache()
	except Exception:
		frappe.log_error("pricing cache invalidate skipped", "v15_6_23 patch")
