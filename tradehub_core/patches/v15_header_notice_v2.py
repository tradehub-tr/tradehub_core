import frappe


def execute():
	"""Header Notice display_mode + background_color additions (idempotent)."""
	frappe.reload_doc("tradehub_core", "doctype", "header_notice")
	frappe.reload_doc("tradehub_core", "doctype", "header_notice_settings")
