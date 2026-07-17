"""Eksik role profile'ları fixture'tan oku ve DB'ye seed et.

Frappe v15 fixture sync sub-user invite akışında çağrılmadığı için manuel.
"""

from __future__ import annotations

import json
import os

import frappe


def execute() -> dict:
	"""role_profile.json fixture'ını DB'ye yükle. Eksik rolleri de ekle."""
	app_path = frappe.get_app_path("tradehub_core")
	fixture_path = os.path.join(app_path, "tradehub_core", "fixtures", "role_profile.json")
	role_path = os.path.join(app_path, "tradehub_core", "fixtures", "role.json")

	# Önce eksik rolleri seed et
	created_roles = []
	skipped_roles = []
	with open(role_path) as f:
		roles = json.load(f)
	for r in roles:
		role_name = r.get("name") or r.get("role_name")
		if not role_name or frappe.db.exists("Role", role_name):
			skipped_roles.append(role_name)
			continue
		try:
			doc = frappe.new_doc("Role")
			for k, v in r.items():
				if k == "doctype":
					continue
				setattr(doc, k, v)
			doc.insert(ignore_permissions=True)
			created_roles.append(role_name)
		except Exception as exc:
			frappe.log_error(f"Role seed failed for {role_name}: {exc}", "seed_role_profiles")

	# Rol profile'larını yükle
	created_profiles = []
	skipped_profiles = []
	failed_profiles = []
	with open(fixture_path) as f:
		profiles = json.load(f)

	for p in profiles:
		name = p["name"]
		if frappe.db.exists("Role Profile", name):
			skipped_profiles.append(name)
			continue
		try:
			doc = frappe.new_doc("Role Profile")
			doc.role_profile = p.get("role_profile") or name
			# Child rolleri ekle — sadece DB'de var olan roller
			for role_row in p.get("roles", []):
				rname = role_row.get("role")
				if rname and frappe.db.exists("Role", rname):
					doc.append("roles", {"role": rname})
			doc.insert(ignore_permissions=True)
			created_profiles.append(name)
		except Exception as exc:
			failed_profiles.append({"name": name, "error": str(exc)})

	frappe.db.commit()
	return {
		"roles_created": created_roles,
		"roles_skipped": skipped_roles,
		"profiles_created": created_profiles,
		"profiles_skipped": skipped_profiles,
		"profiles_failed": failed_profiles,
	}


def reset_user_password(email: str, new_password: str = "Bora1234!") -> dict:
	"""Hızlı: bir kullanıcının şifresini reset et (test için)."""
	# F-010: Production guard
	site_name = getattr(frappe.local, "site", "")
	if site_name and not (site_name.endswith(".localhost") or site_name.endswith(".local")):
		return {"error": "Bu fonksiyon yalnızca .localhost/.local sitelerde çalışabilir"}
	if not frappe.db.exists("User", email):
		return {"error": f"User {email} bulunamadı"}
	from frappe.utils.password import update_password

	update_password(email, new_password)
	frappe.db.commit()
	# F-010: Şifreyi response'da döndürme
	return {"ok": True, "user": email}
