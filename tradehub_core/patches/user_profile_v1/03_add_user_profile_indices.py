"""Patch 3: User Profile performans index'leri."""

import frappe


def execute():
	indices = [
		["user"],
		["can_buy", "status"],
		["can_sell", "kyb_status"],
		["country"],
		["member_id"],
	]
	for cols in indices:
		try:
			frappe.db.add_index("User Profile", cols)
		except Exception as exc:
			frappe.log_error(
				title=f"Patch 3: index ekleme hatası {cols}",
				message=str(exc),
			)
	frappe.db.commit()
