"""İzleme (14.6) — iş kuyruğu, veri büyümesi, API kotası ve senkron durumu tek özet.

`health()` panel/CLI için anlık; `daily_health_snapshot` günlük sayaçları Settings'e yazar
(veri büyümesi trendi için) ve eşik aşımında Error Log'a uyarı düşer.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime


def health() -> dict:
	sj = {s: frappe.db.count("SEO Sync Job", {"status": s}) for s in ("queued", "running", "failed", "dead")}
	eski = frappe.db.count(
		"SEO Sync Job", {"status": "queued", "modified": ["<=", add_to_date(now_datetime(), minutes=-30)]}
	)
	mcp_ay = frappe.db.sql(
		"select coalesce(sum(cost_tokens_in+cost_tokens_out),0), coalesce(sum(cost_usd),0), count(*) from `tabMCP Tool Call` where creation >= date_format(now(), '%Y-%m-01')"
	)[0]
	return {
		"sync_jobs": sj,
		"sync_jobs_stuck_30m": eski,
		"pages": frappe.db.count("SEO Page"),
		"pages_published": frappe.db.count("SEO Page", {"publish_state": "published"}),
		"entities": frappe.db.count("SEO Entity"),
		"findings_open": frappe.db.count("SEO Audit Finding", {"resolved": 0}),
		"drafts_pending": frappe.db.count("MCP Draft", {"status": "draft"}),
		"mcp_month": {"tokens": int(mcp_ay[0]), "usd": float(mcp_ay[1]), "calls": int(mcp_ay[2])},
		"builder_pages_without_mirror": _mirrorsuz(),
	}


def _mirrorsuz() -> int:
	if not frappe.db.exists("DocType", "Builder Page"):
		return 0
	return frappe.db.sql(
		"select count(*) from `tabBuilder Page` bp where coalesce(bp.is_template,0)=0 and not exists (select 1 from `tabSEO Page` p where p.builder_page=bp.name)"
	)[0][0]


def daily_health_snapshot() -> dict:
	h = health()
	s = frappe.get_single("SEO Helper Settings")
	s.db_set({"last_health_json": frappe.as_json(h), "last_health_at": now_datetime()}, update_modified=False)
	if h["sync_jobs"]["dead"] > 0 or h["sync_jobs_stuck_30m"] > 0 or h["builder_pages_without_mirror"] > 0:
		frappe.log_error(title="seo_helper sağlık uyarısı", message=frappe.as_json(h))
	if s.mcp_monthly_token_budget and h["mcp_month"]["tokens"] >= 0.9 * s.mcp_monthly_token_budget:
		frappe.log_error(title="MCP aylık kota %90", message=frappe.as_json(h["mcp_month"]))
	return h
