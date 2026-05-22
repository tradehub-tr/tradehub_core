"""FAZ 5.4 — Role Profile içeriklerini DB'ye seed et + mevcut User'ların rollerini sync et.

Sorun:
  - role_profile.json fixture'da 15 Role Profile tanımlı (Seller Co-Owner,
    Buyer Approver L2, vs.) ama fixture sync child table'larını (Has Role)
    DB'ye yazmamış. tabHas Role parent="Seller Finance Staff" boş.
  - Frappe User.role_profile_name set edilmiş ama Role Profile boş olduğu için
    User.roles'a hiç rol eklenmiyor. Sub-user backend tarafında tenant'ı görür
    (`tradehub_tenant` field) ama Frappe ACL seviyesinde rol yok → bazı
    endpoint çağrılarında session inconsistency, intermittent "Satıcı profili
    bulunamadı" hatası.

Çözüm:
  1. role_profile.json'u oku, her Role Profile için DB'de doc oluştur/güncelle
     (child table Has Role satırları dahil).
  2. role_profile_name set edilmiş User'lar için User.roles'u Role Profile'a
     göre yeniden senkronize et (frappe Document.save() with update_roles=True
     hook'unu zorla tetikle).

İdempotent.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe


def execute() -> dict:
	# 1. Role Profile fixture'ını yükle
	fixture_path = Path(frappe.get_app_path("tradehub_core")) / "tradehub_core" / "fixtures" / "role_profile.json"
	if not fixture_path.exists():
		return {"error": f"fixture missing: {fixture_path}"}

	with open(fixture_path) as f:
		fixtures = json.load(f)

	profiles_synced: list[str] = []
	users_synced: list[str] = []
	skipped_roles: set[str] = set()

	for rp_data in fixtures:
		rp_name = rp_data.get("name") or rp_data.get("role_profile")
		if not rp_name:
			continue

		# Önce missing rolleri filtrele (DB'de var olmayan rol → atla)
		desired_roles: list[str] = []
		for r in rp_data.get("roles", []):
			role_name = r.get("role")
			if not role_name:
				continue
			if not frappe.db.exists("Role", role_name):
				skipped_roles.add(role_name)
				continue
			desired_roles.append(role_name)

		if not desired_roles:
			continue

		# Mevcut Role Profile var mı?
		if frappe.db.exists("Role Profile", rp_name):
			rp = frappe.get_doc("Role Profile", rp_name)
		else:
			rp = frappe.new_doc("Role Profile")
			rp.role_profile = rp_name

		# Child table'ı temizle + yeniden ekle
		existing = {r.role for r in (rp.roles or [])}
		desired = set(desired_roles)
		if existing != desired:
			rp.roles = []
			for role_name in desired_roles:
				rp.append("roles", {"role": role_name})
			rp.save(ignore_permissions=True)
			profiles_synced.append(rp_name)

	frappe.db.commit()

	# 2. role_profile_name set edilmiş User'ların rollerini yeniden sync
	users_with_profile = frappe.get_all(
		"User",
		filters={"role_profile_name": ["!=", ""], "enabled": 1},
		fields=["name", "role_profile_name"],
	)
	for u in users_with_profile:
		rp_name = u.role_profile_name
		if not rp_name or not frappe.db.exists("Role Profile", rp_name):
			continue
		try:
			user_doc = frappe.get_doc("User", u.name)
			# Frappe User.update_roles_after_save hook'u role_profile değişirse roller'u günceller.
			# Burada explicit sync için role_profile'daki rolleri user.roles'a merge et.
			rp = frappe.get_doc("Role Profile", rp_name)
			rp_roles = {r.role for r in (rp.roles or [])}
			current = {r.role for r in (user_doc.roles or [])}
			missing = rp_roles - current
			if missing:
				for role in missing:
					user_doc.append("roles", {"role": role})
				user_doc.save(ignore_permissions=True)
				users_synced.append(u.name)
		except Exception as exc:
			frappe.log_error(
				f"role sync failed for {u.name}: {exc}", "v15_5_4_sync_role_profiles"
			)

	frappe.db.commit()
	frappe.clear_cache()

	return {
		"profiles_synced": profiles_synced,
		"profiles_count": len(profiles_synced),
		"users_synced": users_synced,
		"users_count": len(users_synced),
		"skipped_roles_not_in_db": sorted(skipped_roles),
	}
