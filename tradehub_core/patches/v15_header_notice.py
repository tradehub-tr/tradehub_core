import frappe


def execute():
	"""Header Notice DocType'ını sisteme tanıt (idempotent)."""
	frappe.reload_doc("tradehub_core", "doctype", "header_notice")
