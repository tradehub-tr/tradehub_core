# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Entitlement (L0) çekirdek API'ı.

Tüm yetenek (feature) ve kota (quota) kararları bu modülden geçer.

Mimari:
  - Plan → Subscription Plan DocType (capability_flags + quota_limits JSON)
  - Store → Admin Seller Profile (subscription Link alanı ile Store Subscription'a bağlı)
  - Effective config = Plan + Store Subscription overrides

Cache stratejisi:
  - Store → effective config eşlemesi 5 dk Redis cache
  - Plan kaydı değişince cache invalidate

Hata davranışı:
  - has_feature / within_quota → boolean döner (sessiz)
  - check_feature_or_throw / check_quota_or_throw → ihlalde EntitlementError fırlat

Detay: docs/yetki/TradeHub-Yetkilendirme-Mimarisi-v2.md §3
"""

from __future__ import annotations

import frappe
from frappe import _

# 5 dk cache (saniye)
_CACHE_TTL = 300


class EntitlementError(frappe.PermissionError):
	"""Plan tavanı (entitlement) ihlali.

	Frappe'nin PermissionError'undan türer; HTTP 403 döner ama mesajında
	'plan tavanı' bilgisi bulunur."""

	pass


# ---------------------------------------------------------------------------
# Plan / Subscription resolution
# ---------------------------------------------------------------------------


# K2+K3 fix: subscription "operasyonel" sayıldığı status'lar.
# past_due = ödeme gecikti, ama grace period — kullanıcı faturasını ödeyebilmeli
# (aksi halde deadlock: confirm_payment → capability → has_feature → False → deny).
# suspended/canceled → gerçek bloke; capability düşer.
_OPERATIONAL_STATUSES = ("trial", "active", "past_due")


def get_active_subscription(store: str) -> dict | None:
	"""Verilen store için OPERATIONAL Store Subscription döner (cache'li).

	"Operational" = trial / active / past_due (grace period dahil).
	Suspended / canceled → None (gerçek bloke).

	Args:
	    store: Admin Seller Profile.name

	Returns:
	    Subscription bilgilerini içeren dict, yoksa None.
	    Şema: {name, plan, status, current_period_end, ...}
	"""
	if not store:
		return None

	cache_key = f"tradehub:entitlement:subscription:{store}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached or None  # boş dict → None

	sub_name = frappe.db.get_value(
		"Store Subscription",
		{"store": store, "status": ["in", list(_OPERATIONAL_STATUSES)]},
		"name",
		order_by="started_at desc",
	)

	if not sub_name:
		# Negative cache (kısa TTL) — her isteğin DB'ye gitmesini engelle
		frappe.cache().set_value(cache_key, {}, expires_in_sec=60)
		return None

	sub_doc = frappe.get_cached_doc("Store Subscription", sub_name)
	result = {
		"name": sub_doc.name,
		"plan": sub_doc.plan,
		"status": sub_doc.status,
		"trial_end": str(sub_doc.trial_end) if sub_doc.trial_end else None,
		"current_period_end": str(sub_doc.current_period_end)
		if sub_doc.current_period_end
		else None,
	}
	frappe.cache().set_value(cache_key, result, expires_in_sec=_CACHE_TTL)
	return result


def get_subscription_status(store: str) -> str | None:
	"""K3 fix: subscription'ın STATUS'unu döner — operasyonel filtre uygulanmaz.

	"missing subscription" ile "subscription var ama suspended" ayrımı yapmak
	için kullanılır. ABAC ve UI banner katmanı bunu sorgular.

	Returns: 'trial' | 'active' | 'past_due' | 'suspended' | 'canceled' | None
	"""
	if not store:
		return None
	return frappe.db.get_value(
		"Store Subscription",
		{"store": store},
		"status",
		order_by="started_at desc",
	)


def is_subscription_operational(store: str) -> bool:
	"""K7 helper: subscription operasyonel mi? ABAC write check'lerinde
	kullanılır. False ise write op'ları reddedilir (ABAC katmanında)."""
	status = get_subscription_status(store)
	return status in _OPERATIONAL_STATUSES


def get_plan(store: str) -> str | None:
	"""Verilen store'un aktif plan kodu (örn. 'pro')."""
	sub = get_active_subscription(store)
	return sub["plan"] if sub else None


# ---------------------------------------------------------------------------
# Capability flags + quota limits resolution (effective = plan + overrides)
# ---------------------------------------------------------------------------


def get_capability_flags(store: str) -> dict:
	"""Store için effective capability_flags (plan + overrides).

	Cache'li. Subscription yoksa boş dict döner.
	"""
	cache_key = f"tradehub:entitlement:capabilities:{store}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached

	sub = get_active_subscription(store)
	if not sub:
		flags = {}
	else:
		sub_doc = frappe.get_cached_doc("Store Subscription", sub["name"])
		flags = sub_doc.get_effective_capability_flags()

	frappe.cache().set_value(cache_key, flags, expires_in_sec=_CACHE_TTL)
	return flags


def get_quota_limits(store: str) -> dict:
	"""Store için effective quota_limits (plan + overrides).

	Cache'li. Subscription yoksa boş dict döner.
	"""
	cache_key = f"tradehub:entitlement:quotas:{store}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached

	sub = get_active_subscription(store)
	if not sub:
		quotas = {}
	else:
		sub_doc = frappe.get_cached_doc("Store Subscription", sub["name"])
		quotas = sub_doc.get_effective_quota_limits()

	frappe.cache().set_value(cache_key, quotas, expires_in_sec=_CACHE_TTL)
	return quotas


# ---------------------------------------------------------------------------
# Public API: has_feature / within_quota
# ---------------------------------------------------------------------------


def has_feature(store: str, feature_key: str) -> bool:
	"""Store, verilen capability'ye sahip mi?

	Args:
	    store: Admin Seller Profile.name
	    feature_key: 'feature.*' formatında key

	Returns:
	    True: plan capability_flags[feature_key] == True
	    False: değişik durumlar (subscription yok, key yok, false)
	"""
	if not store or not feature_key:
		return False
	flags = get_capability_flags(store)
	return bool(flags.get(feature_key, False))


def within_quota(store: str, quota_key: str, current_count: int) -> bool:
	"""Store, verilen kota için sınır içinde mi?

	Args:
	    store: Admin Seller Profile.name
	    quota_key: 'quota.*' formatında key
	    current_count: Şu anki sayım (örn. mevcut ürün sayısı)

	Returns:
	    True: current_count < limit (veya limit == -1, sınırsız)
	    False: limit aşıldı veya subscription yok

	Sınır semantikleri:
	    limit == -1 → sınırsız (her zaman True)
	    limit == 0  → devre dışı (her zaman False, current_count ne olursa)
	    limit > 0   → current_count < limit ise True
	"""
	if not store or not quota_key:
		return False
	quotas = get_quota_limits(store)
	limit = quotas.get(quota_key)
	if limit is None:
		# Plan'da tanımlı değil = subscription yok / unsupported quota
		return False
	limit = int(limit)
	if limit == -1:
		return True  # sınırsız
	if limit == 0:
		return False  # devre dışı
	return int(current_count) < limit


# ---------------------------------------------------------------------------
# Throw variants — backend code'da kullan
# ---------------------------------------------------------------------------


def check_feature_or_throw(store: str, feature_key: str, action_description: str = "") -> None:
	"""Feature yoksa EntitlementError fırlat.

	Args:
	    store: Admin Seller Profile.name
	    feature_key: 'feature.*' key
	    action_description: Hata mesajında gösterilecek eylem (örn. "Çoklu Varyant Ürün Ekleme")
	"""
	if has_feature(store, feature_key):
		return

	# Feature Catalog'tan display_name bul
	display_name = (
		frappe.db.get_value("Feature Catalog", feature_key, "display_name") or feature_key
	)
	plan = get_plan(store) or "—"

	# FAZ 1.4 — Audit log (best-effort, import circular'ı önlemek için lazy)
	try:
		from tradehub_core.audit import (
			DECISION_DENY,
			LAYER_L0,
			SEVERITY_NORMAL,
			log_decision,
		)

		log_decision(
			action=action_description or f"feature.check.{feature_key}",
			decision=DECISION_DENY,
			rule_id=f"entitlement.feature.{feature_key}",
			layer=LAYER_L0,
			tenant=store,
			plan_code=plan,
			severity=SEVERITY_NORMAL,
			context={"feature_key": feature_key, "display_name": display_name},
		)
	except Exception:
		pass

	msg = _("Bu özellik ({0}) aktif planınızda ({1}) mevcut değil.").format(display_name, plan)
	if action_description:
		msg = _("{0}: {1}").format(action_description, msg)

	frappe.throw(msg, EntitlementError)


def check_quota_or_throw(
	store: str,
	quota_key: str,
	current_count: int,
	action_description: str = "",
) -> None:
	"""Kota aşılmışsa EntitlementError fırlat.

	Args:
	    store: Admin Seller Profile.name
	    quota_key: 'quota.*' key
	    current_count: Şu anki sayım
	    action_description: Hata mesajında gösterilecek eylem
	"""
	if within_quota(store, quota_key, current_count):
		return

	display_name = (
		frappe.db.get_value("Feature Catalog", quota_key, "display_name") or quota_key
	)
	quotas = get_quota_limits(store)
	limit = quotas.get(quota_key, 0)
	plan = get_plan(store) or "—"

	# FAZ 1.4 — Audit log (best-effort)
	try:
		from tradehub_core.audit import (
			DECISION_DENY,
			LAYER_L0,
			SEVERITY_NORMAL,
			log_decision,
		)

		log_decision(
			action=action_description or f"quota.check.{quota_key}",
			decision=DECISION_DENY,
			rule_id=f"entitlement.quota.{quota_key}",
			layer=LAYER_L0,
			tenant=store,
			plan_code=plan,
			severity=SEVERITY_NORMAL,
			context={
				"quota_key": quota_key,
				"display_name": display_name,
				"limit": limit,
				"current_count": current_count,
			},
		)
	except Exception:
		pass

	msg = _("Planınızın limitine ulaştınız: {0} = {1} (mevcut: {2}, plan: {3}).").format(
		display_name, limit, current_count, plan
	)
	if action_description:
		msg = _("{0}: {1}").format(action_description, msg)

	frappe.throw(msg, EntitlementError)


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def invalidate_store_cache(store: str) -> None:
	"""Verilen store için entitlement cache'ini temizle.

	Çağrı zamanı:
	  - Store Subscription.on_update
	  - Subscription Plan.on_update (etkilenen tüm store'lar için)
	  - Admin Seller Profile.on_update
	"""
	if not store:
		return
	for prefix in ("subscription", "capabilities", "quotas"):
		frappe.cache().delete_value(f"tradehub:entitlement:{prefix}:{store}")


def invalidate_plan_cache(plan_code: str) -> None:
	"""Plan değişikliğinde, o plana sahip tüm store'ların cache'ini temizle."""
	if not plan_code:
		return
	stores = frappe.get_all(
		"Store Subscription",
		filters={"plan": plan_code, "status": ["in", ["trial", "active"]]},
		pluck="store",
	)
	for store in stores:
		invalidate_store_cache(store)
