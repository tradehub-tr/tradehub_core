"""Faz I — Subscription Plan fixture seed (beta acil fix).

Frappe v15 `bench migrate` fixture import etmediği için (sadece schema +
patches.txt) `hooks.py:fixtures` listesinde tanımlı `Subscription Plan`
fixture kayıtları beta'da hiç insert edilmemiş — sonuç:
  - `public_pricing.get_pricing_plans` → `plans: []`
  - Storefront "Paketler şu anda yüklenemedi"
  - Admin panel Planlar tab boş

Bu patch fixture dosyasını okur, DB'de yoksa plan kaydını insert eder.
Mevcut kayıtlara DOKUNMAZ (UPPERCASE/lowercase fark etmez). v15_6_12 patch
zaten mevcut UPPERCASE plan'lara `capability_flags + quota_limits` yazar;
bu patch sadece "tamamen eksik" senaryosunu kapatır.

Idempotent: aynı `name` ile kayıt varsa skip.
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
		return {"seeded": 0, "skipped_existing": 0}

	seeded: list[str] = []
	skipped: list[str] = []

	for entry in fixture_plans:
		if entry.get("doctype") != "Subscription Plan":
			continue
		name = entry.get("name") or ""
		if not name:
			continue
		# Hem lowercase hem UPPERCASE varsa ikisi de skip edilsin
		if frappe.db.exists("Subscription Plan", name) or frappe.db.exists("Subscription Plan", name.upper()):
			skipped.append(name)
			continue

		doc = frappe.new_doc("Subscription Plan")
		# Tüm fixture field'larını uygula (doctype hariç)
		for k, v in entry.items():
			if k == "doctype":
				continue
			# JSON field'ları (capability_flags, quota_limits) string'e çevir
			if isinstance(v, (dict, list)) and k in ("capability_flags", "quota_limits"):
				v = json.dumps(v, ensure_ascii=False)
			doc.set(k, v)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		# Validate bypass — fixture'daki field'lar tutarlı varsayılır
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		seeded.append(doc.name)

	frappe.db.commit()

	# Public pricing cache flush — yeni plan'lar storefront'a anında yansır
	try:
		frappe.cache().delete_value("tradehub:pricing:public")
	except Exception:
		pass

	return {
		"seeded": seeded,
		"skipped_existing": skipped,
	}
