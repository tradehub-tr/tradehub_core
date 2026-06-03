import frappe


def run():
	# PII view caps inspection
	print("=== Sub-user PII view capabilities ===")
	pii_caps = [
		"view.customer_full",
		"view.customer_shipping",
		"view.customer_pii",
		"view.order_amounts",
		"view.financial_summary",
		"view.balance",
		"view.profit_detail",
		"view.bank_info",
		"view.tax_id",
	]
	for cap in pii_caps:
		r = frappe.db.get_value(
			"TH Capability Registry",
			cap,
			["module_group", "default_tier", "is_owner_only", "is_active", "plan_feature_flag"],
			as_dict=True,
		)
		print(f"  {cap:30s} → {r}")

	# Sub-user role profiles that have these capabilities granted
	print("\n=== Cap Grant for PII view capabilities ===")
	rows = frappe.db.sql(
		f"""SELECT role_profile, capability FROM `tabTH Capability Grant`
        WHERE granted=1 AND capability IN ({",".join(["%s"] * len(pii_caps))}) ORDER BY capability, role_profile""",
		tuple(pii_caps),
		as_dict=True,
	)
	by_cap = {}
	for r in rows:
		by_cap.setdefault(r["capability"], []).append(r["role_profile"])
	for cap in pii_caps:
		profiles = by_cap.get(cap, [])
		print(f"  {cap:30s} → granted to: {profiles}")

	# Plan name vs plan_code in DB
	print("\n=== Plan name vs plan_code in DB ===")
	rows = frappe.db.sql("SELECT name, plan_code, plan_name FROM `tabSubscription Plan`", as_dict=True)
	for r in rows:
		print(f"  name={r['name']!r:15} plan_code={r['plan_code']!r:15} plan_name={r['plan_name']!r}")

	# Check entitlement.has_feature impl
	print("\n=== entitlement.has_feature path ===")
	try:
		import inspect

		from tradehub_core import entitlement

		src_path = inspect.getfile(entitlement)
		print(f"  Module path: {src_path}")
	except Exception as e:
		print(f"  ERR: {e}")
