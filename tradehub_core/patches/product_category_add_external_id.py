"""
Product Category: external_id ve sort_order alanları ekle.
Autoname field:external_id olarak değiştirildi — duplicate isimli kategorilere izin vermek için.
"""
import frappe


def execute():
    # external_id sütunu yoksa ekle
    if not frappe.db.has_column("Product Category", "external_id"):
        frappe.db.sql("""
            ALTER TABLE `tabProduct Category`
            ADD COLUMN `external_id` VARCHAR(140) NULL DEFAULT NULL
        """)

    # sort_order sütunu yoksa ekle
    if not frappe.db.has_column("Product Category", "sort_order"):
        frappe.db.sql("""
            ALTER TABLE `tabProduct Category`
            ADD COLUMN `sort_order` INT DEFAULT 0
        """)

    # Mevcut kayıtlar varsa external_id'lerini name'den doldur
    frappe.db.sql("""
        UPDATE `tabProduct Category`
        SET `external_id` = `name`
        WHERE `external_id` IS NULL OR `external_id` = ''
    """)

    frappe.db.commit()
