# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.6 — Süper Admin Permission Console API.

Tüm endpoint'ler System Manager veya Marketplace Admin gerektirir
(satıcı için ayrı endpoint'ler `seller_users.py`'da).

Endpoints:
  - get_overview() — özet istatistikler
  - list_roles() — tüm rol profilleri + rol kapsamı
  - get_role_profile_detail(name) — tek rol profili detayı (kullanıcı sayısı dahil)
  - list_users(filters) — tüm kullanıcılar (tenant/role filtreli)
  - list_subscription_plans() — planlar + kullanıcı sayısı
  - get_plan_detail(plan_code) — capability_flags + quota_limits + kullanan
    satıcı sayısı
  - update_plan_capabilities(plan_code, capability_flags, quota_limits) —
    Süper Admin plan'ı günceller (mevcut Subscription Plan doctype'ı zaten
    izin veriyor; bu endpoint validation + audit eklenmiş wrapper)
  - list_decision_logs(filters) — ADL listeleme
  - list_role_change_logs(filters) — RCL listeleme
  - list_override_logs(filters) — POL listeleme

Detay: docs/yetki/TradeHub-Yetkilendirme-Mimarisi-v2.md §6, Faz 1.6 planı
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from tradehub_core.audit import log_decision

# Süper Admin / Marketplace Admin rolleri (Compliance Officer audit read için)
_ADMIN_ROLES = frozenset({"System Manager", "Marketplace Admin", "Administrator"})
_AUDIT_READ_ROLES = frozenset(
	{"System Manager", "Marketplace Admin", "Administrator", "Compliance Officer"}
)


def _require_admin(action: str = "read") -> None:
	"""Caller Süper Admin / Marketplace Admin mi? Değilse PermissionError."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Yetki gerekli."), frappe.PermissionError)

	roles = set(frappe.get_roles(user)) | {user}  # Administrator literal
	if not (roles & _ADMIN_ROLES):
		# Audit log + reject
		log_decision(
			action=f"permission_console.{action}",
			decision="DENY",
			rule_id="auth.admin_console_required",
			layer="L2",
		)
		frappe.throw(
			_("Bu işlem için Süper Admin veya Marketplace Admin yetkisi gerekir."),
			frappe.PermissionError,
		)


def _require_audit_read() -> None:
	"""Compliance Officer + admin'ler audit log okuyabilir."""
	user = frappe.session.user
	roles = set(frappe.get_roles(user)) | {user}
	if not (roles & _AUDIT_READ_ROLES):
		frappe.throw(_("Audit log okuma yetkisi yok."), frappe.PermissionError)


# ---------------------------------------------------------------------------
# Overview / Dashboard
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_overview() -> dict:
	"""Süper Admin panosu — özet istatistikler.

	Returns:
	    {
	      total_users: int,
	      enabled_users: int,
	      total_sellers: int,
	      total_plans: int,
	      active_subscriptions: int,
	      decisions_24h: int,
	      denies_24h: int,
	      high_severity_24h: int,
	      role_changes_7d: int,
	      overrides_7d: int,
	    }
	"""
	_require_admin("overview")

	from frappe.utils import add_days, now_datetime

	day_ago = add_days(now_datetime(), -1)
	week_ago = add_days(now_datetime(), -7)

	return {
		"total_users": frappe.db.count("User", {"user_type": "System User"}),
		"enabled_users": frappe.db.count("User", {"user_type": "System User", "enabled": 1}),
		"total_sellers": frappe.db.count("Admin Seller Profile"),
		"total_plans": frappe.db.count("Subscription Plan", {"is_active": 1}),
		"active_subscriptions": frappe.db.count(
			"Store Subscription", {"status": ["in", ["trial", "active"]]}
		),
		"decisions_24h": frappe.db.count(
			"Authorization Decision Log", {"timestamp": [">=", day_ago]}
		),
		"denies_24h": frappe.db.count(
			"Authorization Decision Log",
			{"timestamp": [">=", day_ago], "decision": "DENY"},
		),
		"high_severity_24h": frappe.db.count(
			"Authorization Decision Log",
			{"timestamp": [">=", day_ago], "severity": "HIGH"},
		),
		"role_changes_7d": frappe.db.count("Role Change Log", {"timestamp": [">=", week_ago]}),
		"overrides_7d": frappe.db.count(
			"Permission Override Log", {"timestamp": [">=", week_ago]}
		),
	}


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_roles() -> list[dict]:
	"""Tüm Role Profile listesi + her birinin kapsamı.

	Returns:
	    [{name, roles: [...], user_count, category: 'platform'|'seller'|'buyer'|'custom'}]
	"""
	_require_admin("list_roles")

	profiles = frappe.get_all(
		"Role Profile",
		fields=["name", "role_profile"],
		order_by="name asc",
	)

	result = []
	for p in profiles:
		# Profile'a bağlı roller (Has Role child table)
		roles = frappe.get_all(
			"Has Role",
			filters={"parent": p.name, "parenttype": "Role Profile"},
			pluck="role",
		)

		# Bu profil kaç kullanıcıya atanmış?
		user_count = frappe.db.count("User", {"role_profile_name": p.name, "enabled": 1})

		# Kategori (isimden çıkarım)
		name_lower = (p.role_profile or p.name).lower()
		if "platform" in name_lower:
			category = "platform"
		elif "seller" in name_lower:
			category = "seller"
		elif "buyer" in name_lower:
			category = "buyer"
		elif "compliance" in name_lower or "support" in name_lower:
			category = "platform"
		else:
			category = "custom"

		result.append(
			{
				"name": p.name,
				"role_profile": p.role_profile or p.name,
				"roles": roles,
				"user_count": user_count,
				"category": category,
			}
		)

	return result


@frappe.whitelist()
def get_role_profile_detail(name: str) -> dict:
	"""Tek rol profili detayı — kullanıcı listesi dahil."""
	_require_admin("role_detail")

	if not frappe.db.exists("Role Profile", name):
		frappe.throw(_("Rol profili bulunamadı."))

	profile = frappe.get_doc("Role Profile", name)
	roles = [r.role for r in (profile.roles or [])]

	users = frappe.get_all(
		"User",
		filters={"role_profile_name": name},
		fields=["name", "email", "full_name", "enabled", "tradehub_tenant", "last_login"],
		order_by="creation desc",
		limit=200,
	)

	return {
		"name": profile.name,
		"role_profile": profile.role_profile,
		"roles": roles,
		"users": users,
		"user_count": len(users),
	}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_users(
	tenant: str | None = None,
	role_profile: str | None = None,
	enabled: int | None = None,
	limit: int = 100,
) -> list[dict]:
	"""Tüm sistem kullanıcıları (filter'lı).

	Args:
	    tenant: Admin Seller Profile filter (None → tüm tenant'lar)
	    role_profile: Role Profile filter
	    enabled: 1/0
	    limit: Max kayıt
	"""
	_require_admin("list_users")

	filters: dict = {"user_type": "System User"}
	if tenant:
		filters["tradehub_tenant"] = tenant
	if role_profile:
		filters["role_profile_name"] = role_profile
	if enabled is not None:
		filters["enabled"] = int(enabled)

	users = frappe.get_all(
		"User",
		filters=filters,
		fields=[
			"name",
			"email",
			"full_name",
			"enabled",
			"role_profile_name",
			"tradehub_tenant",
			"tradehub_is_owner",
			"last_login",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=int(limit),
	)

	return users


# ---------------------------------------------------------------------------
# Subscription Plans
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_subscription_plans() -> list[dict]:
	"""Tüm planlar + kullanıcı sayısı."""
	_require_admin("list_plans")

	plans = frappe.get_all(
		"Subscription Plan",
		fields=[
			"name",
			"plan_code",
			"plan_name",
			"is_active",
			"is_public",
			"monthly_price",
			"yearly_price",
			"currency",
			"trial_days",
			"display_order",
			"highlighted",
		],
		order_by="display_order asc",
	)

	# Her plan için aktif subscription sayısı
	for p in plans:
		p["active_subscription_count"] = frappe.db.count(
			"Store Subscription",
			{"plan": p["name"], "status": ["in", ["trial", "active"]]},
		)

	return plans


@frappe.whitelist()
def get_plan_detail(plan_code: str) -> dict:
	"""Plan detayı — capability_flags + quota_limits + bu plan'ı kullanan satıcılar."""
	_require_admin("plan_detail")

	if not frappe.db.exists("Subscription Plan", plan_code):
		frappe.throw(_("Plan bulunamadı."))

	plan = frappe.get_cached_doc("Subscription Plan", plan_code)
	caps = plan.get_capability_flags()
	quotas = plan.get_quota_limits()
	regions = [r.region for r in (plan.allowed_regions or [])]

	# Bu plan'ı kullanan store sayısı
	active_count = frappe.db.count(
		"Store Subscription", {"plan": plan_code, "status": ["in", ["trial", "active"]]}
	)

	return {
		"name": plan.name,
		"plan_code": plan.plan_code,
		"plan_name": plan.plan_name,
		"description": plan.description,
		"is_active": bool(plan.is_active),
		"is_public": bool(plan.is_public),
		"monthly_price": float(plan.monthly_price or 0),
		"yearly_price": float(plan.yearly_price or 0),
		"currency": plan.currency,
		"trial_days": int(plan.trial_days or 0),
		"display_order": int(plan.display_order or 100),
		"highlighted": bool(plan.highlighted),
		"capability_flags": caps,
		"quota_limits": quotas,
		"allowed_regions": regions,
		"active_subscription_count": active_count,
	}


@frappe.whitelist()
def update_plan_capabilities(
	plan_code: str,
	capability_flags: str | dict | None = None,
	quota_limits: str | dict | None = None,
) -> dict:
	"""Plan capability_flags + quota_limits güncelle.

	Wrapper: aslında frappe.client.set_value de aynı işi yapar; ama bu endpoint
	audit log + cache invalidation tetikler.
	"""
	_require_admin("update_plan")

	if not frappe.db.exists("Subscription Plan", plan_code):
		frappe.throw(_("Plan bulunamadı."))

	# JSON string'e çevir
	if isinstance(capability_flags, dict):
		capability_flags = json.dumps(capability_flags, ensure_ascii=False)
	if isinstance(quota_limits, dict):
		quota_limits = json.dumps(quota_limits, ensure_ascii=False)

	doc = frappe.get_doc("Subscription Plan", plan_code)
	if capability_flags is not None:
		doc.capability_flags = capability_flags
	if quota_limits is not None:
		doc.quota_limits = quota_limits
	doc.save()  # Subscription Plan.on_update → cache invalidate (entitlement/sync)

	log_decision(
		action="plan.update_capabilities",
		decision="ALLOW",
		rule_id="auth.admin_console",
		layer="L0",
		object_doctype="Subscription Plan",
		object_name=plan_code,
		plan_code=plan_code,
		context={"updated_fields": list(filter(None, [
			"capability_flags" if capability_flags is not None else None,
			"quota_limits" if quota_limits is not None else None,
		]))},
	)

	frappe.db.commit()
	return {"message": _("Plan güncellendi: {0}").format(plan_code)}


# ---------------------------------------------------------------------------
# FAZ 4.1 — Dinamik Pricing yönetimi
# ---------------------------------------------------------------------------

_PRICING_DISPLAY_FIELDS = frozenset({
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
	"is_active",
	"is_public",
})


@frappe.whitelist()
def get_plan_full_detail(plan_code: str) -> dict:
	"""Plan'ın tüm field'ları + pricing_features child table (admin editor için)."""
	_require_admin("plan_full_detail")

	if not frappe.db.exists("Subscription Plan", plan_code):
		frappe.throw(_("Plan bulunamadı."))

	plan = frappe.get_doc("Subscription Plan", plan_code)
	caps = plan.get_capability_flags()
	quotas = plan.get_quota_limits()
	regions = [r.region for r in (plan.allowed_regions or [])]

	features = [
		{
			"display_text": row.display_text,
			"icon": row.icon or "check",
			"is_disabled": bool(row.is_disabled),
			"feature_key": row.feature_key,
			"tooltip": row.tooltip,
			"sort_order": int(row.sort_order or 0),
			"idx": int(row.idx or 0),
		}
		for row in (plan.pricing_features or [])
	]
	features.sort(key=lambda f: (f["sort_order"], f["idx"]))

	active_count = frappe.db.count(
		"Store Subscription", {"plan": plan_code, "status": ["in", ["trial", "active"]]}
	)

	return {
		"name": plan.name,
		"plan_code": plan.plan_code,
		"plan_name": plan.plan_name,
		"description": plan.description,
		"is_active": bool(plan.is_active),
		"is_public": bool(plan.is_public),
		"monthly_price": float(plan.monthly_price or 0),
		"yearly_price": float(plan.yearly_price or 0),
		"currency": plan.currency,
		"trial_days": int(plan.trial_days or 0),
		"display_order": int(plan.display_order or 100),
		"highlighted": bool(plan.highlighted),
		# Pricing display
		"badge_label": plan.badge_label,
		"badge_color": plan.badge_color or "default",
		"theme": plan.theme or "default",
		"short_tagline": plan.short_tagline,
		"commission_rate": float(plan.commission_rate or 0),
		"max_active_listings": int(plan.max_active_listings or 0),
		"cta_label": plan.cta_label,
		"cta_action": plan.cta_action or "signup",
		# Yetkinlikler
		"capability_flags": caps,
		"quota_limits": quotas,
		"allowed_regions": regions,
		# İçerik
		"pricing_features": features,
		# Meta
		"active_subscription_count": active_count,
	}


@frappe.whitelist()
def update_pricing_plan(
	plan_code: str,
	display: str | dict | None = None,
	capability_flags: str | dict | None = None,
	quota_limits: str | dict | None = None,
	pricing_features: str | list | None = None,
) -> dict:
	"""FAZ 4.1 — Tek endpoint'le tüm plan field'larını + child table güncelle.

	Args:
		plan_code: Güncellenecek plan (örn. 'PRO')
		display: Görsel/Pricing field'ları (badge_label, monthly_price, vb.)
		capability_flags: Feature toggle dict ({"feature.x": true, ...})
		quota_limits: Quota dict ({"quota.max_listings": 500, ...})
		pricing_features: Paket içeriği listesi (Pricing Plan Feature child rows)

	Audit:
		- log_decision: plan.update_pricing (ALLOW, severity NORMAL)
		- Subscription Plan.on_update → entitlement + public pricing cache invalidate
	"""
	_require_admin("update_pricing_plan")

	if not frappe.db.exists("Subscription Plan", plan_code):
		frappe.throw(_("Plan bulunamadı."))

	# String → dict parse
	if isinstance(display, str):
		display = json.loads(display) if display.strip() else None
	if isinstance(capability_flags, (str,)):
		capability_flags = json.loads(capability_flags) if capability_flags.strip() else None
	if isinstance(quota_limits, str):
		quota_limits = json.loads(quota_limits) if quota_limits.strip() else None
	if isinstance(pricing_features, str):
		pricing_features = json.loads(pricing_features) if pricing_features.strip() else None

	doc = frappe.get_doc("Subscription Plan", plan_code)
	changed: list[str] = []

	# 1) Display/pricing field'ları
	if display and isinstance(display, dict):
		for key, value in display.items():
			if key not in _PRICING_DISPLAY_FIELDS:
				continue  # whitelist dışı field
			old = doc.get(key)
			if old != value:
				doc.set(key, value)
				changed.append(key)

	# 2) Capability flags (JSON)
	if capability_flags is not None:
		if isinstance(capability_flags, dict):
			doc.capability_flags = json.dumps(capability_flags, ensure_ascii=False)
		else:
			doc.capability_flags = capability_flags
		changed.append("capability_flags")

	# 3) Quota limits (JSON)
	if quota_limits is not None:
		if isinstance(quota_limits, dict):
			doc.quota_limits = json.dumps(quota_limits, ensure_ascii=False)
		else:
			doc.quota_limits = quota_limits
		changed.append("quota_limits")

	# 4) Pricing features (child table replace)
	if pricing_features is not None and isinstance(pricing_features, list):
		doc.set("pricing_features", [])
		for idx, row in enumerate(pricing_features):
			if not isinstance(row, dict) or not row.get("display_text"):
				continue
			doc.append("pricing_features", {
				"display_text": row.get("display_text", "").strip(),
				"icon": row.get("icon") or "check",
				"is_disabled": 1 if row.get("is_disabled") else 0,
				"feature_key": row.get("feature_key") or None,
				"tooltip": row.get("tooltip") or None,
				"sort_order": int(row.get("sort_order") or idx),
			})
		changed.append("pricing_features")

	if not changed:
		return {"message": _("Değişiklik yok."), "plan_code": plan_code}

	doc.save()

	log_decision(
		action="plan.update_pricing",
		decision="ALLOW",
		rule_id="auth.admin_console",
		layer="L0",
		object_doctype="Subscription Plan",
		object_name=plan_code,
		plan_code=plan_code,
		context={"updated_fields": changed},
	)

	frappe.db.commit()
	return {
		"message": _("Plan güncellendi: {0}").format(plan_code),
		"plan_code": plan_code,
		"updated_fields": changed,
	}


@frappe.whitelist()
def list_feature_catalog_keys() -> list[dict]:
	"""Admin editor için Feature Catalog auto-complete listesi."""
	_require_admin("feature_catalog_keys")

	rows = frappe.get_all(
		"Feature Catalog",
		filters={"is_deprecated": 0},
		fields=["feature_key", "display_name", "category", "feature_type"],
		order_by="category asc, feature_key asc",
	)
	return rows


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_decision_logs(
	severity: str | None = None,
	decision: str | None = None,
	layer: str | None = None,
	actor: str | None = None,
	tenant: str | None = None,
	limit: int = 50,
) -> list[dict]:
	"""ADL listeleme (filter'lı)."""
	_require_audit_read()

	filters: dict = {}
	if severity:
		filters["severity"] = severity
	if decision:
		filters["decision"] = decision
	if layer:
		filters["layer"] = layer
	if actor:
		filters["actor"] = actor
	if tenant:
		filters["tenant"] = tenant

	return frappe.get_all(
		"Authorization Decision Log",
		filters=filters,
		fields=[
			"name",
			"timestamp",
			"actor",
			"actor_role",
			"tenant",
			"action",
			"object_doctype",
			"object_name",
			"decision",
			"rule_id",
			"layer",
			"severity",
			"plan_code",
		],
		order_by="timestamp desc",
		limit_page_length=int(limit),
	)


@frappe.whitelist()
def list_role_change_logs(
	target_user: str | None = None,
	change_type: str | None = None,
	tenant: str | None = None,
	limit: int = 50,
) -> list[dict]:
	"""RCL listeleme."""
	_require_audit_read()

	filters: dict = {}
	if target_user:
		filters["target_user"] = target_user
	if change_type:
		filters["change_type"] = change_type
	if tenant:
		filters["tenant"] = tenant

	return frappe.get_all(
		"Role Change Log",
		filters=filters,
		fields=[
			"name",
			"timestamp",
			"changed_by",
			"target_user",
			"tenant",
			"change_type",
			"before_roles",
			"after_roles",
			"is_temporary",
		],
		order_by="timestamp desc",
		limit_page_length=int(limit),
	)


@frappe.whitelist()
def list_override_logs(
	severity: str | None = None,
	admin_user: str | None = None,
	limit: int = 50,
) -> list[dict]:
	"""POL listeleme."""
	_require_audit_read()

	filters: dict = {}
	if severity:
		filters["severity"] = severity
	if admin_user:
		filters["admin_user"] = admin_user

	return frappe.get_all(
		"Permission Override Log",
		filters=filters,
		fields=[
			"name",
			"timestamp",
			"admin_user",
			"target_object",
			"override_action",
			"original_decision",
			"final_decision",
			"severity",
			"justification",
		],
		order_by="timestamp desc",
		limit_page_length=int(limit),
	)
