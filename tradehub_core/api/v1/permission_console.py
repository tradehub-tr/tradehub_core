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
_AUDIT_READ_ROLES = frozenset({"System Manager", "Marketplace Admin", "Administrator", "Compliance Officer"})


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
		"decisions_24h": frappe.db.count("Authorization Decision Log", {"timestamp": [">=", day_ago]}),
		"denies_24h": frappe.db.count(
			"Authorization Decision Log",
			{"timestamp": [">=", day_ago], "decision": "DENY"},
		),
		"high_severity_24h": frappe.db.count(
			"Authorization Decision Log",
			{"timestamp": [">=", day_ago], "severity": "HIGH"},
		),
		"role_changes_7d": frappe.db.count("Role Change Log", {"timestamp": [">=", week_ago]}),
		"overrides_7d": frappe.db.count("Permission Override Log", {"timestamp": [">=", week_ago]}),
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
	# ERPNext default Role Profile'ları TradeHub bağlamında anlamlı değil —
	# Permission Console listesinden gizlenir (aksi takdirde "Özel" kategorisinde
	# Accounts/Inventory/Manufacturing gibi gürültü görünür).
	profiles = [p for p in profiles if p.name not in _ERPNEXT_DEFAULT_PROFILES]

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
				"is_protected": p.name in _PROTECTED_ROLE_PROFILES,
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
		"is_protected": name in _PROTECTED_ROLE_PROFILES,
	}


# ---------------------------------------------------------------------------
# Role Profile CRUD (Süper Admin yeni rol ekler / günceller / siler)
# ---------------------------------------------------------------------------

# Fixture'dan gelen çekirdek Role Profile'lar — silinemez ve içerdiği roller
# değiştirilemez (UI'da disabled görünür). Sadece açıklama gibi cosmetic
# alanlar düzenlenebilir. Yeni custom profile'lar tüm CRUD'a açık.
_PROTECTED_ROLE_PROFILES = frozenset(
	{
		"Seller Full Access",
		"Seller Co-Owner",
		"Seller Manager",
		"Seller Operations",
		"Seller Finance Staff",
		"Seller Viewer Only",
		"Buyer Full Access",
		"Buyer Approver L1",
		"Buyer Approver L2",
		"Buyer Operations",
		"Buyer Finance Staff",
		"Buyer Viewer Only",
		"Compliance Manager",
		"Platform Finance Manager",
		"Platform Super Admin",
		"Support Staff",
	}
)


# Rol Profile içine ATANAMAZ Frappe rolleri — privilege escalation engeli.
# Süper admin bu rolleri eklemek isterse `Frappe Desk > User > Roles`
# üzerinden manuel ekleyebilir (orada da audit log devrede). Permission
# Console üzerinden zincirleme atanmasını engelliyoruz.
_FORBIDDEN_ASSIGNABLE_ROLES = frozenset(
	{
		# Frappe platform power roles
		"System Manager",
		"Administrator",
		"All",
		# Marketplace platform power roles
		"Marketplace Admin",
	}
)


def _validate_roles_exist(roles: list[str]) -> list[str]:
	"""Verilen Frappe rol adları DB'de var mı? Eksikleri döndür."""
	if not roles:
		return []
	existing = set(frappe.get_all("Role", filters={"name": ["in", roles]}, pluck="name"))
	return [r for r in roles if r not in existing]


def _validate_roles_assignable(roles: list[str]) -> list[str]:
	"""Power-role atanma denemesi varsa hata listesini döndür.

	`_FORBIDDEN_ASSIGNABLE_ROLES`'tan herhangi biri varsa engeller —
	Marketplace Admin'in `roles=["System Manager"]` ile yetki yükseltmesini
	kapatır.
	"""
	if not roles:
		return []
	return [r for r in roles if r in _FORBIDDEN_ASSIGNABLE_ROLES]


_TRADEHUB_ROLE_PREFIXES = (
	"Seller ",
	"Buyer ",
	"Marketplace ",
	"Compliance ",
	"Platform ",
	"Support ",
	"Verified ",
)
# TradeHub için anlamlı, prefix'siz core role'ler.
# Faz F.1 — Boşaltıldı: System Manager `_FORBIDDEN_ASSIGNABLE_ROLES` ile
# çakışıyordu. İleride non-power core role gerekirse buraya ekleyin.
_INCLUDED_CORE_ROLES: frozenset[str] = frozenset()


@frappe.whitelist(methods=["GET"])
def list_assignable_roles() -> list[dict]:
	"""Role Profile içine atanabilecek Frappe rolleri.

	Filtre stratejisi:
	  - `_TRADEHUB_ROLE_PREFIXES` ile başlayanlar (Seller/Buyer/Marketplace vs.)
	  - `_INCLUDED_CORE_ROLES` listesindeki Frappe core role'ler
	  - `is_custom=1` ile süper admin tarafından oluşturulan özel role'ler
	  - `_FORBIDDEN_ASSIGNABLE_ROLES` (System Manager, Administrator,
	    Marketplace Admin, All) HER ZAMAN gizlenir — yazma yolu da
	    `_validate_roles_assignable` ile bloklu, listeleme tarafında da
	    sızdırmamak için filtre tekrarı (Faz F.1).

	Returns: [{name, desk_access, category}] — category: "tradehub"|"core"|"custom".
	"""
	_require_admin("list_assignable_roles")
	rows = frappe.get_all(
		"Role",
		filters={"disabled": 0},
		fields=["name", "desk_access", "is_custom"],
		order_by="name asc",
	)
	out = []
	for r in rows:
		name = r["name"]
		if name in _FORBIDDEN_ASSIGNABLE_ROLES:
			continue  # Power role'ler atanamaz → UI listesinde de görünmez
		if name.startswith(_TRADEHUB_ROLE_PREFIXES):
			category = "tradehub"
		elif name in _INCLUDED_CORE_ROLES:
			category = "core"
		elif r.get("is_custom"):
			category = "custom"
		else:
			continue
		out.append(
			{
				"name": name,
				"desk_access": bool(r.get("desk_access")),
				"category": category,
			}
		)
	return out


@frappe.whitelist(methods=["POST"])
def create_role_profile(
	role_profile: str,
	roles: list[str] | str | None = None,
	parent_profile: str | None = None,
) -> dict:
	"""Yeni Role Profile oluştur.

	Args:
	    role_profile: Yeni profilin adı (örn. "Seller Custom Manager")
	    roles: İçereceği Frappe rol adları (liste veya JSON string)
	    parent_profile: Opsiyonel — verilirse parent'in TH Module Policy + TH
	        Capability Grant kayıtları yeni profile için klonlanır. Aksi
	        takdirde yeni profile için hiçbir modül kapısı tanımlı olmaz ve
	        backend `get_module_mode_map` boş döner; bu da yeni rolü
	        "süper-yetkili gibi" yapar (tüm modüller default visible).

	Returns:
	    {"name", "role_profile", "roles", "inherited_grants", "inherited_policies"}
	"""
	_require_admin("create_role_profile")

	name = (role_profile or "").strip()
	if not name:
		frappe.throw(_("Rol profili adı boş bırakılamaz."))
	if len(name) > 80:
		frappe.throw(_("Rol profili adı 80 karakteri geçemez."))
	if frappe.db.exists("Role Profile", name):
		frappe.throw(_("Bu isimde bir Rol Profili zaten var: {0}").format(name))

	parent = (parent_profile or "").strip() or None
	if parent and not frappe.db.exists("Role Profile", parent):
		frappe.throw(_("Şablon (parent) rol profili bulunamadı: {0}").format(parent))
	# K6 — protected parent klonu privilege escalation vektörü; Platform Super
	# Admin gibi korumalı profile'ı template olarak almak owner-only ve
	# protected capability'leri yeni profile'a kopyalardı.
	if parent and parent in _PROTECTED_ROLE_PROFILES:
		frappe.throw(_("'{0}' korumalı bir rol profilidir; şablon olarak kullanılamaz.").format(parent))

	if isinstance(roles, str):
		try:
			roles = json.loads(roles)
		except (ValueError, TypeError):
			roles = []
	roles = [r for r in (roles or []) if r and isinstance(r, str)]

	missing = _validate_roles_exist(roles)
	if missing:
		frappe.throw(_("Şu Frappe rolleri bulunamadı: {0}").format(", ".join(missing)))
	# K5 — power-role atanma engeli (privilege escalation)
	forbidden = _validate_roles_assignable(roles)
	if forbidden:
		frappe.throw(
			_("Şu Frappe rolleri Permission Console üzerinden atanamaz (power role): {0}").format(
				", ".join(forbidden)
			)
		)

	doc = frappe.new_doc("Role Profile")
	doc.role_profile = name
	for role_name in roles:
		doc.append("roles", {"role": role_name})
	doc.insert(ignore_permissions=True)

	inherited_grants = 0
	inherited_policies = 0
	if parent:
		inherited_grants, inherited_policies = _clone_profile_rbac(parent, name)

	frappe.db.commit()

	# Cache flush (yeni profile policy/grant'lar etkin olsun)
	from tradehub_core.utils.permission_resolver import flush_all_cache

	flush_all_cache()

	log_decision(
		action="permission_console.create_role_profile",
		decision="ALLOW",
		rule_id="auth.admin_role_crud",
		layer="L2",
		object_doctype="Role Profile",
		object_name=doc.name,
		severity="HIGH" if parent else "NORMAL",
		context={
			"role_profile": doc.name,
			"roles": roles,
			"parent_profile": parent,
			"inherited_grants": inherited_grants,
			"inherited_policies": inherited_policies,
		},
	)

	return {
		"name": doc.name,
		"role_profile": doc.role_profile,
		"roles": [r.role for r in doc.roles],
		"parent_profile": parent,
		"inherited_grants": inherited_grants,
		"inherited_policies": inherited_policies,
	}


def _clone_profile_rbac(parent: str, target: str) -> tuple[int, int]:
	"""Parent profile'ın TH Capability Grant + TH Module Policy kayıtlarını
	target profile için klonlar. expires_at/effective_to alanları kopyalanır
	(parent'tan kaynaklı geçici izinler aynen taşınsın).

	Idempotent değil — caller target için bu fonksiyonu yalnızca create akışında
	çağırmalı (mevcut kayıt varsa duplicate insert kırılır).

	Returns: (grant_count, policy_count)
	"""
	grants = frappe.get_all(
		"TH Capability Grant",
		filters={"role_profile": parent},
		fields=["capability", "granted", "expires_at", "note"],
	)
	for g in grants:
		doc = frappe.new_doc("TH Capability Grant")
		doc.role_profile = target
		doc.capability = g["capability"]
		doc.granted = g["granted"]
		doc.expires_at = g.get("expires_at")
		doc.note = f"Inherited from {parent}"
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

	policies = frappe.get_all(
		"TH Module Policy",
		filters={"role_profile": parent},
		fields=["module", "mode", "effective_from", "effective_to", "note"],
	)
	for p in policies:
		doc = frappe.new_doc("TH Module Policy")
		doc.role_profile = target
		doc.module = p["module"]
		doc.mode = p["mode"]
		doc.effective_from = p.get("effective_from")
		doc.effective_to = p.get("effective_to")
		doc.note = f"Inherited from {parent}"
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

	return len(grants), len(policies)


@frappe.whitelist(methods=["POST"])
def update_role_profile(name: str, roles: list[str] | str | None = None) -> dict:
	"""Mevcut Role Profile'ın içerdiği rolleri günceller.

	Çekirdek (korumalı) profilelerin rol içeriği değiştirilemez — protected
	listesi `_PROTECTED_ROLE_PROFILES`'tan kontrol edilir.

	Profile rolleri değiştikten sonra bu profile'a atanmış tüm enabled
	kullanıcıların gerçek Frappe rolleri **tam sync** edilir: profile'a
	eklenen roller user'a eklenir, profile'dan çıkarılan roller user'dan
	çıkarılır. Aksi takdirde Frappe `role_profile_name` aynı kalırken sync
	tetiklemediği için user'lar eski rolleri taşımaya devam ederdi.
	"""
	_require_admin("update_role_profile")

	if not frappe.db.exists("Role Profile", name):
		frappe.throw(_("Rol profili bulunamadı: {0}").format(name))
	if name in _PROTECTED_ROLE_PROFILES:
		frappe.throw(_("'{0}' korumalı bir rol profilidir; içerdiği roller değiştirilemez.").format(name))

	if isinstance(roles, str):
		try:
			roles = json.loads(roles)
		except (ValueError, TypeError):
			roles = []
	roles = [r for r in (roles or []) if r and isinstance(r, str)]

	missing = _validate_roles_exist(roles)
	if missing:
		frappe.throw(_("Şu Frappe rolleri bulunamadı: {0}").format(", ".join(missing)))
	# K5 — power-role atanma engeli (privilege escalation)
	forbidden = _validate_roles_assignable(roles)
	if forbidden:
		frappe.throw(
			_("Şu Frappe rolleri Permission Console üzerinden atanamaz (power role): {0}").format(
				", ".join(forbidden)
			)
		)

	doc = frappe.get_doc("Role Profile", name)
	before_roles = [r.role for r in (doc.roles or [])]
	doc.set("roles", [])
	for role_name in roles:
		doc.append("roles", {"role": role_name})
	doc.save(ignore_permissions=True)

	synced_users = _sync_users_with_role_profile(name, set(roles))

	frappe.db.commit()

	# Cache flush — bu profile'a bağlı kullanıcılar
	from tradehub_core.utils.permission_resolver import flush_all_cache

	flush_all_cache()

	log_decision(
		action="permission_console.update_role_profile",
		decision="ALLOW",
		rule_id="auth.admin_role_crud",
		layer="L2",
		object_doctype="Role Profile",
		object_name=name,
		severity="HIGH" if synced_users > 0 else "NORMAL",
		context={
			"role_profile": name,
			"before": before_roles,
			"after": roles,
			"synced_users": synced_users,
		},
	)

	return {
		"name": doc.name,
		"role_profile": doc.role_profile,
		"roles": [r.role for r in doc.roles],
		"synced_users": synced_users,
	}


def _sync_users_with_role_profile(profile_name: str, target_roles: set[str]) -> int:
	"""Bu profile'a atanmış enabled kullanıcıların Frappe rollerini target_roles
	ile tam sync eder (add + remove).

	Frappe `role_profile_name` aynı kalırken profile içeriği değiştiğinde
	otomatik sync yapmıyor — bu helper aksaklığı kapatır. Each user için
	mevcut Has Role child rows ile diff alır, eksikleri ekler, fazlalıkları
	çıkarır.

	Returns: sync edilen user sayısı.
	"""
	user_names = frappe.get_all(
		"User",
		filters={"role_profile_name": profile_name, "enabled": 1},
		pluck="name",
	)
	count = 0
	for user_name in user_names:
		try:
			user_doc = frappe.get_doc("User", user_name)
			current = {r.role for r in (user_doc.roles or []) if r.role}
			to_add = target_roles - current
			to_remove = current - target_roles
			if not to_add and not to_remove:
				continue
			user_doc.set(
				"roles",
				[{"role": r.role} for r in (user_doc.roles or []) if r.role and r.role not in to_remove],
			)
			for role in to_add:
				if frappe.db.exists("Role", role):
					user_doc.append("roles", {"role": role})
			user_doc.flags.ignore_permissions = True
			user_doc.save(ignore_permissions=True)
			count += 1
		except Exception as exc:
			frappe.log_error(
				f"_sync_users_with_role_profile {user_name}/{profile_name}: {exc}",
				"permission_console.update_role_profile",
			)
	return count


@frappe.whitelist(methods=["POST"])
def delete_role_profile(name: str) -> dict:
	"""Role Profile sil.

	Engeller:
	  - Korumalı (fixture) profile'lar silinemez
	  - Kullanıcı atanmış profile'lar silinemez (önce kullanıcılar başka
	    profile'a taşınmalı)
	"""
	_require_admin("delete_role_profile")

	if not frappe.db.exists("Role Profile", name):
		frappe.throw(_("Rol profili bulunamadı: {0}").format(name))
	if name in _PROTECTED_ROLE_PROFILES:
		frappe.throw(_("'{0}' korumalı bir rol profilidir; silinemez.").format(name))

	user_count = frappe.db.count("User", {"role_profile_name": name})
	if user_count:
		frappe.throw(_("Bu profil {0} kullanıcıya atanmış. Önce kullanıcıları taşıyın.").format(user_count))

	# Bağlı grant ve policy kayıtlarını da temizle (orphan bırakma)
	frappe.db.delete("TH Capability Grant", {"role_profile": name})
	frappe.db.delete("TH Module Policy", {"role_profile": name})
	frappe.delete_doc("Role Profile", name, ignore_permissions=True)
	frappe.db.commit()

	from tradehub_core.utils.permission_resolver import flush_all_cache

	flush_all_cache()

	log_decision(
		action="permission_console.delete_role_profile",
		decision="ALLOW",
		rule_id="auth.admin_role_crud",
		layer="L2",
		object_doctype="Role Profile",
		object_name=name,
		severity="HIGH",
		context={"role_profile": name},
	)

	return {"deleted": name}


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


# Sistem-kritik plan kodları — silinemez. Süper admin yeni custom plan ekler
# ama bu temel kademeler her zaman bulunmak zorunda (entitlement seed referans
# tabanı).
_PROTECTED_PLAN_CODES = frozenset(
	{"FREE", "STARTER", "PRO", "ENTERPRISE", "free", "starter", "pro", "enterprise"}
)


def _require_system_manager_for_plan_crud(action: str) -> None:
	"""Plan CRUD revenue-bearing — sadece System Manager + Administrator.
	Marketplace Admin engellenir (Faz F.4 financial separation ile aynı).
	"""
	_require_admin(action)
	user = frappe.session.user
	if user == "Administrator":
		return
	roles = set(frappe.get_roles(user))
	if "System Manager" not in roles:
		log_decision(
			action=f"permission_console.{action}",
			decision="DENY",
			rule_id="auth.system_manager_required_for_plan_crud",
			layer="L2",
			severity="HIGH",
		)
		frappe.throw(
			_("Plan oluşturma/silme için System Manager yetkisi gerekir (Marketplace Admin için yetersiz)."),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["POST"])
def create_subscription_plan(
	plan_code: str,
	plan_name: str,
	description: str = "",
	monthly_price: float | int | str = 0,
	yearly_price: float | int | str = 0,
	currency: str = "EUR",
	commission_rate: float | int | str = 0,
	max_active_listings: int | str = 0,
	trial_days: int | str = 0,
	is_active: bool | int | str = True,
	is_public: bool | int | str = False,
) -> dict:
	"""Yeni Subscription Plan oluştur.

	Default: `is_public=False` — admin önce capability_flags/quota_limits
	doldurur, sonra public yapar (storefront sızıntı koruması).

	System Manager-only (revenue-bearing). Plan code unique enforced; lowercase
	alphanumeric+hyphen-underscore (`_PLAN_CODE_PATTERN`).
	"""
	_require_system_manager_for_plan_crud("create_subscription_plan")

	code = (plan_code or "").strip()
	name = (plan_name or "").strip()
	if not code:
		frappe.throw(_("plan_code zorunlu."), frappe.ValidationError)
	if not name:
		frappe.throw(_("plan_name zorunlu."), frappe.ValidationError)
	# Hem lowercase hem UPPERCASE varlık kontrolü
	if frappe.db.exists("Subscription Plan", code) or frappe.db.exists("Subscription Plan", code.upper()):
		frappe.throw(_("Bu plan_code zaten kullanılıyor: {0}").format(code))

	doc = frappe.new_doc("Subscription Plan")
	doc.plan_code = code
	doc.plan_name = name
	doc.description = description or ""
	doc.monthly_price = float(monthly_price or 0)
	doc.yearly_price = float(yearly_price or 0)
	doc.currency = currency or "EUR"
	doc.commission_rate = float(commission_rate or 0)
	doc.max_active_listings = int(max_active_listings or 0)
	doc.trial_days = int(trial_days or 0)
	doc.is_active = 1 if str(is_active).lower() in ("1", "true", "yes") else 0
	doc.is_public = 1 if str(is_public).lower() in ("1", "true", "yes") else 0
	doc.capability_flags = "{}"
	doc.quota_limits = "{}"
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)

	# Public pricing cache flush
	try:
		frappe.cache().delete_value("tradehub:pricing:public")
	except Exception:
		pass

	log_decision(
		action="permission_console.create_subscription_plan",
		decision="ALLOW",
		rule_id="auth.admin_plan_crud",
		layer="L0",
		object_doctype="Subscription Plan",
		object_name=doc.name,
		plan_code=code,
		severity="HIGH",
		context={
			"plan_code": code,
			"plan_name": name,
			"is_active": doc.is_active,
			"is_public": doc.is_public,
			"monthly_price": doc.monthly_price,
			"currency": doc.currency,
		},
	)

	return {
		"name": doc.name,
		"plan_code": code,
		"plan_name": name,
		"is_active": doc.is_active,
		"is_public": doc.is_public,
	}


@frappe.whitelist(methods=["POST"])
def delete_subscription_plan(plan_code: str) -> dict:
	"""Subscription Plan sil.

	Engeller:
	  - Protected plan code (FREE/STARTER/PRO/ENTERPRISE) silinemez
	  - Aktif/trial Store Subscription'ı olan plan silinemez

	Cascade:
	  - capability_flags + quota_limits + pricing_features child rows da silinir
	    (Frappe delete_doc default davranışı)
	"""
	_require_system_manager_for_plan_crud("delete_subscription_plan")

	code = (plan_code or "").strip()
	if not code:
		frappe.throw(_("plan_code zorunlu."), frappe.ValidationError)
	if not frappe.db.exists("Subscription Plan", code):
		frappe.throw(_("Plan bulunamadı: {0}").format(code))
	if code in _PROTECTED_PLAN_CODES:
		frappe.throw(
			_("'{0}' korumalı temel plan kodudur; silinemez.").format(code),
			frappe.PermissionError,
		)

	# Aktif/trial Store Subscription kontrolü
	active_subs = frappe.db.count(
		"Store Subscription",
		{"plan": code, "status": ["in", ["trial", "active"]]},
	)
	if active_subs:
		frappe.throw(
			_("Bu planın {0} aktif aboneliği var. Önce abonelikleri başka plana taşıyın.").format(active_subs)
		)

	# Plan kaydını sil
	frappe.delete_doc("Subscription Plan", code, ignore_permissions=True, force=1)
	frappe.db.commit()

	# Cache flush
	try:
		frappe.cache().delete_value("tradehub:pricing:public")
		frappe.cache().delete_keys("tradehub:entitlement:")
	except Exception:
		pass

	log_decision(
		action="permission_console.delete_subscription_plan",
		decision="ALLOW",
		rule_id="auth.admin_plan_crud",
		layer="L0",
		object_doctype="Subscription Plan",
		object_name=code,
		plan_code=code,
		severity="HIGH",
		context={"plan_code": code},
	)

	return {"deleted": code}


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


def _merge_plan_json_field(
	doc, field_name: str, incoming: str | dict | None, *, replace: bool = False
) -> dict | None:
	"""Subscription Plan JSON field (capability_flags / quota_limits) güvenli merge.

	Faz E.1 — Mevcut endpoint'ler partial payload'da REPLACE yapıyordu →
	frontend tek key gönderirse plan'daki diğer 33 key kayboluyordu (canlı
	test'te kanıtlanmış veri kaybı bug'ı). Bu helper:
	  1. Mevcut JSON'u parse eder
	  2. `replace=False` (default) → gelen dict ile mevcut dict'i .update() eder
	  3. `replace=True` → caller bilinçli olarak tam replace isterse seçer

	Returns: parse edilmiş güncel dict (audit context için), payload yoksa None.
	"""
	if incoming is None:
		return None
	if isinstance(incoming, str):
		incoming = json.loads(incoming) if incoming.strip() else {}
	if not isinstance(incoming, dict):
		frappe.throw(_("{0} dict tipinde olmalı.").format(field_name), frappe.ValidationError)

	if replace:
		merged = dict(incoming)
	else:
		current_raw = doc.get(field_name) or "{}"
		try:
			current = json.loads(current_raw) if isinstance(current_raw, str) else (current_raw or {})
		except (ValueError, TypeError):
			current = {}
		if not isinstance(current, dict):
			current = {}
		merged = dict(current)
		merged.update(incoming)

	doc.set(field_name, json.dumps(merged, sort_keys=True, ensure_ascii=False))
	return merged


@frappe.whitelist(methods=["POST"])
def update_plan_capabilities(
	plan_code: str,
	capability_flags: str | dict | None = None,
	quota_limits: str | dict | None = None,
	replace: bool | int | str = False,
) -> dict:
	"""Plan capability_flags + quota_limits güncelle (MERGE semantiği).

	Faz E.1 — Default MERGE: partial payload sadece gönderilen key'leri günceller,
	diğerlerini korur. `replace=True` ile bilinçli tam replace mümkün.

	Wrapper: aslında frappe.client.set_value de aynı işi yapar; ama bu endpoint
	audit log + cache invalidation tetikler.
	"""
	_require_admin("update_plan")

	if not frappe.db.exists("Subscription Plan", plan_code):
		frappe.throw(_("Plan bulunamadı."))

	replace_bool = str(replace).strip().lower() in ("1", "true", "yes")
	doc = frappe.get_doc("Subscription Plan", plan_code)

	cap_merged = _merge_plan_json_field(doc, "capability_flags", capability_flags, replace=replace_bool)
	quota_merged = _merge_plan_json_field(doc, "quota_limits", quota_limits, replace=replace_bool)
	doc.save()  # Subscription Plan.on_update → cache invalidate (entitlement/sync)

	log_decision(
		action="plan.update_capabilities",
		decision="ALLOW",
		rule_id="auth.admin_plan_update",
		layer="L0",
		object_doctype="Subscription Plan",
		object_name=plan_code,
		plan_code=plan_code,
		severity="HIGH" if replace_bool else "NORMAL",
		context={
			"replace": replace_bool,
			"updated_fields": list(
				filter(
					None,
					[
						"capability_flags" if cap_merged is not None else None,
						"quota_limits" if quota_merged is not None else None,
					],
				)
			),
			"capability_flags_count": len(cap_merged) if cap_merged else None,
			"quota_limits_count": len(quota_merged) if quota_merged else None,
		},
	)

	frappe.db.commit()
	return {"message": _("Plan güncellendi: {0}").format(plan_code)}


# ---------------------------------------------------------------------------
# FAZ 4.1 — Dinamik Pricing yönetimi
# ---------------------------------------------------------------------------

_PRICING_DISPLAY_FIELDS = frozenset(
	{
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
		"field_commission_type",
		"field_commission_rate",
		"field_commission_fixed_amount",
		"field_commission_mode",
		"field_commission_duration",
		"max_active_listings",
		"cta_label",
		"cta_action",
		"price_override_label",
		"highlighted",
		"display_order",
		"trial_days",
		"is_active",
		"is_public",
	}
)

# Faz F.4 — Para etkili (revenue-bearing) alanlar SADECE System Manager
# tarafından değiştirilebilir. Marketplace Admin badge/copy/theme gibi cosmetic
# alanları düzenleyebilir ama fiyat, komisyon, trial gün, plan aktivasyonu gibi
# alanlara dokunamaz (finansal tampering engeli).
_PRICING_FINANCIAL_FIELDS = frozenset(
	{
		"monthly_price",
		"yearly_price",
		"currency",
		"commission_rate",
		"trial_days",
		"is_active",
		"is_public",
	}
)


def _caller_can_edit_financial_fields() -> bool:
	"""Sadece System Manager veya Administrator pricing fiyat alanlarını
	değiştirebilir. Marketplace Admin display alanlarıyla sınırlı.
	"""
	user = frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return "System Manager" in roles


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
		"field_commission_type": plan.field_commission_type or "Yüzde",
		"field_commission_rate": float(plan.field_commission_rate or 0),
		"field_commission_fixed_amount": float(plan.field_commission_fixed_amount or 0),
		"field_commission_mode": plan.field_commission_mode or "Tek seferlik",
		"field_commission_duration": int(plan.field_commission_duration or 0),
		"max_active_listings": int(plan.max_active_listings or 0),
		"cta_label": plan.cta_label,
		"cta_action": plan.cta_action or "signup",
		"price_override_label": plan.price_override_label or "",
		# Yetkinlikler
		"capability_flags": caps,
		"quota_limits": quotas,
		"allowed_regions": regions,
		# İçerik
		"pricing_features": features,
		"quota_tiers": [
			{"min_sales": int(r.min_sales or 0), "bonus_amount": float(r.bonus_amount or 0)}
			for r in (plan.quota_tiers or [])
		],
		# Meta
		"active_subscription_count": active_count,
	}


@frappe.whitelist(methods=["POST"])
def update_pricing_plan(
	plan_code: str,
	display: str | dict | None = None,
	capability_flags: str | dict | None = None,
	quota_limits: str | dict | None = None,
	pricing_features: str | list | None = None,
	quota_tiers: str | list | None = None,
	replace: bool | int | str = False,
) -> dict:
	"""FAZ 4.1 — Tek endpoint'le tüm plan field'larını + child table güncelle.

	Faz E.1 — capability_flags/quota_limits için MERGE semantiği (default).
	Partial payload (örn. `{"feature.x": True}`) artık diğer 33 key'i silmez.
	`replace=True` bilinçli tam replace seçeneği.

	Args:
		plan_code: Güncellenecek plan (örn. 'PRO')
		display: Görsel/Pricing field'ları (badge_label, monthly_price, vb.)
		capability_flags: Feature toggle dict (MERGE)
		quota_limits: Quota dict (MERGE)
		pricing_features: Paket içeriği listesi (child table REPLACE — list semantiği)
		replace: capability_flags + quota_limits için tam replace istersen True
	"""
	_require_admin("update_pricing_plan")

	if not frappe.db.exists("Subscription Plan", plan_code):
		frappe.throw(_("Plan bulunamadı."))

	replace_bool = str(replace).strip().lower() in ("1", "true", "yes")

	# String → dict parse (display ve pricing_features için; cap/quota helper'da parse)
	if isinstance(display, str):
		display = json.loads(display) if display.strip() else None
	if isinstance(capability_flags, str):
		capability_flags = json.loads(capability_flags) if capability_flags.strip() else None
	if isinstance(quota_limits, str):
		quota_limits = json.loads(quota_limits) if quota_limits.strip() else None
	if isinstance(pricing_features, str):
		pricing_features = json.loads(pricing_features) if pricing_features.strip() else None
	if isinstance(quota_tiers, str):
		quota_tiers = json.loads(quota_tiers) if quota_tiers.strip() else None

	doc = frappe.get_doc("Subscription Plan", plan_code)
	changed: list[str] = []

	# Faz F.4 — Financial field separation: Marketplace Admin sadece display
	# alanlarını değiştirebilir; fiyat, komisyon, trial, aktivasyon, public
	# alanları yalnız System Manager'a açık.
	can_edit_financial = _caller_can_edit_financial_fields()
	blocked_financial: list[str] = []

	# 1) Display/pricing field'ları
	# Sayısal alanlar boş/null gelirse 0'a normalize et — teklif-bazlı planlar
	# (ör. Enterprise) fiyatı boş bırakabilmeli; aksi halde reqd `monthly_price`
	# "Value missing" verir.
	_numeric_display = {
		"monthly_price",
		"yearly_price",
		"commission_rate",
		"field_commission_rate",
		"field_commission_fixed_amount",
		"field_commission_duration",
		"max_active_listings",
		"trial_days",
		"display_order",
	}
	if display and isinstance(display, dict):
		for key, value in display.items():
			if key not in _PRICING_DISPLAY_FIELDS:
				continue  # whitelist dışı field
			if not can_edit_financial and key in _PRICING_FINANCIAL_FIELDS:
				blocked_financial.append(key)
				continue
			if key in _numeric_display and (value is None or value == ""):
				value = 0
			old = doc.get(key)
			if old != value:
				doc.set(key, value)
				changed.append(key)

	if blocked_financial:
		# Caller bilinçli olarak finansal alan değiştirmeye çalıştı — sessiz
		# atlamak yerine throw ile sinyalle ki UI mesaj gösterebilsin.
		frappe.throw(
			_("Şu fiyat/finans alanları sadece System Manager tarafından değiştirilebilir: {0}").format(
				", ".join(sorted(blocked_financial))
			),
			frappe.PermissionError,
		)

	# 2) Capability flags (MERGE — Faz E.1)
	if _merge_plan_json_field(doc, "capability_flags", capability_flags, replace=replace_bool) is not None:
		changed.append("capability_flags")

	# 3) Quota limits (MERGE — Faz E.1)
	if _merge_plan_json_field(doc, "quota_limits", quota_limits, replace=replace_bool) is not None:
		changed.append("quota_limits")

	# 4) Pricing features (child table replace)
	if pricing_features is not None and isinstance(pricing_features, list):
		doc.set("pricing_features", [])
		for idx, row in enumerate(pricing_features):
			if not isinstance(row, dict) or not row.get("display_text"):
				continue
			doc.append(
				"pricing_features",
				{
					"display_text": row.get("display_text", "").strip(),
					"icon": row.get("icon") or "check",
					"is_disabled": 1 if row.get("is_disabled") else 0,
					"feature_key": row.get("feature_key") or None,
					"tooltip": row.get("tooltip") or None,
					"sort_order": int(row.get("sort_order") or idx),
				},
			)
		changed.append("pricing_features")

	# 5) Saha kota eşikleri (child table replace) — paket-bazı bonus tablosu
	if quota_tiers is not None and isinstance(quota_tiers, list):
		doc.set("quota_tiers", [])
		for row in quota_tiers:
			if not isinstance(row, dict):
				continue
			min_sales = int(row.get("min_sales") or 0)
			if min_sales <= 0:
				continue
			doc.append(
				"quota_tiers",
				{"min_sales": min_sales, "bonus_amount": float(row.get("bonus_amount") or 0)},
			)
		changed.append("quota_tiers")

	if not changed:
		return {"message": _("Değişiklik yok."), "plan_code": plan_code}

	doc.save()

	log_decision(
		action="plan.update_pricing",
		decision="ALLOW",
		rule_id="auth.admin_pricing_update",
		layer="L0",
		object_doctype="Subscription Plan",
		object_name=plan_code,
		plan_code=plan_code,
		severity="HIGH" if replace_bool else "NORMAL",
		context={
			"replace": replace_bool,
			"updated_fields": changed,
		},
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
	action: str | None = None,
	limit: int = 50,
) -> list[dict]:
	"""ADL listeleme (filter'lı).

	Sprint 5 ekleri:
	  - `action` parametresi: belirli action (örn. "pii.field_masked") filtreler.
	  - Response'a `context` field'ı eklendi — masked_fields gibi metadata için.
	"""
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
	if action:
		filters["action"] = action

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
			"context",
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


# ===========================================================================
# Sprint 6 — DB-driven RBAC: Capability & Module yönetimi
# ===========================================================================

_ALLOWED_MODULE_MODES = frozenset({"visible", "masked", "hidden"})

# ERPNext'in fixture'dan gelen default Role Profile'ları — TradeHub bağlamında
# anlamlı olmadığı için Permission Console'dan tamamen gizlenir.
_ERPNEXT_DEFAULT_PROFILES = frozenset(
	{
		"Accounts",
		"Customer",
		"Employee",
		"HR",
		"Inventory",
		"Manufacturing",
		"Material User",
		"Projects",
		"Purchase",
		"Quality",
		"Sales",
		"Stock",
		"Supplier",
	}
)


def _all_rbac_profiles() -> list[str]:
	"""TH RBAC matrislerinin ilgilendiği Role Profile listesi.

	TradeHub fixture profile'ları + süper admin tarafından oluşturulan custom
	profile'lar dahil; ERPNext'in default fixture profile'ları hariç (anlamsız
	gürültü). Yeni eklenen custom profile'lar otomatik dahil olur — eskiden
	hardcoded prefix listesine girmeyen profile'lar Capability sütun olarak
	görünmüyordu.
	"""
	rows = frappe.get_all("Role Profile", fields=["name"], order_by="name asc")
	return [r["name"] for r in rows if r["name"] not in _ERPNEXT_DEFAULT_PROFILES]


@frappe.whitelist()
def list_capabilities() -> dict:
	"""TH Capability Registry + grant matrisi — CapabilityMatrixTab.vue.

	Output:
	    {
	      "role_profiles": ["Seller Full Access", ...],
	      "capabilities": [
	        {
	          "key": str,                # capability_key
	          "label": str,
	          "module_group": str,
	          "default_tier": str,
	          "is_owner_only": bool,
	          "is_protected": bool,
	          "requires_kyc": bool,
	          "requires_aml": bool,
	          "plan_feature_flag": str,
	          "is_active": bool,
	          "description": str,
	          "grants": [role_profile, ...]  # granted=1 olan profile'lar
	        }
	      ]
	    }
	"""
	_require_admin("list_capabilities")

	capabilities = frappe.get_all(
		"TH Capability Registry",
		fields=[
			"name",
			"label",
			"description",
			"module_group",
			"default_tier",
			"is_owner_only",
			"is_protected",
			"requires_kyc",
			"requires_aml",
			"plan_feature_flag",
			"is_active",
		],
		order_by="module_group asc, name asc",
		limit_page_length=0,
	)
	# `key` MariaDB reserved kelime — SQL alias yerine post-process rename
	for c in capabilities:
		c["key"] = c.pop("name")

	# Grant matrisini tek query'de çek (N+1'den kaçın)
	from frappe.utils import now_datetime

	all_grants = frappe.db.sql(
		"""
		SELECT capability, role_profile
		FROM `tabTH Capability Grant`
		WHERE granted = 1
		  AND (expires_at IS NULL OR expires_at > %(now)s)
		""",
		{"now": now_datetime()},
		as_dict=True,
	)
	grants_by_cap: dict[str, list[str]] = {}
	for g in all_grants:
		grants_by_cap.setdefault(g["capability"], []).append(g["role_profile"])

	for c in capabilities:
		c["grants"] = grants_by_cap.get(c["key"], [])

	return {"role_profiles": _all_rbac_profiles(), "capabilities": capabilities}


@frappe.whitelist(methods=["POST"])
def update_capability_grant(
	role_profile: str,
	capability: str,
	granted: bool | int | str,
	note: str = "",
) -> dict:
	"""Capability matrix toggle — UI'da bir hücreye tıklanınca çağrılır.

	granted=True   → upsert (yoksa yarat, varsa granted=1 set et)
	granted=False  → varsa sil

	Korumalı capability (is_protected=1) Owner profile'ından çekilemez (fail-secure)."""
	_require_admin("update_capability_grant")

	if not role_profile or not capability:
		frappe.throw(_("role_profile ve capability zorunlu."), frappe.ValidationError)

	if not frappe.db.exists("Role Profile", role_profile):
		frappe.throw(_("Role Profile bulunamadı: {0}").format(role_profile))
	if not frappe.db.exists("TH Capability Registry", capability):
		frappe.throw(_("Capability bulunamadı: {0}").format(capability))

	cap_meta = frappe.db.get_value("TH Capability Registry", capability, ["is_protected"], as_dict=True) or {}

	# "1"/"true"/True hepsi truthy
	granted_bool = str(granted).strip().lower() in ("1", "true", "yes")

	if not granted_bool and cap_meta.get("is_protected") and role_profile == "Seller Full Access":
		frappe.throw(
			_("Korumalı capability Owner'dan çekilemez: {0}").format(capability),
			frappe.PermissionError,
		)

	existing = frappe.db.get_value(
		"TH Capability Grant",
		{"role_profile": role_profile, "capability": capability},
		"name",
	)

	action_label = "noop"
	grant_name: str | None = existing
	if granted_bool:
		if existing:
			from frappe.utils import now_datetime

			frappe.db.set_value(
				"TH Capability Grant",
				existing,
				{
					"granted": 1,
					"note": note or "Console toggle",
					"granted_by": frappe.session.user,
					"granted_at": now_datetime(),
				},
			)
			action_label = "updated"
		else:
			doc = frappe.new_doc("TH Capability Grant")
			doc.role_profile = role_profile
			doc.capability = capability
			doc.granted = 1
			doc.note = note or "Console grant"
			# Süper admin doğrulandı (_require_admin) — controller validate hâlâ
			# çift kayıt + audit alanları için çalışır; bypass yok.
			doc.insert(ignore_permissions=True)
			action_label = "created"
			grant_name = doc.name
	elif existing:
		frappe.delete_doc("TH Capability Grant", existing, ignore_permissions=True, force=1)
		action_label = "deleted"

	# Audit (Faz C — K11)
	log_decision(
		action="permission_console.update_capability_grant",
		decision="ALLOW",
		rule_id="auth.admin_capability_toggle",
		layer="L2",
		object_doctype="TH Capability Grant",
		object_name=grant_name,
		severity="HIGH" if action_label in ("created", "deleted") else "NORMAL",
		context={
			"role_profile": role_profile,
			"capability": capability,
			"granted": granted_bool,
			"action": action_label,
			"is_protected": bool(cap_meta.get("is_protected")),
		},
	)
	return {"action": action_label, "name": grant_name}


@frappe.whitelist()
def list_modules_tree(panel: str = "seller") -> dict:
	"""TH Module Registry tree + policy haritası — ModuleMatrixTab.vue.

	Tree NSM `lft` sırasıyla döner; frontend parent-child ilişkisini
	`parent` field'ından oluşturur.

	Output:
	    {
	      "panel": "seller",
	      "role_profiles": [...],
	      "modules": [
	        {
	          "key": "seller.store",
	          "parent": null,
	          "item_type": "section",
	          "section_key": "store",
	          "label": "Mağazam",
	          "icon": "store",
	          "color": "#7c3aed",
	          "order": 3,
	          "route": "",
	          "doctype_ref": "",
	          "seller_owned": false,
	          "is_active": true,
	          "is_protected": false,
	          "policies": {"Seller Manager": "hidden", ...}
	        }
	      ]
	    }
	"""
	_require_admin("list_modules_tree")

	if panel not in ("seller", "admin", "storefront", "shared"):
		panel = "seller"

	modules = frappe.get_all(
		"TH Module Registry",
		filters={"panel": panel},
		fields=[
			"name",
			"parent_th_module_registry",
			"item_type",
			"section_key",
			"label",
			"icon",
			"color",
			"display_order",
			"route",
			"doctype_ref",
			"seller_owned",
			"is_active",
			"is_protected",
		],
		order_by="lft asc",
		limit_page_length=0,
	)
	# Frontend friendly rename — `key`/`order` MariaDB reserved
	for m in modules:
		m["key"] = m.pop("name")
		m["parent"] = m.pop("parent_th_module_registry")
		m["order"] = m.pop("display_order")

	# Policy haritasını tek query'de çek
	policies_by_module: dict[str, dict[str, str]] = {}
	all_policies = frappe.db.sql(
		"""
		SELECT p.module, p.role_profile, p.mode
		FROM `tabTH Module Policy` p
		INNER JOIN `tabTH Module Registry` r ON r.name = p.module
		WHERE r.panel = %(panel)s
		""",
		{"panel": panel},
		as_dict=True,
	)
	for p in all_policies:
		policies_by_module.setdefault(p["module"], {})[p["role_profile"]] = p["mode"]

	for m in modules:
		m["policies"] = policies_by_module.get(m["key"], {})

	return {"panel": panel, "role_profiles": _all_rbac_profiles(), "modules": modules}


@frappe.whitelist(methods=["POST"])
def update_module_policy(
	module: str,
	role_profile: str,
	mode: str,
	note: str = "",
) -> dict:
	"""Module × Role Profile mode set/upsert/delete.

	mode "visible" + kayıt yoksa → noop (varsayılan visible)
	mode "visible" + kayıt varsa → kaydı sil (varsayılana dön)
	mode "hidden"/"masked" + kayıt yoksa → yarat
	mode "hidden"/"masked" + kayıt varsa → güncelle

	Korumalı modül (is_protected=1) için hidden yapılamaz — fail-secure."""
	_require_admin("update_module_policy")

	if not module or not role_profile or not mode:
		frappe.throw(_("module, role_profile, mode zorunlu."), frappe.ValidationError)

	if mode not in _ALLOWED_MODULE_MODES:
		frappe.throw(
			_("Geçersiz mode: {0}. İzinli: visible, masked, hidden").format(mode),
			frappe.ValidationError,
		)

	if not frappe.db.exists("TH Module Registry", module):
		frappe.throw(_("Modül bulunamadı: {0}").format(module))
	if not frappe.db.exists("Role Profile", role_profile):
		frappe.throw(_("Role Profile bulunamadı: {0}").format(role_profile))

	module_meta = frappe.db.get_value("TH Module Registry", module, ["is_protected"], as_dict=True) or {}
	if module_meta.get("is_protected") and mode == "hidden":
		frappe.throw(
			_("Korumalı modül gizlenemez: {0}").format(module),
			frappe.PermissionError,
		)

	existing = frappe.db.get_value(
		"TH Module Policy",
		{"module": module, "role_profile": role_profile},
		"name",
	)

	action_label = "noop"
	policy_name: str | None = existing
	before_mode = frappe.db.get_value("TH Module Policy", existing, "mode") if existing else None

	if mode == "visible":
		if existing:
			frappe.delete_doc("TH Module Policy", existing, ignore_permissions=True, force=1)
			action_label = "reset_to_default"
	elif existing:
		frappe.db.set_value(
			"TH Module Policy",
			existing,
			{"mode": mode, "note": note or "Console toggle"},
		)
		action_label = "updated"
	else:
		doc = frappe.new_doc("TH Module Policy")
		doc.module = module
		doc.role_profile = role_profile
		doc.mode = mode
		doc.note = note or "Console policy"
		doc.insert(ignore_permissions=True)
		action_label = "created"
		policy_name = doc.name

	# Audit (Faz C — K11)
	log_decision(
		action="permission_console.update_module_policy",
		decision="ALLOW",
		rule_id="auth.admin_module_policy_toggle",
		layer="L2",
		object_doctype="TH Module Policy",
		object_name=policy_name,
		severity="HIGH" if mode == "hidden" or action_label == "reset_to_default" else "NORMAL",
		context={
			"module": module,
			"role_profile": role_profile,
			"before_mode": before_mode,
			"after_mode": mode,
			"action": action_label,
			"is_protected": bool(module_meta.get("is_protected")),
		},
	)
	return {"action": action_label, "name": policy_name}


@frappe.whitelist()
def list_plan_capability_sync() -> dict:
	"""Sprint 5 — Plan kapısı tutarlılığı.

	Her capability için (plan_feature_flag'i olan) hangi subscription_plan'da
	enabled olup olmadığını döner. UI tutarsızlık uyarısı için kullanır.

	Output:
	    {
	      "plans": ["FREE", "STARTER", "PRO", "ENTERPRISE"],
	      "capabilities": [
	        {
	          "key": "rfq.quote",
	          "plan_feature_flag": "feature.rfq_module",
	          "plan_status": {"FREE": false, "STARTER": false, "PRO": true, "ENTERPRISE": true},
	          "is_consistent": true,           # En az 1 plan'da enabled
	          "is_unsynced": false,            # Hiçbir plan'da yok (kritik uyarı)
	          "plans_enabled": ["PRO", "ENTERPRISE"],
	          "plans_missing": ["FREE", "STARTER"]
	        }
	      ],
	      "stats": {
	        "total_plan_gated": 2,
	        "unsynced_count": 2,
	        "fully_synced_count": 0
	      }
	    }
	"""
	_require_admin("list_plan_capability_sync")

	plans = frappe.get_all(
		"Subscription Plan",
		filters={"is_active": 1},
		fields=["plan_code", "plan_name", "capability_flags"],
		order_by="display_order asc",
	)

	# Plan başına decoded flags dict — JSON parse bir kere
	plan_flags: dict[str, dict] = {}
	plan_codes: list[str] = []
	for p in plans:
		plan_codes.append(p["plan_code"])
		raw = p.get("capability_flags") or "{}"
		try:
			plan_flags[p["plan_code"]] = json.loads(raw) if isinstance(raw, str) else (raw or {})
		except (ValueError, TypeError):
			plan_flags[p["plan_code"]] = {}

	# Sadece plan_feature_flag taşıyan capability'ler — tutarlılık konusu
	plan_gated_caps = frappe.get_all(
		"TH Capability Registry",
		filters={"plan_feature_flag": ["!=", ""], "is_active": 1},
		fields=["name", "label", "plan_feature_flag"],
		order_by="name asc",
	)

	result_caps: list[dict] = []
	unsynced_count = 0
	fully_synced_count = 0

	for cap in plan_gated_caps:
		feature_key = cap["plan_feature_flag"]
		plan_status: dict[str, bool] = {}
		plans_enabled: list[str] = []
		plans_missing: list[str] = []
		for pc in plan_codes:
			enabled = bool(plan_flags.get(pc, {}).get(feature_key, False))
			plan_status[pc] = enabled
			if enabled:
				plans_enabled.append(pc)
			else:
				plans_missing.append(pc)

		is_unsynced = len(plans_enabled) == 0
		is_consistent = not is_unsynced

		if is_unsynced:
			unsynced_count += 1
		if not plans_missing:
			fully_synced_count += 1

		result_caps.append(
			{
				"key": cap["name"],
				"label": cap["label"],
				"plan_feature_flag": feature_key,
				"plan_status": plan_status,
				"is_consistent": is_consistent,
				"is_unsynced": is_unsynced,
				"plans_enabled": plans_enabled,
				"plans_missing": plans_missing,
			}
		)

	return {
		"plans": plan_codes,
		"capabilities": result_caps,
		"stats": {
			"total_plan_gated": len(plan_gated_caps),
			"unsynced_count": unsynced_count,
			"fully_synced_count": fully_synced_count,
		},
	}


@frappe.whitelist(methods=["POST"])
def update_plan_capability_flag(
	plan_codes,
	feature_flag: str,
	enabled: bool | int | str,
) -> dict:
	"""Sprint 5 — Subscription Plan capability_flags JSON'ında feature flag'i set/unset.

	Args:
	    plan_codes: Tekil string (PRO) veya JSON array string ("['PRO','ENTERPRISE']")
	    feature_flag: "feature.rfq_module" gibi capability_key
	    enabled: True → flag=true; False → flag=false

	Returns:
	    {"updated": [plan_code, ...], "feature_flag": str, "enabled": bool}

	Side effects:
	  - Plan kayıtları save edilir → Subscription Plan controller doğrulama tetikler
	  - Entitlement Redis cache flush (her store için bu feature yeniden hesaplanır)

	Korumalı: System Manager / Marketplace Admin gerekir.
	"""
	_require_admin("update_plan_capability_flag")

	if not feature_flag:
		frappe.throw(_("feature_flag zorunlu."), frappe.ValidationError)

	# plan_codes parse
	if isinstance(plan_codes, str):
		s = plan_codes.strip()
		if s.startswith("["):
			try:
				plan_codes = json.loads(s)
			except (ValueError, TypeError):
				frappe.throw(_("Geçersiz plan_codes JSON."), frappe.ValidationError)
		else:
			plan_codes = [s]
	if not isinstance(plan_codes, list) or not plan_codes:
		frappe.throw(_("En az bir plan_code gerekir."), frappe.ValidationError)

	enabled_bool = str(enabled).strip().lower() in ("1", "true", "yes")

	updated: list[str] = []
	missing: list[str] = []

	for code in plan_codes:
		if not frappe.db.exists("Subscription Plan", code):
			missing.append(code)
			continue

		plan = frappe.get_doc("Subscription Plan", code)
		raw = plan.capability_flags or "{}"
		try:
			flags = json.loads(raw) if isinstance(raw, str) else (raw or {})
		except (ValueError, TypeError):
			flags = {}
		if not isinstance(flags, dict):
			flags = {}

		flags[feature_flag] = enabled_bool
		plan.capability_flags = json.dumps(flags, sort_keys=True)
		plan.flags.ignore_permissions = True
		plan.save(ignore_permissions=True)
		updated.append(code)

	# Entitlement Redis cache flush — store başına capability_flags yeniden hesaplanır
	try:
		frappe.cache().delete_keys("tradehub:entitlement:")
	except Exception:
		frappe.log_error("entitlement cache flush failed", "update_plan_capability_flag")

	# Capability resolver cache de etkilenmiş olabilir (plan_allows kullanıyor)
	try:
		from tradehub_core.utils.permission_resolver import flush_all_cache

		flush_all_cache()
	except Exception:
		pass

	frappe.db.commit()

	# Audit (Faz C — K11)
	log_decision(
		action="permission_console.update_plan_capability_flag",
		decision="ALLOW",
		rule_id="auth.admin_plan_flag_toggle",
		layer="L0",
		object_doctype="Subscription Plan",
		object_name=None,
		severity="HIGH",
		context={
			"feature_flag": feature_flag,
			"enabled": enabled_bool,
			"updated_plans": updated,
			"missing_plans": missing,
		},
	)

	return {
		"updated": updated,
		"missing": missing,
		"feature_flag": feature_flag,
		"enabled": enabled_bool,
	}


@frappe.whitelist()
def list_rbac_audit(limit: int = 50) -> dict:
	"""TH Capability + Module değişikliklerinin audit akışı.

	Kaynak: Frappe Version (track_changes=1 olan 4 DocType için).

	Output:
	    {
	      "entries": [
	        {timestamp, actor, target_doctype, target_name, summary, source}
	      ],
	      "count": N
	    }
	"""
	_require_admin("list_rbac_audit")

	try:
		limit_int = max(1, min(int(limit), 200))
	except (ValueError, TypeError):
		limit_int = 50

	versions = frappe.db.sql(
		"""
		SELECT name, ref_doctype, docname, owner, creation
		FROM `tabVersion`
		WHERE ref_doctype IN (
		    'TH Capability Registry',
		    'TH Capability Grant',
		    'TH Module Registry',
		    'TH Module Policy'
		)
		ORDER BY creation DESC
		LIMIT %(limit)s
		""",
		{"limit": limit_int},
		as_dict=True,
	)

	entries = [
		{
			"timestamp": v["creation"],
			"actor": v["owner"],
			"target_doctype": v["ref_doctype"],
			"target_name": v["docname"],
			"summary": f"{v['ref_doctype']}: {v['docname']}",
			"source": "Version",
		}
		for v in versions
	]

	# Sprint 5 — FIELD_MASKED entries (rate-limited mask events).
	# Authorization Decision Log'daki "pii.field_masked" action'ları toplanır.
	try:
		mask_events = frappe.db.sql(
			"""
			SELECT name, timestamp, actor, object_doctype, object_name, rule_id, context
			FROM `tabAuthorization Decision Log`
			WHERE action = %(action)s AND decision = %(decision)s
			ORDER BY timestamp DESC
			LIMIT %(limit)s
			""",
			{
				"action": "pii.field_masked",
				"decision": "FIELD_MASKED",
				"limit": limit_int,
			},
			as_dict=True,
		)
		for e in mask_events:
			# context JSON içinde masked_fields var
			masked_fields_str = ""
			try:
				ctx = json.loads(e.get("context") or "{}") if e.get("context") else {}
				masked_fields = ctx.get("masked_fields") or []
				if masked_fields:
					masked_fields_str = ", ".join(masked_fields)
			except (ValueError, TypeError):
				masked_fields_str = ""

			summary = f"{e['object_doctype']}/{e['object_name']}"
			if masked_fields_str:
				summary += f" — maskeli: {masked_fields_str}"

			entries.append(
				{
					"timestamp": e["timestamp"],
					"actor": e["actor"],
					"target_doctype": e["object_doctype"],
					"target_name": e["object_name"],
					"summary": summary,
					"source": "FieldMask",
				}
			)
	except Exception:
		# Authorization Decision Log opsiyonel — yoksa sessizce devam
		pass

	# Karışık entries'i timestamp'e göre yeniden sırala + limit'le
	entries.sort(key=lambda x: x["timestamp"], reverse=True)
	entries = entries[:limit_int]

	return {"entries": entries, "count": len(entries)}
