"""FAZ 9.8 — Mevcut satıcıların performans metriklerini gerçek veriden doldur.

Günlük scheduler (recompute_seller_performance_metrics) bundan sonra her gün
çalışacak; bu patch mevcut satıcıları beklemeden bir kez hesaplar:
total_orders (Order sayımı), response_rate/response_time (Listing Review yanıtı),
score_grade (rating). İdempotent — recompute saf, tekrar çalışınca aynı sonucu yazar.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	if not frappe.db.exists("DocType", "Admin Seller Profile"):
		return {"skipped": "no_doctype"}
	from tradehub_core.tasks import recompute_seller_performance_metrics

	recompute_seller_performance_metrics()
	return {"done": True}
