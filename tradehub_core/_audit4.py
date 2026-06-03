import json

import frappe


def run():
	# Capability Grant - capability column
	print("=== CAP GRANT (by role_profile) ===")
	rows = frappe.db.sql(
		"""SELECT role_profile, capability, granted FROM `tabTH Capability Grant` ORDER BY role_profile, capability""",
		as_dict=True,
	)
	by = {}
	for r in rows:
		if r["granted"]:
			by.setdefault(r["role_profile"], []).append(r["capability"])
	for prof in sorted(by.keys()):
		caps = by[prof]
		print(f"\n  {prof} ({len(caps)} granted caps):")
		for c in caps:
			print(f"    {c}")

	# Plan capability_flags JSON
	print("\n\n=== SUBSCRIPTION PLAN capability_flags ===")
	rows = frappe.db.sql(
		"""SELECT name, capability_flags FROM `tabSubscription Plan` ORDER BY name""", as_dict=True
	)
	plan_keys_per = {}
	plan_keys_union = set()
	for r in rows:
		raw = r.get("capability_flags") or "{}"
		try:
			d = json.loads(raw) if isinstance(raw, str) else raw
		except Exception:
			d = {}
		if isinstance(d, dict):
			plan_keys_per[r["name"]] = d
			plan_keys_union |= set(d.keys())
			print(f"\n  Plan: {r['name']} (keys={len(d)}, true={sum(1 for v in d.values() if v)})")
			for k in sorted(d.keys()):
				print(f"    {k} = {d[k]}")

	# Drift
	print("\n\n=== DRIFT SUMMARY ===")
	from tradehub_core.utils.seller_capabilities import _OWNER_ONLY_CAPABILITIES, SELLER_CAPABILITIES

	py_keys = set(SELLER_CAPABILITIES.keys()) | set(_OWNER_ONLY_CAPABILITIES)
	db_keys = set(frappe.db.sql_list("SELECT name FROM `tabTH Capability Registry`"))
	print(f"  Python total caps: {len(py_keys)}")
	print(f"  DB Cap Registry caps: {len(db_keys)}")
	print(f"  In Python NOT in DB: {sorted(py_keys - db_keys)}")
	print(f"  In DB NOT in Python: {sorted(db_keys - py_keys)}")

	py_pf = {k: v[1] for k, v in SELLER_CAPABILITIES.items() if v[1]}
	db_pf_rows = frappe.db.sql(
		"SELECT name, plan_feature_flag FROM `tabTH Capability Registry` WHERE plan_feature_flag IS NOT NULL AND plan_feature_flag != ''",
		as_dict=True,
	)
	db_pf = {r["name"]: r["plan_feature_flag"] for r in db_pf_rows}
	print(f"\n  Python cap → plan_feature: {py_pf}")
	print(f"  DB cap → plan_feature_flag: {db_pf}")
	print("  MISMATCHES:")
	for k in sorted(set(py_pf) | set(db_pf)):
		if py_pf.get(k) != db_pf.get(k):
			print(f"    {k}: PY={py_pf.get(k)} DB={db_pf.get(k)}")

	catalog_keys = set(frappe.db.sql_list("SELECT name FROM `tabFeature Catalog`"))
	used_db = set(db_pf.values())
	used_py = set(py_pf.values())
	print(f"\n  Feature Catalog DB keys ({len(catalog_keys)}): {sorted(catalog_keys)}")
	print(f"\n  DB plan_feature_flags NOT in Catalog (DRIFT!): {sorted(used_db - catalog_keys)}")
	print(f"  Python plan_features NOT in Catalog (DRIFT!): {sorted(used_py - catalog_keys)}")
	print(f"\n  Plan flag keys NOT in Catalog (DRIFT!): {sorted(plan_keys_union - catalog_keys)}")
	print(f"  Catalog keys NEVER in any plan: {sorted(catalog_keys - plan_keys_union)}")

	# Check fixture-file Feature Catalog vs DB
	import os

	fc_path = "/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tradehub_core/fixtures/feature_catalog.json"
	if os.path.exists(fc_path):
		with open(fc_path) as f:
			data = json.load(f)
		fixture_keys = {d.get("name") for d in data}
		print(f"\n  Feature Catalog FIXTURE keys ({len(fixture_keys)})")
		print(f"  In fixture NOT in DB: {sorted(fixture_keys - catalog_keys)}")
		print(f"  In DB NOT in fixture: {sorted(catalog_keys - fixture_keys)}")

	# Check plan fixture
	sp_path = "/home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/tradehub_core/fixtures/subscription_plan.json"
	if os.path.exists(sp_path):
		with open(sp_path) as f:
			data = json.load(f)
		for d in data:
			try:
				pf = json.loads(d.get("capability_flags", "{}"))
				print(
					f"\n  FIXTURE Plan {d['name']}: keys={len(pf)} (vs DB {len(plan_keys_per.get(d['name'], {}))})"
				)
				fkeys = set(pf.keys())
				dkeys = set(plan_keys_per.get(d["name"], {}).keys())
				if fkeys - dkeys:
					print(f"    In fixture NOT in DB: {sorted(fkeys - dkeys)}")
				if dkeys - fkeys:
					print(f"    In DB NOT in fixture: {sorted(dkeys - fkeys)}")
			except Exception as e:
				print(f"   ERR parse {d.get('name')}: {e}")
