# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 4.1 — Storefront public pricing endpoint.

Storefront `sell.html` sayfası bu endpoint'ten 4 (veya N) public planı çeker:
  - is_active=1, is_public=1 olanlar
  - display_order'a göre sıralı
  - pricing_features child table dahil (paket içeriği bullet'lar)
  - Feature Catalog'taki display_name'ler join'lenir
  - 5 dakikalık Redis cache (anahtar: tradehub:pricing:public)

Cache invalidation: Subscription Plan on_update hook'unda çağrılır
(entitlement.sync.on_subscription_plan_update).
"""

from __future__ import annotations

import json

import frappe
from frappe import _

_CACHE_KEY = "tradehub:pricing:public"
_CACHE_TTL_SECONDS = 300  # 5 dk


@frappe.whitelist(allow_guest=True)
def get_pricing_plans() -> dict:
	"""Storefront pricing card'ları için public plan listesi.

	Returns:
		{
			"plans": [
				{
					"plan_code": "pro",
					"plan_name": "Professional",
					"badge_label": "EN POPÜLER",
					"badge_color": "yellow",
					"theme": "dark",
					"short_tagline": "...",
					"monthly_price": 499.0,
					"yearly_price": 4990.0,
					"currency": "EUR",
					"commission_rate": 6.0,
					"max_active_listings": 500,
					"cta_label": "Professional seç",
					"cta_action": "signup_billing",
					"highlighted": true,
					"trial_days": 14,
					"features": [
						{"display_text": "...", "icon": "check", "is_disabled": false, "tooltip": null},
						...
					]
				},
				...
			],
			"meta": {
				"currency": "EUR",
				"updated_at": "2026-05-21 12:34:56"
			}
		}
	"""
	cached = frappe.cache().get_value(_CACHE_KEY)
	if cached:
		try:
			return json.loads(cached)
		except (json.JSONDecodeError, TypeError):
			pass  # bozuk cache, yeniden hesapla

	plans_raw = frappe.get_all(
		"Subscription Plan",
		filters={"is_active": 1, "is_public": 1},
		fields=[
			"name",
			"plan_code",
			"plan_name",
			"description",
			"badge_label",
			"badge_color",
			"theme",
			"short_tagline",
			"monthly_price",
			"yearly_price",
			"currency",
			"commission_rate",
			"commission_is_custom",
			"max_active_listings",
			"cta_label",
			"cta_action",
			"price_override_label",
			"highlighted",
			"display_order",
			"trial_days",
		],
		order_by="display_order asc, plan_code asc",
	)

	if not plans_raw:
		response: dict = {"plans": [], "meta": {"currency": "EUR", "updated_at": frappe.utils.now()}}
		frappe.cache().set_value(_CACHE_KEY, json.dumps(response), expires_in_sec=_CACHE_TTL_SECONDS)
		return response

	plan_names = [p["name"] for p in plans_raw]
	feature_rows = frappe.get_all(
		"Pricing Plan Feature",
		filters={"parent": ["in", plan_names], "parenttype": "Subscription Plan"},
		fields=[
			"parent",
			"display_text",
			"icon",
			"is_disabled",
			"feature_key",
			"value_type",
			"is_included",
			"text_value",
			"show_on_card",
			"sort_order",
			"tooltip",
			"idx",
		],
		order_by="parent asc, sort_order asc, idx asc",
	)

	# Feature Catalog'tan display_name (boş display_text fallback'i) + is_coming_soon
	# ("Yakında" rozeti — henüz çalışmayan özellik).
	_fc_rows = frappe.get_all("Feature Catalog", fields=["feature_key", "display_name", "is_coming_soon"])
	name_map = {r["feature_key"]: r["display_name"] for r in _fc_rows}
	coming_map = {r["feature_key"]: bool(r.get("is_coming_soon")) for r in _fc_rows}

	# Faz A — per-kart `show_on_card` plan başına (Pricing Plan Feature hücresi);
	# her plan kendi kart özet listesini kürasyon eder (admin "Kartta" + seed patch).
	features_by_plan: dict[str, list[dict]] = {}
	# matris için (feature_key, plan_code) → row değeri
	cell_by_key_and_plan: dict[tuple[str, str], dict] = {}
	plan_code_by_name = {p["name"]: (p.get("plan_code") or p["name"]) for p in plans_raw}
	for row in feature_rows:
		fkey = row.get("feature_key")
		parent = row["parent"]
		features_by_plan.setdefault(parent, []).append(
			{
				"display_text": row.get("display_text") or name_map.get(fkey) or "",
				"icon": row.get("icon") or "check",
				"is_disabled": bool(row.get("is_disabled")),
				"feature_key": fkey,
				"tooltip": row.get("tooltip"),
				"show_on_card": bool(row.get("show_on_card")),
				"text_value": row.get("text_value") or "",
				"coming_soon": coming_map.get(fkey, False),
			}
		)
		fkey = row.get("feature_key")
		if fkey:
			plan_code = plan_code_by_name.get(row["parent"], row["parent"])
			cell_by_key_and_plan[(fkey, plan_code)] = {
				"value_type": row.get("value_type") or "checkbox",
				"is_included": bool(row.get("is_included")),
				"text_value": row.get("text_value") or "",
			}

	plans: list[dict] = []
	for p in plans_raw:
		plans.append(
			{
				"plan_code": p.get("plan_code"),
				"plan_name": p.get("plan_name"),
				"description": p.get("description"),
				"badge_label": p.get("badge_label"),
				"badge_color": p.get("badge_color") or "default",
				"theme": p.get("theme") or "default",
				"short_tagline": p.get("short_tagline"),
				"monthly_price": float(p.get("monthly_price") or 0),
				"yearly_price": float(p.get("yearly_price") or 0),
				"currency": p.get("currency") or "EUR",
				"commission_rate": float(p.get("commission_rate") or 0),
				"commission_custom": bool(p.get("commission_is_custom")),
				"max_active_listings": int(p.get("max_active_listings") or 0),
				"cta_label": p.get("cta_label") or _("Devam et"),
				"cta_action": p.get("cta_action") or "signup",
				"price_override_label": p.get("price_override_label") or "",
				"highlighted": bool(p.get("highlighted")),
				"trial_days": int(p.get("trial_days") or 0),
				"features": features_by_plan.get(p["name"], []),
			}
		)

	# O11: Multi-currency desteği — eğer planlar farklı currency'lerdeyse
	# `meta.currency`'yi en yaygın olana ayarla ve `mixed=True` flag'i ekle.
	# Frontend per-plan currency kullanmalı; meta.currency sadece fallback ve
	# global gösterim için.
	currencies = [p.get("currency") or "EUR" for p in plans]
	if not currencies:
		dominant_currency = "EUR"
		mixed = False
	else:
		from collections import Counter

		counter = Counter(currencies)
		dominant_currency = counter.most_common(1)[0][0]
		mixed = len(counter) > 1

	# Storefront feature matris — Feature Catalog'tan kategorize edilmiş
	# feature listesi + her plan için cell değeri.
	plan_codes = [p.get("plan_code") for p in plans_raw if p.get("plan_code")]
	# Komisyon & aktif ürün limiti İÇİN plan model field'ı TEK OTORİTEDİR
	# (sadece boşken devreye giren bir fallback değil — matris text_value'yu
	# EZER). Gerekçe:
	#   1) `max_active_listings` field'ı entitlement motorunun gerçekten
	#      uyguladığı limittir; matris text_value bundan saparsa storefront
	#      yanlış limit reklamı yapar. Display her zaman operasyonel gerçeği
	#      göstermeli.
	#   2) Pricing kart "şerit"i (PricingCard) bu iki değeri doğrudan plan
	#      field'ından okur; matris de aynı field'dan beslenince kart ve
	#      karşılaştırma tablosu BİREBİR aynı olur (binlik ayraç, "Sınırsız",
	#      "Özel" dahil — frontend `fmtListings` / komisyon biçimiyle eşleşir).
	# Admin "Paket İçeriği"nde komisyon/limit düzenlerse bulk_update zaten
	# değeri plan field'ına sync ediyor → field güncel kalır.
	plan_field_overrides: dict[tuple[str, str], str] = {}
	for p in plans_raw:
		code = p.get("plan_code")
		if not code:
			continue
		cr = float(p.get("commission_rate") or 0)
		# Kart ile aynı: admin komisyonu boş bıraktıysa (commission_is_custom)
		# "Özel"; aksi halde gerçek oran — 0 dahil ("%0" geçerli pazarlama değeri).
		plan_field_overrides[("quota.commission_rate", code)] = (
			_("Özel") if p.get("commission_is_custom") else f"%{int(cr) if cr.is_integer() else cr}"
		)
		mal = p.get("max_active_listings")
		# Kart `fmtListings` ile aynı: > 0 → tr-TR binlik ayraç ("2.500"),
		# 0/None → "Sınırsız".
		plan_field_overrides[("quota.max_active_listings", code)] = (
			f"{int(mal):,}".replace(",", ".") if mal and int(mal) > 0 else _("Sınırsız")
		)
	features_matrix = _build_features_matrix(cell_by_key_and_plan, plan_codes, plan_field_overrides)

	# Global trial konfigürasyonu (Trial Settings) — storefront buton-üstü CTA + üst bant.
	from tradehub_core.tradehub_core.doctype.trial_settings.trial_settings import (
		get_trial_settings,
	)

	_ts = get_trial_settings()
	_trial_plan_code = (
		plan_code_by_name.get(_ts["trial_plan"], _ts["trial_plan"]) if _ts["trial_plan"] else ""
	)
	trial_config = {
		"enabled": _ts["trial_enabled"] and bool(_trial_plan_code),
		"plan_code": _trial_plan_code,
		"days": _ts["trial_days"],
		"cta_label": _ts["trial_cta_label"],
	}

	response = {
		"plans": plans,
		"features_matrix": features_matrix,
		"trial_config": trial_config,
		"meta": {
			"currency": dominant_currency,
			"mixed_currency": mixed,
			"updated_at": frappe.utils.now(),
		},
	}
	frappe.cache().set_value(_CACHE_KEY, json.dumps(response), expires_in_sec=_CACHE_TTL_SECONDS)
	return response


def _build_features_matrix(
	cell_by_key_and_plan: dict[tuple[str, str], dict],
	plan_codes: list[str],
	plan_field_overrides: dict[tuple[str, str], str] | None = None,
) -> dict:
	"""Feature Catalog'taki display_category'leri kategori grupları halinde
	döndür. Her feature için 4 plan değerini map'le.

	Returns:
		{
			"categories": [
				{
					"name": "Komisyon & Limitler",
					"features": [
						{
							"feature_key": "...",
							"display_name": "...",
							"value_type": "checkbox" | "text",
							"tooltip": "...",
							"values_by_plan": {
								"FREE": {"is_included": True, "text_value": ""},
								...
							}
						},
						...
					]
				},
				...
			]
		}
	"""
	catalog_rows = frappe.get_all(
		"Feature Catalog",
		filters={"is_deprecated": 0, "display_category": ["is", "set"]},
		fields=[
			"feature_key",
			"display_name",
			"display_category",
			"display_order",
			"feature_type",
			"value_type",
			"enum_options",
			"unit",
			"description",
			"is_coming_soon",
		],
		order_by="display_category asc, display_order asc, display_name asc",
	)
	# `is set` boş string'leri yakalamayabilir → ek filtre
	catalog_rows = [r for r in catalog_rows if (r.get("display_category") or "").strip()]

	categories_map: dict[str, list[dict]] = {}
	category_order: list[str] = []
	for row in catalog_rows:
		cat = row["display_category"]
		if cat not in categories_map:
			categories_map[cat] = []
			category_order.append(cat)

		# Faz A — value_type kaynağı Feature Catalog (feature-seviyesi).
		control_type = row.get("value_type") or "boolean"
		legacy_vt = "checkbox" if control_type == "boolean" else "text"
		enum_options = [o.strip() for o in (row.get("enum_options") or "").split(",") if o.strip()]
		values_by_plan: dict[str, dict] = {}
		overrides = plan_field_overrides or {}
		for code in plan_codes:
			cell = cell_by_key_and_plan.get((row["feature_key"], code))
			# Plan field otoritesi (komisyon/limit) varsa text_value'yu EZER;
			# diğer feature'larda override_text="" → matris hücresi geçerli.
			override_text = overrides.get((row["feature_key"], code), "")
			if cell:
				text_value = override_text or cell.get("text_value", "")
				values_by_plan[code] = {
					"value_type": legacy_vt,
					# Field-otoriteli key'lerde her zaman dahil (değer var);
					# diğerlerinde hücrenin is_included'ı.
					"is_included": True if override_text else cell.get("is_included", False),
					"text_value": text_value,
				}
			else:
				# Hücre yok: field override'ı varsa onu kullan, yoksa boş.
				values_by_plan[code] = {
					"value_type": legacy_vt,
					"is_included": bool(override_text),
					"text_value": override_text,
				}

		categories_map[cat].append(
			{
				"feature_key": row["feature_key"],
				"display_name": row["display_name"],
				"value_type": legacy_vt,
				"control_type": control_type,
				"enum_options": enum_options,
				"unit": row.get("unit") or "",
				"tooltip": row.get("description") or None,
				"coming_soon": bool(row.get("is_coming_soon")),
				"values_by_plan": values_by_plan,
			}
		)

	# Storefront kategori sıralaması: sabit (Komisyon, Vitrin, Destek, Kurumsal)
	preferred_order = [
		"Komisyon & Limitler",
		"Vitrin & Mağaza",
		"B2B Ticaret Modülleri",
		"Pazarlama & Görünürlük",
		"Güven & Doğrulama",
		"Destek & Kurumsal",
	]
	ordered_categories = [c for c in preferred_order if c in categories_map]
	# kalan diğer kategoriler (varsa) — display_order alfabetik sıra ile
	for c in category_order:
		if c not in ordered_categories:
			ordered_categories.append(c)

	return {"categories": [{"name": c, "features": categories_map[c]} for c in ordered_categories]}


def invalidate_pricing_cache() -> None:
	"""Public pricing cache'ini temizle.

	Çağrı zamanı:
	  - Subscription Plan on_update (entitlement.sync.on_subscription_plan_update)
	  - Pricing Plan Feature child değişimi (parent on_update tetiklenir)
	"""
	frappe.cache().delete_value(_CACHE_KEY)
