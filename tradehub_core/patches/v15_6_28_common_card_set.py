"""Pricing kartlarında ORTAK özellik seti — tüm kartlar eşit uzunluk (✓/✗).

Her kartta AYNI 10 özellik gösterilir; o pakette dahilse ✓, değilse ✗ (üstü çizili).
Klasik karşılaştırma formatı; kartlar birebir aynı uzunlukta olur.

Idempotent: her plan için önce tüm pricing_features show_on_card=0, sonra 10 ortak
feature_key show_on_card=1 + is_disabled=(is_included? 0 : 1).
"""

from __future__ import annotations

import frappe

from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

# Tüm kartlarda gösterilecek ortak özellik seti (paketleri ayırt eden, dengeli)
COMMON_SET = [
	"feature.store.basic_storefront",  # Temel Vitrin
	"feature.pim.basic_product",  # Temel Ürün
	"feature.storefront.languages",  # Çoklu dil
	"feature.commerce.trade_assurance",  # Trade Assurance / güvenli ödeme
	"feature.functional.commission_report",  # Komisyon Raporu
	"feature.storefront.rich_media",  # Video & 360° medya
	"feature.store.custom_theme",  # Özel Tema
	"feature.functional.rfq",  # RFQ (Teklif Talebi)
	"feature.crm.module",  # CRM Modülü
	"feature.analytics.advanced",  # Gelişmiş Raporlar
	"feature.support.dedicated",  # Atanmış Destek
]

# Her pakette DAHİL (✓) olması istenen özellikler — Basic dahil is_included=1 zorlanır.
ALWAYS_INCLUDED = {
	"feature.storefront.languages",  # Çoklu dil
	"feature.commerce.trade_assurance",  # Güvenli ödeme
}


def execute():
	common = set(COMMON_SET)
	for plan in frappe.get_all("Subscription Plan", pluck="name"):
		doc = frappe.get_doc("Subscription Plan", plan)
		changed = False
		for r in doc.pricing_features:
			# Her pakette dahil olması istenenleri included yap
			if r.feature_key in ALWAYS_INCLUDED and not int(bool(r.is_included)):
				r.is_included = 1
				changed = True
			if r.feature_key in common:
				inc = int(bool(r.is_included))
				want_card, want_dis = 1, (0 if inc else 1)
			else:
				want_card, want_dis = 0, int(bool(r.is_disabled))
			if int(bool(r.show_on_card)) != want_card or int(bool(r.is_disabled)) != want_dis:
				r.show_on_card = want_card
				r.is_disabled = want_dis
				changed = True
		if changed:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
	invalidate_pricing_cache()
