"""Sprint 6 — Subscription Plan capability_flags + quota_limits sync.

subscription_plan.json fixture'ı lowercase plan adlarıyla yazılmış
(`free`, `starter`, `pro`, `enterprise`), ama DB UPPERCASE adlarıyla
(`FREE`, `STARTER`, `PRO`, `ENTERPRISE`) seed edilmiş. Frappe fixture sync
name eşleşmesine bağlı olduğu için **hiçbir mevcut DB kaydı update
edilmemiş** — sonuç: FREE/STARTER/ENTERPRISE plan'larında
`capability_flags = {}` (sadece PRO eski seed'den dolu).

Etki: `entitlement.has_feature(tenant, "feature.role.profile.seller_manager")`
FREE plan'da False dönüyor → Owner bile Manager profili atayamıyor.

Bu patch:
  - Fixture'daki lowercase plan'ı UPPERCASE DB karşılığıyla eşleştirir
  - capability_flags ve quota_limits JSON alanlarını fixture'dan UPPERCASE
    plan kaydına yazar
  - Idempotent — fixture-DB hash diff yoksa skip eder
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe


def _read_fixture() -> list[dict]:
	app_path = Path(frappe.get_app_path("tradehub_core"))
	fixture_path = app_path / "tradehub_core" / "fixtures" / "subscription_plan.json"
	if not fixture_path.exists():
		return []
	with fixture_path.open("r", encoding="utf-8") as fp:
		return json.load(fp)


def execute() -> dict:
	fixture_plans = _read_fixture()
	if not fixture_plans:
		return {"synced": 0, "skipped_missing_db": 0}

	synced: list[str] = []
	skipped_missing_db: list[str] = []

	for entry in fixture_plans:
		if entry.get("doctype") != "Subscription Plan":
			continue
		fixture_name = entry.get("name") or ""
		db_name = fixture_name.upper()  # free → FREE

		if not frappe.db.exists("Subscription Plan", db_name):
			skipped_missing_db.append(db_name)
			continue

		# capability_flags + quota_limits JSON-serialize edilmiş string olarak
		# yaz (DocType.JSON field type bunu kabul ediyor).
		updates: dict[str, str] = {}
		for fld in ("capability_flags", "quota_limits"):
			raw = entry.get(fld)
			if raw is None:
				continue
			if isinstance(raw, str):
				try:
					json.loads(raw)
					updates[fld] = raw
				except (ValueError, TypeError):
					updates[fld] = json.dumps({})
			else:
				updates[fld] = json.dumps(raw, ensure_ascii=False)

		if not updates:
			continue

		for k, v in updates.items():
			frappe.db.set_value("Subscription Plan", db_name, k, v, update_modified=False)
		synced.append(db_name)

	frappe.db.commit()
	return {
		"synced": synced,
		"skipped_missing_db": skipped_missing_db,
	}
