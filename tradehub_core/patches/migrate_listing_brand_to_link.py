"""
Listing.brand alanını Data'dan Link'e migrate eder. String olarak
saklanan marka isimlerini, önce create_brand_records_from_listing_strings
patch'i tarafından oluşturulan Brand kayıtlarının 'name' değerleriyle
eşler. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Brand"):
		return
	if not frappe.db.table_exists("Listing"):
		return

	columns = frappe.db.sql("DESC `tabListing`", as_dict=True)
	brand_col = next((c for c in columns if c["Field"] == "brand"), None)
	if not brand_col:
		return

	rows = frappe.db.sql(
		"""
		SELECT name, brand
		FROM `tabListing`
		WHERE brand IS NOT NULL AND brand != ''
		""",
		as_dict=True,
	)
	if not rows:
		return

	brand_lookup = {}
	for b in frappe.db.get_all("Brand", fields=["name", "brand_name", "brand_code"]):
		brand_lookup[b.brand_name.strip().lower()] = b.name
		brand_lookup[(b.brand_code or "").strip().lower()] = b.name

	migrated = 0
	skipped = 0
	for row in rows:
		current = (row.brand or "").strip()
		if not current:
			continue
		if frappe.db.exists("Brand", current):
			continue
		key = current.lower()
		target = brand_lookup.get(key)
		if not target:
			skipped += 1
			continue
		frappe.db.set_value("Listing", row.name, "brand", target, update_modified=False)
		migrated += 1

	frappe.db.commit()
	frappe.logger("patches").info(f"[migrate_listing_brand_to_link] Migrated {migrated} rows, skipped {skipped} unmapped.")
