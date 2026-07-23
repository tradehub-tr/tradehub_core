"""
Listing.brand alanında string olarak saklanan marka isimlerinden
Brand DocType kayıtları oluşturur. Idempotent.

Çalıştırılmadan ÖNCE Brand doctype'ının bench migrate ile oluşmuş olması
gerekir. Bu patch migrate_listing_brand_to_link'ten ÖNCE çalışmalıdır.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Brand"):
		return

	existing_brand_codes = set(frappe.db.get_all("Brand", pluck="name"))

	rows = frappe.db.sql(
		"""
		SELECT DISTINCT TRIM(brand) AS brand
		FROM `tabListing`
		WHERE brand IS NOT NULL AND TRIM(brand) != ''
		""",
		as_dict=True,
	)

	created = 0
	for row in rows:
		raw_name = (row.brand or "").strip()
		if not raw_name:
			continue
		code = _slugify_code(raw_name)
		if not code or code in existing_brand_codes:
			continue

		doc = frappe.new_doc("Brand")
		doc.brand_code = code
		doc.brand_name = raw_name
		doc.slug = frappe.scrub(raw_name).replace("_", "-")
		doc.official_status = "Unverified"
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		try:
			doc.insert(ignore_if_duplicate=True)
			existing_brand_codes.add(code)
			created += 1
		except Exception:
			frappe.log_error(
				title="create_brand_records_from_listing_strings",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()
	frappe.logger("patches").info(f"[create_brand_records_from_listing_strings] Created {created} Brand records.")


def _slugify_code(name: str) -> str:
	base = frappe.scrub(name).upper().replace("_", "-")
	base = "".join(ch for ch in base if ch.isalnum() or ch == "-")
	return base[:140]
