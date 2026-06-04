"""Sprint 3 RBAC — Seller Owner rolü backfill.

Sorun:
  seller_application._approve_application Sprint 2 akışında User'a sadece
  "Seller" rolünü ekliyordu (kod yorumu: "Sprint 3'te Seller Owner'a geçecek").
  Bu yüzden tüm mevcut Active ASP sahipleri "Seller Owner" rolü olmadan
  geziyor; auth.is_owner çift kapısı (tradehub_is_owner=1 AND "Seller Owner"
  in roles) tutmuyor → admin-panel sidebar'da KYB Doğrulama / Ekibim /
  Mağaza Ayarları gizli kalıyor (data: ali.bal/SEL-00002 — Suspended,
  bora.aydeger/SEL-00001 — Active fakat manuel rolle düzeltilmiş).

Çözüm (sadece Active ASP'ler için, fail-secure):
  1. ASP Active ise → user'a Seller + Seller Owner rolleri (idempotent),
     tradehub_is_owner=1, tradehub_tenant=ASP.name (NULL ise),
     role_profile_name="Seller Full Access" (boşsa).
  2. ASP Suspended/Blocked olanlara dokunma — gerçek bir revoke yaşanmış
     olabilir; tutarlılık için ayrıca _revoke_approval düzeltildi.

İdempotent: rolleri/flag'leri tekrar tekrar set etmek güvenli.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	active_owners = frappe.get_all(
		"Admin Seller Profile",
		filters={"status": "Active"},
		fields=["name", "user"],
	)

	updated_users: list[str] = []
	skipped_no_user: list[str] = []
	already_consistent: list[str] = []

	for asp in active_owners:
		user = asp.get("user")
		asp_name = asp.get("name")
		if not user or not frappe.db.exists("User", user):
			skipped_no_user.append(asp_name)
			continue

		current_roles = set(frappe.get_roles(user))
		missing_roles = [r for r in ("Seller", "Seller Owner") if r not in current_roles]

		user_row = (
			frappe.db.get_value(
				"User",
				user,
				["tradehub_is_owner", "tradehub_tenant", "role_profile_name"],
				as_dict=True,
			)
			or {}
		)
		updates: dict[str, object] = {}
		if not user_row.get("tradehub_is_owner"):
			updates["tradehub_is_owner"] = 1
		if not user_row.get("tradehub_tenant"):
			updates["tradehub_tenant"] = asp_name
		if not user_row.get("role_profile_name"):
			updates["role_profile_name"] = "Seller Full Access"

		if not missing_roles and not updates:
			already_consistent.append(user)
			continue

		if missing_roles:
			user_doc = frappe.get_doc("User", user)
			user_doc.add_roles(*missing_roles)

		if updates:
			frappe.db.set_value("User", user, updates, update_modified=False)

		updated_users.append(user)

	frappe.db.commit()

	return {
		"updated": updated_users,
		"already_consistent": already_consistent,
		"skipped_no_user": skipped_no_user,
		"total_active_asp": len(active_owners),
	}
