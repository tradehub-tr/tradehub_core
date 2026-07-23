"""Hızlı setup: tenant'a aktif Store Subscription bağla."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate


def assign_plan(tenant: str, plan_code: str = "PRO") -> dict:
	"""Tenant'a Pro plan ata (Store Subscription oluştur)."""
	if not frappe.db.exists("Admin Seller Profile", tenant):
		return {"error": f"Tenant {tenant} yok"}

	plan_name = frappe.db.get_value("Subscription Plan", {"plan_code": plan_code}, "name")
	if not plan_name:
		return {"error": f"Plan {plan_code} yok"}

	existing = frappe.db.get_value(
		"Store Subscription",
		{"tenant": tenant, "status": "Active"},
		"name",
	)

	if existing:
		doc = frappe.get_doc("Store Subscription", existing)
		doc.subscription_plan = plan_name
		try:
			doc.max_sub_users = 25
			doc.max_listings = 500
		except Exception:
			frappe.log_error("Store Subscription field set failed on update", "seed_subscription")
			pass
		doc.save(ignore_permissions=True)
		action = "updated"
	else:
		doc = frappe.new_doc("Store Subscription")
		doc.tenant = tenant
		doc.subscription_plan = plan_name
		doc.status = "Active"
		doc.start_date = nowdate()
		doc.end_date = add_days(nowdate(), 365)
		try:
			doc.max_sub_users = 25
			doc.max_listings = 500
		except Exception:
			frappe.log_error("Store Subscription field set failed on insert", "seed_subscription")
			pass
		doc.insert(ignore_permissions=True)
		action = "created"

	frappe.db.commit()
	return {
		"ok": True,
		"tenant": tenant,
		"plan": plan_code,
		"action": action,
		"max_sub_users": 25,
	}
