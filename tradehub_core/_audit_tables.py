import frappe


def run():
	# Find tables containing "Capability" or "Feature" or "Subscription Plan"
	print("=== Tables matching RBAC names ===")
	rows = frappe.db.sql("SHOW TABLES LIKE '%Capability%'", as_dict=False)
	for r in rows:
		print("  ", r)
	rows = frappe.db.sql("SHOW TABLES LIKE '%Feature%'", as_dict=False)
	for r in rows:
		print("  ", r)
	rows = frappe.db.sql("SHOW TABLES LIKE '%Subscription%'", as_dict=False)
	for r in rows:
		print("  ", r)
	rows = frappe.db.sql("SHOW TABLES LIKE '%TH %'", as_dict=False)
	for r in rows:
		print("  ", r)
	rows = frappe.db.sql("SHOW TABLES LIKE 'tabTH%'", as_dict=False)
	for r in rows:
		print("  ", r)
	print()
	print("=== DocType registry ===")
	for nm in [
		"TH Capability Registry",
		"TH Capability Grant",
		"Feature Catalog",
		"Subscription Plan",
		"Module Registry",
		"Module Policy",
	]:
		exists = frappe.db.exists("DocType", nm)
		print(f"  DocType '{nm}': {'EXISTS' if exists else 'MISSING'}")
