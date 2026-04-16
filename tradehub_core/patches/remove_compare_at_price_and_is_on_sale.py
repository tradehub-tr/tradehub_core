"""Drop the now-unused compare_at_price and is_on_sale columns from tabListing.

The Top Deals model was simplified to use only base_price (Listeleme Fiyatı),
selling_price and discount_percentage. compare_at_price was redundant with
base_price as the strikethrough source, and is_on_sale was a flag the admin
form never exposed — it created stale "fake deal" data that confused users.

Idempotent: checks for column existence before dropping. Safe to re-run.
"""

import frappe


def execute():
	table = "tabListing"

	# Drop columns only if they still exist (idempotent)
	columns = frappe.db.get_table_columns("Listing")
	if "compare_at_price" in columns:
		frappe.db.sql(f"ALTER TABLE `{table}` DROP COLUMN `compare_at_price`")
	if "is_on_sale" in columns:
		frappe.db.sql(f"ALTER TABLE `{table}` DROP COLUMN `is_on_sale`")

	frappe.db.commit()
