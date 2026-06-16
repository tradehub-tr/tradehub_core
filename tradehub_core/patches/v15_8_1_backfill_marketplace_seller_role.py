# Copyright (c) 2026, TradeHub Team and contributors

"""Magaza sahiplerine (Seller Full Access role profile) `Marketplace Seller`
rolunu kalici olarak ver.

SORUN: `Marketplace Seller` 44 doctype'in temel rol-seviyesi veri-erisim kapisi
(Bulk Import Job, Listing, CRM ...). Magaza sahibi user'lar `role_profile_name =
"Seller Full Access"` ile yonetiliyor ve `User.save` rolleri profile'a gore
RESETLIYOR. Profile'da Marketplace Seller olmadigi icin `add_roles(...)` her
save'de siliniyordu (seller_role_sync hook'u bu yuzden bu user'larda etkisiz).
Sonuc: magaza sahipleri "does not have doctype access via role permission for
Bulk Import Job" aliyordu.

COZUM (iki katman):
  1. Rolu "Seller Full Access" Role Profile'ina ekle -> kaynak dogruluk; gelecekteki
     User.save profile-sync'lerinde rol KORUNUR.
  2. Mevcut owner user'lara Has Role satirini DOGRUDAN ekle (parent User'i save
     ETMEDEN) -> user_type'i bozmaz (Marketplace Seller desk_access=1; full save
     Website User'i System User'a cevirebilir). seed `_grant_verified_seller_role`
     ile ayni kanitlanmis yontem.

Idempotent: var olan rol/satir atlanir. Role Profile child'i dogrudan eklenir,
parent save edilmez -> Role Profile.on_update cascade'i (toplu user resync /
user_type flip) tetiklenmez.
"""

from __future__ import annotations

import frappe

ROLE = "Marketplace Seller"
OWNER_PROFILE = "Seller Full Access"


def _ensure_has_role(parent: str, parenttype: str) -> bool:
	"""parent (User ya da Role Profile) icin ROLE Has Role satirini garanti et.

	Returns: yeni eklendiyse True, zaten varsa False.
	"""
	if frappe.db.exists(
		"Has Role", {"parent": parent, "parenttype": parenttype, "role": ROLE}
	):
		return False
	frappe.get_doc(
		{
			"doctype": "Has Role",
			"parenttype": parenttype,
			"parentfield": "roles",
			"parent": parent,
			"role": ROLE,
		}
	).insert(ignore_permissions=True)
	return True


def execute() -> None:
	if not frappe.db.exists("Role", ROLE):
		return

	# 1) Role Profile'a ekle (kalici kaynak)
	if frappe.db.exists("Role Profile", OWNER_PROFILE):
		_ensure_has_role(OWNER_PROFILE, "Role Profile")

	# 2) Bu profili kullanan tum user'lara dogrudan ekle (user_type'i bozmadan)
	users = frappe.get_all(
		"User", filters={"role_profile_name": OWNER_PROFILE}, pluck="name"
	)
	granted = 0
	for user in users:
		if user in ("Guest", "Administrator"):
			continue
		if _ensure_has_role(user, "User"):
			frappe.clear_cache(user=user)
			granted += 1

	frappe.db.commit()
	frappe.logger().info(
		f"backfill_marketplace_seller_role: '{OWNER_PROFILE}' profiline rol eklendi, "
		f"{granted} magaza sahibi user'a verildi"
	)
