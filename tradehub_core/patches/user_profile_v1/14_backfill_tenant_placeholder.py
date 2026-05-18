"""Patch 14: Sprint 3 öncesi tenant field placeholder.
Tenant DocType henüz yok; Sprint 3'te yaratıldığında bu patch genişler ve
'Default Marketplace' tenant'ı backfill eder.
Sprint 2'de NO-OP."""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Tenant"):
		# Sprint 3 öncesi — tenant DocType henüz yok
		return

	# Sprint 3'te bu patch'in placeholder yerini alacak gerçek kod:
	# default_tenant_name = "Default Marketplace"
	# if not frappe.db.exists("Tenant", default_tenant_name):
	#     frappe.get_doc({"doctype": "Tenant", "tenant_name": default_tenant_name}).insert()
	# frappe.db.sql("UPDATE `tabUser Profile` SET tenant = %s WHERE tenant IS NULL", (default_tenant_name,))
	# frappe.db.commit()
