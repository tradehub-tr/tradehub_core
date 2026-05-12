"""Faz 5 — Review Analytics + Admin Dashboard.

Günlük cron `daily_snapshot` ile Review Analytics Snapshot kaydı oluşur.
`get_admin_dashboard_metrics` admin paneli için anlık metrikleri döner.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, now_datetime, today


def _safe_count(doctype: str, filters: dict | None = None) -> int:
	try:
		return int(frappe.db.count(doctype, filters=filters or {}))
	except Exception:
		return 0


def _safe_avg(doctype: str, field: str, filters: dict | None = None) -> float:
	try:
		filters = filters or {}
		where = "1=1"
		params = []
		for k, v in filters.items():
			where += f" AND `{k}` = %s"
			params.append(v)
		row = frappe.db.sql(
			f"SELECT AVG(`{field}`) FROM `tab{doctype}` WHERE {where}",
			params,
		)
		return round(float(row[0][0] or 0), 2)
	except Exception:
		return 0.0


def daily_snapshot():
	"""Daily scheduler — review analytics günlük snapshot."""
	d = getdate(today())
	existing = frappe.db.get_value("Review Analytics Snapshot", {"snapshot_date": d}, "name")
	if existing:
		# Aynı gün varsa güncelle
		doc = frappe.get_doc("Review Analytics Snapshot", existing)
	else:
		doc = frappe.new_doc("Review Analytics Snapshot")
		doc.snapshot_date = d

	doc.total_reviews = _safe_count("Listing Review")
	doc.approved_reviews = _safe_count("Listing Review", {"status": "Approved"})
	doc.pending_reviews = _safe_count("Listing Review", {"status": "Pending"})
	doc.hidden_reviews = _safe_count("Listing Review", {"status": "Hidden"})
	doc.rejected_reviews = _safe_count("Listing Review", {"status": "Rejected"})

	doc.avg_rating = _safe_avg("Listing Review", "rating", {"status": "Approved"})

	# Weighted average — Listing'lerin avg'sı (cache field)
	try:
		row = frappe.db.sql("SELECT AVG(weighted_rating) FROM `tabListing` WHERE weighted_rating > 0")
		doc.avg_weighted_rating = round(float(row[0][0] or 0), 2)
	except Exception:
		doc.avg_weighted_rating = 0

	# Risk skoru dağılımı
	try:
		risk_rows = frappe.db.sql(
			"""
			SELECT
				SUM(CASE WHEN risk_score >= 61 THEN 1 ELSE 0 END) AS high,
				SUM(CASE WHEN risk_score BETWEEN 31 AND 60 THEN 1 ELSE 0 END) AS med,
				SUM(CASE WHEN risk_score < 31 THEN 1 ELSE 0 END) AS low
			FROM `tabListing Review`
		""",
			as_dict=True,
		)
		if risk_rows:
			doc.high_risk_count = int(risk_rows[0].high or 0)
			doc.medium_risk_count = int(risk_rows[0].med or 0)
			doc.low_risk_count = int(risk_rows[0].low or 0)
	except Exception:
		pass

	doc.total_helpful_votes = _safe_count("Review Helpful Vote")
	doc.total_abuse_reports = _safe_count("Review Abuse Report")

	# Bugünkü çeviri sayısı
	try:
		today_str = str(d)
		row = frappe.db.sql(
			"SELECT COUNT(*) FROM `tabTranslation Usage Log` WHERE DATE(logged_at) = %s", (today_str,)
		)
		doc.total_translations_today = int(row[0][0] or 0) if row else 0
	except Exception:
		doc.total_translations_today = 0

	doc.total_disputes_open = _safe_count("Order Dispute", {"status": "Open"})

	# Reviewer tier dağılımı
	for tier_field, tier_name in [
		("newcomer_count", "Newcomer"),
		("trusted_count", "Trusted"),
		("top_contributor_count", "Top Contributor"),
		("verified_pro_count", "Verified Pro"),
	]:
		setattr(doc, tier_field, _safe_count("Reviewer Reputation", {"tier": tier_name}))

	doc.computed_at = now_datetime()

	if existing:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "snapshot": doc.name}


@frappe.whitelist()
def get_admin_dashboard_metrics():
	"""Admin paneli için anlık metrikler (snapshot beklemeden)."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)

	return {
		"total_reviews": _safe_count("Listing Review"),
		"pending_reviews": _safe_count("Listing Review", {"status": "Pending"}),
		"high_risk_today": _safe_count("Review Risk Score", {"is_high_risk": 1}),
		"open_disputes": _safe_count("Order Dispute", {"status": "Open"}),
		"active_invitations": _safe_count("Trusted Reviewer Invitation", {"status": "Invited"}),
		"translations_today": _safe_count("Translation Usage Log"),
		"tier_distribution": {
			"Newcomer": _safe_count("Reviewer Reputation", {"tier": "Newcomer"}),
			"Trusted": _safe_count("Reviewer Reputation", {"tier": "Trusted"}),
			"Top Contributor": _safe_count("Reviewer Reputation", {"tier": "Top Contributor"}),
			"Verified Pro": _safe_count("Reviewer Reputation", {"tier": "Verified Pro"}),
		},
	}


@frappe.whitelist()
def get_snapshot_history(days: int = 30):
	"""Son N gün için snapshot history (chart için)."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)
	rows = frappe.get_all(
		"Review Analytics Snapshot",
		fields=[
			"snapshot_date",
			"total_reviews",
			"approved_reviews",
			"avg_rating",
			"avg_weighted_rating",
			"high_risk_count",
			"total_disputes_open",
		],
		order_by="snapshot_date DESC",
		limit=int(days),
	)
	return {"snapshots": rows, "total": len(rows)}
