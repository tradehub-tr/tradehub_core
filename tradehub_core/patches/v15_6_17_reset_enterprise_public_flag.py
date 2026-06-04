"""Faz H.1 — ENTERPRISE plan `is_public` reset (D17).

Fixture `subscription_plan.json` ENTERPRISE plan'ı `is_public: 0` ile
tanımlıyor — niyet "contact sales" akışı için storefront pricing card'ında
gösterilmemesi. Ancak DB'de bir yerde `is_public=1` set edilmiş; bu
storefront'tan capability_flags/quota_limits gibi privileged plan
ayarlarının sızdırılmasına neden olabilir (`public_pricing.py:get_pricing_plans`
`is_public=1` filter ile ENTERPRISE'ı public listeye dahil ediyor).

Bu patch DB'de `ENTERPRISE.is_public=0` set eder. Idempotent: zaten 0 ise
skip.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	if not frappe.db.exists("Subscription Plan", "ENTERPRISE"):
		return {"skipped": "ENTERPRISE plan not found"}

	current = frappe.db.get_value("Subscription Plan", "ENTERPRISE", "is_public")
	if current == 0:
		return {"already_private": True}

	frappe.db.set_value(
		"Subscription Plan",
		"ENTERPRISE",
		"is_public",
		0,
		update_modified=False,
	)
	frappe.db.commit()

	# Public pricing cache flush
	try:
		frappe.cache().delete_keys("tradehub:pricing:public")
	except Exception:
		pass

	return {"reset": "ENTERPRISE.is_public=0"}
