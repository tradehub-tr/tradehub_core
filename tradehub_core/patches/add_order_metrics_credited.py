"""Add the hidden `metrics_credited` flag column to tabOrder.

This boolean tracks whether an Order's items have already been counted into
the corresponding Listing.order_count. The Order on_update / after_insert
hook (`bump_listing_order_counts`) reads/writes this flag to stay
idempotent — it only credits a listing once per order, and only uncredits
when the order leaves the SOLD_STATES set.

Without this flag, a single order would re-increment listing counts on
every save (status changes, note edits, tracking number updates...), so
the homepage Top Ranking would inflate fast.

Idempotent: the patch checks for the column before adding it, safe to
re-run.
"""

import frappe


def execute():
	columns = frappe.db.get_table_columns("Order")
	if "metrics_credited" in columns:
		return

	frappe.db.sql("ALTER TABLE `tabOrder` " "ADD COLUMN `metrics_credited` TINYINT(1) NOT NULL DEFAULT 0")
	frappe.db.commit()
