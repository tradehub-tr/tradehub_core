"""Approved Seller Application'ı olan ama Seller rolü atanmamış kullanıcılara
Seller rolünü ata.

Geçmişte Seller Application status'u "Approved"a manuel olarak (ör. SQL UPDATE
veya direkt admin müdahalesi) çekilmiş kullanıcılarda on_update hook'u
tetiklenememiş olabilir. Bu yüzden Seller rolü eksik kalmış kullanıcılar
oluyor — Frappe permission flow'unda if_owner=1 olsa bile rolün varlığı şart
olduğu için bu kullanıcılar kendi DocType'larına (KYB Verification, Seller
Profile) REST API üzerinden erişemiyor (403).

Idempotent: Seller rolü zaten varsa noop. Tekrar tekrar çalıştırılabilir.
"""

import frappe


def execute():
	rows = frappe.db.sql(
		"""
		SELECT applicant_user
		FROM `tabSeller Application`
		WHERE status = 'Approved'
		  AND IFNULL(applicant_user, '') != ''
		""",
		as_dict=True,
	)

	updated = 0
	for row in rows:
		user = row.get("applicant_user")
		if not user:
			continue
		if not frappe.db.exists("User", user):
			continue
		if "Seller" in frappe.get_roles(user):
			continue
		try:
			user_doc = frappe.get_doc("User", user)
			user_doc.add_roles("Seller")
			updated += 1
		except Exception as e:
			frappe.log_error(
				message=f"Failed to add Seller role to {user}: {e}",
				title="assign_seller_role_legacy",
			)

	if updated:
		frappe.db.commit()

	print(f"[assign_seller_role_legacy] Seller rolü atanan kullanıcı sayısı: {updated}")
