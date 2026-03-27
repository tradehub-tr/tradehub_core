"""
Cart Item: listing_variant alanını Link'ten Data'ya dönüştür.
Inline varyant sentetik ID'lerinin (ör: LST-00004-Renk-Siyah) saklanabilmesi için.
"""
import frappe


def execute():
    frappe.db.sql("""
        ALTER TABLE `tabCart Item`
        MODIFY COLUMN `listing_variant` VARCHAR(140) NULL DEFAULT NULL
    """)
    frappe.db.commit()
