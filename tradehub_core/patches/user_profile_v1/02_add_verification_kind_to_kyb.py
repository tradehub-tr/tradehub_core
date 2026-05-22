"""Patch 2: KYB Verification'a verification_kind field eklenir (S26).
Mevcut tüm kayıtlar default 'KYB' set edilir."""

import frappe


def execute():
	frappe.reload_doc("tradehub_core", "doctype", "kyb_verification")
	if frappe.db.has_column("KYB Verification", "verification_kind"):
		frappe.db.sql("""
			UPDATE `tabKYB Verification`
			SET verification_kind = 'KYB'
			WHERE verification_kind IS NULL OR verification_kind = ''
		""")
	frappe.db.commit()
