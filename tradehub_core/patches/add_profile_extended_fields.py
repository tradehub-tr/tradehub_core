import frappe


def execute():
	"""Reload doctypes to create new profile columns."""
	frappe.reload_doc("tradehub_core", "doctype", "buyer_profile", force=True)
	frappe.reload_doc("tradehub_core", "doctype", "seller_profile", force=True)
