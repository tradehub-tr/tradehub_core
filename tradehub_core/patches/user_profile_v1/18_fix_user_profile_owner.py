"""Patch 18: User Profile.owner alanını user email'e set eder.
Patch 5/6 raw SQL INSERT'lerde owner='Administrator' bırakıldı; bu DocPerm
if_owner=1 kuralını bozdu (Ali kendi profilini get_list ile göremiyordu).
Idempotent — defalarca koşulabilir."""

import frappe


def execute():
	frappe.db.sql("""
		UPDATE `tabUser Profile`
		SET owner = user, modified_by = user
		WHERE user IS NOT NULL AND user != '' AND owner != user
	""")
	cnt = frappe.db.sql("""SELECT COUNT(*) FROM `tabUser Profile` WHERE owner = user""")[0][0]
	frappe.db.commit()
	frappe.log_error(
		title="Patch 18: User Profile.owner fix",
		message=f"Updated owner field to user email. Total profiles with correct owner: {cnt}",
	)
