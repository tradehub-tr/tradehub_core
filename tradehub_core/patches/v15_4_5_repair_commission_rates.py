"""FAZ 4.5 — Subscription Plan commission_rate + max_active_listings tamiri.

v15_4_1 seed condition'lı (`if not get_value(...)`), v15_4_2 force ise sadece
display field'larını yazıyor — aradaki bir noktada commission_rate'ler 0'a
düşmüş. Storefront matrix tablosu kart KOMISYON sütunundan farklı görünmesin
diye plan modelini referans değerlere getiriyoruz.

İdempotent — zaten doğru olan değerleri tekrar yazmaz.
"""

from __future__ import annotations

import frappe

_REPAIRS: dict[str, dict[str, float]] = {
	"FREE": {"commission_rate": 15.0, "max_active_listings": 10},
	"STARTER": {"commission_rate": 8.0, "max_active_listings": 50},
	"PRO": {"commission_rate": 6.0, "max_active_listings": 500},
	"ENTERPRISE": {"commission_rate": 4.0, "max_active_listings": 0},  # 0 = sınırsız
}


def execute() -> dict:
	if not frappe.db.exists("DocType", "Subscription Plan"):
		return {"skipped": "doctype_missing"}

	updated: list[str] = []
	for plan_code, fields in _REPAIRS.items():
		plan_name = frappe.db.get_value("Subscription Plan", {"plan_code": plan_code}, "name")
		if not plan_name:
			continue
		current = (
			frappe.db.get_value(
				"Subscription Plan",
				plan_name,
				list(fields.keys()),
				as_dict=True,
			)
			or {}
		)
		for field, new_value in fields.items():
			if float(current.get(field) or 0) == float(new_value):
				continue
			frappe.db.set_value("Subscription Plan", plan_name, field, new_value)
			updated.append(f"{plan_code}.{field}")

	if updated:
		frappe.db.commit()
		try:
			from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

			invalidate_pricing_cache()
		except Exception as exc:
			frappe.log_error(f"pricing cache invalidate failed: {exc}", "v15_4_5_repair")

	return {"updated": updated, "count": len(updated)}
