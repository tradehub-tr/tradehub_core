"""Pricing kartları için küratörlü `show_on_card` başlangıç seti.

Her plan kartında SADECE öne çıkan özellikler görünsün (Basic ~7, Pro ~10),
Enterprise'da TÜM included özellikler işaretli ("her şey dahil").

Idempotent: her plan için önce tüm pricing_features show_on_card=0, sonra seçili
feature_key'ler (yalnızca o planda is_included ise) show_on_card=1.
Bu sadece başlangıç küratörlüğü — admin "Paket İçeriği" matrisinden değiştirebilir.
"""

from __future__ import annotations

import frappe

from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

# Basic (FREE) kartında öne çıkacak özellikler
BASIC_CARD = [
	"quota.commission_rate",
	"quota.max_active_listings",
	"feature.store.basic_storefront",
	"feature.storefront.languages",
	"feature.pim.basic_product",
	"feature.functional.commission_report",
	"feature.support.tier",
]

# Pro Platinium (PRO) kartında öne çıkacak özellikler
PRO_CARD = [
	"quota.commission_rate",
	"quota.max_active_listings",
	"feature.storefront.rich_media",
	"feature.store.custom_theme",
	"feature.functional.rfq",
	"feature.crm.module",
	"feature.functional.cargo_integration",
	"feature.analytics.advanced",
	"feature.marketing.keyword_ads",
	"feature.api.access",
]

# plan_code → kart key listesi; ENTERPRISE özel (tüm included)
CARD_BY_PLAN = {"FREE": BASIC_CARD, "PRO": PRO_CARD}


def execute():
	for plan in frappe.get_all("Subscription Plan", pluck="name"):
		doc = frappe.get_doc("Subscription Plan", plan)
		if plan == "ENTERPRISE":
			# Enterprise: tüm included özellikler kartta
			wanted = None  # özel işaret
		else:
			wanted = set(CARD_BY_PLAN.get(plan, []))

		changed = False
		for r in doc.pricing_features:
			if wanted is None:
				target = 1 if int(bool(r.is_included)) else 0
			else:
				target = 1 if (r.feature_key in wanted and int(bool(r.is_included))) else 0
			if int(bool(r.show_on_card)) != target:
				r.show_on_card = target
				changed = True

		if changed:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
	invalidate_pricing_cache()
