"""WP3 (TUR-139) — `quota.max_storage_mb` planlara seed.

**KRİTİK:** `entitlement.core.within_quota` semantiği: plan'da tanımsız key
→ `None` → `within_quota` **False** döner (deny). `check_media_storage_quota`
artık gerçek enforcement yapıyor; bu patch atlanırsa `quota.max_storage_mb`
hiçbir plan'da tanımlı olmaz ve **tüm satıcıların medya yüklemesi reddedilir**.

Semantik (`entitlement.core.within_quota` ile aynı sözleşme):
  -1 → sınırsız
   0 → devre dışı (her yükleme reddedilir — kasıtlı olarak KULLANILMIYOR,
       hiçbir plan medya yüklemeyi tamamen kapatmıyor)
  >0 → MB cinsinden sınır

Kademe (plan kodu case-insensitive alt string eşleşmesi — hem eski UPPERCASE
FREE/STARTER/PRO/ENTERPRISE hem yeni lowercase free/pro/enterprise/pro-annual
gibi custom varyantları kapsar, bkz. `subscription_plan.py:_PLAN_CODE_PATTERN`
yorumu):
  enterprise → -1 (sınırsız)
  pro / premium → 5000 (5 GB)
  starter → 2000 (2 GB)
  free / eşleşmeyen (bilinmeyen custom plan) → 500 (Feature Catalog default_value)

Idempotent: `quota.max_storage_mb` zaten planın `quota_limits` JSON'unda
tanımlıysa DOKUNULMAZ (mevcut admin override'ları ezilmez).

Desen: `v15_6_15_fix_quota_orders_unlimited.py`.
"""

from __future__ import annotations

import json

import frappe

_TARGET_KEY = "quota.max_storage_mb"

_UNLIMITED = -1
_TIER_DEFAULTS: tuple[tuple[str, int], ...] = (
	("enterprise", _UNLIMITED),
	("pro", 5000),
	("premium", 5000),
	("starter", 2000),
)
_FALLBACK_MB = 500  # free + tanımlanamayan custom planlar (Feature Catalog default_value)


def _default_for_plan(plan_name: str) -> int:
	lname = (plan_name or "").lower()
	for token, value in _TIER_DEFAULTS:
		if token in lname:
			return value
	return _FALLBACK_MB


def execute() -> dict:
	plans = frappe.get_all("Subscription Plan", fields=["name", "quota_limits"])
	updated: list[str] = []
	skipped: list[str] = []

	for p in plans:
		raw = p.get("quota_limits")
		try:
			quotas = json.loads(raw) if isinstance(raw, str) else (raw or {})
		except (ValueError, TypeError):
			continue
		if not isinstance(quotas, dict):
			continue

		if _TARGET_KEY in quotas:
			skipped.append(p["name"])
			continue

		quotas[_TARGET_KEY] = _default_for_plan(p["name"])
		frappe.db.set_value(
			"Subscription Plan",
			p["name"],
			"quota_limits",
			json.dumps(quotas, sort_keys=True, ensure_ascii=False),
			update_modified=False,
		)
		updated.append(p["name"])

	frappe.db.commit()

	# Entitlement cache flush — yeni kota anında etkili olsun (aksi hâlde 5 dk
	# stale cache boyunca hâlâ None döner ve within_quota False vermeye devam eder).
	try:
		frappe.cache().delete_keys("tradehub:entitlement:")
	except Exception:
		frappe.log_error("entitlement cache flush failed", "v15_9_17_seed_storage_quota")

	return {"updated": updated, "skipped_already_set": skipped}
