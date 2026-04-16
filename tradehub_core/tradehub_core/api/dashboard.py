# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Platform Dashboard API for super admins.

Provides aggregated platform-wide metrics:
- Overview KPIs (GMV, orders, AOV, payment success, pending applications)
- GMV trend (time series)
- Seller onboarding funnel
- Top sellers by revenue
- Seller application status breakdown
- Profile status breakdown
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, getdate, nowdate

ORDER_STATUS_COMPLETED = ("Kargoda", "Tamamlandı")
ORDER_STATUS_CANCELLED = ("İptal Edildi",)
PAYMENT_STATUS_SUCCESS = ("Tamamlandı", "Eşleşti")


def _is_super_admin():
	"""Check if current user is a platform super admin."""
	user = frappe.session.user
	if user == "Administrator":
		return True
	roles = frappe.get_roles(user)
	return "System Manager" in roles or "Marketplace Manager" in roles


def _require_super_admin():
	if not _is_super_admin():
		frappe.throw(
			_("Bu veriye erişim yetkiniz yok."),
			frappe.PermissionError,
		)


def _date_range(period):
	"""Resolve preset period keys into (from_date, to_date, bucket)."""
	today = getdate(nowdate())
	if period == "7d":
		return add_days(today, -6), today, "day"
	if period == "30d":
		return add_days(today, -29), today, "day"
	if period == "90d":
		return add_days(today, -89), today, "week"
	if period == "365d":
		return add_months(today, -12), today, "month"
	return add_days(today, -29), today, "day"


@frappe.whitelist()
def get_platform_overview(period="30d"):
	"""Return top-level KPIs and breakdowns for the super admin overview.

	Args:
	    period: Preset key — "7d" | "30d" | "90d" | "365d"

	Returns:
	    dict with keys: kpis, application_status, profile_status,
	    previous_period_kpis
	"""
	_require_super_admin()

	from_date, to_date, _bucket = _date_range(period)
	prev_to = add_days(from_date, -1)
	span_days = (getdate(to_date) - getdate(from_date)).days + 1
	prev_from = add_days(prev_to, -(span_days - 1))

	current = _kpi_block(from_date, to_date)
	previous = _kpi_block(prev_from, prev_to)

	return {
		"period": period,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"kpis": current,
		"previous_kpis": previous,
		"application_status": _application_status_breakdown(),
		"profile_status": _profile_status_breakdown(),
		"totals": _platform_totals(),
	}


def _kpi_block(from_date, to_date):
	"""Compute KPI aggregates for a given date range."""
	# GMV: sum of completed order totals in range
	gmv_row = frappe.db.sql(
		"""
        SELECT
            COALESCE(SUM(total), 0) AS gmv,
            COUNT(*) AS order_count,
            COALESCE(AVG(total), 0) AS aov
        FROM `tabOrder`
        WHERE order_date BETWEEN %(from_date)s AND %(to_date)s
          AND status NOT IN %(cancelled)s
        """,
		{
			"from_date": from_date,
			"to_date": to_date,
			"cancelled": ORDER_STATUS_CANCELLED,
		},
		as_dict=True,
	)
	gmv = flt(gmv_row[0].gmv) if gmv_row else 0.0
	order_count = cint(gmv_row[0].order_count) if gmv_row else 0
	aov = flt(gmv_row[0].aov) if gmv_row else 0.0

	# Payment success rate
	pay_row = frappe.db.sql(
		"""
        SELECT
            SUM(CASE WHEN status IN %(success)s THEN 1 ELSE 0 END) AS success_count,
            COUNT(*) AS total
        FROM `tabPayment Transaction`
        WHERE transaction_date BETWEEN %(from_date)s AND %(to_date)s
        """,
		{
			"from_date": from_date,
			"to_date": to_date,
			"success": PAYMENT_STATUS_SUCCESS,
		},
		as_dict=True,
	)
	pay_total = cint(pay_row[0].total) if pay_row else 0
	pay_success = cint(pay_row[0].success_count) if pay_row else 0
	payment_success_rate = (pay_success / pay_total * 100) if pay_total else 0.0

	# Pending applications (global — not time-windowed)
	pending_apps = frappe.db.count(
		"Seller Application",
		filters=[["status", "in", ["Submitted", "Under Review"]]],
	)

	# Open RFQs (global)
	open_rfqs = frappe.db.count(
		"RFQ",
		filters=[["status", "in", ["Pending", "Approved"]]],
	)

	return {
		"gmv": round(gmv, 2),
		"order_count": order_count,
		"aov": round(aov, 2),
		"payment_success_rate": round(payment_success_rate, 1),
		"pending_applications": pending_apps,
		"open_rfqs": open_rfqs,
	}


def _application_status_breakdown():
	"""Count seller applications per status."""
	rows = frappe.db.sql(
		"""
        SELECT status, COUNT(*) AS count
        FROM `tabSeller Application`
        GROUP BY status
        """,
		as_dict=True,
	)
	return {r.status or "Unknown": cint(r.count) for r in rows}


def _profile_status_breakdown():
	"""Count buyer and seller profiles per status."""
	buyers = frappe.db.sql(
		"""
        SELECT status, COUNT(*) AS count
        FROM `tabBuyer Profile`
        GROUP BY status
        """,
		as_dict=True,
	)
	sellers = frappe.db.sql(
		"""
        SELECT status, COUNT(*) AS count
        FROM `tabAdmin Seller Profile`
        GROUP BY status
        """,
		as_dict=True,
	)
	return {
		"buyer": {r.status or "Unknown": cint(r.count) for r in buyers},
		"seller": {r.status or "Unknown": cint(r.count) for r in sellers},
	}


def _platform_totals():
	"""Total user/profile counts."""
	return {
		"users": frappe.db.count("User", filters=[["user_type", "=", "System User"], ["enabled", "=", 1]]),
		"buyer_profiles": frappe.db.count("Buyer Profile"),
		"seller_profiles": frappe.db.count("Admin Seller Profile"),
		"seller_applications": frappe.db.count("Seller Application"),
	}


@frappe.whitelist()
def get_gmv_trend(period="30d"):
	"""Return GMV and order count bucketed over time.

	Args:
	    period: "7d" | "30d" | "90d" | "365d"

	Returns:
	    dict with keys: bucket, points:[{label, gmv, orders}]
	"""
	_require_super_admin()

	from_date, to_date, bucket = _date_range(period)

	if bucket == "day":
		fmt = "%Y-%m-%d"
	elif bucket == "week":
		fmt = "%x-W%v"
	else:
		fmt = "%Y-%m"

	rows = frappe.db.sql(
		"""
        SELECT
            DATE_FORMAT(order_date, %(fmt)s) AS label,
            MIN(order_date) AS bucket_start,
            COALESCE(SUM(total), 0) AS gmv,
            COUNT(*) AS orders
        FROM `tabOrder`
        WHERE order_date BETWEEN %(from_date)s AND %(to_date)s
          AND status NOT IN %(cancelled)s
        GROUP BY label
        ORDER BY bucket_start ASC
        """,
		{
			"fmt": fmt,
			"from_date": from_date,
			"to_date": to_date,
			"cancelled": ORDER_STATUS_CANCELLED,
		},
		as_dict=True,
	)

	points = [
		{
			"label": r.label,
			"bucket_start": str(r.bucket_start) if r.bucket_start else None,
			"gmv": round(flt(r.gmv), 2),
			"orders": cint(r.orders),
		}
		for r in rows
	]

	return {
		"period": period,
		"bucket": bucket,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"points": points,
	}


@frappe.whitelist()
def get_onboarding_funnel():
	"""Return seller onboarding funnel stages with counts.

	Stages:
	1. Total users (Website User)
	2. Submitted seller application (any status)
	3. Under Review
	4. Approved
	5. Active seller profile
	"""
	_require_super_admin()

	total_users = frappe.db.count("User", filters=[["user_type", "=", "System User"], ["enabled", "=", 1]])
	total_applications = frappe.db.count("Seller Application")
	under_review = frappe.db.count("Seller Application", filters=[["status", "=", "Under Review"]])
	approved = frappe.db.count("Seller Application", filters=[["status", "=", "Approved"]])
	active_sellers = frappe.db.count("Admin Seller Profile", filters=[["status", "=", "Active"]])

	return {
		"stages": [
			{"key": "users", "label": "Kullanıcı", "count": total_users},
			{"key": "applications", "label": "Başvuru", "count": total_applications},
			{"key": "under_review", "label": "İnceleniyor", "count": under_review},
			{"key": "approved", "label": "Onaylandı", "count": approved},
			{"key": "active", "label": "Aktif Satıcı", "count": active_sellers},
		],
	}


@frappe.whitelist()
def get_top_sellers(metric="gmv", period="30d", limit=10):
	"""Return top sellers ranked by GMV or order count.

	Args:
	    metric: "gmv" | "orders"
	    period: "7d" | "30d" | "90d" | "365d"
	    limit: result size (max 50)

	Returns:
	    list of { seller, seller_name, gmv, orders }
	"""
	_require_super_admin()

	limit = min(max(cint(limit) or 10, 1), 50)
	from_date, to_date, _bucket = _date_range(period)

	if metric == "orders":
		order_by = "orders DESC"
	else:
		order_by = "gmv DESC"

	rows = frappe.db.sql(
		f"""
        SELECT
            o.seller AS seller,
            COALESCE(asp.seller_name, o.seller) AS seller_name,
            COALESCE(SUM(o.total), 0) AS gmv,
            COUNT(*) AS orders
        FROM `tabOrder` o
        LEFT JOIN `tabAdmin Seller Profile` asp ON asp.name = o.seller
        WHERE o.order_date BETWEEN %(from_date)s AND %(to_date)s
          AND o.status NOT IN %(cancelled)s
          AND o.seller IS NOT NULL AND o.seller != ''
        GROUP BY o.seller, asp.seller_name
        ORDER BY {order_by}
        LIMIT %(limit)s
        """,
		{
			"from_date": from_date,
			"to_date": to_date,
			"cancelled": ORDER_STATUS_CANCELLED,
			"limit": limit,
		},
		as_dict=True,
	)

	return {
		"metric": metric,
		"period": period,
		"rows": [
			{
				"seller": r.seller,
				"seller_name": r.seller_name,
				"gmv": round(flt(r.gmv), 2),
				"orders": cint(r.orders),
			}
			for r in rows
		],
	}
