"""Sprint 6 — Feature Catalog DB ↔ fixture resync.

Fixture (feature_catalog.json) revize edildi ancak DB'ye sync edilmedi.
DB'de 15 eski key, fixture'da 40 yeni key var (%62 drift). Sonuç:
  - `feature.crm_module` ve `feature.rfq_module` DB'de var, ama fixture'da
    yeni isimler (`feature.crm.module`, `feature.functional.rfq`) ile yer
    almıyor → v15_6_10 patch'i Subscription Plan'a yeni key yazdığında
    `_validate_capability_flags` patlar.
  - Feature Catalog DB ↔ Subscription Plan capability_flags JSON arasında
    tutarsızlık.

Bu patch:
  1. fixture'daki tüm Feature Catalog entry'lerini DB'ye **upsert** eder
     (varsa update, yoksa insert) — disiplinli idempotent.
  2. Eski isimli iki kaydı (`feature.crm_module`, `feature.rfq_module`)
     KORUR ama `is_deprecated=1` flag'i ile işaretler — eski Subscription
     Plan capability_flags JSON'ları kırılmasın (v15_6_10 migration onları
     rename edecek).

Patch sırası: v15_6_11 → v15_6_10 (resync önce, key migration sonra).
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe


def _read_fixture() -> list[dict]:
	"""feature_catalog.json fixture'ını parse et."""
	app_path = Path(frappe.get_app_path("tradehub_core"))
	fixture_path = app_path / "tradehub_core" / "fixtures" / "feature_catalog.json"
	if not fixture_path.exists():
		return []
	with fixture_path.open("r", encoding="utf-8") as fp:
		return json.load(fp)


def execute() -> dict:
	fixture_entries = _read_fixture()
	if not fixture_entries:
		return {"upserted": 0, "deprecated": 0, "skipped_invalid": 0}

	upserted = 0
	skipped_invalid = 0
	fixture_keys: set[str] = set()

	for entry in fixture_entries:
		feature_key = entry.get("feature_key") or entry.get("name")
		if not feature_key or entry.get("doctype") != "Feature Catalog":
			skipped_invalid += 1
			continue
		fixture_keys.add(feature_key)

		fields = {
			"feature_key": feature_key,
			"display_name": entry.get("display_name") or feature_key,
			"category": entry.get("category") or "FunctionalFeatures",
			"feature_type": entry.get("feature_type") or "Capability",
			"default_value": entry.get("default_value", "false"),
			"description": entry.get("description") or "",
			"is_deprecated": 0,
		}

		existing = frappe.db.exists("Feature Catalog", feature_key)
		if existing:
			# Update — disiplinli upsert
			for k, v in fields.items():
				frappe.db.set_value("Feature Catalog", feature_key, k, v, update_modified=False)
		else:
			doc = frappe.new_doc("Feature Catalog")
			doc.update(fields)
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
		upserted += 1

	# Eski isimli kayıtları deprecated işaretle (mümkünse — DocType'ta
	# is_deprecated field'ı yoksa sessizce atla)
	deprecated = 0
	legacy_keys = ["feature.crm_module", "feature.rfq_module"]
	has_deprecated_field = "is_deprecated" in frappe.get_meta("Feature Catalog").get_valid_columns()
	for legacy in legacy_keys:
		if not frappe.db.exists("Feature Catalog", legacy):
			continue
		if has_deprecated_field:
			frappe.db.set_value("Feature Catalog", legacy, "is_deprecated", 1, update_modified=False)
		deprecated += 1

	frappe.db.commit()

	return {
		"upserted": upserted,
		"deprecated": deprecated,
		"skipped_invalid": skipped_invalid,
		"fixture_keys_count": len(fixture_keys),
	}
