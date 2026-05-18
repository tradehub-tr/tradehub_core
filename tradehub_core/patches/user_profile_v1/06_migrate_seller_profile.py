"""Patch 6: Seller Profile → User Profile migration (frappe.db.set_value bypass).
Bloker 1: Seller olan her kullanıcı için account_type=Business ZORLA set edilir.
Bloker 2: doc.save() ÇAĞRILMAZ — controller hook bypass."""

import frappe
from frappe.utils import now


def execute():
	if not frappe.db.table_exists("Seller Profile"):
		return

	sellers = frappe.db.sql("""SELECT * FROM `tabSeller Profile`""", as_dict=True)
	merged_count = 0
	new_count = 0

	for s in sellers:
		existing = frappe.db.exists("User Profile", {"user": s.user})

		if existing:
			# MERGE: mevcut User Profile'a Seller verisi eklenir
			update_dict = {
				"can_sell": 1,
				"account_type": "Business",  # Bloker 1: Seller zorunlu Business
				"tax_id": s.tax_id,
				"tax_id_type": s.tax_id_type,
				"tax_office": s.tax_office,
				"bank_name": s.bank_name,
				"iban": s.iban,
				"account_holder_name": s.account_holder_name,
				"kyb_status": s.kyb_status,
				"migrated_from_seller_profile": s.name,
			}
			current = frappe.db.get_value(
				"User Profile",
				existing,
				["company_name", "phone"],
				as_dict=True,
			)
			if current and not current.company_name and s.business_name:
				update_dict["company_name"] = s.business_name[:140]
			if current and not current.phone and s.contact_phone:
				update_dict["phone"] = (s.contact_phone or "")[:20]

			# frappe.db.set_value — controller bypass
			frappe.db.set_value("User Profile", existing, update_dict, update_modified=False)
			merged_count += 1
		else:
			# Yeni Seller-only User Profile (overlap dışı)
			now_dt = now()
			frappe.db.sql(
				"""
				INSERT INTO `tabUser Profile` (
					name, user, can_buy, can_sell, can_admin, status,
					full_name, phone, country, account_type, company_name,
					tax_id, tax_id_type, tax_office,
					bank_name, iban, account_holder_name, kyb_status,
					business_type, job_title, website, year_established, employee_count,
					about_us, selling_platforms, industry_preferences,
					sourcing_frequency, annual_spending,
					created_via, migrated_at, migrated_from_seller_profile,
					joined_at, buyer_level,
					creation, modified, owner, modified_by, docstatus
				) VALUES (
					%(user)s, %(user)s, 0, 1, 0, %(status)s,
					%(full_name)s, %(phone)s, %(country)s, 'Business', %(company_name)s,
					%(tax_id)s, %(tax_id_type)s, %(tax_office)s,
					%(bank_name)s, %(iban)s, %(account_holder_name)s, %(kyb_status)s,
					%(business_type)s, %(job_title)s, %(website)s, %(year_established)s, %(employee_count)s,
					%(about_us)s, %(selling_platforms)s, %(industry_preferences)s,
					%(sourcing_frequency)s, %(annual_spending)s,
					'migration', %(now)s, %(migrated_from)s,
					%(now)s, 'Bronze',
					%(now)s, %(now)s, 'Administrator', 'Administrator', 0
				)
			""",
				{
					"user": s.user,
					"status": s.status or "Active",
					"full_name": (s.seller_name or s.user)[:140],
					"phone": (s.contact_phone or "")[:20],
					"country": s.country,
					"company_name": (s.business_name or "")[:140],
					"tax_id": s.tax_id,
					"tax_id_type": s.tax_id_type,
					"tax_office": s.tax_office,
					"bank_name": s.bank_name,
					"iban": s.iban,
					"account_holder_name": s.account_holder_name,
					"kyb_status": s.kyb_status,
					"business_type": s.business_type,
					"job_title": s.job_title,
					"website": s.website,
					"year_established": s.year_established or 0,
					"employee_count": s.employee_count,
					"about_us": s.about_us,
					"selling_platforms": s.selling_platforms,
					"industry_preferences": s.industry_preferences,
					"sourcing_frequency": s.sourcing_frequency,
					"annual_spending": s.annual_spending,
					"now": now_dt,
					"migrated_from": s.name,
				},
			)
			new_count += 1

	frappe.db.commit()
	frappe.log_error(
		title="Patch 6: Seller Profile migration",
		message=f"Merged (hybrid): {merged_count}, New (seller-only): {new_count}, Total: {len(sellers)}",
	)
