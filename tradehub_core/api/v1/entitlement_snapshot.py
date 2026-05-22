# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.7 — Storefront entitlement snapshot endpoint.

Buyer/Seller'a kendi entitlement snapshot'ını döner. Frontend bu snapshot'ı
session storage'da 5 dk cache'ler ve UI gating (sepete ekle butonu, RFQ form,
KYC banner) için kullanır.

**Önemli:** Bu endpoint sadece **deneyim ipucu** üretir — gerçek güvenlik
kararı her korumalı eylemde backend'den taze sorulur. Frontend snapshot'ı
güvenlik sınırı DEĞİLDİR.

Detay: docs/yetki/TradeHub-Yetkilendirme-Mimarisi-v2.md §6.3
"""

from __future__ import annotations

import frappe
from frappe import _

from tradehub_core.entitlement import get_active_subscription, get_capability_flags, get_quota_limits

# Snapshot'a dahil edilecek SADECE bu prefix'lerdeki feature key'leri
# (gizli/finansal/role-management gibi backend-only feature'lar dışarı sızmaz)
_STOREFRONT_FEATURE_PREFIXES = (
	"feature.pim.",  # Çoklu varyant, attribute set vb.
	"feature.functional.",  # RFQ, onay zinciri, kargo
	"feature.store.",  # Vitrin, tema, domain
	"feature.api.",  # API erişimi (storefront'ta bilgi amaçlı)
	"feature.analytics.basic",  # Sadece basic
)

_STOREFRONT_QUOTA_KEYS = (
	"quota.max_products",
	"quota.max_regions",
	"quota.max_sub_users",
)


def _filter_for_storefront(flags: dict) -> dict:
	"""Storefront'a sadece güvenli feature key'leri dön."""
	return {k: v for k, v in flags.items() if any(k.startswith(p) for p in _STOREFRONT_FEATURE_PREFIXES)}


def _filter_quotas_for_storefront(quotas: dict) -> dict:
	"""Storefront'a sadece bilgi amaçlı kotaları dön."""
	return {k: v for k, v in quotas.items() if k in _STOREFRONT_QUOTA_KEYS}


@frappe.whitelist()
def get_snapshot() -> dict:
	"""Mevcut kullanıcı için lightweight entitlement snapshot.

	Returns:
	  {
	    "user": <email>,
	    "is_buyer": bool,
	    "is_seller": bool,
	    "kyc_status": str | None,
	    "kyb_status": str | None,
	    "can_buy": bool,
	    "can_sell": bool,
	    "tenant": <store name | None>,
	    "plan_code": <str | None>,
	    "subscription_status": <str | None>,
	    "trial_end": <iso | None>,
	    "features": {feature_key: bool, ...},   # filtered subset
	    "quotas":   {quota_key: int, ...},      # filtered subset
	    "ttl_seconds": 300,
	  }

	Cache: frontend sessionStorage'da 5 dk tut.

	Güvenlik: Bu endpoint sadece **görüntülenebilir** feature/quota'ları döner;
	finansal veya rol-yönetim flag'leri dışarı çıkmaz. Asıl korumalı eylemler
	backend'de tekrar `has_feature`/`within_quota` ile doğrulanır.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return {
			"user": "Guest",
			"is_buyer": False,
			"is_seller": False,
			"can_buy": False,
			"can_sell": False,
			"features": {},
			"quotas": {},
			"ttl_seconds": 300,
		}

	# User Profile snapshot (Sprint 2 sonrası tek user profile entity)
	user_profile = (
		frappe.db.get_value(
			"User Profile",
			{"user": user},
			[
				"account_type",
				"kyc_status",
				"kyb_status",
				"can_buy",
				"can_sell",
			],
			as_dict=True,
		)
		or {}
	)

	roles = set(frappe.get_roles(user))
	is_seller = "Marketplace Seller" in roles or "Seller" in roles or "Seller Owner" in roles
	is_buyer = "Marketplace Buyer" in roles or "Buyer" in roles

	# Satıcı snapshot: kendi store'unun entitlement'ı
	tenant = None
	plan_code = None
	subscription_status = None
	trial_end = None
	features: dict = {}
	quotas: dict = {}

	if is_seller:
		# Kullanıcı bir Admin Seller Profile'a bağlı mı (Owner veya sub-user)?
		tenant = frappe.db.get_value("User", user, "tradehub_tenant") or frappe.db.get_value(
			"Admin Seller Profile", {"user": user, "status": "Active"}, "name"
		)

		if tenant:
			sub = get_active_subscription(tenant)
			if sub:
				plan_code = sub.get("plan")
				subscription_status = sub.get("status")
				trial_end = sub.get("trial_end")
				features = _filter_for_storefront(get_capability_flags(tenant))
				quotas = _filter_quotas_for_storefront(get_quota_limits(tenant))

	return {
		"user": user,
		"is_buyer": bool(is_buyer),
		"is_seller": bool(is_seller),
		"account_type": user_profile.get("account_type"),
		"kyc_status": user_profile.get("kyc_status"),
		"kyb_status": user_profile.get("kyb_status"),
		"can_buy": bool(user_profile.get("can_buy")),
		"can_sell": bool(user_profile.get("can_sell")),
		"tenant": tenant,
		"plan_code": plan_code,
		"subscription_status": subscription_status,
		"trial_end": trial_end,
		"features": features,
		"quotas": quotas,
		"ttl_seconds": 300,
	}


@frappe.whitelist()
def check_feature(feature_key: str) -> dict:
	"""Tek bir feature için fresh check (cache by-pass).

	Frontend "Bu butonu aktive et" gibi kritik anlarda kullanır — snapshot
	stale olabileceği için ayrı endpoint.
	"""
	if not feature_key:
		frappe.throw(_("feature_key gerekli"))

	user = frappe.session.user
	if not user or user == "Guest":
		return {"feature_key": feature_key, "has_feature": False, "reason": "guest"}

	tenant = frappe.db.get_value("User", user, "tradehub_tenant") or frappe.db.get_value(
		"Admin Seller Profile", {"user": user, "status": "Active"}, "name"
	)
	if not tenant:
		return {
			"feature_key": feature_key,
			"has_feature": False,
			"reason": "no_tenant",
		}

	from tradehub_core.entitlement import has_feature

	result = has_feature(tenant, feature_key)
	return {
		"feature_key": feature_key,
		"has_feature": bool(result),
		"tenant": tenant,
	}
