import json

import frappe


def run():
	# Direct count
	cap_count = frappe.db.sql("SELECT COUNT(*) FROM `tabTH Capability Registry`")[0][0]
	feat_count = frappe.db.sql("SELECT COUNT(*) FROM `tabFeature Catalog`")[0][0]
	grant_count = frappe.db.sql("SELECT COUNT(*) FROM `tabTH Capability Grant`")[0][0]
	plan_count = frappe.db.sql("SELECT COUNT(*) FROM `tabSubscription Plan`")[0][0]
	print(f"Cap Registry: {cap_count}")
	print(f"Feature Catalog: {feat_count}")
	print(f"Cap Grant: {grant_count}")
	print(f"Subscription Plan: {plan_count}")

	# Cap Registry rows
	print("\n=== CAP REGISTRY ROWS ===")
	rows = frappe.db.sql(
		"""SELECT name, plan_feature_flag, is_owner_only, requires_kyc, requires_aml, is_active, default_tier, module_group FROM `tabTH Capability Registry` ORDER BY name""",
		as_dict=True,
	)
	for r in rows:
		print(
			f"  {r['name']:40s} flag={str(r.get('plan_feature_flag') or '-'):35s} owner={r['is_owner_only']} kyc={r['requires_kyc']} aml={r['requires_aml']} active={r['is_active']} tier={r['default_tier']!s:25s} mod={r.get('module_group')}"
		)

	# Feature Catalog
	print("\n=== FEATURE CATALOG ===")
	rows = frappe.db.sql(
		"""SELECT name, feature_key, feature_type, category FROM `tabFeature Catalog` ORDER BY name""",
		as_dict=True,
	)
	for r in rows:
		print(f"  {r['name']:55s} type={r['feature_type']:12s} cat={r['category']}")

	# Capability Grant
	print("\n=== CAP GRANT (by role_profile) ===")
	rows = frappe.db.sql(
		"""SELECT role_profile, capability_key FROM `tabTH Capability Grant` ORDER BY role_profile, capability_key""",
		as_dict=True,
	)
	by = {}
	for r in rows:
		by.setdefault(r["role_profile"], []).append(r["capability_key"])
	for prof in sorted(by.keys()):
		caps = by[prof]
		print(f"\n  {prof} ({len(caps)} caps):")
		for c in caps:
			print(f"    {c}")

	# Plan capability_flags JSON
	print("\n=== SUBSCRIPTION PLAN capability_flags ===")
	rows = frappe.db.sql(
		"""SELECT name, capability_flags FROM `tabSubscription Plan` ORDER BY name""", as_dict=True
	)
	for r in rows:
		raw = r.get("capability_flags") or "{}"
		try:
			d = json.loads(raw) if isinstance(raw, str) else raw
		except Exception:
			d = {}
		if isinstance(d, dict):
			print(f"\n  Plan: {r['name']} (keys={len(d)})")
			for k in sorted(d.keys()):
				print(f"    {k} = {d[k]}")

	print("\n=== DRIFT ===")
	from tradehub_core.utils.seller_capabilities import _OWNER_ONLY_CAPABILITIES, SELLER_CAPABILITIES

	py_keys = set(SELLER_CAPABILITIES.keys()) | set(_OWNER_ONLY_CAPABILITIES)
	db_keys = set(frappe.db.sql_list("SELECT name FROM `tabTH Capability Registry`"))
	print(f"  Python total caps: {len(py_keys)}")
	print(f"  DB Cap Registry caps: {len(db_keys)}")
	print(f"  In Python NOT DB: {sorted(py_keys - db_keys)}")
	print(f"  In DB NOT Python: {sorted(db_keys - py_keys)}")

	# Python plan_feature vs DB
	py_pf = {k: v[1] for k, v in SELLER_CAPABILITIES.items() if v[1]}
	db_pf_rows = frappe.db.sql(
		"SELECT name, plan_feature_flag FROM `tabTH Capability Registry` WHERE plan_feature_flag IS NOT NULL AND plan_feature_flag != ''",
		as_dict=True,
	)
	db_pf = {r["name"]: r["plan_feature_flag"] for r in db_pf_rows}
	print(f"\n  Python cap→plan_feature ({len(py_pf)}): {py_pf}")
	print(f"  DB cap→plan_feature_flag ({len(db_pf)}): {db_pf}")
	print("  Mismatches:")
	for k in sorted(set(py_pf) | set(db_pf)):
		if py_pf.get(k) != db_pf.get(k):
			print(f"    {k}: PY={py_pf.get(k)!s} DB={db_pf.get(k)!s}")

	# Catalog drift
	catalog_keys = set(frappe.db.sql_list("SELECT name FROM `tabFeature Catalog`"))
	used_db = set(db_pf.values())
	print(f"\n  Catalog keys: {len(catalog_keys)}")
	print(f"  DB plan_feature_flags NOT in Catalog (DRIFT!): {sorted(used_db - catalog_keys)}")

	# Plan flag keys vs Catalog
	plan_keys_union = set()
	plan_keys_per = {}
	for r in frappe.db.sql("SELECT name, capability_flags FROM `tabSubscription Plan`", as_dict=True):
		try:
			d = json.loads(r.get("capability_flags") or "{}")
			if isinstance(d, dict):
				plan_keys_per[r["name"]] = set(d.keys())
				plan_keys_union |= set(d.keys())
		except Exception:
			pass
	print(f"\n  Plan flag keys NOT in Catalog (DRIFT!): {sorted(plan_keys_union - catalog_keys)}")
	print(f"  Catalog keys NEVER in any plan: {sorted(catalog_keys - plan_keys_union)}")
	print(f"  Plan key counts: { {p: len(k) for p, k in plan_keys_per.items()} }")
