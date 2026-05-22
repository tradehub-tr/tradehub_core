"""Patch 7: Hibrit kullanıcı doğrulama (idempotent check).
Patch 5+6 zaten merge yapıyor; bu patch hibrit kullanıcı tutarlılığını doğrular."""

import frappe


def execute():
	if not (frappe.db.table_exists("Buyer Profile") and frappe.db.table_exists("Seller Profile")):
		return

	hybrid_users = frappe.db.sql(
		"""
		SELECT b.user FROM `tabBuyer Profile` b
		INNER JOIN `tabSeller Profile` s ON s.user = b.user
	""",
		as_list=True,
	)

	fixed = 0
	for (user_email,) in hybrid_users:
		up = frappe.db.exists("User Profile", {"user": user_email})
		if not up:
			frappe.log_error(
				title="Patch 7: Hybrid user User Profile bulunamadı",
				message=f"User: {user_email}",
			)
			continue

		# Hibrit kullanıcı: can_buy=1, can_sell=1, account_type=Business (Seller olduğu için)
		current = frappe.db.get_value(
			"User Profile",
			up,
			["can_buy", "can_sell", "account_type"],
			as_dict=True,
		)
		needs_fix = {}
		if not current.can_buy:
			needs_fix["can_buy"] = 1
		if not current.can_sell:
			needs_fix["can_sell"] = 1
		if current.account_type != "Business":
			needs_fix["account_type"] = "Business"

		if needs_fix:
			frappe.db.set_value("User Profile", up, needs_fix, update_modified=False)
			fixed += 1

	frappe.db.commit()
	frappe.log_error(
		title="Patch 7: Hybrid user verification",
		message=f"Hybrid users: {len(hybrid_users)}, Fixed: {fixed}",
	)
