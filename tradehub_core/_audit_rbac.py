import json

import frappe


def patch_status():
	patches = [
		"v15_6_0_seed_capability_registry",
		"v15_6_1_seed_capability_grant",
		"v15_6_2_seed_module_registry",
		"v15_6_3_seed_module_policy",
		"v15_6_4_seed_view_tax_id",
		"v15_6_5_seed_view_customer_pii",
		"v15_6_6_apply_pii_permlevel",
		"v15_6_7_promote_pii_permlevel_to_2",
		"v15_6_8_lock_non_privileged_pii_read",
		"v15_6_9_backfill_user_role_profile",
		"v15_6_10_fix_capability_feature_flags",
	]
	out = {}
	for p in patches:
		r = frappe.db.get_value("Patch Log", {"patch": f"tradehub_core.patches.{p}"}, "name")
		out[p] = "RUN" if r else "MISSING"
	print("=== PATCH STATUS ===")
	for k, v in out.items():
		print(f"  {k}: {v}")


def cap_registry():
	if not frappe.db.table_exists("tabTH Capability Registry"):
		print("=== CAP REGISTRY: TABLE MISSING ===")
		return
	rows = frappe.get_all(
		"TH Capability Registry",
		fields=[
			"name",
			"capability_key",
			"plan_feature_flag",
			"is_owner_only",
			"requires_kyc",
			"requires_aml",
			"is_active",
			"default_tier",
			"module_group",
		],
	)
	print(f"=== CAP REGISTRY ({len(rows)} rows) ===")
	for r in sorted(rows, key=lambda x: x.get("capability_key") or ""):
		print(
			f"  {r.get('capability_key')!s:40s} plan_flag={r.get('plan_feature_flag')!s:30s} owner_only={r.get('is_owner_only')} kyc={r.get('requires_kyc')} aml={r.get('requires_aml')} active={r.get('is_active')} tier={r.get('default_tier')} mod={r.get('module_group')}"
		)


def feature_catalog():
	if not frappe.db.table_exists("tabFeature Catalog"):
		print("=== FEATURE CATALOG: TABLE MISSING ===")
		return
	rows = frappe.get_all("Feature Catalog", fields=["name", "feature_key", "feature_type", "category"])
	print(f"=== FEATURE CATALOG ({len(rows)} rows) ===")
	for r in sorted(rows, key=lambda x: x.get("name") or ""):
		print(f"  {r.get('name')!s:55s} type={r.get('feature_type')!s:12s} cat={r.get('category')}")


def plans():
	if not frappe.db.table_exists("tabSubscription Plan"):
		print("=== SUB PLAN: TABLE MISSING ===")
		return
	rows = frappe.get_all("Subscription Plan", fields=["name", "capability_flags"])
	print(f"=== SUBSCRIPTION PLANS ({len(rows)}) ===")
	for r in rows:
		raw = r.get("capability_flags")
		try:
			flags = json.loads(raw) if isinstance(raw, str) else raw
		except Exception:
			print(f"  {r['name']}: BAD JSON")
			continue
		if not isinstance(flags, dict):
			print(f"  {r['name']}: NOT DICT")
			continue
		print(f"  {r['name']}: keys={len(flags)} -- enabled={sum(1 for v in flags.values() if v)}")
		for k in sorted(flags.keys()):
			print(f"    {k} = {flags[k]}")


def drift():
	print("=== DRIFT CHECKS ===")
	# 1) cap registry keys vs python SELLER_CAPABILITIES
	from tradehub_core.utils.seller_capabilities import _OWNER_ONLY_CAPABILITIES, SELLER_CAPABILITIES

	if frappe.db.table_exists("tabTH Capability Registry"):
		db_keys = set(frappe.get_all("TH Capability Registry", pluck="capability_key"))
	else:
		db_keys = set()
	py_keys = set(SELLER_CAPABILITIES.keys()) | set(_OWNER_ONLY_CAPABILITIES)
	print(
		f"  Python total caps: {len(py_keys)} (SELLER_CAPABILITIES={len(SELLER_CAPABILITIES)} + OWNER_ONLY={len(_OWNER_ONLY_CAPABILITIES)})"
	)
	print(f"  DB Capability Registry caps: {len(db_keys)}")
	print(f"  In Python but NOT in DB: {sorted(py_keys - db_keys)}")
	print(f"  In DB but NOT in Python: {sorted(db_keys - py_keys)}")

	# 2) Python plan_feature (2nd tuple item) vs DB plan_feature_flag
	py_plan_map = {k: v[1] for k, v in SELLER_CAPABILITIES.items() if v[1]}
	db_plan_map = {}
	if frappe.db.table_exists("tabTH Capability Registry"):
		for r in frappe.get_all("TH Capability Registry", fields=["capability_key", "plan_feature_flag"]):
			if r.get("plan_feature_flag"):
				db_plan_map[r["capability_key"]] = r["plan_feature_flag"]
	print(f"\n  PYTHON cap → plan_feature mapping ({len(py_plan_map)}):")
	for k in sorted(py_plan_map):
		print(f"    {k} → {py_plan_map[k]}")
	print(f"  DB cap → plan_feature_flag mapping ({len(db_plan_map)}):")
	for k in sorted(db_plan_map):
		print(f"    {k} → {db_plan_map[k]}")
	common = set(py_plan_map) & set(db_plan_map)
	print("  MISMATCHES (different value in Python vs DB):")
	for k in sorted(common):
		if py_plan_map[k] != db_plan_map[k]:
			print(f"    {k}: PY={py_plan_map[k]} | DB={db_plan_map[k]}")

	# 3) DB cap registry plan_feature_flag set vs Feature Catalog
	if frappe.db.table_exists("tabFeature Catalog"):
		catalog_keys = set(frappe.get_all("Feature Catalog", pluck="name"))
	else:
		catalog_keys = set()
	used_db_flags = set(db_plan_map.values())
	used_py_flags = set(py_plan_map.values())
	print(f"\n  Feature Catalog keys: {len(catalog_keys)}")
	print(f"  DB plan_feature_flags NOT in Catalog: {sorted(used_db_flags - catalog_keys)}")
	print(f"  Python plan_features NOT in Catalog: {sorted(used_py_flags - catalog_keys)}")

	# 4) Subscription plan capability_flags JSON keys vs feature catalog
	plan_flags_union = set()
	if frappe.db.table_exists("tabSubscription Plan"):
		for r in frappe.get_all("Subscription Plan", fields=["name", "capability_flags"]):
			raw = r.get("capability_flags") or "{}"
			try:
				d = json.loads(raw) if isinstance(raw, str) else raw
				if isinstance(d, dict):
					plan_flags_union |= set(d.keys())
			except Exception:
				pass
	print(f"\n  Subscription Plan capability_flags total unique keys: {len(plan_flags_union)}")
	print(f"  Plan keys NOT in Catalog (drift!): {sorted(plan_flags_union - catalog_keys)}")
	print(f"  Catalog keys NEVER used in any plan: {sorted(catalog_keys - plan_flags_union)}")


def cap_grants():
	if not frappe.db.table_exists("tabTH Capability Grant"):
		print("=== CAP GRANT: TABLE MISSING ===")
		return
	rows = frappe.get_all("TH Capability Grant", fields=["name", "role_profile", "capability_key"])
	print(f"=== CAPABILITY GRANT ({len(rows)} rows) ===")
	# Group by profile
	by_profile = {}
	for r in rows:
		by_profile.setdefault(r.get("role_profile"), []).append(r.get("capability_key"))
	for prof, caps in sorted(by_profile.items()):
		print(f"\n  Profile: {prof} ({len(caps)} caps)")
		for c in sorted(caps):
			print(f"    {c}")


def run():
	patch_status()
	print()
	cap_registry()
	print()
	feature_catalog()
	print()
	drift()
	print()
	cap_grants()
	print()
	plans()
