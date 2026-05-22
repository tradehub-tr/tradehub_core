"""Owner bilgilerini özetler."""

import frappe


def show_owners() -> dict:
	owners = frappe.get_all(
		"User",
		filters={"tradehub_is_owner": 1},
		fields=["name", "email", "tradehub_tenant", "enabled"],
		limit_page_length=20,
	)
	tenant_users = frappe.get_all(
		"User",
		filters={"tradehub_tenant": ["like", "SEL-%"]},
		fields=["name", "email", "tradehub_tenant", "tradehub_is_owner"],
		limit_page_length=10,
	)
	return {
		"owner_count": len(owners),
		"owners": owners,
		"sel_tenant_users_sample": tenant_users[:10],
	}


def make_user_owner(email: str, tenant: str) -> dict:
	"""Hızlı setup: bir kullanıcıyı belirli tenant'ın Owner'ı yap."""
	if not frappe.db.exists("User", email):
		return {"error": f"User {email} bulunamadı"}
	if not frappe.db.exists("Admin Seller Profile", tenant):
		return {"error": f"Tenant {tenant} bulunamadı"}
	frappe.db.set_value("User", email, "tradehub_is_owner", 1)
	frappe.db.set_value("User", email, "tradehub_tenant", tenant)
	frappe.db.commit()
	return {"ok": True, "user": email, "tenant": tenant}
