"""Süper admin paneli uçları (admin-panel `/seo/helper`) — yalnız System Manager / SEO Manager.

Satıcı tarafına uç YOK (karar: önce süper admin denenecek). Onay/red, anahtar işlemleri ve
denetim mevcut uçlara (mcp.api / mcp.ops / core.queue) delege edilir; burada yalnız liste ve
özet vardır. Rol denetimi açık `PermissionError` ile (frappe.only_for testte etkisiz).
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from tradehub_core.seo_helper.core.permissions import _is_admin

MAX_LIMIT = 200


def _require_admin() -> None:
	if not _is_admin():
		frappe.throw(_("Bu ekran yalnız SEO Manager / System Manager içindir"), frappe.PermissionError)


def _lim(limit, default=50) -> int:
	try:
		return max(1, min(int(limit or default), MAX_LIMIT))
	except (TypeError, ValueError):
		return default


def _j(v):
	if not v:
		return {}
	try:
		return json.loads(v) if isinstance(v, str) else v
	except json.JSONDecodeError:
		return {"raw": v}


@frappe.whitelist(methods=["GET"])
def summary() -> dict:
	"""Üst kartlar: bekleyen/doğrulaması geçmeyen taslak, dead iş, aylık MCP maliyeti, aynasız sayfa."""
	_require_admin()
	from tradehub_core.seo_helper.core.monitoring import health

	h = health()
	gecmeyen = frappe.db.sql(
		"select count(*) from `tabMCP Draft` where status='draft' and validation like '%\"publishable\": false%'"
	)[0][0]
	return {
		"drafts_pending": h["drafts_pending"],
		"drafts_invalid": int(gecmeyen),
		"jobs": h["sync_jobs"],
		"jobs_stuck_30m": h["sync_jobs_stuck_30m"],
		"mcp_month": h["mcp_month"],
		"mcp_budget": frappe.get_cached_doc("SEO Helper Settings").mcp_monthly_token_budget or 0,
		"pages": h["pages"],
		"pages_published": h["pages_published"],
		"findings_open": h["findings_open"],
		"builder_pages_without_mirror": h["builder_pages_without_mirror"],
	}


@frappe.whitelist(methods=["GET"])
def drafts(
	status: str = "draft", store: str = "", draft_type: str = "", search: str = "", limit_start=0, limit=50
):
	_require_admin()
	filters: dict = {}
	if status and status != "all":
		filters["status"] = status
	if store:
		filters["store"] = store
	if draft_type:
		filters["draft_type"] = draft_type
	if search:
		filters["target_name"] = ["like", f"%{search}%"]
	rows = frappe.get_all(
		"MCP Draft",
		filters=filters,
		fields=[
			"name",
			"creation",
			"draft_type",
			"status",
			"client",
			"store",
			"target_doctype",
			"target_name",
			"validation",
			"reviewed_by",
			"reviewed_at",
			"review_note",
		],
		order_by="creation desc",
		limit_start=_lim(limit_start, 0) if limit_start else 0,
		limit_page_length=_lim(limit),
	)
	istemciler = {
		c.name: c.client_name
		for c in frappe.get_all("MCP Client", fields=["name", "client_name"], limit_page_length=500)
	}
	for r in rows:
		val = _j(r.validation)
		r.publishable = bool(val.get("publishable", True))
		r.finding_codes = [f.get("code") for f in val.get("findings", []) if isinstance(f, dict)]
		r.client_name = istemciler.get(r.client, r.client)
		r.validation = None
	return {"rows": rows, "total": frappe.db.count("MCP Draft", filters)}


@frappe.whitelist(methods=["GET"])
def draft_detail(name: str) -> dict:
	_require_admin()
	d = frappe.get_doc("MCP Draft", name)
	mevcut = None
	if (
		d.target_doctype == "Builder Page"
		and d.target_name
		and frappe.db.exists("Builder Page", d.target_name)
	):
		mevcut = frappe.db.get_value(
			"Builder Page",
			d.target_name,
			["page_title", "meta_description", "route", "published", "canonical_url", "seo_publish_state"],
			as_dict=True,
		)
	cagri = frappe.db.get_value(
		"MCP Tool Call",
		{"draft": d.name},
		["tool", "duration_ms", "cost_usd", "cost_tokens_in", "cost_tokens_out", "result"],
		as_dict=True,
	)
	return {
		"name": d.name,
		"draft_type": d.draft_type,
		"status": d.status,
		"client": d.client,
		"client_name": frappe.db.get_value("MCP Client", d.client, "client_name") if d.client else None,
		"store": d.store,
		"target_doctype": d.target_doctype,
		"target_name": d.target_name,
		"payload": _j(d.payload),
		"validation": _j(d.validation),
		"current": mevcut,
		"tool_call": cagri,
		"reviewed_by": d.reviewed_by,
		"reviewed_at": d.reviewed_at,
		"review_note": d.review_note,
		"creation": d.creation,
	}


@frappe.whitelist(methods=["GET"])
def pages(search: str = "", state: str = "", limit_start=0, limit=50) -> dict:
	_require_admin()
	filters: dict = {}
	if search:
		filters["route"] = ["like", f"%{search}%"]
	if state:
		filters["publish_state"] = state
	rows = frappe.get_all(
		"SEO Page",
		filters=filters,
		fields=[
			"name",
			"route",
			"lang",
			"title",
			"publish_state",
			"indexable",
			"publishable",
			"effective_canonical",
			"effective_robots",
			"last_evaluated_at",
			"data_version",
			"builder_page",
			"store",
			"source",
		],
		order_by="modified desc",
		limit_start=_lim(limit_start, 0) if limit_start else 0,
		limit_page_length=_lim(limit),
	)
	if rows:
		sayilar = frappe.db.sql(
			"select page, sum(severity='error') e, sum(severity='warning') w from `tabSEO Audit Finding` "
			"where page in %(p)s and resolved=0 group by page",
			{"p": [r.name for r in rows]},
			as_dict=True,
		)
		m = {s.page: s for s in sayilar}
		for r in rows:
			r.errors = int((m.get(r.name) or {}).get("e") or 0)
			r.warnings = int((m.get(r.name) or {}).get("w") or 0)
	return {"rows": rows, "total": frappe.db.count("SEO Page", filters)}


@frappe.whitelist(methods=["GET"])
def findings(page: str = "", crawl_run: str = "", limit=100) -> list:
	_require_admin()
	filters: dict = {"resolved": 0}
	if page:
		filters["page"] = page
	if crawl_run:
		filters["crawl_run"] = crawl_run
	return frappe.get_all(
		"SEO Audit Finding",
		filters=filters,
		fields=["name", "page", "route", "severity", "code", "message", "crawl_run", "creation"],
		order_by="severity asc, creation desc",
		limit_page_length=_lim(limit, 100),
	)


@frappe.whitelist(methods=["GET"])
def crawl_runs(limit=20) -> list:
	_require_admin()
	return frappe.get_all(
		"SEO Crawl Run",
		fields=[
			"name",
			"status",
			"triggered_by",
			"pages_total",
			"pages_ok",
			"findings",
			"started_at",
			"finished_at",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=_lim(limit, 20),
	)


@frappe.whitelist(methods=["POST"])
def audit_run(routes=None) -> dict:
	"""Seçili route'lar (boşsa tüm sayfalar) için denetimi `mcp` kuyruğuna at — MCP aracıyla aynı iş."""
	_require_admin()
	from tradehub_core.seo_helper.core.queue import enqueue_after_commit

	routes = _j(routes) if isinstance(routes, str) else (routes or [])
	if not isinstance(routes, list):
		frappe.throw(_("routes liste olmalı"), frappe.ValidationError)
	routes = ["/" + str(r).strip("/") for r in routes if isinstance(r, str) and r.strip()][:500]
	run = frappe.get_doc(
		{
			"doctype": "SEO Crawl Run",
			"scope": json.dumps({"routes": routes, "store": None}),
			"status": "queued",
			"triggered_by": f"panel:{frappe.session.user}",
			"queue": "mcp",
		}
	).insert(ignore_permissions=True)  # sistem kaydı; rol denetimi yukarıda
	job = enqueue_after_commit(
		"mcp.long", {"tool": "audit", "crawl_run": run.name}, queue="mcp", dedupe_key=f"audit:{run.name}"
	)
	return {"crawl_run": run.name, "job": job}


@frappe.whitelist(methods=["GET"])
def queue(status: str = "", limit=50) -> dict:
	_require_admin()
	filters: dict = {}
	if status and status != "all":
		filters["status"] = status
	rows = frappe.get_all(
		"SEO Sync Job",
		filters=filters,
		fields=[
			"name",
			"job_type",
			"queue",
			"status",
			"attempts",
			"next_attempt_at",
			"started_at",
			"finished_at",
			"last_error",
			"store",
			"creation",
		],
		order_by="modified desc",
		limit_page_length=_lim(limit),
	)
	sayilar = {
		s: frappe.db.count("SEO Sync Job", {"status": s})
		for s in ("queued", "running", "failed", "dead", "done")
	}
	takili = frappe.db.count(
		"SEO Sync Job", {"status": "queued", "modified": ["<=", add_to_date(now_datetime(), minutes=-30)]}
	)
	return {"rows": rows, "counts": sayilar, "stuck_30m": takili}


@frappe.whitelist(methods=["POST"])
def requeue_jobs(jobs=None, all_dead: int = 0) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.core.queue import requeue

	jobs = _j(jobs) if isinstance(jobs, str) else (jobs or [])
	if int(all_dead or 0):
		jobs = frappe.get_all(
			"SEO Sync Job", filters={"status": "dead"}, pluck="name", limit_page_length=MAX_LIMIT
		)
	n = 0
	for j in jobs:
		if isinstance(j, str) and frappe.db.exists("SEO Sync Job", j):
			requeue(j)
			n += 1
	return {"requeued": n}


@frappe.whitelist(methods=["GET"])
def clients() -> list:
	"""MCP istemcileri + bu ayki kullanım. Anahtar özeti (hash) asla dönmez."""
	_require_admin()
	rows = frappe.get_all(
		"MCP Client",
		fields=[
			"name",
			"client_name",
			"role",
			"scopes",
			"store",
			"enabled",
			"api_key_prefix",
			"key_rotated_at",
			"last_used_at",
			"monthly_token_budget",
			"tokens_used_month",
			"calls_month",
		],
		order_by="creation desc",
		limit_page_length=MAX_LIMIT,
	)
	ay = frappe.db.sql(
		"select client, count(*) calls, coalesce(sum(cost_usd),0) usd, sum(result='error') errors, sum(result='denied') denied "
		"from `tabMCP Tool Call` where creation >= date_format(now(), '%Y-%m-01') group by client",
		as_dict=True,
	)
	m = {a.client: a for a in ay}
	for r in rows:
		a = m.get(r.name) or {}
		r.month_calls = int(a.get("calls") or 0)
		r.month_usd = float(a.get("usd") or 0)
		r.month_errors = int(a.get("errors") or 0)
		r.month_denied = int(a.get("denied") or 0)
	return rows


@frappe.whitelist(methods=["GET"])
def tool_calls(client: str = "", result: str = "", limit=50) -> list:
	_require_admin()
	filters: dict = {}
	if client:
		filters["client"] = client
	if result:
		filters["result"] = result
	return frappe.get_all(
		"MCP Tool Call",
		filters=filters,
		fields=[
			"name",
			"creation",
			"client",
			"tool",
			"store",
			"result",
			"duration_ms",
			"cost_usd",
			"cost_tokens_in",
			"cost_tokens_out",
			"error",
			"draft",
		],
		order_by="creation desc",
		limit_page_length=_lim(limit),
	)
