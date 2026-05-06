"""
Aktif Admin Seller Profile sahibi tüm user'lara `Marketplace Seller` rolünü ekle.

Tarihçe: Onboarding (`SellerApplication._approve_application`) sadece `Seller`
rolünü atıyordu; CRM doctype'larındaki Frappe role-level DocPerm ise
`Marketplace Seller`'a bağlı. Hook (`utils.seller_role_sync`) bundan sonraki
tüm yeni profillerde rolü otomatik atar — bu patch geçmişe yönelik backfill.

Idempotent: rol zaten varsa skip.
"""

import frappe

from tradehub_core.utils.seller_role_sync import ROLE, sync_marketplace_seller_role


def execute():
	if not frappe.db.exists("Role", ROLE):
		# grant_seller_crm_permissions patch'i bu rolü kullanıyor; o henüz
		# çalışmadıysa skip — sıralama patches.txt'te kontrol ediliyor.
		return

	profiles = frappe.get_all(
		"Admin Seller Profile",
		filters={"status": "Active", "user": ("is", "set")},
		fields=["name", "user", "status"],
	)

	for row in profiles:
		# sync_marketplace_seller_role kendi içinde idempotent (rol zaten varsa
		# atlar). Doc objesi oluşturmaya gerek yok — dict yeterli.
		try:
			sync_marketplace_seller_role(row)
		except Exception:
			frappe.log_error(
				title="backfill_marketplace_seller_role",
				message=f"Profil {row.get('name')} (user={row.get('user')}) için rol senkronu başarısız.",
			)

	frappe.db.commit()
	frappe.clear_cache()
