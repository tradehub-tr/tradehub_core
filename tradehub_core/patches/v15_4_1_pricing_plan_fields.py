# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 4.1 — Subscription Plan'a pricing/storefront field'ları ekle.

Yeni alanlar:
  - badge_label (Data) — "EN POPÜLER", "BAŞLANGIÇ"
  - badge_color (Select) — yellow/black/premium/default
  - short_tagline (Small Text)
  - commission_rate (Percent)
  - max_active_listings (Int — display)
  - cta_label (Data)
  - cta_action (Select) — signup / signup_billing / contact_sales
  - theme (Select) — default / dark / premium
  - pricing_features (Table → Pricing Plan Feature)

Idempotent.

⚠ CANONICAL SOURCE-OF-TRUTH NOT:
  Bu patch'in `_INITIAL_PLAN_PRESETS` dict'i sadece **yeni site'lerin** seed'i
  için. Production'da live değerler için referans şu patch'ler:
    - v15_4_4_unify_signup_cta — cta_label (Ücretsiz başla / Satışla konuş)
    - v15_4_5_repair_commission_rates — commission_rate + max_active_listings
  CTA/oran değişikliğini buraya değil, yeni patch'e yaz.
"""

from __future__ import annotations

import frappe

_FIELDS = [
	{
		"dt": "Subscription Plan",
		"fieldname": "sb_pricing_display",
		"fieldtype": "Section Break",
		"label": "Pricing / Storefront Görünümü",
		"insert_after": "trial_days",
		"collapsible": 1,
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "badge_label",
		"fieldtype": "Data",
		"label": "Badge Label",
		"insert_after": "sb_pricing_display",
		"description": "Pricing card üst rozeti — 'EN POPÜLER', 'BAŞLANGIÇ', 'ÖLÇEKLENEN', 'KURUMSAL'",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "badge_color",
		"fieldtype": "Select",
		"label": "Badge Rengi",
		"options": "default\nyellow\nblack\npremium",
		"default": "default",
		"insert_after": "badge_label",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "cb_pricing_1",
		"fieldtype": "Column Break",
		"insert_after": "badge_color",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "theme",
		"fieldtype": "Select",
		"label": "Tema",
		"options": "default\ndark\npremium",
		"default": "default",
		"insert_after": "cb_pricing_1",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "short_tagline",
		"fieldtype": "Small Text",
		"label": "Kısa Slogan",
		"insert_after": "theme",
		"description": "Pricing card'da fiyat üstünde gösterilen 1-2 cümle",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "sb_pricing_meta",
		"fieldtype": "Section Break",
		"label": "Pricing Metadata",
		"insert_after": "short_tagline",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "commission_rate",
		"fieldtype": "Percent",
		"label": "Komisyon Oranı (%)",
		"insert_after": "sb_pricing_meta",
		"description": "Storefront'ta gösterilecek komisyon oranı (örn. 8.0 → %8)",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "max_active_listings",
		"fieldtype": "Int",
		"label": "Max Aktif Ürün (display)",
		"insert_after": "commission_rate",
		"description": "Storefront'ta gösterilecek limit. 0 = sınırsız. Backend gerçek quota_limits'ten okunur.",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "cb_pricing_2",
		"fieldtype": "Column Break",
		"insert_after": "max_active_listings",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "cta_label",
		"fieldtype": "Data",
		"label": "CTA Buton Metni",
		"insert_after": "cb_pricing_2",
		"description": "Pricing card aksiyon butonu — 'Starter ile başla', 'Professional seç'",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "cta_action",
		"fieldtype": "Select",
		"label": "CTA Aksiyon",
		"options": "signup\nsignup_billing\ncontact_sales\nlearn_more",
		"default": "signup",
		"insert_after": "cta_label",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "sb_pricing_features",
		"fieldtype": "Section Break",
		"label": "Paket İçeriği (Storefront)",
		"insert_after": "cta_action",
	},
	{
		"dt": "Subscription Plan",
		"fieldname": "pricing_features",
		"fieldtype": "Table",
		"label": "Pricing Features",
		"options": "Pricing Plan Feature",
		"insert_after": "sb_pricing_features",
	},
]


# Mevcut 4 plana default pricing değerleri
_PRESETS = {
	"FREE": {
		"badge_label": "ÜCRETSİZ",
		"badge_color": "default",
		"theme": "default",
		"short_tagline": "İlk üyeliğiniz bizden — temel marketplace deneyimi",
		"commission_rate": 10.0,
		"max_active_listings": 10,
		"cta_label": "Ücretsiz başla",
		"cta_action": "signup",
	},
	"STARTER": {
		"badge_label": "BAŞLANGIÇ",
		"badge_color": "default",
		"theme": "default",
		"short_tagline": "Global pazara ilk adımını atan küçük üreticiler için.",
		"commission_rate": 8.0,
		"max_active_listings": 50,
		"cta_label": "Ücretsiz başla",
		"cta_action": "signup_billing",
	},
	"PRO": {
		"badge_label": "EN POPÜLER",
		"badge_color": "yellow",
		"theme": "dark",
		"short_tagline": "Düzenli sipariş alan, büyümek isteyen üreticilerin ana paketi.",
		"commission_rate": 6.0,
		"max_active_listings": 500,
		"cta_label": "Ücretsiz başla",
		"cta_action": "signup_billing",
	},
	"ENTERPRISE": {
		"badge_label": "KURUMSAL",
		"badge_color": "premium",
		"theme": "premium",
		"short_tagline": "Çok tesisli üretici ve markalar için özel çözüm.",
		"commission_rate": 4.0,
		"max_active_listings": 0,  # 0 = sınırsız
		"cta_label": "Satışla konuş",
		"cta_action": "contact_sales",
	},
}


def execute() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	if not frappe.db.exists("DocType", "Subscription Plan"):
		return

	fields_by_doctype: dict[str, list[dict]] = {}
	for spec in _FIELDS:
		dt = spec.pop("dt")
		fields_by_doctype.setdefault(dt, []).append(spec)

	create_custom_fields(fields_by_doctype, ignore_validate=True)

	# Default değerleri set et
	for plan_code, presets in _PRESETS.items():
		if not frappe.db.exists("Subscription Plan", {"plan_code": plan_code}):
			continue
		plan_name = frappe.db.get_value("Subscription Plan", {"plan_code": plan_code}, "name")
		for field, value in presets.items():
			if not frappe.db.get_value("Subscription Plan", plan_name, field):
				try:
					frappe.db.set_value("Subscription Plan", plan_name, field, value)
				except Exception as exc:
					frappe.log_error(f"plan preset {plan_code}.{field} fail: {exc}", "pricing_patch")

	frappe.db.commit()
