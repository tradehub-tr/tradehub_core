"""Add `is_sample` flag to tabCart Item.

Sample (numune) cart rows are kept on a separate row from the wholesale row of
the same listing/variant so the storefront can label them "Numune" and price
them at `Listing.sample_price` without colliding with bulk pricing tiers.

Idempotent: checks for the column before adding, safe to re-run.
"""

import frappe


def execute():
	columns = frappe.db.get_table_columns("Cart Item")
	if "is_sample" in columns:
		return

	frappe.db.sql("ALTER TABLE `tabCart Item` ADD COLUMN `is_sample` TINYINT(1) NOT NULL DEFAULT 0")
	frappe.db.commit()
