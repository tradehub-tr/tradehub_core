"""Add composite index on Listing for the Top Deals query.

The Top Deals page filters listings by (product_category, deal flags) and orders
by discount_percentage / modified. With thousands of listings, a full table scan
becomes the bottleneck. A composite index lets MySQL jump straight to the matching
rows without scanning the whole table.

Idempotent: frappe.db.add_index is a no-op if the index already exists.
"""

import frappe


def execute():
	# Composite index for the Top Deals "grouped by category" query
	frappe.db.add_index(
		"Listing",
		["product_category", "is_on_sale", "discount_percentage", "modified"],
		index_name="idx_listing_top_deals_grouped",
	)

	# Composite index for the flat per-category deal listing
	frappe.db.add_index(
		"Listing",
		["product_category", "discount_percentage"],
		index_name="idx_listing_category_discount",
	)

	frappe.db.commit()
