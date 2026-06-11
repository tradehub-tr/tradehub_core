"""Faz J — Storefront pricing matrix Feature Catalog seed + Plan-Feature mapping.

Önce storefront'taki hardcoded MatrixRow listesi (SellPageLayout.ts) backend'e
taşındı. Bu patch:

1. Feature Catalog'a 18 feature seed eder (display_category, display_order ile
   yeni eklenen field'ları kullanır).
2. Her mevcut Subscription Plan (FREE/STARTER/PRO/ENTERPRISE) için
   Pricing Plan Feature row'larını seed eder — value_type + is_included +
   text_value alanları doldurularak.

Idempotent: aynı feature_key varsa skip, aynı plan+feature varsa skip.
"""

from __future__ import annotations

import frappe

# Storefront pricing matrix — 4 kategori, 18 feature.
# Her feature: (feature_key, display_name, display_category, display_order,
#               value_type, plan_values: dict[plan_code, value])
# value: checkbox için bool (True/False), text için str.
PRICING_FEATURES: list[tuple[str, str, str, int, str, dict[str, object]]] = [
	# ── Komisyon & Limitler ─────────────────────────────────────────────
	(
		"quota.commission_rate",
		"Satış komisyonu",
		"Komisyon & Limitler",
		10,
		"text",
		{"FREE": "Özel", "STARTER": "Özel", "PRO": "Özel", "ENTERPRISE": "Özel"},
	),
	(
		"quota.max_active_listings",
		"Aktif ürün limiti",
		"Komisyon & Limitler",
		20,
		"text",
		{
			"FREE": "Sınırsız",
			"STARTER": "Sınırsız",
			"PRO": "Sınırsız",
			"ENTERPRISE": "Sınırsız",
		},
	),
	(
		"feature.sales.sample_sales",
		"Numune satışı",
		"Komisyon & Limitler",
		30,
		"checkbox",
		{"FREE": True, "STARTER": True, "PRO": True, "ENTERPRISE": True},
	),
	(
		"feature.pim.bulk_csv_upload",
		"Toplu yükleme (CSV)",
		"Komisyon & Limitler",
		40,
		"checkbox",
		{"FREE": True, "STARTER": True, "PRO": True, "ENTERPRISE": True},
	),
	# ── Vitrin & Sergileme ──────────────────────────────────────────────
	(
		"feature.storefront.manufacturer_badge_tier",
		"Üretici rozeti",
		"Vitrin & Sergileme",
		10,
		"text",
		{
			"FREE": "Standart",
			"STARTER": "Gümüş",
			"PRO": "Altın",
			"ENTERPRISE": "Platinum",
		},
	),
	(
		"feature.storefront.tier",
		"Vitrin tipi",
		"Vitrin & Sergileme",
		20,
		"text",
		{
			"FREE": "Standart",
			"STARTER": "Premium",
			"PRO": "Premium+",
			"ENTERPRISE": "Tam özel",
		},
	),
	(
		"feature.storefront.languages",
		"Çoklu dil",
		"Vitrin & Sergileme",
		30,
		"text",
		{
			"FREE": "2 dil",
			"STARTER": "4 dil",
			"PRO": "6 dil",
			"ENTERPRISE": "15+ dil",
		},
	),
	(
		"feature.storefront.rich_media",
		"Video & 360°",
		"Vitrin & Sergileme",
		40,
		"checkbox",
		{"FREE": False, "STARTER": False, "PRO": True, "ENTERPRISE": True},
	),
	(
		"quota.featured_listings_monthly",
		"Öne çıkan listeleme/ay",
		"Vitrin & Sergileme",
		50,
		"text",
		{"FREE": "—", "STARTER": "5", "PRO": "20", "ENTERPRISE": "Sınırsız"},
	),
	# ── Destek & Operasyon ──────────────────────────────────────────────
	(
		"feature.support.tier",
		"Destek",
		"Destek & Operasyon",
		10,
		"text",
		{
			"FREE": "Email",
			"STARTER": "Öncelikli",
			"PRO": "Hesap yöneticisi",
			"ENTERPRISE": "7/24 dedicated",
		},
	),
	(
		"quota.team_seats",
		"Ekip kullanıcısı",
		"Destek & Operasyon",
		20,
		"text",
		{"FREE": "1", "STARTER": "3", "PRO": "10", "ENTERPRISE": "Sınırsız"},
	),
	(
		"quota.ad_credit_monthly",
		"Reklam kredisi/ay",
		"Destek & Operasyon",
		30,
		"text",
		{"FREE": "—", "STARTER": "€100", "PRO": "€300", "ENTERPRISE": "Özel"},
	),
	(
		"feature.support.vat_refund_advisory",
		"KDV iadesi danışmanlığı",
		"Destek & Operasyon",
		40,
		"checkbox",
		{"FREE": True, "STARTER": True, "PRO": True, "ENTERPRISE": True},
	),
	(
		"feature.logistics.insured_shipping",
		"Sigortalı kargo",
		"Destek & Operasyon",
		50,
		"checkbox",
		{"FREE": True, "STARTER": True, "PRO": True, "ENTERPRISE": True},
	),
	(
		"feature.support.event_invitations",
		"Fuar/etkinlik daveti",
		"Destek & Operasyon",
		60,
		"checkbox",
		{"FREE": False, "STARTER": False, "PRO": True, "ENTERPRISE": True},
	),
	# ── Kurumsal ────────────────────────────────────────────────────────
	(
		"feature.api.access",
		"API erişimi",
		"Kurumsal",
		10,
		"text",
		{
			"FREE": "—",
			"STARTER": "Limitli",
			"PRO": "Tam",
			"ENTERPRISE": "Özel SLA",
		},
	),
	(
		"feature.api.erp_integration",
		"ERP/muhasebe entegrasyonu",
		"Kurumsal",
		20,
		"text",
		{"FREE": "—", "STARTER": "—", "PRO": "Beta", "ENTERPRISE": "Tam"},
	),
	(
		"feature.commerce.custom_payment_terms",
		"Özel ödeme koşulları",
		"Kurumsal",
		30,
		"checkbox",
		{"FREE": False, "STARTER": False, "PRO": False, "ENTERPRISE": True},
	),
	(
		"feature.storefront.custom_subdomain",
		"Alt domain",
		"Kurumsal",
		40,
		"checkbox",
		{"FREE": False, "STARTER": False, "PRO": False, "ENTERPRISE": True},
	),
]


def _category_to_internal(display_category: str) -> str:
	"""Display category → mevcut Feature Catalog.category enum'una map."""
	mapping = {
		"Komisyon & Limitler": "QuotaLimits",
		"Vitrin & Sergileme": "StoreFeatures",
		"Destek & Operasyon": "FunctionalFeatures",
		"Kurumsal": "APIFeatures",
	}
	return mapping.get(display_category, "StoreFeatures")


def _seed_feature_catalog() -> dict:
	"""Feature Catalog'a 18 feature'ı seed et. Mevcut kayıtları güncellemez."""
	created: list[str] = []
	updated_display: list[str] = []
	for key, display_name, display_category, display_order, _value_type, _values in PRICING_FEATURES:
		if frappe.db.exists("Feature Catalog", key):
			# display_category / display_order eksikse doldur (yeni field)
			doc = frappe.get_doc("Feature Catalog", key)
			changed = False
			if not doc.get("display_category"):
				doc.display_category = display_category
				changed = True
			if not doc.get("display_order"):
				doc.display_order = display_order
				changed = True
			if changed:
				doc.flags.ignore_permissions = True
				doc.save(ignore_permissions=True)
				updated_display.append(key)
			continue

		# feature_type validator ile uyumlu: feature.* → Capability, quota.* → Quota.
		# value_type pricing UI render içindir (checkbox vs text), backend tipiyle bağımsız.
		feature_type = "Quota" if key.startswith("quota.") else "Capability"
		doc = frappe.new_doc("Feature Catalog")
		doc.feature_key = key
		doc.display_name = display_name
		doc.category = _category_to_internal(display_category)
		doc.feature_type = feature_type
		doc.display_category = display_category
		doc.display_order = display_order
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created.append(key)
	return {"created": created, "updated_display": updated_display}


def _seed_plan_features() -> dict:
	"""Her Subscription Plan için Pricing Plan Feature row'larını seed et.
	Hem UPPERCASE hem lowercase plan kodlarını destekler."""
	# UPPERCASE veya lowercase varyantları
	plan_codes = ["FREE", "STARTER", "PRO", "ENTERPRISE"]
	plans_by_code: dict[str, str] = {}  # plan_code → actual plan name
	for code in plan_codes:
		for variant in (code, code.lower()):
			if frappe.db.exists("Subscription Plan", variant):
				plans_by_code[code] = variant
				break

	added: list[tuple[str, str]] = []
	skipped_existing: list[tuple[str, str]] = []
	for code, plan_name in plans_by_code.items():
		plan = frappe.get_doc("Subscription Plan", plan_name)
		# Mevcut feature_key'lerin set'i (yeniden eklemeyiz)
		existing_keys = {
			row.get("feature_key") for row in (plan.get("pricing_features") or []) if row.get("feature_key")
		}
		row_changed = False
		for key, display_name, _display_category, display_order, value_type, values in PRICING_FEATURES:
			if key in existing_keys:
				skipped_existing.append((plan_name, key))
				continue
			val = values.get(code)
			if val is None:
				continue
			row = plan.append("pricing_features", {})
			row.feature_key = key
			row.value_type = value_type
			row.sort_order = display_order
			if value_type == "checkbox":
				row.is_included = 1 if bool(val) else 0
				row.text_value = ""
			else:
				row.is_included = 0
				row.text_value = str(val)
			# legacy display_text: matris UI'ı Feature Catalog'tan beslenir
			row.display_text = display_name
			added.append((plan_name, key))
			row_changed = True

		if row_changed:
			plan.flags.ignore_permissions = True
			plan.flags.ignore_mandatory = True
			plan.flags.ignore_links = True
			plan.save(ignore_permissions=True)
	return {
		"added_rows": added,
		"skipped_existing": skipped_existing,
		"plans_seeded": list(plans_by_code.values()),
	}


def execute() -> dict:
	"""Migration patch entry point."""
	catalog_result = _seed_feature_catalog()
	plan_result = _seed_plan_features()
	frappe.db.commit()
	# Storefront cache flush
	try:
		frappe.cache().delete_value("tradehub:pricing:public")
	except Exception:  # noqa: BLE001
		pass
	return {
		"feature_catalog": catalog_result,
		"plan_features": plan_result,
	}
