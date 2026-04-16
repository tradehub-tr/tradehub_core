"""Add fields required by the Related Products (İlgili Ürünler) feature.

Adds:
  - Listing.price_tier (Select Q1/Q2/Q3/Q4) — populated by the nightly batch,
    speeds up Similar/Substitute scoring by avoiding per-card quartile lookups.
  - Product Category.is_accessory_category (Check) — auto-flagged by a daily
    job scanning category names for accessory keywords; used by the Accessory
    scorer.
  - Related Listing Cache composite index (source_listing, relation_type,
    final_score DESC) — drives the storefront API's grouped lookup in <10ms.

Idempotent: each column/index is checked before being added.
"""

import frappe


def execute():
	_add_column_if_missing(
		"Listing",
		"price_tier",
		"VARCHAR(2) DEFAULT NULL",
	)
	_add_column_if_missing(
		"Product Category",
		"is_accessory_category",
		"TINYINT(1) NOT NULL DEFAULT 0",
	)
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
	frappe.db.commit()


def _add_column_if_missing(doctype: str, column: str, definition: str) -> None:
	table = f"tab{doctype}"
	if not frappe.db.table_exists(doctype):
		# DocType may not be migrated yet in a fresh install; skip safely.
		return
	columns = frappe.db.get_table_columns(doctype)
	if column in columns:
		return
	frappe.db.sql(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


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
