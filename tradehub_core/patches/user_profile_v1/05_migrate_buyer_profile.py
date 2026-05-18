"""Patch 5: Buyer Profile → User Profile migration (raw SQL bypass).
Bloker 2: doc.insert() ÇAĞRILMAZ (hook bypass).
Bloker 1: business_type veya company_name doluysa Business; aksi Individual."""

import frappe
from frappe.utils import now


def execute():
	if not frappe.db.table_exists("Buyer Profile"):
		return

	buyers = frappe.db.sql("""SELECT * FROM `tabBuyer Profile`""", as_dict=True)
	migrated_count = 0
	skipped_count = 0

	for b in buyers:
		# IDEMPOTENCY: User Profile zaten var mı?
		if frappe.db.exists("User Profile", {"user": b.user}):
			skipped_count += 1
			continue

		# account_type mapping (Bloker 1 Seçenek C)
		is_business = bool(b.business_type or b.company_name)
		account_type = "Business" if is_business else "Individual"

		now_dt = now()

		frappe.db.sql(
			"""
			INSERT INTO `tabUser Profile` (
				name, user, can_buy, can_sell, can_admin, status,
				full_name, phone, country, account_type, company_name,
				email_verified, email_verified_at, email_verified_method,
				business_type, job_title, website, year_established, employee_count,
				about_us, selling_platforms, industry_preferences,
				sourcing_frequency, annual_spending,
				created_via, migrated_at, migrated_from_buyer_profile,
				joined_at, total_spent, total_orders, payment_on_time_rate,
				return_rate, average_order_value, dispute_rate, feedback_rate,
				cancellation_rate, account_age_days, days_since_last_active,
				buyer_score, buyer_level,
				creation, modified, owner, modified_by, docstatus
			) VALUES (
				%(user)s, %(user)s, 1, 0, 0, %(status)s,
				%(full_name)s, %(phone)s, %(country)s, %(account_type)s, %(company_name)s,
				%(email_verified)s, %(email_verified_at)s, %(email_verified_method)s,
				%(business_type)s, %(job_title)s, %(website)s, %(year_established)s, %(employee_count)s,
				%(about_us)s, %(selling_platforms)s, %(industry_preferences)s,
				%(sourcing_frequency)s, %(annual_spending)s,
				'migration', %(now)s, %(migrated_from)s,
				%(now)s, 0, 0, 0,
				0, 0, 0, 0,
				0, 0, 0,
				0, 'Bronze',
				%(now)s, %(now)s, 'Administrator', 'Administrator', 0
			)
		""",
			{
				"user": b.user,
				"status": b.status or "Active",
				"full_name": (b.buyer_name or b.user)[:140],
				"phone": (b.phone or "")[:20],
				"country": b.country,
				"account_type": account_type,
				"company_name": (b.company_name or "")[:140],
				"email_verified": b.email_verified or 0,
				"email_verified_at": b.email_verified_at,
				"email_verified_method": b.email_verified_method,
				"business_type": b.business_type,
				"job_title": b.job_title,
				"website": b.website,
				"year_established": b.year_established or 0,
				"employee_count": b.employee_count,
				"about_us": b.about_us,
				"selling_platforms": b.selling_platforms,
				"industry_preferences": b.industry_preferences,
				"sourcing_frequency": b.sourcing_frequency,
				"annual_spending": b.annual_spending,
				"now": now_dt,
				"migrated_from": b.name,
			},
		)
		migrated_count += 1

	frappe.db.commit()
	frappe.log_error(
		title="Patch 5: Buyer Profile migration",
		message=f"Migrated: {migrated_count}, Skipped (already exists): {skipped_count}, Total Buyer Profile: {len(buyers)}",
	)
