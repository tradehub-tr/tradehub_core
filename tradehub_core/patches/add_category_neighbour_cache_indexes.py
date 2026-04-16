"""Add composite index on Category Neighbour Cache for hot-path lookups.

The Complementary cold-start fallback queries:

    SELECT neighbour_category, similarity
    FROM `tabCategory Neighbour Cache`
    WHERE category = %s AND similarity >= %s
    ORDER BY similarity DESC
    LIMIT %s

A composite (category, similarity DESC) index covers WHERE + ORDER BY
in a single index seek, keeping the lookup at O(log N) regardless of
table size.

Runs in post_model_sync so the table created by Frappe's DocType sync
(from doctype/category_neighbour_cache/) is guaranteed to exist.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Category Neighbour Cache"):
		return

	_add_index_if_missing(
		"Category Neighbour Cache",
		"idx_cnc_cat_sim",
		"category, similarity DESC",
	)
	_add_index_if_missing(
		"Category Neighbour Cache",
		"idx_cnc_neighbour",
		"neighbour_category",
	)
	frappe.db.commit()


def _add_index_if_missing(doctype: str, index_name: str, cols_expr: str) -> None:
	table = f"tab{doctype}"
	existing = frappe.db.sql(
		f"SHOW INDEX FROM `{table}` WHERE Key_name = %s",
		(index_name,),
	)
	if existing:
		return
	frappe.db.sql(f"CREATE INDEX `{index_name}` ON `{table}` ({cols_expr})")
