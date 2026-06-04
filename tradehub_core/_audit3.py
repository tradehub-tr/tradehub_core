import frappe


def run():
	# find columns of cap grant
	cols = frappe.db.sql("SHOW COLUMNS FROM `tabTH Capability Grant`", as_dict=True)
	print("=== TH Capability Grant columns ===")
	for c in cols:
		print(f"  {c['Field']} ({c['Type']})")
	print()
	cols2 = frappe.db.sql("SHOW COLUMNS FROM `tabTH Capability Registry`", as_dict=True)
	print("=== TH Capability Registry columns ===")
	for c in cols2:
		print(f"  {c['Field']} ({c['Type']})")
	print()
	cols3 = frappe.db.sql("SHOW COLUMNS FROM `tabFeature Catalog`", as_dict=True)
	print("=== Feature Catalog columns ===")
	for c in cols3:
		print(f"  {c['Field']} ({c['Type']})")
