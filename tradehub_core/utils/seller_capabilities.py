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
_TIER_MANAGEMENT: frozenset[str] = frozenset({"Seller Full Access", "Seller Co-Owner", "Seller Manager"})

# Operasyon: Yönetim + Operations (Staff role taşıyanlar).
_TIER_OPERATIONS: frozenset[str] = frozenset(
	{"Seller Full Access", "Seller Co-Owner", "Seller Manager", "Seller Operations"}
)

# Finans: Yönetim + Finance Staff (Finance role taşıyanlar).
_TIER_FINANCE: frozenset[str] = frozenset(
	{"Seller Full Access", "Seller Co-Owner", "Seller Manager", "Seller Finance Staff"}
)

# Satış: Yönetim + Sales Rep (ürün + müşteri iletişimi, ama stok/kargo yönetimi yok).
_TIER_SALES: frozenset[str] = frozenset(
	{"Seller Full Access", "Seller Co-Owner", "Seller Manager", "Seller Sales Rep"}
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
_PLATFORM_ROLES: frozenset[str] = frozenset({"System Manager", "Marketplace Admin", "Administrator"})

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
# Sales tier — Manager + Co-Owner + Sales Rep + Owner. Audit'te tier'ı tanımlı
# ama _TIER_ROLE_FALLBACK'a eklenmemişti → has_seller_capability fallback yolu
# Sales Rep'i tanımıyordu.
_TIER_SALES_ROLES: frozenset[str] = frozenset({"Seller Sales", "Seller Admin", "Seller Owner"})
_TIER_COOWNER_ROLES: frozenset[str] = frozenset({"Seller Co-Owner", "Seller Owner"})

# Tier set → role set lookup (matrise paralel — tier kimliği için profile set kullanılıyor)
_TIER_ROLE_FALLBACK: dict[frozenset[str], frozenset[str]] = {
	_TIER_OPERATIONS: _TIER_OPERATIONS_ROLES,
	_TIER_FINANCE: _TIER_FINANCE_ROLES,
	_TIER_MANAGEMENT: _TIER_MANAGEMENT_ROLES,
	_TIER_SALES: _TIER_SALES_ROLES,
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
	# Plan-bağımlı operasyon feature'ları (Feature Catalog key'leri):
	"rfq.quote": (_TIER_OPERATIONS, "feature.functional.rfq"),
	"crm.lead_capture": (_TIER_OPERATIONS, "feature.crm.module"),
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
	# ── Veri görünürlük (dashboard maskeleme + UI gating) ──
	"view.financial_summary": (_TIER_FINANCE, None),  # GMV, ortalama sepet, ciro trendi
	"view.profit_detail": (_TIER_MANAGEMENT, None),  # Kâr marjı (yalnızca yönetim+)
	"view.balance": (_TIER_FINANCE, None),  # Bakiye, ödeme geçmişi
	"view.bank_info": (_TIER_COOWNER, None),  # IBAN (okuma)
	"view.customer_full": (_TIER_SALES, None),  # Tam müşteri bilgisi
	"view.customer_shipping": (_TIER_OPERATIONS, None),  # Kargo için min bilgi
	"view.order_amounts": (_TIER_FINANCE, None),  # Sipariş tutarları
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
		# Tenant bağlı değil → plan-bağımlı feature kullanılamaz (fail-closed).
		# NOT: Tenant'ı olan ama subscription'ı olmayan store'lar da has_feature()
		# tarafından False döner (entitlement.core negative cache ile).
		# Free plan otomatik atanmıyorsa tüm plan-dependent capability'ler kapalı kalır.
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
	"""K5 fix: AML/sanctions kontrolü.

	KYB Verification'dan aml_check_status ve sanctions_status field'larını
	kontrol eder. "Hit Found" veya "Match Found" ise False döner.
	Field'lar henüz eklenmemişse graceful fallback (True). Capability
	layer'a hook noktası şimdiden mevcut.
	"""
	try:
		kyb = frappe.db.get_value(
			"KYB Verification",
			{"user": user, "docstatus": 1},
			["aml_check_status", "sanctions_status"],
			as_dict=True,
		)
	except Exception:
		# Field'lar henüz yoksa (column unknown) → graceful fallback
		return True

	if not kyb:
		return True

	blocked = {"Hit Found", "Match Found"}
	if (kyb.get("aml_check_status") or "") in blocked:
		return False
	if (kyb.get("sanctions_status") or "") in blocked:
		return False
	return True


def _get_capability_metadata(capability_key: str) -> dict | None:
	"""TH Capability Registry'den capability metadata oku.

	None döner ise:
	  - DocType henüz oluşturulmamış (migration öncesi), veya
	  - Capability registry'e seed edilmemiş

	Bu durumda Python SELLER_CAPABILITIES dict'i fallback olarak kullanılır
	(geçiş süresi, Sprint 6 sonrası kaldırılacak).
	"""
	try:
		if not frappe.db.table_exists("tabTH Capability Registry"):
			return None
	except Exception:
		return None

	return frappe.db.get_value(
		"TH Capability Registry",
		capability_key,
		[
			"is_active",
			"is_owner_only",
			"requires_kyc",
			"requires_aml",
			"plan_feature_flag",
			"default_tier",
		],
		as_dict=True,
	)


def has_seller_capability(capability: str, user: str | None = None) -> bool:
	"""User'ın verilen capability'ye sahip olup olmadığını döner.

	Sprint 6 RBAC refactor sonrası:
	  - Capability metadata TH Capability Registry'den okunur (is_owner_only,
	    requires_kyc, requires_aml, plan_feature_flag).
	  - Role profile → capability grant kontrolü TH Capability Grant'tan
	    (permission_resolver.has_capability).
	  - Capability registry'de tanımlı değilse Python SELLER_CAPABILITIES dict
	    fallback olarak kullanılır (geçiş süresi).

	Karar zinciri:
	  1. Guest/boş user → False
	  2. Administrator → True
	  3. Platform admin rolleri (System Manager / Marketplace Admin) → True
	  4. User.enabled=0 → False (deactive user capability alamaz)
	  5. Seller relation YOK → False (C1 fix)
	  6. Capability metadata DB'den (varsa) → owner-only / plan / KYC / AML kapıları
	  7. is_owner=1 + non-owner-only + tüm kapılar geçti → True
	  8. TH Capability Grant'tan profile match → True
	  9. Role delegation tier_roles fallback → True
	  10. Aksi → False
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

	# DB-first: TH Capability Registry'den metadata
	cap_meta = _get_capability_metadata(capability)

	if cap_meta is not None:
		# DB-driven karar yolu
		if not cap_meta.get("is_active"):
			return False

		is_owner_only_db = bool(cap_meta.get("is_owner_only"))
		requires_kyc_db = bool(cap_meta.get("requires_kyc"))
		requires_aml_db = bool(cap_meta.get("requires_aml"))
		plan_feature = cap_meta.get("plan_feature_flag") or None

		# Owner-only kapı
		if is_owner_only_db:
			if not is_owner:
				return False
			if requires_kyc_db and not _check_kyc_verified(user):
				return False
			return True

		# Plan kapısı
		tenant = _user_tenant(user, user_data)
		if not _plan_allows(tenant, plan_feature):
			return False

		# KYC / AML
		if requires_kyc_db and not _check_kyc_verified(user):
			return False
		if requires_aml_db and not _check_aml_clean(user):
			return False

		# Owner → tüm non-owner-only capability'leri alır
		if is_owner:
			return True

		# TH Capability Grant kontrolü
		from tradehub_core.utils.permission_resolver import has_capability as _has_cap_db

		if _has_cap_db(user, capability):
			return True

		# K6: Role Delegation fallback
		cap_def = SELLER_CAPABILITIES.get(capability)
		if cap_def:
			allowed_profiles, _ = cap_def
			tier_roles = _TIER_ROLE_FALLBACK.get(allowed_profiles)
			if tier_roles and (roles & tier_roles):
				return True

		return False

	# Fallback: capability DB'de yok → eski Python sistemi
	# (Sprint 6 sonrası bu blok kaldırılacak)
	if capability in _OWNER_ONLY_CAPABILITIES:
		if not is_owner:
			return False
		if capability in _REQUIRES_KYC and not _check_kyc_verified(user):
			return False
		return True

	cap_def = SELLER_CAPABILITIES.get(capability)
	if not cap_def:
		return False
	allowed_profiles, plan_feature = cap_def

	tenant = _user_tenant(user, user_data)
	if not _plan_allows(tenant, plan_feature):
		return False

	if capability in _REQUIRES_KYC and not _check_kyc_verified(user):
		return False
	if capability in _REQUIRES_AML_CLEAN and not _check_aml_clean(user):
		return False

	if is_owner:
		return True

	user_profile = (user_data.get("role_profile_name") or "").strip()
	if user_profile in allowed_profiles:
		return True

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

	Sprint 6 RBAC: DB-first (TH Capability Registry + TH Capability Grant).
	Registry seed edilmemişse Python SELLER_CAPABILITIES dict fallback'i devreye girer.

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
		return _all_capabilities_from_db_or_python()

	roles = set(frappe.get_roles(user))
	if roles & _PLATFORM_ROLES:
		return _all_capabilities_from_db_or_python()

	user_data = _resolve_user_state(user)

	# Has_seller_capability ile aynı preconditions
	if user_data.get("enabled") == 0:
		return []
	if not _is_seller_user(user, user_data):
		return []

	is_owner = bool(user_data.get("tradehub_is_owner"))
	tenant = _user_tenant(user, user_data)
	kyc_ok = _check_kyc_verified(user)
	aml_ok = _check_aml_clean(user)

	# DB-first
	try:
		if frappe.db.table_exists("tabTH Capability Registry"):
			return _get_user_capabilities_db(user, is_owner, tenant, kyc_ok, aml_ok)
	except Exception:
		frappe.log_error(
			"get_user_capabilities DB lookup failed — Python fallback",
			"seller_capabilities",
		)

	# Fallback: eski Python kodu
	profile = (user_data.get("role_profile_name") or "").strip()
	caps: list[str] = []
	if is_owner:
		for cap in _OWNER_ONLY_CAPABILITIES:
			if cap in _REQUIRES_KYC and not kyc_ok:
				continue
			caps.append(cap)
	for cap, (allowed_profiles, plan_feature) in SELLER_CAPABILITIES.items():
		if not _plan_allows(tenant, plan_feature):
			continue
		if cap in _REQUIRES_KYC and not kyc_ok:
			continue
		if cap in _REQUIRES_AML_CLEAN and not aml_ok:
			continue
		if is_owner or profile in allowed_profiles:
			caps.append(cap)
			continue
		tier_roles = _TIER_ROLE_FALLBACK.get(allowed_profiles)
		if tier_roles and (roles & tier_roles):
			caps.append(cap)
	return caps


def _all_capabilities_from_db_or_python() -> list[str]:
	"""Platform admin için: tüm aktif capability key'leri."""
	try:
		if frappe.db.table_exists("tabTH Capability Registry"):
			rows = frappe.get_all(
				"TH Capability Registry",
				filters={"is_active": 1},
				fields=["capability_key"],
			)
			db_keys = [r["capability_key"] for r in rows]
			if db_keys:
				return db_keys
	except Exception:
		pass
	return list(SELLER_CAPABILITIES.keys()) + list(_OWNER_ONLY_CAPABILITIES)


def _get_user_capabilities_db(
	user: str,
	is_owner: bool,
	tenant: str | None,
	kyc_ok: bool,
	aml_ok: bool,
) -> list[str]:
	"""DB-driven capability seti hesaplama."""
	all_caps = frappe.get_all(
		"TH Capability Registry",
		filters={"is_active": 1},
		fields=[
			"name",
			"is_owner_only",
			"requires_kyc",
			"requires_aml",
			"plan_feature_flag",
		],
	)

	from tradehub_core.utils.permission_resolver import get_capabilities as _granted_caps_fn

	granted_caps = _granted_caps_fn(user) if not is_owner else set()

	result: list[str] = []
	for meta in all_caps:
		cap_key = meta["name"]
		is_owner_only = bool(meta.get("is_owner_only"))
		req_kyc = bool(meta.get("requires_kyc"))
		req_aml = bool(meta.get("requires_aml"))
		plan_feature = meta.get("plan_feature_flag") or None

		if is_owner_only:
			if not is_owner:
				continue
			if req_kyc and not kyc_ok:
				continue
			result.append(cap_key)
			continue

		if not _plan_allows(tenant, plan_feature):
			continue
		if req_kyc and not kyc_ok:
			continue
		if req_aml and not aml_ok:
			continue

		if is_owner or cap_key in granted_caps:
			result.append(cap_key)

	return result
