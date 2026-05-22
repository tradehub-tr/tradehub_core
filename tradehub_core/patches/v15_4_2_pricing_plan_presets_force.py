# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 4.1.b — Mevcut 4 plana pricing display ayarlarını force apply.

Önceki patch (v15_4_1) `if not get_value(...)` koşulu nedeniyle field-default'u
olan değerleri override edemedi. Bu patch ilk kez çalışırken display_order,
highlighted, cta_action gibi field'ları kesin değerlerle set eder.

Idempotent ama tek-seferlik (flag ile koruyor).

⚠ CANONICAL SOURCE-OF-TRUTH NOT:
  - CTA label'lar için: `v15_4_4_unify_signup_cta` (Basic/Starter/Pro hepsi
    "Ücretsiz başla", Enterprise "Satışla konuş")
  - Commission/max_listings için: `v15_4_5_repair_commission_rates`
  Bu dosyadaki `_PRESETS` değerleri tarihsel; runtime sonuçları için yukarıdaki
  iki patch'i takip et. CTA değişikliği gerekirse v15_4_4'ü düzelt, yeni patch
  ekleme; veya yeni patch (v15_4_N) ile override et.
"""

from __future__ import annotations

import frappe

_FLAG_KEY = "tradehub:patch:v15_4_2_pricing_force_applied"

_PRESETS = {
	"FREE": {
		"display_order": 10,
		"highlighted": 0,
		"is_public": 1,
		"cta_action": "signup",
		"cta_label": "Ücretsiz başla",
	},
	"STARTER": {
		"display_order": 20,
		"highlighted": 0,
		"is_public": 1,
		"cta_action": "signup_billing",
		"cta_label": "Ücretsiz başla",
		"yearly_price": 3990.0,
	},
	"PRO": {
		"display_order": 30,
		"highlighted": 1,  # PRO == EN POPÜLER
		"is_public": 1,
		"cta_action": "signup_billing",
		"cta_label": "Ücretsiz başla",
		"monthly_price": 499.0,
		"yearly_price": 4990.0,
	},
	"ENTERPRISE": {
		"display_order": 40,
		"highlighted": 0,
		"is_public": 1,
		"cta_action": "contact_sales",
		"cta_label": "Satışla konuş",
	},
}


def execute() -> None:
	if frappe.cache().get_value(_FLAG_KEY):
		return  # tek-seferlik

	if not frappe.db.exists("DocType", "Subscription Plan"):
		return

	for plan_code, presets in _PRESETS.items():
		plan_name = frappe.db.get_value("Subscription Plan", {"plan_code": plan_code}, "name")
		if not plan_name:
			continue
		for field, value in presets.items():
			try:
				frappe.db.set_value("Subscription Plan", plan_name, field, value)
			except Exception as exc:
				frappe.log_error(f"plan force preset {plan_code}.{field} fail: {exc}", "pricing_patch_force")

	frappe.db.commit()
	frappe.cache().set_value(_FLAG_KEY, 1)
