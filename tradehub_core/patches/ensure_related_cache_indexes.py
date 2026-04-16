"""Ensure indexes used by storefront API + atomic shadow swap exist.

Re-checks the indexes added by add_related_products_fields (idempotent)
plus a composite Listing index that speeds up the chunk dispatcher's
active-listing enumeration on 100K+ row tables.
"""

import frappe


def execute():
	_add_index_if_missing(
		"Related Listing Cache",
		"idx_rlc_source_type_score",
		"source_listing, relation_type, final_score DESC",
	)
	_add_index_if_missing(
		"Related Listing Cache",
		"idx_rlc_target",
		"target_listing",
	)
	_add_index_if_missing(
		"Listing",
		"idx_listing_active_pricetier",
		"status, is_visible, product_category",
	)
	frappe.db.commit()


def _add_index_if_missing(doctype: str, index_name: str, cols_expr: str) -> None:
	table = f"tab{doctype}"
	if not frappe.db.table_exists(doctype):
		return
	existing = frappe.db.sql(
		f"SHOW INDEX FROM `{table}` WHERE Key_name = %s",
		(index_name,),
	)
	if existing:
		return
	frappe.db.sql(f"CREATE INDEX `{index_name}` ON `{table}` ({cols_expr})")
