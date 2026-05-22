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
			"max_active_listings",
			"cta_label",
			"cta_action",
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
			"sort_order",
			"tooltip",
			"idx",
		],
		order_by="parent asc, sort_order asc, idx asc",
	)

	features_by_plan: dict[str, list[dict]] = {}
	for row in feature_rows:
		features_by_plan.setdefault(row["parent"], []).append(
			{
				"display_text": row["display_text"],
				"icon": row.get("icon") or "check",
				"is_disabled": bool(row.get("is_disabled")),
				"feature_key": row.get("feature_key"),
				"tooltip": row.get("tooltip"),
			}
		)

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
				"max_active_listings": int(p.get("max_active_listings") or 0),
				"cta_label": p.get("cta_label") or _("Devam et"),
				"cta_action": p.get("cta_action") or "signup",
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

	response = {
		"plans": plans,
		"meta": {
			"currency": dominant_currency,
			"mixed_currency": mixed,
			"updated_at": frappe.utils.now(),
		},
	}
	frappe.cache().set_value(_CACHE_KEY, json.dumps(response), expires_in_sec=_CACHE_TTL_SECONDS)
	return response


def invalidate_pricing_cache() -> None:
	"""Public pricing cache'ini temizle.

	Çağrı zamanı:
	  - Subscription Plan on_update (entitlement.sync.on_subscription_plan_update)
	  - Pricing Plan Feature child değişimi (parent on_update tetiklenir)
	"""
	frappe.cache().delete_value(_CACHE_KEY)
