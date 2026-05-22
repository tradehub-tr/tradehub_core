"""FAZ 4.4 — Pricing CTA dilini birleştir: Basic/Starter/Pro = "Ücretsiz başla".

Önceki preset (v15_4_2) plan-specific CTA'lar yazıyordu ("Starter ile başla",
"Professional seç"). UI ekibi tek bir "Ücretsiz başla" mesajının daha güçlü
dönüşüm verdiğini gözlemledi — Enterprise hariç hepsi tek dile geliyor.

İdempotent: aynı değer zaten set ise no-op. Public pricing cache invalidate.
"""

from __future__ import annotations

import frappe

_UNIFIED_LABEL = "Ücretsiz başla"
_TARGET_PLAN_CODES = ("FREE", "STARTER", "PRO")


def execute() -> dict:
	if not frappe.db.exists("DocType", "Subscription Plan"):
		return {"skipped": "doctype_missing"}

	updated: list[str] = []
	for plan_code in _TARGET_PLAN_CODES:
		plan_name = frappe.db.get_value(
			"Subscription Plan", {"plan_code": plan_code}, "name"
		)
		if not plan_name:
			continue
		current = frappe.db.get_value("Subscription Plan", plan_name, "cta_label")
		if current == _UNIFIED_LABEL:
			continue
		frappe.db.set_value("Subscription Plan", plan_name, "cta_label", _UNIFIED_LABEL)
		updated.append(plan_code)

	if updated:
		frappe.db.commit()
		# Storefront 5 dk cache — invalidate et ki yeni metin hemen görünsün
		try:
			from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

			invalidate_pricing_cache()
		except Exception as exc:
			frappe.log_error(f"pricing cache invalidate failed: {exc}", "v15_4_4_unify_cta")

	return {"updated": updated, "count": len(updated)}
