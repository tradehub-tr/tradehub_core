"""Enterprise "en dolu paket": tüm pricing özellikleri kartta + 2 yeni Enterprise-özel özellik.

- 2 yeni Feature Catalog özelliği (pricing-display; gerçek enforcement YOK, capability_flags'e
  eklenmez): feature.ai.translate (AI Çeviri → Vitrin & Mağaza),
  feature.support.dedicated (Atanmış Destek → Destek & Kurumsal).
- Bu 2 özellik SADECE Enterprise'da açık+kartta; Basic/Pro'da kapalı.
- Enterprise'ın TÜM pricing_features hücreleri → is_included=1, show_on_card=1, is_disabled=0
  (quota/enum text_value KORUNUR — mevcut Enterprise değerleri zaten en üst).

Idempotent: feature/hücre yoksa oluştur, varsa güncelle. Enforcement değişmez.
"""

from __future__ import annotations

import frappe

from tradehub_core.api.v1.feature_catalog import _legacy_cell_type
from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

# (feature_key, display_name, display_category, internal_category)
NEW_FEATURES = [
	("feature.ai.translate", "AI Çeviri", "Vitrin & Mağaza", "StoreFeatures"),
	("feature.support.dedicated", "Atanmış Destek", "Destek & Kurumsal", "FunctionalFeatures"),
]

ENTERPRISE = "ENTERPRISE"


def execute():
	# 1) 2 yeni Feature Catalog kaydı (idempotent)
	for key, name, dcat, icat in NEW_FEATURES:
		if not frappe.db.exists("Feature Catalog", key):
			doc = frappe.new_doc("Feature Catalog")
			doc.feature_key = key
			doc.display_name = name
			doc.display_category = dcat
			doc.category = icat
			doc.feature_type = "Capability"
			doc.value_type = "boolean"
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
		else:
			frappe.db.set_value(
				"Feature Catalog",
				key,
				{"display_category": dcat, "value_type": "boolean"},
				update_modified=False,
			)

	new_keys = [k for k, *_ in NEW_FEATURES]

	# 2) Her plan için hücreleri kur
	for plan in frappe.get_all("Subscription Plan", pluck="name"):
		doc = frappe.get_doc("Subscription Plan", plan)
		is_ent = plan == ENTERPRISE
		existing = {r.feature_key: r for r in doc.pricing_features if r.feature_key}
		changed = False

		# 2a) 2 yeni özelliğin hücresi — sadece Enterprise'da açık+kartta
		for key in new_keys:
			inc = 1 if is_ent else 0
			row = existing.get(key)
			if row:
				if (
					int(bool(row.is_included)) != inc
					or int(bool(row.show_on_card)) != inc
					or int(bool(row.is_disabled)) != 0
					or row.value_type != "checkbox"
				):
					row.is_included = inc
					row.show_on_card = inc
					row.is_disabled = 0
					row.value_type = "checkbox"
					changed = True
			else:
				doc.append(
					"pricing_features",
					{
						"feature_key": key,
						"value_type": "checkbox",
						"is_included": inc,
						"text_value": "",
						"show_on_card": inc,
						"is_disabled": 0,
					},
				)
				changed = True

		# 2b) Enterprise: katalogdaki TÜM display_category'li özellikler için hücre
		# garantile → is_included=1, show_on_card=1, is_disabled=0 (text_value korunur;
		# eksik hücre boş text ile eklenir, kart display_name'i ✓ gösterir).
		if is_ent:
			catalog = frappe.get_all(
				"Feature Catalog",
				filters={"is_deprecated": 0, "display_category": ["is", "set"]},
				fields=["feature_key", "value_type"],
			)
			cur = {r.feature_key: r for r in doc.pricing_features if r.feature_key}
			for cf in catalog:
				key = cf["feature_key"]
				legacy = _legacy_cell_type(cf.get("value_type") or "boolean")
				row = cur.get(key)
				if row:
					if (
						int(bool(row.is_included)) != 1
						or int(bool(row.show_on_card)) != 1
						or int(bool(row.is_disabled)) != 0
					):
						row.is_included = 1
						row.show_on_card = 1
						row.is_disabled = 0
						changed = True
				else:
					doc.append(
						"pricing_features",
						{
							"feature_key": key,
							"value_type": legacy,
							"is_included": 1,
							"text_value": "",
							"show_on_card": 1,
							"is_disabled": 0,
						},
					)
					changed = True

		if changed:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
	invalidate_pricing_cache()
