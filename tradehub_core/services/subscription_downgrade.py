# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Subscription plan downgrade — sub-user role profile sync.

Plan değiştiğinde (özellikle downgrade), yeni plan'ın `capability_flags`'inde
artık desteklenmeyen role profilindeki sub-user'lar bir alt-tier'a düşürülür.
Pricing vaadi ile uyumlu çalışma sağlar:
  PRO → STARTER: Co-Owner kullanıcıları Manager'a düşer (eğer Manager destekleniyorsa)
  STARTER → FREE: Manager + Operations + Finance Staff kullanıcıları pasifleşir
  ENTERPRISE → PRO: custom role profilleri standard'a düşer

Owner asla bu hook'tan etkilenmez (is_owner=1 user'lar profil değişmez).

Audit: her downgrade Role Change Log'a yazılır (log_role_change).
"""

from __future__ import annotations

import frappe

# Tier hierarchy — alt-tier downgrade için.
# Bir profile artık plan'da desteklenmiyorsa, listedeki sıralı alt-tier'lardan
# ilk desteklenen seçilir. Hiçbiri desteklenmiyorsa kullanıcı pasifleştirilir.
_DOWNGRADE_CHAIN: dict[str, list[str]] = {
	"Seller Full Access": ["Seller Co-Owner", "Seller Manager", "Seller Operations"],
	"Seller Co-Owner": ["Seller Manager", "Seller Operations"],
	"Seller Manager": ["Seller Operations"],
	# Finance Staff ve Operations dengeli iki uzman role — birbirine downgrade olmaz.
	# Plan'da yoksa pasifleştir.
	"Seller Operations": [],
	"Seller Finance Staff": [],
}


def _plan_supports_profile(plan_doc, role_profile: str) -> bool:
	"""Plan'ın capability_flags'inde verilen role profile feature key'i true mu?

	Profile name → feature key dönüşümü: 'Seller Co-Owner' → 'feature.role.profile.seller_co_owner'.
	"""
	if not plan_doc:
		return False

	code = role_profile.lower().replace(" ", "_").replace("-", "_")
	feature_key = f"feature.role.profile.{code}"

	# capability_flags JSON field
	flags_raw = plan_doc.get("capability_flags") if hasattr(plan_doc, "get") else None
	if not flags_raw:
		return False

	import json

	try:
		flags = json.loads(flags_raw) if isinstance(flags_raw, str) else flags_raw
	except (ValueError, TypeError):
		return False

	return bool(flags.get(feature_key))


def _find_supported_alt_profile(plan_doc, original_profile: str) -> str | None:
	"""Plan'da desteklenmeyen role profile için downgrade chain'de ilk
	desteklenen alt-tier'ı bul. Hiçbiri yoksa None döner (pasifleştir)."""
	chain = _DOWNGRADE_CHAIN.get(original_profile, [])
	for alt in chain:
		if _plan_supports_profile(plan_doc, alt):
			return alt
	return None


def apply_role_downgrade_for_plan_change(
	store: str,
	new_plan_name: str,
) -> dict:
	"""Plan değişikliğinden sonra mağazanın sub-user'larını yeni plan'a göre
	sync et.

	Args:
	    store: Admin Seller Profile.name (tenant)
	    new_plan_name: Yeni Subscription Plan.name

	Returns:
	    {downgraded: [...], deactivated: [...], unchanged: [...]}
	"""
	plan_doc = frappe.get_doc("Subscription Plan", new_plan_name)

	# Bu tenant'taki tüm sub-user'lar (Owner hariç)
	sub_users = frappe.get_all(
		"User",
		filters={
			"tradehub_tenant": store,
			"enabled": 1,
			"tradehub_is_owner": 0,
		},
		fields=["name", "role_profile_name"],
	)

	downgraded: list[dict] = []
	deactivated: list[dict] = []
	unchanged: list[str] = []

	for sub in sub_users:
		profile = sub.role_profile_name
		if not profile:
			unchanged.append(sub.name)
			continue

		# Plan bu profili destekliyorsa dokunma
		if _plan_supports_profile(plan_doc, profile):
			unchanged.append(sub.name)
			continue

		# Plan desteklemiyor → alt-tier ara
		alt = _find_supported_alt_profile(plan_doc, profile)
		if alt:
			_apply_profile_change(sub.name, profile, alt, reason=f"Plan downgrade: {new_plan_name}")
			downgraded.append({"user": sub.name, "from": profile, "to": alt})
		else:
			_deactivate_user(sub.name, reason=f"Plan downgrade: {new_plan_name} bu role'ü desteklemiyor")
			deactivated.append({"user": sub.name, "from": profile})

	return {
		"store": store,
		"new_plan": new_plan_name,
		"downgraded": downgraded,
		"deactivated": deactivated,
		"unchanged": unchanged,
	}


def _apply_profile_change(user: str, old_profile: str, new_profile: str, reason: str) -> None:
	"""User'ın role_profile_name'ini değiştir + audit log."""
	# User.save() ile değiştir (Has Role sync için)
	user_doc = frappe.get_doc("User", user)
	user_doc.role_profile_name = new_profile
	# Notification Settings vb. owner-only doc'lara erişim için global flag
	prev_flag = frappe.flags.ignore_permissions
	frappe.flags.ignore_permissions = True
	try:
		user_doc.save(ignore_permissions=True)
	finally:
		frappe.flags.ignore_permissions = prev_flag

	# Audit
	try:
		from tradehub_core.audit import log_role_change

		log_role_change(
			target_user=user,
			change_type="plan_downgrade_profile_change",
			tenant=user_doc.tradehub_tenant,
			before_role_profiles=[old_profile],
			after_role_profiles=[new_profile],
			reason=reason,
		)
	except Exception as exc:  # noqa: BLE001 — audit kritik değil
		frappe.log_error(f"plan_downgrade audit fail: {exc}", "subscription_downgrade")


def _deactivate_user(user: str, reason: str) -> None:
	"""Sub-user'ı pasifleştir + tam session/cache temizliği + audit. K8 fix."""
	user_doc = frappe.get_doc("User", user)
	user_doc.enabled = 0
	prev_flag = frappe.flags.ignore_permissions
	frappe.flags.ignore_permissions = True
	try:
		user_doc.save(ignore_permissions=True)
	finally:
		frappe.flags.ignore_permissions = prev_flag

	# K8: tam session + cache + API token temizliği (race window kapat)
	from tradehub_core.utils.user_lifecycle import purge_user_sessions_and_caches

	purge_user_sessions_and_caches(user)

	try:
		from tradehub_core.audit import log_role_change

		log_role_change(
			target_user=user,
			change_type="plan_downgrade_deactivate",
			tenant=user_doc.tradehub_tenant,
			reason=reason,
		)
	except Exception as exc:  # noqa: BLE001
		frappe.log_error(f"plan_downgrade audit fail: {exc}", "subscription_downgrade")


def is_downgrade(old_plan: str | None, new_plan: str) -> bool:
	"""Plan değişikliği bir downgrade mı? (Bilinen plan tier ordering'i ile)

	Tier order: FREE < STARTER < PRO < ENTERPRISE
	Bilinmeyen plan adları için False (sadece bilinen downgrade'leri yakala).
	"""
	if not old_plan or old_plan == new_plan:
		return False

	tier_order = {"FREE": 0, "STARTER": 1, "PRO": 2, "ENTERPRISE": 3}
	old_tier = tier_order.get(old_plan.upper())
	new_tier = tier_order.get(new_plan.upper())
	if old_tier is None or new_tier is None:
		# Bilinmeyen plan adı — sub-user'lara dokunmayalım (riskli)
		return False
	return new_tier < old_tier
