"""G0 rol matrisi — Seller Logistics rolünü satıcı Role Profile'larına bağlar.

Sorun:
	"Seller Logistics" rolü Shipment DocPerm'inde (read) tanımlıydı ama hiçbir
	Role Profile'a atanmamıştı — satıcı fiilen hiçbir sevkiyat kaydını
	listeleyemiyordu (full audit P3 açık kararı). G0 kararı (K2): yeni rol
	AÇILMAZ, mevcut satıcı profillerine bu rol bağlanır; tenant sınırını
	DocPerm değil `shipment_query_conditions` (seller_profile) çizer.

Çözüm:
	1) "Seller Logistics" Role kaydı yoksa oluşturulur (desk erişimsiz).
	2) Fixture'la aynı 4 profile Has Role satırı eklenir: Seller Full Access,
	   Seller Co-Owner, Seller Manager, Seller Operations. Finance Staff ve
	   Viewer-only profilleri BİLİNÇLİ dışarıda — operasyon rolü değiller.
	3) Profil değişikliği MEVCUT kullanıcılara elle yansıtılır: Frappe, Role
	   Profile güncellemesini bağlı kullanıcılara otomatik itmiyor (ölçüldü:
	   ali.bal profili Seller Full Access'ken rol listesine düşmedi) — profili
	   taşıyan her kullanıcıya rol satırı eklenir.

	Fixture (role_profile.json) aynı turda güncellendi; bu patch fixture'ın
	dokunamadığı MEVCUT siteler için. İdempotent.
"""

from __future__ import annotations

import frappe

_ROLE = "Seller Logistics"

_TARGET_PROFILES: tuple[str, ...] = (
	"Seller Full Access",
	"Seller Co-Owner",
	"Seller Manager",
	"Seller Operations",
)


def execute() -> dict:
	if not frappe.db.exists("Role", _ROLE):
		role = frappe.new_doc("Role")
		role.role_name = _ROLE
		role.desk_access = 0
		role.flags.ignore_permissions = True
		role.insert(ignore_permissions=True)
		role_action = "role_created"
	else:
		role_action = "role_exists"

	added: list[str] = []
	skipped: list[str] = []
	missing: list[str] = []

	for profile_name in _TARGET_PROFILES:
		if not frappe.db.exists("Role Profile", profile_name):
			missing.append(profile_name)
			continue

		profile = frappe.get_doc("Role Profile", profile_name)
		if any(row.role == _ROLE for row in profile.roles):
			skipped.append(profile_name)
			continue

		profile.append("roles", {"role": _ROLE})
		profile.flags.ignore_permissions = True
		profile.save(ignore_permissions=True)
		added.append(profile_name)

	if missing:
		frappe.log_error(
			f"Seller Logistics atanamadı, Role Profile yok: {missing}",
			"v15_9_21_g0_seller_logistics_role_assignment",
		)

	synced_users = _sync_profile_users()

	frappe.db.commit()
	return {
		"role": role_action,
		"added": added,
		"skipped": skipped,
		"missing": missing,
		"synced_users": synced_users,
	}


def _sync_profile_users() -> list[str]:
	"""Hedef profilleri taşıyan kullanıcılara rolü doğrudan ekler.

	Sistem bakım yolu, kullanıcı girdisi akmıyor — ignore_permissions bu
	yüzden güvenli.
	"""
	synced: list[str] = []
	users = frappe.get_all(
		"User",
		filters={"role_profile_name": ["in", list(_TARGET_PROFILES)], "enabled": 1},
		pluck="name",
	)
	for name in users:
		if frappe.db.exists("Has Role", {"parenttype": "User", "parent": name, "role": _ROLE}):
			continue
		user = frappe.get_doc("User", name)
		user.append("roles", {"role": _ROLE})
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)
		synced.append(name)
	return synced
