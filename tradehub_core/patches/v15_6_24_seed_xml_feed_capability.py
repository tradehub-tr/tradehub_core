"""Sprint 6 — `feature.import.xml_feed` capability'sini sisteme tanıt.

Paket 2 (XML Feed) entitlement flag'i. İki şey yapar:

  1. Feature Catalog'a `feature.import.xml_feed` entry'sini upsert eder
     (PlansTab "Yetkinlikler" sekmesinin key'i tanıması ve super admin'in
     editleyebilmesi için katalogda bulunmalı).
  2. Mevcut 4 Subscription Plan kaydının capability_flags JSON'una flag'i
     ekler — free=false, starter/pro/enterprise=true. Sadece flag JSON'da
     YOKSA ekler (idempotent; super admin'in elle değiştirdiği değeri ezmez).

Plan kodları DB'de UPPERCASE (FREE/STARTER/PRO/ENTERPRISE) seed edilmiştir
(bkz. v15_6_12). Fixture lowercase olduğu için burada upper() ile eşleştirilir.

Patch tekrar çalışırsa kırılmaz: katalog upsert idempotent, plan flag'i zaten
varsa atlanır.
"""

from __future__ import annotations

import json

import frappe

FEATURE_KEY = "feature.import.xml_feed"

# Plan kodu (UPPERCASE DB karşılığı) → flag default değeri
_PLAN_DEFAULTS = {
	"FREE": False,
	"STARTER": True,
	"PRO": True,
	"ENTERPRISE": True,
}

_CATALOG_FIELDS = {
	"feature_key": FEATURE_KEY,
	"display_name": "XML Feed ile Otomatik Ürün Çekme",
	"category": "PIMFeatures",
	"feature_type": "Capability",
	"default_value": "false",
	"description": ("Satıcının XML feed URL'sinden zamanlanmış (24 saatlik) otomatik ürün içe aktarımı."),
}


def _upsert_catalog() -> str:
	"""Feature Catalog'a entry'yi upsert et. 'inserted' | 'updated' döner."""
	if frappe.db.exists("Feature Catalog", FEATURE_KEY):
		for k, v in _CATALOG_FIELDS.items():
			frappe.db.set_value("Feature Catalog", FEATURE_KEY, k, v, update_modified=False)
		return "updated"

	doc = frappe.new_doc("Feature Catalog")
	doc.update(_CATALOG_FIELDS)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return "inserted"


def execute() -> dict:
	catalog_action = _upsert_catalog()

	seeded: list[str] = []
	already_present: list[str] = []
	missing_plan: list[str] = []

	for plan_code, default_value in _PLAN_DEFAULTS.items():
		if not frappe.db.exists("Subscription Plan", plan_code):
			missing_plan.append(plan_code)
			continue

		raw = frappe.db.get_value("Subscription Plan", plan_code, "capability_flags")
		try:
			flags = json.loads(raw) if raw else {}
		except (ValueError, TypeError):
			flags = {}

		# Idempotent: super admin elle ayarladıysa ezme.
		if FEATURE_KEY in flags:
			already_present.append(plan_code)
			continue

		flags[FEATURE_KEY] = default_value
		frappe.db.set_value(
			"Subscription Plan",
			plan_code,
			"capability_flags",
			json.dumps(flags, ensure_ascii=False),
			update_modified=False,
		)
		seeded.append(plan_code)

	frappe.db.commit()

	# Plan değiştiyse etkilenen store'ların entitlement cache'ini temizle.
	if seeded:
		from tradehub_core.entitlement import invalidate_plan_cache

		for plan_code in seeded:
			invalidate_plan_cache(plan_code)

	return {
		"catalog": catalog_action,
		"seeded": seeded,
		"already_present": already_present,
		"missing_plan": missing_plan,
	}
