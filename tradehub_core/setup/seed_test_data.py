"""Test data seed — Plan + Region + minimum feature catalog.

Idempotent: var olanları atlar.
"""

from __future__ import annotations

import frappe

_PLANS = [
	{
		"plan_code": "FREE",
		"plan_name": "Free",
		"monthly_price": 0,
		"currency": "EUR",
		"description": "Free tier — temel marketplace erişimi",
	},
	{
		"plan_code": "STARTER",
		"plan_name": "Starter",
		"monthly_price": 399,
		"currency": "EUR",
		"description": "Starter — küçük işletme için temel paket",
	},
	{
		"plan_code": "PRO",
		"plan_name": "Pro",
		"monthly_price": 599,
		"currency": "EUR",
		"description": "Pro — B2B onay zinciri + advanced features",
	},
	{
		"plan_code": "ENTERPRISE",
		"plan_name": "Enterprise",
		"monthly_price": 0,
		"currency": "EUR",
		"description": "Enterprise — custom price, full feature set",
	},
]

_REGIONS = [
	{
		"region_code": "TR",
		"region_name": "Türkiye",
		"region_type": "country",
		"jurisdiction": "KVKK",
		"default_currency": "TRY",
		"default_language": "tr",
		"countries": "TR",
	},
	{
		"region_code": "EU",
		"region_name": "European Union",
		"region_type": "economic_zone",
		"jurisdiction": "GDPR",
		"default_currency": "EUR",
		"default_language": "en",
		"countries": "DE,FR,IT,ES,NL,BE,AT,PT,IE,FI,SE,DK,PL,CZ,HU,RO,BG,HR,SI,SK,LU,LT,LV,EE,CY,MT,GR",
	},
	{
		"region_code": "MENA",
		"region_name": "Middle East & North Africa",
		"region_type": "economic_zone",
		"jurisdiction": "MENA",
		"default_currency": "USD",
		"default_language": "ar",
		"countries": "AE,SA,EG,QA,KW,OM,BH,JO,LB,IL,MA,DZ,TN,LY",
	},
	{
		"region_code": "CIS",
		"region_name": "Commonwealth of Independent States",
		"region_type": "economic_zone",
		"jurisdiction": "CIS",
		"default_currency": "USD",
		"default_language": "ru",
		"countries": "AZ,KZ,UZ,TM,KG,RU,BY,AM",
	},
]


def execute() -> dict:
	"""Plan + Region seed."""
	created_plans = []
	skipped_plans = []
	for spec in _PLANS:
		code = spec["plan_code"]
		if frappe.db.exists("Subscription Plan", {"plan_code": code}):
			skipped_plans.append(code)
			continue
		try:
			doc = frappe.new_doc("Subscription Plan")
			for k, v in spec.items():
				setattr(doc, k, v)
			doc.is_active = 1
			doc.insert(ignore_permissions=True)
			created_plans.append(code)
		except Exception as exc:
			frappe.log_error(f"Plan seed failed for {code}: {exc}", "seed_test_data")

	created_regions = []
	skipped_regions = []
	for spec in _REGIONS:
		code = spec["region_code"]
		if frappe.db.exists("Region", code):
			skipped_regions.append(code)
			continue
		try:
			doc = frappe.new_doc("Region")
			for k, v in spec.items():
				setattr(doc, k, v)
			doc.is_active = 1
			doc.insert(ignore_permissions=True)
			created_regions.append(code)
		except Exception as exc:
			frappe.log_error(f"Region seed failed for {code}: {exc}", "seed_test_data")

	frappe.db.commit()
	return {
		"plans_created": created_plans,
		"plans_skipped": skipped_plans,
		"regions_created": created_regions,
		"regions_skipped": skipped_regions,
	}
