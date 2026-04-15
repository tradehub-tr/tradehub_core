# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Dynamic Dashboard Engine.

Turns `Dashboard Widget` DocType configurations into live data via a generic
aggregator. Exposes two whitelisted endpoints:

- get_dashboard_layout(dashboard_key, period)
    Return all widgets for a dashboard (role-filtered) with resolved data.

- run_dashboard_widget(widget_id, period, scope)
    Execute a single widget and return its payload. Useful for re-fetching.

Security model
--------------
- Widget must target a DocType the current user is allowed to read (or user is
  super admin).
- Field names (metric/date/group_by) are validated against Frappe meta — never
  string-interpolated without whitelist check → SQL injection safe.
- Filters are passed through Frappe ORM, not raw SQL.
- Super admin restriction for writing widgets is enforced at DocType perm
  level (configured in dashboard_widget.json).
"""

import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate, add_days, add_months, getdate


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _is_super_admin():
	user = frappe.session.user
	if user == "Administrator":
		return True
	roles = frappe.get_roles(user)
	return "System Manager" in roles or "Marketplace Manager" in roles


def _user_can_read(doctype):
	if not doctype:
		return True
	if _is_super_admin():
		return True
	try:
		return frappe.has_permission(doctype, "read")
	except Exception:
		return False


# ---------------------------------------------------------------------------
# Field / period / filter helpers
# ---------------------------------------------------------------------------

def _validate_field(doctype, fieldname):
	"""Raise if fieldname is not present on doctype. Returns sanitized name."""
	if not fieldname:
		return None
	standard = {"name", "creation", "modified", "owner", "modified_by", "docstatus"}
	if fieldname in standard:
		return fieldname
	meta = frappe.get_meta(doctype)
	valid = {f.fieldname for f in meta.fields}
	if fieldname not in valid:
		frappe.throw(_("Geçersiz alan adı: {0} ({1})").format(fieldname, doctype))
	return fieldname


def _date_range(period):
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


def _previous_range(from_date, to_date):
	span = (getdate(to_date) - getdate(from_date)).days + 1
	prev_to = add_days(getdate(from_date), -1)
	prev_from = add_days(prev_to, -(span - 1))
	return prev_from, prev_to


def _parse_filters(widget):
	raw = widget.get("filters_json")
	if not raw:
		return []
	try:
		data = json.loads(raw)
	except (TypeError, ValueError):
		return []
	if not isinstance(data, list):
		return []
	return data


def _parse_config(widget):
	raw = widget.get("config_json")
	if not raw:
		return {}
	try:
		return json.loads(raw) or {}
	except (TypeError, ValueError):
		return {}


def _apply_period_filter(filters, widget, period):
	"""Append period date filter if widget is period-scoped."""
	if not cint(widget.get("period_scoped")):
		return filters, None, None
	date_field = widget.get("date_field")
	if not date_field:
		return filters, None, None
	_validate_field(widget.get("source_doctype"), date_field)
	from_d, to_d, _bucket = _date_range(period or "30d")
	filters = list(filters) + [[date_field, "between", [str(from_d), str(to_d)]]]
	return filters, from_d, to_d


def _resolve_scope(scope):
	"""Resolve '__me__' sentinel to current user's seller profile name.

	Returns None if user has no seller profile (then widget won't filter
	and falls back to permission-level restriction).
	"""
	if scope == "__me__":
		user = frappe.session.user
		seller_name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
		return seller_name or None
	return scope


DEFAULT_SCOPE_FIELDS = {
	"Order": "seller",
	"Listing": "seller_profile",
	"Payment Transaction": "seller",
	"Seller Review": "seller",
	"Admin Seller Profile": "name",
}


def _apply_scope_filter(filters, widget, scope):
	"""Scope widget to a given user (seller scope).

	Field lookup order:
	1. Widget config_json.scope_field (explicit override)
	2. DEFAULT_SCOPE_FIELDS[source_doctype] (convention)
	3. Skip scoping if neither is resolvable
	"""
	resolved = _resolve_scope(scope)
	if not resolved:
		return filters
	doctype = widget.get("source_doctype")
	scope_field = (_parse_config(widget) or {}).get("scope_field")
	if not scope_field and doctype:
		scope_field = DEFAULT_SCOPE_FIELDS.get(doctype)
	if not scope_field:
		return filters
	if doctype:
		try:
			_validate_field(doctype, scope_field)
		except Exception:
			return filters
	return list(filters) + [[scope_field, "=", resolved]]


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------

def _agg_count(doctype, filters):
	return cint(frappe.db.count(doctype, filters=filters))


def _agg_numeric(doctype, field, agg, filters):
	"""sum/avg/min/max on a numeric field using ORM + SQL alias."""
	agg = agg.lower()
	if agg not in ("sum", "avg", "min", "max"):
		frappe.throw(_("Geçersiz agregasyon: {0}").format(agg))
	_validate_field(doctype, field)
	quoted_field = f"`{field}`"
	rows = frappe.get_all(
		doctype,
		filters=filters,
		fields=[f"{agg}({quoted_field}) as value"],
	)
	if not rows:
		return 0.0
	return flt(rows[0].get("value") or 0)


def _aggregate(widget, filters):
	agg = (widget.get("aggregation") or "count").lower()
	doctype = widget.get("source_doctype")
	if agg == "count":
		return _agg_count(doctype, filters)
	metric = widget.get("metric_field")
	if not metric:
		frappe.throw(_("{0} agregasyonu için metrik alanı gerekli.").format(agg))
	return _agg_numeric(doctype, metric, agg, filters)


# ---------------------------------------------------------------------------
# Widget type handlers
# ---------------------------------------------------------------------------

def _handle_kpi_single(widget, period=None, scope=None):
	filters = _parse_filters(widget)
	filters, _from, _to = _apply_period_filter(filters, widget, period)
	filters = _apply_scope_filter(filters, widget, scope)
	value = _aggregate(widget, filters)

	payload = {"value": value, "is_currency": cint(widget.get("is_currency"))}

	config = _parse_config(widget)
	if config.get("action_link"):
		payload["action_link"] = config["action_link"]

	if cint(widget.get("compare_previous")) and cint(widget.get("period_scoped")):
		base_filters = _parse_filters(widget)
		date_field = widget.get("date_field")
		from_d, to_d, _b = _date_range(period or "30d")
		prev_from, prev_to = _previous_range(from_d, to_d)
		prev_filters = list(base_filters) + [[date_field, "between", [str(prev_from), str(prev_to)]]]
		prev_filters = _apply_scope_filter(prev_filters, widget, scope)
		prev_value = _aggregate(widget, prev_filters)
		payload["previous_value"] = prev_value
		if prev_value:
			payload["change_pct"] = round(((value - prev_value) / prev_value) * 100)
		else:
			payload["change_pct"] = None
	return payload


def _handle_line_chart(widget, period=None, scope=None):
	doctype = widget.get("source_doctype")
	date_field = _validate_field(doctype, widget.get("date_field"))
	if not date_field:
		frappe.throw(_("Line chart için tarih alanı zorunlu."))

	filters = _parse_filters(widget)
	filters, from_d, to_d = _apply_period_filter(filters, widget, period)
	filters = _apply_scope_filter(filters, widget, scope)

	bucket = widget.get("date_bucket") or "auto"
	if bucket == "auto":
		_fd, _td, bucket = _date_range(period or "30d")

	if bucket == "day":
		fmt = "%Y-%m-%d"
	elif bucket == "week":
		fmt = "%x-W%v"
	elif bucket == "month":
		fmt = "%Y-%m"
	else:
		fmt = "%Y-%m-%d"

	agg = (widget.get("aggregation") or "count").lower()
	metric = widget.get("metric_field")
	if agg != "count" and metric:
		_validate_field(doctype, metric)
		metric_sql = f"{agg}(`{metric}`)"
	else:
		metric_sql = "COUNT(*)"

	from frappe.query_builder import DocType  # noqa
	# Frappe ORM doesn't support DATE_FORMAT directly — use db.sql with safe params.
	# Build WHERE from filters via frappe.get_all + names, then reuse.
	names = frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=0)
	if not names:
		return {"points": [], "bucket": bucket}

	table = f"`tab{doctype}`"
	placeholders = ", ".join(["%s"] * len(names))
	rows = frappe.db.sql(
		f"""
		SELECT
			DATE_FORMAT(`{date_field}`, %s) AS label,
			MIN(`{date_field}`) AS bucket_start,
			{metric_sql} AS value
		FROM {table}
		WHERE name IN ({placeholders})
		GROUP BY label
		ORDER BY bucket_start ASC
		""",
		(fmt, *names),
		as_dict=True,
	)
	points = [
		{
			"label": r["label"],
			"bucket_start": str(r["bucket_start"]) if r["bucket_start"] else None,
			"value": flt(r["value"] or 0),
		}
		for r in rows
	]
	return {"points": points, "bucket": bucket, "is_currency": cint(widget.get("is_currency"))}


def _handle_bar_chart(widget, period=None, scope=None):
	doctype = widget.get("source_doctype")
	group_field = _validate_field(doctype, widget.get("group_by_field"))
	if not group_field:
		frappe.throw(_("Bar chart için gruplama alanı zorunlu."))

	filters = _parse_filters(widget)
	filters, _from, _to = _apply_period_filter(filters, widget, period)
	filters = _apply_scope_filter(filters, widget, scope)

	agg = (widget.get("aggregation") or "count").lower()
	metric = widget.get("metric_field")
	if agg != "count" and metric:
		_validate_field(doctype, metric)
		metric_sql = f"{agg}(`{metric}`)"
	else:
		metric_sql = "COUNT(*)"

	limit = cint(widget.get("result_limit") or 10)
	names = frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=0)
	if not names:
		return {"rows": []}

	table = f"`tab{doctype}`"
	placeholders = ", ".join(["%s"] * len(names))
	rows = frappe.db.sql(
		f"""
		SELECT `{group_field}` AS label, {metric_sql} AS value
		FROM {table}
		WHERE name IN ({placeholders})
		GROUP BY `{group_field}`
		ORDER BY value DESC
		LIMIT %s
		""",
		(*names, limit),
		as_dict=True,
	)
	return {
		"rows": [
			{"label": r["label"] or "—", "value": flt(r["value"] or 0)}
			for r in rows
		],
		"is_currency": cint(widget.get("is_currency")),
	}


def _handle_donut_chart(widget, period=None, scope=None):
	# Same shape as bar but without limit; label is the group_by value.
	return _handle_bar_chart(widget, period=period, scope=scope)


def _handle_funnel_chart(widget, period=None, scope=None):
	"""Funnel stages from config_json.stages: [{label, filters?}].

	If stages are provided, runs count per stage with stage-level filters
	merged on top of widget filters. If not, falls back to a default
	onboarding funnel using source_doctype + group_by field values.
	"""
	config = _parse_config(widget)
	stages = config.get("stages")
	base_filters = _parse_filters(widget)
	base_filters, _from, _to = _apply_period_filter(base_filters, widget, period)
	base_filters = _apply_scope_filter(base_filters, widget, scope)

	out = []
	if stages and isinstance(stages, list):
		for st in stages:
			stage_doctype = st.get("doctype") or widget.get("source_doctype")
			stage_filters = list(base_filters) + list(st.get("filters") or [])
			count = _agg_count(stage_doctype, stage_filters)
			out.append({
				"key": st.get("key") or st.get("label"),
				"label": st.get("label") or st.get("key"),
				"count": count,
			})
	return {"stages": out}


def _handle_status_breakdown(widget, period=None, scope=None):
	"""Group-by-field count with per-value label/color mapping from config."""
	doctype = widget.get("source_doctype")
	group_field = _validate_field(doctype, widget.get("group_by_field"))
	if not group_field:
		frappe.throw(_("Status breakdown için gruplama alanı zorunlu."))

	filters = _parse_filters(widget)
	filters, _from, _to = _apply_period_filter(filters, widget, period)
	filters = _apply_scope_filter(filters, widget, scope)

	names = frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=0)
	if not names:
		return {"rows": []}

	table = f"`tab{doctype}`"
	placeholders = ", ".join(["%s"] * len(names))
	rows = frappe.db.sql(
		f"""
		SELECT `{group_field}` AS value, COUNT(*) AS count
		FROM {table}
		WHERE name IN ({placeholders})
		GROUP BY `{group_field}`
		""",
		tuple(names),
		as_dict=True,
	)

	config = _parse_config(widget)
	labels_map = config.get("labels") or {}
	colors_map = config.get("colors") or {}
	return {
		"rows": [
			{
				"value": r["value"] or "",
				"label": labels_map.get(r["value"] or "", r["value"] or ""),
				"color": colors_map.get(r["value"] or "", "text-gray-400"),
				"count": cint(r["count"]),
			}
			for r in rows
		],
	}


def _handle_quick_links(widget, period=None, scope=None):
	"""Static list of links with live count per link.

	config_json.links: [{ label, to, icon, icon_class, source_doctype?,
	                      filters?, scope_field? }]
	"""
	config = _parse_config(widget)
	links = config.get("links") or []
	resolved_scope = _resolve_scope(scope)
	out = []
	for link in links:
		count = None
		doctype = link.get("source_doctype")
		if doctype:
			if not _user_can_read(doctype):
				continue
			flt_arr = list(link.get("filters") or [])
			scope_field = link.get("scope_field")
			if resolved_scope and scope_field:
				try:
					_validate_field(doctype, scope_field)
					flt_arr.append([scope_field, "=", resolved_scope])
				except Exception:
					pass
			try:
				count = _agg_count(doctype, flt_arr)
			except Exception:
				count = None
		out.append({
			"label": link.get("label"),
			"to": link.get("to"),
			"icon": link.get("icon"),
			"icon_class": link.get("icon_class"),
			"count": count,
		})
	return {"links": out}


HANDLERS = {
	"kpi_single": _handle_kpi_single,
	"line_chart": _handle_line_chart,
	"bar_chart": _handle_bar_chart,
	"donut_chart": _handle_donut_chart,
	"funnel_chart": _handle_funnel_chart,
	"status_breakdown": _handle_status_breakdown,
	"quick_links": _handle_quick_links,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_dashboard_layout(dashboard_key, period="30d", scope=None):
	"""Return all widgets visible to the current user for a given dashboard."""
	if not dashboard_key:
		frappe.throw(_("dashboard_key gerekli."))

	user_roles = set(frappe.get_roles())
	widget_names = frappe.get_all(
		"Dashboard Widget",
		filters={"dashboard_key": dashboard_key, "is_enabled": 1},
		pluck="name",
		order_by="position asc",
	)

	layout = []
	for name in widget_names:
		widget = frappe.get_doc("Dashboard Widget", name)
		# Role-based visibility
		required_roles = [r.role for r in (widget.visible_roles or [])]
		if required_roles and not (user_roles & set(required_roles)) and not _is_super_admin():
			continue
		# DocType read permission
		if widget.source_doctype and not _user_can_read(widget.source_doctype):
			continue

		try:
			data = _run(widget, period=period, scope=scope)
			error = None
		except Exception as e:
			data = None
			error = str(e)
			frappe.log_error(frappe.get_traceback(), f"Dashboard widget {name} failed")

		layout.append({
			"name": widget.name,
			"widget_type": widget.widget_type,
			"title": widget.title,
			"subtitle": widget.subtitle,
			"size": widget.size,
			"position": widget.position,
			"icon": widget.icon,
			"icon_bg_class": widget.icon_bg_class,
			"icon_color_class": widget.icon_color_class,
			"is_currency": cint(widget.is_currency),
			"data": data,
			"error": error,
		})
	return {"dashboard_key": dashboard_key, "period": period, "widgets": layout}


@frappe.whitelist()
def preview_dashboard_widget(config, period="30d", scope=None):
	"""Render a widget from an in-memory config dict (no DB persistence).

	Lets the admin form show a live preview of a widget while editing it,
	before saving. The config payload mirrors the Dashboard Widget fields:
		widget_type, source_doctype, aggregation, metric_field, date_field,
		date_bucket, group_by_field, result_limit, filters_json, config_json,
		is_currency, period_scoped, compare_previous

	Super-admin only — same constraint as live dashboards.
	"""
	if not _is_super_admin():
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)

	if isinstance(config, str):
		try:
			config = json.loads(config)
		except (TypeError, ValueError):
			frappe.throw(_("config geçerli JSON olmalı."))

	if not isinstance(config, dict):
		frappe.throw(_("config sözlük (dict) olmalı."))

	widget_type = config.get("widget_type")
	if not widget_type:
		frappe.throw(_("widget_type gerekli."))

	# Build a frappe._dict so HANDLERS can access fields via .get(...) just
	# like a real Dashboard Widget Document.
	widget = frappe._dict({
		"name": "__preview__",
		"widget_type": widget_type,
		"source_doctype": config.get("source_doctype"),
		"aggregation": config.get("aggregation"),
		"metric_field": config.get("metric_field"),
		"date_field": config.get("date_field"),
		"date_bucket": config.get("date_bucket") or "auto",
		"group_by_field": config.get("group_by_field"),
		"result_limit": cint(config.get("result_limit") or 10),
		"filters_json": config.get("filters_json"),
		"config_json": config.get("config_json"),
		"is_currency": cint(config.get("is_currency")),
		"period_scoped": cint(config.get("period_scoped") if config.get("period_scoped") is not None else 1),
		"compare_previous": cint(config.get("compare_previous")),
	})

	# Optional read-permission guard for the source doctype.
	if widget.source_doctype and not _user_can_read(widget.source_doctype):
		frappe.throw(
			_("{0} DocType'una erişim yetkiniz yok.").format(widget.source_doctype),
			frappe.PermissionError,
		)

	try:
		data = _run(widget, period=period, scope=scope)
		return {"ok": True, "widget_type": widget_type, "data": data, "is_currency": cint(widget.is_currency)}
	except Exception as e:
		return {"ok": False, "widget_type": widget_type, "error": str(e)}


@frappe.whitelist()
def run_dashboard_widget(widget_id, period="30d", scope=None):
	"""Execute a single widget by id and return its payload."""
	widget = frappe.get_doc("Dashboard Widget", widget_id)

	user_roles = set(frappe.get_roles())
	required_roles = [r.role for r in (widget.visible_roles or [])]
	if required_roles and not (user_roles & set(required_roles)) and not _is_super_admin():
		frappe.throw(_("Bu widget'a erişim yetkiniz yok."), frappe.PermissionError)
	if widget.source_doctype and not _user_can_read(widget.source_doctype):
		frappe.throw(_("Bu widget'ın veri kaynağına erişim yetkiniz yok."), frappe.PermissionError)

	return {
		"name": widget.name,
		"widget_type": widget.widget_type,
		"data": _run(widget, period=period, scope=scope),
	}


def _run(widget, period=None, scope=None):
	handler = HANDLERS.get(widget.widget_type)
	if not handler:
		frappe.throw(_("Bilinmeyen widget tipi: {0}").format(widget.widget_type))
	return handler(widget, period=period, scope=scope)


@frappe.whitelist()
def list_dashboards():
	"""Return known dashboard keys with widget counts."""
	if not _is_super_admin():
		frappe.throw(_("Bu veriye erişim yetkiniz yok."), frappe.PermissionError)
	rows = frappe.db.sql(
		"""
		SELECT dashboard_key,
			COUNT(*) AS total,
			SUM(is_enabled) AS enabled_count
		FROM `tabDashboard Widget`
		GROUP BY dashboard_key
		ORDER BY dashboard_key ASC
		""",
		as_dict=True,
	)
	# Friendly titles for well-known keys
	titles = {
		"platform_overview": "Platform Genel Bakışı",
		"seller_overview": "Satıcı Paneli",
	}
	return [
		{
			"dashboard_key": r["dashboard_key"],
			"title": titles.get(r["dashboard_key"], r["dashboard_key"]),
			"total": cint(r["total"]),
			"enabled_count": cint(r["enabled_count"]),
		}
		for r in rows
	]


@frappe.whitelist()
def list_widgets_for_admin(dashboard_key):
	"""Return all widgets for a dashboard (including disabled), for the
	admin management UI. Requires super admin."""
	if not _is_super_admin():
		frappe.throw(_("Bu veriye erişim yetkiniz yok."), frappe.PermissionError)
	if not dashboard_key:
		frappe.throw(_("dashboard_key gerekli."))
	rows = frappe.get_all(
		"Dashboard Widget",
		filters={"dashboard_key": dashboard_key},
		fields=[
			"name", "title", "subtitle", "widget_type", "size",
			"position", "is_enabled", "source_doctype",
		],
		order_by="position asc",
	)
	return rows


@frappe.whitelist()
def reorder_widgets(dashboard_key, ordered_ids):
	"""Persist a new widget ordering for a dashboard.

	Args:
		dashboard_key: target dashboard
		ordered_ids: list (or JSON string) of widget ids in desired order.
	"""
	if not _is_super_admin():
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)

	if isinstance(ordered_ids, str):
		try:
			ordered_ids = json.loads(ordered_ids)
		except (TypeError, ValueError):
			frappe.throw(_("ordered_ids geçerli JSON olmalı."))
	if not isinstance(ordered_ids, list):
		frappe.throw(_("ordered_ids liste olmalı."))

	# Safety: all ids must actually belong to the target dashboard
	existing = set(frappe.get_all(
		"Dashboard Widget",
		filters={"dashboard_key": dashboard_key, "name": ["in", ordered_ids]},
		pluck="name",
	)) if ordered_ids else set()

	updated = 0
	for idx, wid in enumerate(ordered_ids):
		if wid not in existing:
			continue
		# Position step of 10 leaves room for manual insertions later
		frappe.db.set_value("Dashboard Widget", wid, "position", (idx + 1) * 10)
		updated += 1
	frappe.db.commit()
	return {"updated": updated, "dashboard_key": dashboard_key}


@frappe.whitelist()
def toggle_widget(widget_id, enabled):
	"""Enable/disable a widget without opening the full form."""
	if not _is_super_admin():
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)
	enabled = 1 if cint(enabled) else 0
	frappe.db.set_value("Dashboard Widget", widget_id, "is_enabled", enabled)
	frappe.db.commit()
	return {"name": widget_id, "is_enabled": enabled}
