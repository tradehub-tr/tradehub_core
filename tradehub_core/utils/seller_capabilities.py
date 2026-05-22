# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Seller sub-user kapasite (capability) matrisi — tek kaynak doğruluğu.

Karar: rol profili (`User.role_profile_name`) bazlı capability check.
Manager ile Co-Owner aynı `Has Role` setine sahip olduğu için (Admin + Finance
+ Staff + Viewer) salt rol intersection'ı yetmez — profil adı üzerinden ayrım
yapılır. Owner-only işlemler için ayrıca `tradehub_is_owner` flag'i şart.

Kullanım:

    from tradehub_core.utils.seller_capabilities import require_seller_capability

    @frappe.whitelist()
    def seller_ship_order(...):
        require_seller_capability("order.ship")
        ...

Tasarım notları:
  - Platform admin (System Manager / Marketplace Admin) tüm capability'leri bypass eder.
  - Owner (tradehub_is_owner=1) tüm non-platform capability'lerini otomatik alır
    (Full Access profili dışında bile — örn. owner-only banka değişikliği).
  - Tanımlanmamış capability default deny — yanlış yazılan capability adı
    işlemi açmaz, kapatır (fail-secure).
  - i18n: hata mesajı kullanıcıya gösterilir, çevirilebilir.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

import frappe
from frappe import _

# ---------------------------------------------------------------------------
# Rol profili setleri — capability matrisi için yeniden kullanılır
# ---------------------------------------------------------------------------

# Yönetim katmanı: Owner + Co-Owner + Manager (Admin role taşıyan profiller).
_TIER_MANAGEMENT: frozenset[str] = frozenset(
	{"Seller Full Access", "Seller Co-Owner", "Seller Manager"}
)

# Operasyon: Yönetim + Operations (Staff role taşıyanlar).
_TIER_OPERATIONS: frozenset[str] = frozenset(
	{"Seller Full Access", "Seller Co-Owner", "Seller Manager", "Seller Operations"}
)

# Finans: Yönetim + Finance Staff (Finance role taşıyanlar).
_TIER_FINANCE: frozenset[str] = frozenset(
	{"Seller Full Access", "Seller Co-Owner", "Seller Manager", "Seller Finance Staff"}
)

# Sub-user / ekip yönetimi: yalnızca Owner + Co-Owner.
# Manager dahil DEĞİL (Manager = Admin rol seti + ekip yönetimi yok).
_TIER_COOWNER: frozenset[str] = frozenset({"Seller Full Access", "Seller Co-Owner"})

# Owner-only — capability listesinde özel handling (tradehub_is_owner flag'i de aranır).
_OWNER_ONLY_CAPABILITIES: frozenset[str] = frozenset(
	{
		"bank_info.write",
		"tax_info.write",
		"account.delete",
		"owner.transfer",
		"subscription.change",
		"two_factor.disable",
	}
)

# Platform tarafı bypass — bu rollere sahip user her capability'yi geçer.
_PLATFORM_ROLES: frozenset[str] = frozenset(
	{"System Manager", "Marketplace Admin", "Administrator"}
)

# K6 fix: Tier'lara karşılık Frappe Role'leri — Role Delegation görünürlüğü için.
# Bir user'ın role_profile_name'i tier dışında olsa bile, User.roles'da bu role
# varsa (delegation ile) tier'a sahip sayılır.
# Profile → roles mapping (role_profile.json fixture'ından türetilmiş):
#   Seller Full Access     = Owner + Admin + Finance + Staff + Viewer
#   Seller Co-Owner        = Admin + Finance + Staff + Viewer
#   Seller Manager         = Admin + Finance + Staff + Viewer
#   Seller Operations      = Staff + Viewer
#   Seller Finance Staff   = Finance + Viewer
#
# Tier'a "girmek için yeterli olan tek role" (sufficient condition):
_TIER_OPERATIONS_ROLES: frozenset[str] = frozenset({"Seller Staff", "Seller Admin", "Seller Owner"})
_TIER_FINANCE_ROLES: frozenset[str] = frozenset({"Seller Finance", "Seller Admin", "Seller Owner"})
_TIER_MANAGEMENT_ROLES: frozenset[str] = frozenset({"Seller Admin", "Seller Owner"})
_TIER_COOWNER_ROLES: frozenset[str] = frozenset({"Seller Co-Owner", "Seller Owner"})

# Tier set → role set lookup (matrise paralel — tier kimliği için profile set kullanılıyor)
_TIER_ROLE_FALLBACK: dict[frozenset[str], frozenset[str]] = {
	_TIER_OPERATIONS: _TIER_OPERATIONS_ROLES,
	_TIER_FINANCE: _TIER_FINANCE_ROLES,
	_TIER_MANAGEMENT: _TIER_MANAGEMENT_ROLES,
	_TIER_COOWNER: _TIER_COOWNER_ROLES,
}

# ---------------------------------------------------------------------------
# Capability matrisi
# ---------------------------------------------------------------------------
# Anahtar = "<domain>.<action>" konvansiyonu.
# Değer = (tier_set, plan_feature_key | None) tuple'ı.
#   - tier_set: bu capability'yi alabilecek role profile'lar
#   - plan_feature_key: subscription plan'da bu feature aktif olmalı; None ise
#     plan'a bakılmaz (her plan kullanabilir, sadece temel feature)
#
# Plan-bağımlı capability'ler için plan_feature_key tanımla:
#   - rfq.quote → feature.rfq_module (RFQ modülü Pro+)
#   - crm.lead_capture → feature.crm_module (CRM modülü Pro+)
#
# Owner-only capability'ler bu dict'te YOK — `_OWNER_ONLY_CAPABILITIES`'te
# ayrı yönetilirler.

# K4/K5 fix: KYC/AML şart eden capability'ler.
# Finance-tier ve bank_info için KYC verified zorunlu. ABAC layer Payment
# Intent doctype'ında zaten KYC kontrolü yapıyor; bu set capability layer'da
# da defense-in-depth + UI gating sağlar (KYC pending user butonu görmesin).
_REQUIRES_KYC: frozenset[str] = frozenset(
	{
		"order.confirm_payment",
		"order.refund",
		"balance.withdraw",
		"bank_info.write",
	}
)

# AML aktif olduğunda (Sprint 3) bu set'teki capability'ler de gate'lenir.
# Şu an `_check_aml_clean` placeholder (her zaman True), Sprint 3'te aktif.
_REQUIRES_AML_CLEAN: frozenset[str] = frozenset(
	{
		"order.confirm_payment",
		"order.refund",
		"balance.withdraw",
	}
)

SELLER_CAPABILITIES: dict[str, tuple[frozenset[str], str | None]] = {
	# ── Operasyon (sipariş + ürün + galeri + kategori + müşteri sorusu) ──
	"order.ship": (_TIER_OPERATIONS, None),
	"listing.write": (_TIER_OPERATIONS, None),
	"listing.publish": (_TIER_OPERATIONS, None),
	"gallery.write": (_TIER_OPERATIONS, None),
	"category.write": (_TIER_OPERATIONS, None),
	"inquiry.reply": (_TIER_OPERATIONS, None),
	# Plan-bağımlı operasyon feature'ları:
	"rfq.quote": (_TIER_OPERATIONS, "feature.rfq_module"),
	"crm.lead_capture": (_TIER_OPERATIONS, "feature.crm_module"),
	# ── Finans (ödeme onayı / iade / bakiye) ──
	"order.confirm_payment": (_TIER_FINANCE, None),
	"order.refund": (_TIER_FINANCE, None),
	"balance.withdraw": (_TIER_FINANCE, None),
	# ── Yönetim (Admin role gereken işler — Manager üstü) ──
	"listing.delete": (_TIER_MANAGEMENT, None),
	"seller_profile.write": (_TIER_MANAGEMENT, None),
	"storefront.write": (_TIER_MANAGEMENT, None),
	"cert.write": (_TIER_MANAGEMENT, None),
	"address.write": (_TIER_MANAGEMENT, None),
	"kyb.submit": (_TIER_MANAGEMENT, None),
	# ── Ekip yönetimi (sadece Owner + Co-Owner) ──
	# Not: invite_sub_user zaten plan-bazlı role profile validation yapıyor
	# (_validate_role_profile_for_plan). Burası UI gating için.
	"subuser.manage": (_TIER_COOWNER, None),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_user_state(user: str) -> dict:
	"""User'ın capability hesaplaması için gereken tüm field'larını tek
	query'de çek — performance + tutarlılık için.

	Returns: {enabled, tradehub_is_owner, tradehub_tenant, role_profile_name}
	Eksik user → tüm field'lar None döner.
	"""
	data = (
		frappe.db.get_value(
			"User",
			user,
			["enabled", "tradehub_is_owner", "tradehub_tenant", "role_profile_name"],
			as_dict=True,
		)
		or {}
	)
	# dict-like: dict ya da frappe._dict (her ikisi de .get() destekler)
	return data


def _is_seller_user(user: str, user_data: dict | None = None) -> bool:
	"""Caller gerçekten bir seller mı? (Owner veya tenant'a bağlı sub-user)

	C1 fix: role_profile_name field'ı tek başına yeterli değil — buyer'a
	yanlış profil atanırsa string-match privilege escalation primitive olur.
	Capability vermeden ÖNCE seller relation şartı.

	user_data: opsiyonel — _resolve_user_state çıktısı (gereksiz query atlamak için).
	"""
	if user_data is None:
		user_data = _resolve_user_state(user)

	if user_data.get("tradehub_tenant"):
		return True
	# Owner check: User'a Admin Seller Profile sahibi mi?
	return bool(frappe.db.exists("Admin Seller Profile", {"user": user}))


def _user_tenant(user: str, user_data: dict | None = None) -> str | None:
	"""Capability check için tenant resolve et. Owner için kendi Admin Seller
	Profile'ından, sub-user için tradehub_tenant'tan al."""
	if user_data is None:
		user_data = _resolve_user_state(user)
	tenant = user_data.get("tradehub_tenant")
	if tenant:
		return tenant
	# Owner'ın kendi mağaza profili
	return frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")


def _plan_allows(tenant: str | None, plan_feature: str | None) -> bool:
	"""Tenant'ın subscription plan'ı verilen feature'a sahip mi?

	plan_feature None ise (temel capability) → True (plan kısıtı yok)
	tenant None ise → False (subscription yok = plan-bağımlı feature yasak)
	"""
	if not plan_feature:
		return True
	if not tenant:
		# Subscription bağlı değil → plan-bağımlı feature kullanılamaz
		return False
	from tradehub_core.entitlement import has_feature

	return has_feature(tenant, plan_feature)


def _check_kyc_verified(user: str) -> bool:
	"""K4 fix: KYC-required capability'ler için verification kontrolü.

	User Profile.kyc_status veya kyb_status 'Verified' olmalı (ABAC ile aynı
	semantik). Profile yoksa graceful fallback: izin ver (legacy users).
	"""
	up = frappe.db.get_value(
		"User Profile",
		{"user": user},
		["kyc_status", "kyb_status", "account_type"],
		as_dict=True,
	)
	if not up:
		# Profile yok = legacy user, geçişe izin (ABAC ile uyumlu)
		return True
	# Individual hesap → KYC bypass (Business olmayanlar için ABAC pattern'i)
	if (up.get("account_type") or "") == "Individual":
		return True
	# KYC veya KYB Verified ise geç
	return up.get("kyc_status") == "Verified" or up.get("kyb_status") == "Verified"


def _check_aml_clean(user: str) -> bool:
	"""K5 fix: AML/sanctions placeholder.

	Sprint 2 öncesi: KYB Verification'da aml_check_status field'ı yok →
	her zaman True (ABAC ile uyumlu graceful fallback).
	Sprint 3'te aktif olunca burası gerçek check yapacak — capability
	layer'a hook noktası şimdiden mevcut.
	"""
	# Sprint 3'te KYB Verification.aml_check_status okuyacak.
	# Şu an placeholder: True.
	_ = user  # ileride kullanılacak
	return True


def has_seller_capability(capability: str, user: str | None = None) -> bool:
	"""User'ın verilen capability'ye sahip olup olmadığını döner.

	Karar zinciri:
	  1. Guest/boş user → False
	  2. Administrator → True
	  3. Platform admin rolleri (System Manager / Marketplace Admin) → True
	  4. User.enabled=0 → False (deactive user capability alamaz)
	  5. Seller relation YOK → False (C1 fix)
	  6. Owner-only capability + user is_owner değil → False
	  7. is_owner=1 + non-owner-only → plan kısıtı varsa plan check yap, geçerse True
	  8. Capability tanımsız → False (fail-secure)
	  9. user.role_profile_name in allowed_profiles AND plan allows → True
	  10. Aksi → False

	Plan-bağımlı capability'ler (rfq.quote, crm.lead_capture) için subscription
	plan'da feature aktif olmalı. Owner bile plan yoksa o feature'ı kullanamaz
	(pricing vaadi tutarlılığı).

	Args:
	    capability: "order.ship" gibi capability key
	    user: Kontrol edilecek user (default: session.user)
	"""
	user = user or frappe.session.user
	if not user or user in ("Guest", ""):
		return False

	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))
	if roles & _PLATFORM_ROLES:
		return True

	user_data = _resolve_user_state(user)

	# H3 fix: pasifleştirilmiş user capability alamaz.
	if user_data.get("enabled") == 0:
		return False

	# C1 fix: seller relation şart.
	if not _is_seller_user(user, user_data):
		return False

	is_owner = bool(user_data.get("tradehub_is_owner"))

	# Owner-only capability — sadece flag taşıyan Owner geçebilir.
	if capability in _OWNER_ONLY_CAPABILITIES:
		if not is_owner:
			return False
		# K4: bank_info.write owner-only AMA KYC verified de şart
		if capability in _REQUIRES_KYC and not _check_kyc_verified(user):
			return False
		return True

	cap_def = SELLER_CAPABILITIES.get(capability)
	if not cap_def:
		# Tanımsız capability → fail-secure.
		return False
	allowed_profiles, plan_feature = cap_def

	# Plan check — owner dahil herkes için (pricing tutarlılığı)
	tenant = _user_tenant(user, user_data)
	if not _plan_allows(tenant, plan_feature):
		return False

	# K4: KYC verified şart? (Finance + bank_info için)
	if capability in _REQUIRES_KYC and not _check_kyc_verified(user):
		return False

	# K5: AML clean şart? (Finance için — Sprint 3'te aktif)
	if capability in _REQUIRES_AML_CLEAN and not _check_aml_clean(user):
		return False

	# Owner non-owner-only capability'lerin hepsini alır (plan + KYC geçtiyse).
	if is_owner:
		return True

	user_profile = (user_data.get("role_profile_name") or "").strip()
	if user_profile in allowed_profiles:
		return True

	# K6 fix: Role Delegation görünürlüğü.
	# Profile match etmedi — ama user delegasyonla sufficient role almış olabilir
	# (örn. Operations user'a Seller Finance role delegate edildi → order.refund alabilir).
	# `roles` zaten yukarıda hesaplandı.
	tier_roles = _TIER_ROLE_FALLBACK.get(allowed_profiles)
	if tier_roles and (roles & tier_roles):
		return True

	return False


def require_seller_capability(capability: str, user: str | None = None) -> None:
	"""has_seller_capability False ise frappe.PermissionError fırlatır.

	Endpoint'lerin başında çağrılır. Audit'e log atmaz (audit gerekiyorsa
	endpoint kendi log_role_change'ini çağırsın).
	"""
	if not has_seller_capability(capability, user):
		frappe.throw(
			_("Bu işlem için yetkiniz yok. Gerekli yetki: {0}").format(capability),
			frappe.PermissionError,
		)


def seller_capability_required(capability: str) -> Callable:
	"""Decorator versiyon — @frappe.whitelist() altında kullanılır.

	Örnek:
	    @frappe.whitelist()
	    @seller_capability_required("order.ship")
	    def seller_ship_order(order_number, tracking_number=""):
	        ...
	"""

	def decorator(fn: Callable) -> Callable:
		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			require_seller_capability(capability)
			return fn(*args, **kwargs)

		return wrapper

	return decorator


def get_user_capabilities(user: str | None = None) -> list[str]:
	"""User'ın sahip olduğu tüm capability key'lerini döner — UI gating için.

	Frontend bunu /api/method/...get_session_user response'unda alır,
	useAuthStore.userCapabilities olarak expose eder, sonra v-if="can('order.ship')"
	pattern'ı ile butonları gizler.

	has_seller_capability ile AYNI precondition zincirini uygular (deactive
	user, seller relation şartı, owner-only). Tutarsızlık olmamalı —
	UI'da görünen capability backend'de de geçer.
	"""
	user = user or frappe.session.user
	if not user or user in ("Guest", ""):
		return []

	if user == "Administrator":
		return list(SELLER_CAPABILITIES.keys())

	roles = set(frappe.get_roles(user))
	if roles & _PLATFORM_ROLES:
		return list(SELLER_CAPABILITIES.keys())

	user_data = _resolve_user_state(user)

	# Has_seller_capability ile aynı preconditions
	if user_data.get("enabled") == 0:
		return []
	if not _is_seller_user(user, user_data):
		return []

	is_owner = bool(user_data.get("tradehub_is_owner"))
	profile = (user_data.get("role_profile_name") or "").strip()
	tenant = _user_tenant(user, user_data)

	# K4/K5: KYC + AML check helpers (her cap için tekrar çalıştırma, bir kez)
	kyc_ok = _check_kyc_verified(user)
	aml_ok = _check_aml_clean(user)

	caps: list[str] = []
	# Owner-only — sadece tradehub_is_owner=1 alır (plan-bağımsız).
	if is_owner:
		for cap in _OWNER_ONLY_CAPABILITIES:
			# K4: bank_info.write için KYC verified gereksin
			if cap in _REQUIRES_KYC and not kyc_ok:
				continue
			caps.append(cap)
	# Standart capability'ler — role tier + plan + KYC/AML kontrolü.
	for cap, (allowed_profiles, plan_feature) in SELLER_CAPABILITIES.items():
		# Plan check (plan_feature None ise her plan geçer)
		if not _plan_allows(tenant, plan_feature):
			continue
		# K4: KYC verified şart?
		if cap in _REQUIRES_KYC and not kyc_ok:
			continue
		# K5: AML clean şart?
		if cap in _REQUIRES_AML_CLEAN and not aml_ok:
			continue
		# Role check: owner her şeyi alır; profile match; veya K6: delegated role match
		if is_owner or profile in allowed_profiles:
			caps.append(cap)
			continue
		tier_roles = _TIER_ROLE_FALLBACK.get(allowed_profiles)
		if tier_roles and (roles & tier_roles):
			caps.append(cap)
	return caps
