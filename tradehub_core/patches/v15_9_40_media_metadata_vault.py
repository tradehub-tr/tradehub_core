import frappe


def execute():
	frappe.reload_doc("tradehub_core", "doctype", "media_metadata_vault", force=True)
