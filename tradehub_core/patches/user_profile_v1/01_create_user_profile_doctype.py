"""Patch 1: User Profile DocType reload + tablo yaratma."""

import frappe


def execute():
	frappe.reload_doc("tradehub_core", "doctype", "user_profile")
	frappe.db.commit()
	if not frappe.db.table_exists("User Profile"):
		frappe.throw("Patch 1 FAIL: tabUser Profile tablo yaratılamadı")
