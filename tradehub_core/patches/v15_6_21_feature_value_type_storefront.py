"""Faz A — value_type'ı feature-seviyesine taşı (entitlement-pattern redesign).

Önce `value_type` her Pricing Plan Feature hücresinde ayrı tutuluyordu; backend
"dominant" heuristiğiyle tahmin ediyordu → aynı feature farklı planlarda farklı
kontrol tipiyle görünüyordu (komisyon: checkbox vs "0" text karışıklığı).

Bu patch Feature Catalog'a eklenen `value_type` (boolean/quota/enum/text) +
`enum_options` alanlarını mevcut veriden türetir:

- Hücrelerin çoğu checkbox ise → boolean
- text ağırlıklı ise:
    - bilinen kademe (tier) key'leri → enum (seçenekler hücre değerlerinden)
    - quota.* key'leri → quota (commission_rate için birim '%')
    - diğerleri → text

Ayrıca legacy `Pricing Plan Feature.value_type` katalogla senkron edilir
(boolean→checkbox, diğer→text) ki storefront/admin geriye uyumlu kalsın; ve
feature-seviyesi `show_on_card` (Faz 1) per-plan hücrelere kopyalanır.

Idempotent: tekrar çalışırsa aynı sonucu üretir.
"""

from __future__ import annotations

import frappe

# Metin değerleri ayrık kademe (tier) olan feature'lar → enum.
_TIER_ENUM_KEYS = {
	"feature.storefront.manufacturer_badge_tier",
	"feature.storefront.tier",
}

# quota feature'ları için birim.
_QUOTA_UNIT = {
	"quota.commission_rate": "%",
}


def _distinct_options(cells: list[dict], plan_order: dict[str, int]) -> list[str]:
	"""Hücre text değerlerinden, plan sırasına göre tekrarsız seçenek listesi."""
	ordered = sorted(cells, key=lambda c: plan_order.get(c["parent"], 999))
	out: list[str] = []
	for c in ordered:
		val = (c.get("text_value") or "").strip()
		if val and val not in out:
			out.append(val)
	return out


def _derive_value_type(key: str, cells: list[dict], feature_type: str) -> str:
	# Key prefix en güvenilir sinyal — mevcut hücre verisi karışık olabilir
	# (ör. komisyon bazı planlarda checkbox seed edilmiş). Bu yüzden önce key:
	if key in _TIER_ENUM_KEYS:
		return "enum"
	if key.startswith("quota."):
		return "quota"
	# feature.* → hücre dominantına göre boolean veya text
	cb = sum(1 for c in cells if (c.get("value_type") or "checkbox") == "checkbox")
	tx = sum(1 for c in cells if c.get("value_type") == "text")
	if tx > cb:
		return "text"
	return "boolean"


def execute() -> None:
	plan_order = {
		p["name"]: (p.get("display_order") or 0)
		for p in frappe.get_all("Subscription Plan", fields=["name", "display_order"])
	}

	features = frappe.get_all(
		"Feature Catalog",
		filters={"display_category": ["is", "set"]},
		fields=["name", "feature_key", "feature_type", "unit", "show_on_card"],
	)

	for f in features:
		key = f["feature_key"]
		cells = frappe.get_all(
			"Pricing Plan Feature",
			filters={"feature_key": key, "parenttype": "Subscription Plan"},
			fields=["name", "parent", "value_type", "text_value", "is_included"],
		)

		vt = _derive_value_type(key, cells, f.get("feature_type") or "Capability")
		update: dict[str, object] = {"value_type": vt}
		if vt == "quota" and key in _QUOTA_UNIT and not f.get("unit"):
			update["unit"] = _QUOTA_UNIT[key]
		if vt == "enum":
			opts = _distinct_options(cells, plan_order)
			if opts:
				update["enum_options"] = ",".join(opts)
		frappe.db.set_value("Feature Catalog", f["name"], update)

		# Legacy hücre value_type'ı katalogla senkronla (geriye uyum)
		legacy = "checkbox" if vt == "boolean" else "text"
		default_card = 1 if f.get("show_on_card") else 0
		for c in cells:
			cell_update: dict[str, object] = {"value_type": legacy}
			# Faz 1'deki feature-seviyesi show_on_card'ı per-plan hücrelere taşı
			if default_card:
				cell_update["show_on_card"] = 1
			frappe.db.set_value("Pricing Plan Feature", c["name"], cell_update)

	frappe.db.commit()

	try:
		from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

		invalidate_pricing_cache()
	except Exception:
		frappe.log_error("pricing cache invalidate skipped", "v15_6_21 patch")
