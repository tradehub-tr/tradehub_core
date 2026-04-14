"""Add `sell_in_moq_multiples` flag to tabListing.

When enabled, the product may only be ordered in multiples of Min Order Qty
(MOQ). Example: MOQ=5 → allowed quantities 5, 10, 15, ... Storefront
quantity steppers and add-to-cart validation enforce this rule.

Idempotent: checks for the column before adding, safe to re-run.
"""
import frappe


def execute():
    columns = frappe.db.get_table_columns("Listing")
    if "sell_in_moq_multiples" in columns:
        return

    frappe.db.sql(
        "ALTER TABLE `tabListing` "
        "ADD COLUMN `sell_in_moq_multiples` TINYINT(1) NOT NULL DEFAULT 0"
    )
    frappe.db.commit()
