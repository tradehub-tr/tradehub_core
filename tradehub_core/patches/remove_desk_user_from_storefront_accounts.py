"""Storefront kullanıcılarından (Buyer/Seller) ``Desk User`` rolünü ve
``System User`` user_type'ını kaldır.

**Neden?**
Buyer veya Seller olan kullanıcılar Frappe Desk'e (`/app`) girmemeli — sızıntıya
yol açar (sistem mailleri, ECA Rule, başka kullanıcıların verileri vb. Desk'in
genel inbox/list view'larında görünebilir).

Storefront kullanıcıları:
  • ``/panel`` (admin-panel) — kendi mağaza yönetimi (Seller olduklarında)
  • ``/pages/...`` (storefront) — alıcı dashboard, satıcı dashboard
**Frappe Desk'e (`/app`) gerek yok.**

**Mantık**
1. Buyer Profile / Seller Profile / Seller Application'a bağlı tüm User'ları topla
2. Eğer bu User aynı zamanda admin rollerinden birine sahipse (System Manager,
   Administrator, Marketplace Admin) → MUAF (admin paneline ihtiyacı var)
3. Aksi halde:
   • ``Desk User`` rolünü ``tabHas Role`` üzerinden DELETE et
   • ``User.user_type='System User'`` ise ``Website User``'a UPDATE et
4. Cache invalidate (sonraki request yeni state'i görsün)

**Idempotent**: tekrar çalıştığında zaten temiz olanlara dokunmaz (DELETE ve
UPDATE'in WHERE'leri filter eder).

**Geri alma**: Bu patch reversible değil; admin manuel olarak Frappe Desk'ten
ilgili User'a ``Desk User`` rolünü tekrar ekleyebilir.
"""

import frappe

ADMIN_ROLE_NAMES = {"System Manager", "Administrator", "Marketplace Admin"}


def execute():
	# Storefront kullanıcı listesi: Buyer Profile + Seller Profile + Seller Application
	storefront_users: set[str] = set()

	storefront_users.update(
		frappe.db.sql_list(
			"SELECT DISTINCT `user` FROM `tabBuyer Profile` WHERE `user` IS NOT NULL AND `user` != ''"
		)
	)
	storefront_users.update(
		frappe.db.sql_list(
			"SELECT DISTINCT `user` FROM `tabSeller Profile` WHERE `user` IS NOT NULL AND `user` != ''"
		)
	)
	storefront_users.update(
		frappe.db.sql_list(
			"SELECT DISTINCT `applicant_user` FROM `tabSeller Application` "
			"WHERE `applicant_user` IS NOT NULL AND `applicant_user` != ''"
		)
	)

	# System users — kesin muaf
	storefront_users.discard("Administrator")
	storefront_users.discard("Guest")
	storefront_users.discard(None)

	cleaned_role = 0
	cleaned_type = 0
	skipped_admin = 0
	skipped_missing = 0

	for user in storefront_users:
		# User var mı?
		if not frappe.db.exists("User", user):
			skipped_missing += 1
			continue

		# Admin rolüne sahipse muaf — admin paneline ihtiyacı var
		try:
			user_roles = set(frappe.get_roles(user))
		except Exception:
			user_roles = set()

		if user_roles & ADMIN_ROLE_NAMES:
			skipped_admin += 1
			continue

		# 1. Desk User rolünü kaldır
		# Frappe v15 'tabHas Role' child table; parent=User.name, parenttype='User'
		frappe.db.sql(
			"DELETE FROM `tabHas Role` WHERE `parent`=%s AND `role`='Desk User' AND `parenttype`='User'",
			(user,),
		)
		# pymysql .rowcount cursor üzerinde; frappe wrapper'ı sonucu dönmez,
		# yine de WHERE eşleşmesi varsa silinir.
		if "Desk User" in user_roles:
			cleaned_role += 1

		# 2. user_type='System User' ise 'Website User'a düşür
		# (idempotent: zaten Website User ise UPDATE 0 row etkiler)
		current_type = frappe.db.get_value("User", user, "user_type")
		if current_type == "System User":
			frappe.db.sql(
				"UPDATE `tabUser` SET `user_type`='Website User' WHERE `name`=%s",
				(user,),
			)
			cleaned_type += 1

		# 3. Cache invalidate — sonraki request yeni rolleri okusun
		try:
			frappe.clear_cache(user=user)
		except Exception:
			# clear_cache hatası migration'ı bozmasın
			pass

	frappe.db.commit()

	# Migration özet log'u — admin Error Log'da görür
	frappe.log_error(
		title="remove_desk_user_from_storefront_accounts: completed",
		message=(
			f"Storefront cleanup migration:\n"
			f"  Total candidate users: {len(storefront_users)}\n"
			f"  Desk User role removed: {cleaned_role}\n"
			f"  user_type System User → Website User: {cleaned_type}\n"
			f"  Skipped (admin role): {skipped_admin}\n"
			f"  Skipped (User not found): {skipped_missing}"
		),
	)
