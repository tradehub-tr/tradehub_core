"""Faz 6 — Listing A/B Testing Framework.

Aynı satıcının farklı varyasyonlarını review metric'leriyle karşılaştır.
Daily scheduler `evaluate_finished_tests` ile bitmiş test'lerin winner'ı
hesaplanır ve cache'lenir.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, today


def _metric_value(listing: str, metric: str) -> float:
	"""Verilen metric için bir Listing'in skoru."""
	if metric == "weighted_rating":
		return float(frappe.db.get_value("Listing", listing, "weighted_rating") or 0)
	if metric == "review_count":
		return float(frappe.db.get_value("Listing", listing, "review_count") or 0)
	if metric == "helpful_ratio":
		row = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(helpful_count), 0) AS h,
				COALESCE(SUM(not_helpful_count), 0) AS nh
			FROM `tabListing Review`
			WHERE listing=%s AND status='Approved'
		""",
			(listing,),
			as_dict=True,
		)
		total = float(row[0].h + row[0].nh) if row else 0
		return float(row[0].h * 100 / total) if total else 0
	if metric == "dispute_rate":
		row = frappe.db.sql(
			"""
			SELECT COUNT(*) AS d FROM `tabListing Review`
			WHERE listing=%s AND status='Approved'
			  AND related_dispute IS NOT NULL
		""",
			(listing,),
		)
		total = float(frappe.db.count("Listing Review", {"listing": listing, "status": "Approved"}))
		dis = float(row[0][0] or 0) if row else 0
		# Lower is better → invert
		return -dis * 100 / total if total else 0
	return 0


@frappe.whitelist()
def start_ab_test(test_name: str) -> dict:
	"""Bir AB Test'i Draft'tan Running'e geçir."""
	from tradehub_core.api.review import _is_admin

	doc = frappe.get_doc("Listing AB Test", test_name)
	# Seller veya admin
	user = frappe.session.user
	seller_user = frappe.db.get_value("Admin Seller Profile", doc.seller, "user")
	if not _is_admin() and seller_user != user:
		frappe.throw("Yetkisiz", frappe.PermissionError)
	if doc.status != "Draft":
		frappe.throw(f"Test zaten {doc.status} durumda")
	if not doc.variants or len(doc.variants) < 2:
		frappe.throw("En az 2 varyant gerekli")

	doc.status = "Running"
	doc.start_date = getdate(today())
	from frappe.utils import add_to_date

	doc.end_date = add_to_date(getdate(today()), days=int(doc.test_period_days or 30))
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "status": "Running", "start": doc.start_date, "end": doc.end_date}


def _evaluate_one(doc) -> dict:
	"""Bir AB Test için winner hesabı."""
	scores = []
	for variant in doc.variants or []:
		score = _metric_value(variant.variant_listing, doc.metric)
		scores.append((variant.variant_listing, score))
	if not scores:
		return {"winner": None, "score": 0}
	scores.sort(key=lambda x: -x[1])
	winner, top_score = scores[0]
	return {"winner": winner, "score": round(top_score, 2), "all_scores": scores}


@frappe.whitelist()
def evaluate_ab_test(test_name: str) -> dict:
	"""Manuel evaluate (admin) — sonucu Test'e yaz."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)
	doc = frappe.get_doc("Listing AB Test", test_name)
	out = _evaluate_one(doc)
	doc.winner = out["winner"]
	doc.winner_score = out["score"]
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return out


def evaluate_finished_tests():
	"""Daily scheduler — bitmiş test'leri evaluate et + Completed yap."""
	cutoff = today()
	tests = frappe.get_all(
		"Listing AB Test", filters={"status": "Running", "end_date": ["<=", cutoff]}, pluck="name"
	)
	for t in tests:
		try:
			doc = frappe.get_doc("Listing AB Test", t)
			out = _evaluate_one(doc)
			doc.winner = out["winner"]
			doc.winner_score = out["score"]
			doc.status = "Completed"
			doc.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(title="ab_evaluate_failed", message=f"test={t}")
	frappe.db.commit()


@frappe.whitelist()
def get_ab_test_report(test_name: str) -> dict:
	"""Test detayını + her varyantın güncel score'ını döner."""
	doc = frappe.get_doc("Listing AB Test", test_name)
	out = _evaluate_one(doc)
	return {
		"name": doc.name,
		"status": doc.status,
		"metric": doc.metric,
		"seller": doc.seller,
		"start_date": doc.start_date,
		"end_date": doc.end_date,
		"winner": doc.winner,
		"winner_score": doc.winner_score,
		"live_scores": out["all_scores"],
	}
