"""Faz E — Storefront plan/feature içerik & tier restructure.

Önceki seed verisi bozuktu (boolean'lar tüm planlarda ✓, quota/enum yalnız PRO).
Bu patch araştırmaya dayalı 6 kategori + 24 feature (5 yeni) + 4 planın tüm tier
değerlerini idempotent biçimde kurar. value_type feature-seviyesi (Faz A).

Kategoriler: Komisyon & Limitler / Vitrin & Mağaza / B2B Ticaret Modülleri /
Pazarlama & Görünürlük / Güven & Doğrulama / Destek & Kurumsal.

Komisyon %8/6/4/Özel — storefront'taki "%4 — %8" ile uyumlu. Ayrıca her plan'ın
commission_rate + max_active_listings alanları senkronlanır (storefront bu iki
satırı plan field'ından override eder).

Idempotent: feature_key'ler upsert; plan hücreleri feature_key ile eşlenir.
"""

from __future__ import annotations

import frappe

PLAN_CODES = ["FREE", "STARTER", "PRO", "ENTERPRISE"]

# (key, name, category, order, vtype, unit, enum_options, (free, starter, pro, ent), desc)
# boolean → değerler bool; quota/enum/text → str.
B = True
F = False
FEATURES = [
	# ── 1) Komisyon & Limitler ─────────────────────────────
	(
		"quota.commission_rate",
		"Satış komisyonu",
		"Komisyon & Limitler",
		10,
		"quota",
		"%",
		None,
		("8", "6", "4", "Özel"),
		"Tamamlanan siparişler üzerinden alınan platform komisyonu.",
	),
	(
		"quota.max_active_listings",
		"Aktif ürün limiti",
		"Komisyon & Limitler",
		20,
		"quota",
		"",
		None,
		("25", "250", "2500", "Sınırsız"),
		"Aynı anda yayında tutulabilecek ürün sayısı.",
	),
	(
		"quota.team_seats",
		"Ekip kullanıcısı",
		"Komisyon & Limitler",
		30,
		"quota",
		"",
		None,
		("1", "3", "10", "Sınırsız"),
		"Mağazaya eklenebilecek alt kullanıcı / ekip koltuğu sayısı.",
	),
	# ── 2) Vitrin & Mağaza ─────────────────────────────────
	(
		"feature.storefront.tier",
		"Vitrin tipi",
		"Vitrin & Mağaza",
		10,
		"enum",
		"",
		["Standart", "Premium", "Premium+", "Tam özel"],
		("Standart", "Premium", "Premium+", "Tam özel"),
		"Mağaza vitrini şablon/özelleştirme seviyesi.",
	),
	(
		"quota.featured_listings_monthly",
		"Öne çıkan listeleme/ay",
		"Vitrin & Mağaza",
		20,
		"quota",
		"",
		None,
		("0", "5", "20", "Sınırsız"),
		"Aylık öne çıkarılabilecek ürün ilanı sayısı.",
	),
	(
		"feature.storefront.languages",
		"Çoklu dil",
		"Vitrin & Mağaza",
		30,
		"enum",
		"",
		["2 dil", "4 dil", "6 dil", "15+ dil"],
		("2 dil", "4 dil", "6 dil", "15+ dil"),
		"Vitrin/ürün sayfalarının desteklediği dil sayısı.",
	),
	(
		"feature.storefront.rich_media",
		"Video & 360° medya",
		"Vitrin & Mağaza",
		40,
		"boolean",
		"",
		None,
		(F, F, B, B),
		"Ürünlerde video ve 360° görsel medya.",
	),
	(
		"feature.storefront.custom_subdomain",
		"Alt domain (markaniz.istoc.com)",
		"Vitrin & Mağaza",
		50,
		"boolean",
		"",
		None,
		(F, F, F, B),
		"Markaya özel alt domain.",
	),
	# ── 3) B2B Ticaret Modülleri ───────────────────────────
	(
		"quota.rfq_quotes_monthly",
		"RFQ teklif kotası/ay",
		"B2B Ticaret Modülleri",
		10,
		"quota",
		"",
		None,
		("0", "10", "50", "Sınırsız"),
		"Aylık yanıtlanabilecek RFQ (teklif talebi) sayısı.",
	),
	(
		"feature.sales.sample_sales",
		"Numune satışı",
		"B2B Ticaret Modülleri",
		20,
		"boolean",
		"",
		None,
		(F, B, B, B),
		"Alıcılara numune satışı yapabilme.",
	),
	(
		"feature.pim.bulk_csv_upload",
		"Toplu yükleme (CSV)",
		"B2B Ticaret Modülleri",
		30,
		"boolean",
		"",
		None,
		(F, B, B, B),
		"CSV/Excel ile toplu ürün yükleme.",
	),
	(
		"feature.commerce.trade_assurance",
		"Trade Assurance / güvenli ödeme",
		"B2B Ticaret Modülleri",
		40,
		"boolean",
		"",
		None,
		(F, F, B, B),
		"Escrow tabanlı alıcı koruması / güvenli ödeme.",
	),
	(
		"feature.commerce.custom_payment_terms",
		"Özel ödeme koşulları",
		"B2B Ticaret Modülleri",
		50,
		"boolean",
		"",
		None,
		(F, F, F, B),
		"Vadeli / özel ödeme koşulları tanımlama.",
	),
	# ── 4) Pazarlama & Görünürlük ──────────────────────────
	(
		"feature.marketing.search_boost",
		"Arama önceliği",
		"Pazarlama & Görünürlük",
		10,
		"enum",
		"",
		["Standart", "Yüksek", "Özel"],
		("Standart", "Standart", "Yüksek", "Özel"),
		"Arama sonuçlarında görünürlük önceliği.",
	),
	(
		"feature.marketing.keyword_ads",
		"Keyword / P4P reklam",
		"Pazarlama & Görünürlük",
		20,
		"boolean",
		"",
		None,
		(F, B, B, B),
		"Anahtar kelime / tıklama-başı reklam erişimi.",
	),
	(
		"quota.ad_credit_monthly",
		"Reklam kredisi/ay",
		"Pazarlama & Görünürlük",
		30,
		"quota",
		"€",
		None,
		("0", "100", "300", "Özel"),
		"Aylık reklam kredisi.",
	),
	(
		"feature.support.event_invitations",
		"Fuar / etkinlik daveti",
		"Pazarlama & Görünürlük",
		40,
		"boolean",
		"",
		None,
		(F, F, B, B),
		"Fuar ve özel etkinliklere davet.",
	),
	# ── 5) Güven & Doğrulama ───────────────────────────────
	(
		"feature.storefront.manufacturer_badge_tier",
		"Üretici doğrulama",
		"Güven & Doğrulama",
		10,
		"enum",
		"",
		["Yok", "Şirket Doğrulandı", "Fabrika Audit'li", "Fabrika Audit'li + Video"],
		("Yok", "Şirket Doğrulandı", "Fabrika Audit'li", "Fabrika Audit'li + Video"),
		"Üretici güven rozeti seviyesi (şirket → fabrika saha audit).",
	),
	(
		"feature.support.vat_refund_advisory",
		"KDV / ihracat danışmanlığı",
		"Güven & Doğrulama",
		20,
		"enum",
		"",
		["Yok", "Sınırlı", "Tam"],
		("Yok", "Yok", "Sınırlı", "Tam"),
		"KDV iadesi ve ihracat süreç danışmanlığı.",
	),
	(
		"feature.logistics.insured_shipping",
		"Sigortalı kargo dahil",
		"Güven & Doğrulama",
		30,
		"boolean",
		"",
		None,
		(F, B, B, B),
		"Sigortalı kargo seçeneği.",
	),
	# ── 6) Destek & Kurumsal ───────────────────────────────
	(
		"feature.support.tier",
		"Destek seviyesi",
		"Destek & Kurumsal",
		10,
		"enum",
		"",
		["E-posta", "Öncelikli", "Hesap yöneticisi", "7×24 tahsisli"],
		("E-posta", "Öncelikli", "Hesap yöneticisi", "7×24 tahsisli"),
		"Müşteri destek seviyesi.",
	),
	(
		"feature.api.access",
		"API erişimi",
		"Destek & Kurumsal",
		20,
		"enum",
		"",
		["Yok", "Limitli", "Tam", "Özel SLA"],
		("Yok", "Limitli", "Tam", "Özel SLA"),
		"Sipariş/stok/fiyat senkron API erişimi.",
	),
	(
		"feature.api.erp_integration",
		"ERP / muhasebe entegrasyonu",
		"Destek & Kurumsal",
		30,
		"boolean",
		"",
		None,
		(F, F, B, B),
		"ERP / muhasebe sistemleriyle entegrasyon.",
	),
	(
		"feature.support.sla",
		"SLA garantisi",
		"Destek & Kurumsal",
		40,
		"boolean",
		"",
		None,
		(F, F, F, B),
		"Hizmet seviyesi anlaşması (uptime/yanıt garantisi).",
	),
]

# Plan commission_rate (Percent) + max_active_listings (Int) field değerleri —
# storefront bu iki satırı plan field'ından override eder.
PLAN_FIELD_VALUES = {
	"FREE": {"commission_rate": 8, "max_active_listings": 25},
	"STARTER": {"commission_rate": 6, "max_active_listings": 250},
	"PRO": {"commission_rate": 4, "max_active_listings": 2500},
	"ENTERPRISE": {"commission_rate": 0, "max_active_listings": 0},
}


def _feature_type(key: str) -> str:
	return "Capability" if key.startswith("feature.") else "Quota"


def _legacy_cell_type(vtype: str) -> str:
	return "checkbox" if vtype == "boolean" else "text"


def _upsert_catalog(spec: dict) -> None:
	key = spec["key"]
	fields = {
		"display_name": spec["name"],
		"display_category": spec["category"],
		"display_order": spec["order"],
		"value_type": spec["vtype"],
		"enum_options": ",".join(spec["enum"]) if spec["enum"] else "",
		"unit": spec["unit"],
		"description": spec["desc"],
		"feature_type": _feature_type(key),
		"is_deprecated": 0,
	}
	if frappe.db.exists("Feature Catalog", key):
		frappe.db.set_value("Feature Catalog", key, fields)
	else:
		doc = frappe.get_doc(
			{"doctype": "Feature Catalog", "feature_key": key, "category": "FunctionalFeatures", **fields}
		)
		doc.insert(ignore_permissions=True)


def execute() -> None:
	specs = []
	for row in FEATURES:
		key, name, cat, order, vtype, unit, enum, vals, desc = row
		specs.append(
			{
				"key": key,
				"name": name,
				"category": cat,
				"order": order,
				"vtype": vtype,
				"unit": unit,
				"enum": enum,
				"vals": vals,
				"desc": desc,
			}
		)

	# 1) Feature Catalog upsert
	for spec in specs:
		_upsert_catalog(spec)

	# 2) Plan code → name
	plans = frappe.get_all("Subscription Plan", fields=["name", "plan_code"])
	name_by_code = {}
	for p in plans:
		code = (p.get("plan_code") or p["name"]).upper()
		name_by_code[code] = p["name"]

	# 3) Her plan için hücre değerleri + plan field'ları
	for idx, code in enumerate(PLAN_CODES):
		plan_name = name_by_code.get(code)
		if not plan_name:
			continue
		plan = frappe.get_doc("Subscription Plan", plan_name)

		# plan field override değerleri
		pf = PLAN_FIELD_VALUES.get(code)
		if pf:
			plan.commission_rate = pf["commission_rate"]
			plan.max_active_listings = pf["max_active_listings"]

		row_by_key = {}
		for r in plan.get("pricing_features") or []:
			if r.get("feature_key"):
				row_by_key[r.feature_key] = r

		for spec in specs:
			val = spec["vals"][idx]
			legacy = _legacy_cell_type(spec["vtype"])
			if spec["vtype"] == "boolean":
				included = 1 if val else 0
				text_value = ""
			else:
				text_value = str(val)
				included = 0 if text_value in ("", "0", "Yok") else 1
			is_disabled = 0 if included else 1
			# Boolean ladder + üretici rozeti kartta gösterilsin (varsayılan)
			show_card = (
				1
				if (spec["vtype"] == "boolean" or spec["key"] == "feature.storefront.manufacturer_badge_tier")
				else 0
			)

			data = {
				"value_type": legacy,
				"is_included": included,
				"is_disabled": is_disabled,
				"text_value": text_value,
				"show_on_card": show_card,
				"display_text": spec["name"],
				"sort_order": spec["order"],
			}
			row = row_by_key.get(spec["key"])
			if row:
				for k, v in data.items():
					setattr(row, k, v)
			else:
				new_row = plan.append("pricing_features", {"feature_key": spec["key"]})
				for k, v in data.items():
					setattr(new_row, k, v)

		plan.flags.ignore_permissions = True
		plan.flags.ignore_mandatory = True
		plan.flags.ignore_links = True
		plan.save(ignore_permissions=True)

	frappe.db.commit()

	try:
		from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

		invalidate_pricing_cache()
	except Exception:
		frappe.log_error("pricing cache invalidate skipped", "v15_6_22 patch")
