"""ACİL REVERT: Marketplace satıcılarını Website User'a geri çevir + rollerin desk_access=1 yap.

Tarihçe:
- 2026-05-11 deneme: System User mimari + desk_access=0 → Frappe v15'in init_request
  aşamasında bozuk sid validate edilirken 417 fırlatma sorunu çözülemedi
- Bu patch eski stabil Website User mimarisini geri yükler

Idempotent: kontrol edip dokunur.
"""

import frappe


def execute():
	updated_users = 0
	updated_roles = 0

	# 1. Tüm Active satıcıları Website User'a geri çevir
	sellers = frappe.db.sql(
		"""
		SELECT DISTINCT asp.user
		FROM `tabAdmin Seller Profile` asp
		WHERE asp.user IS NOT NULL
			AND asp.user != ''
			AND asp.user != 'Administrator'
			AND IFNULL(asp.status, '') = 'Active'
		""",
		as_dict=True,
	)
	for row in sellers:
		user = row.user
		if not user:
			continue
		current = frappe.db.get_value("User", user, "user_type")
		if current and current != "Website User":
			frappe.db.set_value("User", user, "user_type", "Website User", update_modified=False)
			# Eski sessions temizle (fresh login gerekli)
			try:
				frappe.db.sql("DELETE FROM `tabSessions` WHERE user = %s", (user,))
			except Exception:
				frappe.log_error(f"Session cleanup failed for user {user}", "revert_to_website_user_mimari")
				pass
			frappe.logger("patches").info(f"  [user] {user}: {current} → Website User")
			updated_users += 1

	# 2. Buyer + Seller rollerinin desk_access=1 (eski state)
	for role in ("Buyer", "Seller"):
		if not frappe.db.exists("Role", role):
			continue
		current = frappe.db.get_value("Role", role, "desk_access")
		if current != 1:
			frappe.db.set_value("Role", role, "desk_access", 1, update_modified=False)
			frappe.logger("patches").info(f"  [role] {role}: desk_access {current} → 1")
			updated_roles += 1

	frappe.db.commit()

	try:
		frappe.clear_cache()
	except Exception:
		frappe.log_error("Cache clear failed in revert_to_website_user_mimari patch", "revert_to_website_user_mimari")
		pass

	frappe.logger("patches").info(f"[revert_to_website_user_mimari] users={updated_users}, roles={updated_roles}")
