"""'Verified Seller' rolünü oluştur, yanlış atanmış rolleri temizle, doğru olanları ata.

Yeni rol, KYB doğrulanmış satıcıları sipariş gate'inde tanımak için kullanılır
(cart.add_to_cart, cart.create_order, Order.validate üç katman).

KYB durumu Verified DEĞİL olduğu halde rol atanmış kullanıcılar olabilir
(geçmişte Verified iken Under Review/Rejected'a düşmüş, hook eskiden bu durumu
handle etmiyordu). Bu patch hem cleanup hem assignment yapar — idempotent.
"""

import frappe


def execute():
	# 1) Rol kaydını oluştur (idempotent)
	if not frappe.db.exists("Role", "Verified Seller"):
		role = frappe.new_doc("Role")
		role.role_name = "Verified Seller"
		role.desk_access = 0  # Storefront/admin-panel için, Frappe Desk girişi yok
		role.is_custom = 1
		role.flags.ignore_permissions = True
		role.insert(ignore_permissions=True)
		frappe.logger("patches").info("[assign_verified_seller_role] 'Verified Seller' rolü oluşturuldu")

	# 2) CLEANUP — KYB durumu Verified DEĞİL olduğu halde role sahip user'ları bul ve rolü kaldır.
	# (Geçmişte hook'un eski sürümü "Under Review", "Draft" durumlarını handle etmiyordu.)
	wrong_role_users = frappe.db.sql(
		"""
		SELECT hr.parent AS user
		FROM `tabHas Role` hr
		LEFT JOIN `tabKYB Verification` kyb ON kyb.user = hr.parent
		WHERE hr.role = 'Verified Seller'
		  AND hr.parenttype = 'User'
		  AND (kyb.status IS NULL OR kyb.status != 'Verified')
		""",
		as_dict=True,
	)

	removed = 0
	for row in wrong_role_users:
		user = row.get("user")
		if not user or not frappe.db.exists("User", user):
			continue
		try:
			user_doc = frappe.get_doc("User", user)
			user_doc.remove_roles("Verified Seller")
			removed += 1
		except Exception as e:
			frappe.log_error(
				message=f"Failed to remove 'Verified Seller' role from {user}: {e}",
				title="assign_verified_seller_role",
			)

	# 3) Mevcut KYB Verified kullanıcılara rolü ata (eksikleri tamamla)
	verified_users = frappe.db.sql(
		"""
		SELECT user
		FROM `tabKYB Verification`
		WHERE status = 'Verified' AND IFNULL(user, '') != ''
		""",
		as_dict=True,
	)

	assigned = 0
	for row in verified_users:
		user = row.get("user")
		if not user or not frappe.db.exists("User", user):
			continue
		if "Verified Seller" in frappe.get_roles(user):
			continue
		try:
			user_doc = frappe.get_doc("User", user)
			user_doc.add_roles("Verified Seller")
			assigned += 1
		except Exception as e:
			frappe.log_error(
				message=f"Failed to add 'Verified Seller' role to {user}: {e}",
				title="assign_verified_seller_role",
			)

	if assigned or removed:
		frappe.db.commit()

	frappe.logger("patches").info(
		f"[assign_verified_seller_role] cleanup={removed} kullanıcıdan rol kaldırıldı, "
		f"assigned={assigned} kullanıcıya rol atandı"
	)
