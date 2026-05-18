"""Patch 11: User Permission, Custom Field, Property Setter referansları güncelle."""

import frappe


def execute():
	# User Permission
	frappe.db.sql("""
		UPDATE `tabUser Permission`
		SET allow = 'User Profile'
		WHERE allow IN ('Buyer Profile', 'Seller Profile')
	""")

	# Custom Field options (Contact.seller hariç — Admin Seller Profile kalıyor)
	frappe.db.sql("""
		UPDATE `tabCustom Field`
		SET options = 'User Profile'
		WHERE options IN ('Buyer Profile', 'Seller Profile')
	""")

	# Property Setter
	frappe.db.sql("""
		UPDATE `tabProperty Setter`
		SET value = 'User Profile'
		WHERE property = 'options' AND value IN ('Buyer Profile', 'Seller Profile')
	""")

	frappe.db.commit()
