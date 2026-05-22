"""Bir kullanıcıya rol ekle (geçici test helper'ı)."""

import frappe


def add_role_to_user(email: str, role: str) -> dict:
	if not frappe.db.exists("User", email):
		return {"error": f"User {email} yok"}
	if not frappe.db.exists("Role", role):
		return {"error": f"Role {role} yok"}

	user_doc = frappe.get_doc("User", email)
	existing = {r.role for r in (user_doc.roles or [])}
	if role in existing:
		return {"ok": True, "user": email, "status": "already_has_role", "role": role}

	user_doc.append("roles", {"role": role})
	user_doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "user": email, "added_role": role}
