"""Faz E.4 — `quota.max_orders_per_month` semantik düzeltmesi.

Tüm 4 plan (FREE/STARTER/PRO/ENTERPRISE) `quota.max_orders_per_month: 0`
değeriyle seed edildi. `entitlement.within_quota` semantiği:
  - `-1` → sınırsız
  - `0`  → DEVRE DIŞI (limit aşıldı sayılır)
  - `>0` → spesifik limit

Bu durum `0` değerli plan'larda **her order create reddedilir** ki niyet
"sınırsız sipariş işleme" idi (storefront marketing copy bunu vaadediyor).
Patch tüm plan'larda `quota.max_orders_per_month`'u `-1` (sınırsız) yapar.

Diğer quota'lar (api_rate_limit, max_co_owners) `0` değerleri **kasıtlı**
plan kademesi gösteriyor (FREE'de API yok, co-owner yok) — dokunulmaz.

Idempotent: değer zaten -1 ise skip.
"""

from __future__ import annotations

import json

import frappe

_TARGET_KEY = "quota.max_orders_per_month"
_UNLIMITED = -1


def execute() -> dict:
	plans = frappe.get_all("Subscription Plan", fields=["name", "quota_limits"])
	updated: list[str] = []
	skipped: list[str] = []

	for p in plans:
		raw = p.get("quota_limits")
		if not raw:
			continue
		try:
			quotas = json.loads(raw) if isinstance(raw, str) else raw
		except (ValueError, TypeError):
			continue
		if not isinstance(quotas, dict):
			continue

		if quotas.get(_TARGET_KEY) == _UNLIMITED:
			skipped.append(p["name"])
			continue

		quotas[_TARGET_KEY] = _UNLIMITED
		frappe.db.set_value(
			"Subscription Plan",
			p["name"],
			"quota_limits",
			json.dumps(quotas, sort_keys=True, ensure_ascii=False),
			update_modified=False,
		)
		updated.append(p["name"])

	frappe.db.commit()

	# Entitlement cache flush — yeni quota değerleri anında etkili olsun
	try:
		frappe.cache().delete_keys("tradehub:entitlement:")
	except Exception:
		frappe.log_error("entitlement cache flush failed", "v15_6_15")

	return {
		"updated": updated,
		"skipped_already_unlimited": skipped,
	}
