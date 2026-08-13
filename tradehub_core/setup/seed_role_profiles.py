"""Eksik role profile'ları fixture'tan oku ve DB'ye seed et.

Frappe v15 fixture sync sub-user invite akışında çağrılmadığı için manuel.

DİKKAT — fixture tuzağı:
`hooks.py` içindeki `fixtures` listesinde `Role Profile` YOK. Yani
`tradehub_core/fixtures/role_profile.json`'a yeni bir profil eklemek tek başına
hiçbir şey yapmaz; dosyayı DB'ye taşıyan tek mekanizma patch'lerdir ve uygulanmış
bir patch Patch Log yüzünden tekrar çalışmaz. Yeni profil eklerken
`seed_role_profiles_by_name()` çağıran YENİ bir patch yaz.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable

import frappe

FIXTURE_RELATIVE_PATH = ("tradehub_core", "fixtures", "role_profile.json")


def _load_role_profile_fixture() -> list[dict]:
	"""role_profile.json içeriğini döndürür."""
	fixture_path = os.path.join(frappe.get_app_path("tradehub_core"), *FIXTURE_RELATIVE_PATH)
	with open(fixture_path) as f:
		return json.load(f)


def seed_role_profiles_by_name(profile_names: Iterable[str]) -> dict:
	"""Yalnız adı verilen Role Profile'ları fixture'tan okuyup DB'ye yazar.

	`execute()`'dan farkı: tüm fixture'ı değil, yalnız istenen profilleri işler ve
	Role tablosuna dokunmaz. Bir modülün kendi rol profillerini seed etmesi için.

	İdempotent: var olan profile dokunmaz. Atlanan her kayıt için gerekçe döner —
	sessiz `continue` yok, çağıran patch sonucu loglayabilsin.

	Args:
		profile_names: Oluşturulacak Role Profile adları.

	Returns:
		created / skipped_existing / missing_in_fixture / missing_roles anahtarlı rapor.
	"""
	wanted = list(profile_names)
	fixture_by_name = {
		(row.get("name") or row.get("role_profile")): row for row in _load_role_profile_fixture()
	}

	created: list[str] = []
	skipped_existing: list[str] = []
	missing_in_fixture: list[str] = []
	missing_roles: dict[str, list[str]] = {}

	for name in wanted:
		if frappe.db.exists("Role Profile", name):
			skipped_existing.append(name)
			continue

		row = fixture_by_name.get(name)
		if not row:
			missing_in_fixture.append(name)
			continue

		# Fixture'da referans edilen ama DB'de olmayan rol, Role Profile'ı sessizce
		# boş bırakır — bu durumu rapora taşı ki çağıran görebilsin.
		absent = [
			r["role"]
			for r in row.get("roles", [])
			if r.get("role") and not frappe.db.exists("Role", r["role"])
		]
		if absent:
			missing_roles[name] = absent

		doc = frappe.new_doc("Role Profile")
		doc.role_profile = row.get("role_profile") or name
		for role_row in row.get("roles", []):
			role_name = role_row.get("role")
			if role_name and frappe.db.exists("Role", role_name):
				doc.append("roles", {"role": role_name})
		doc.insert(ignore_permissions=True)  # Sistem seed'i, kullanıcı akışı değil
		created.append(name)

	return {
		"created": created,
		"skipped_existing": skipped_existing,
		"missing_in_fixture": missing_in_fixture,
		"missing_roles": missing_roles,
	}


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
