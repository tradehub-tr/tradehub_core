"""MCP kaynaklı uzun işler (14.4) — `mcp` kuyruğunda koşar; kısa web isteğini bloke etmez."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime


def run_long_tool(tool: str, crawl_run: str | None = None, **_) -> dict:
	if tool == "audit":
		return run_audit(crawl_run)
	raise ValueError(f"bilinmeyen uzun araç: {tool}")


def run_audit(crawl_run: str) -> dict:
	"""Basit deterministik denetim: kapsamdaki SEO Page'ler politika motorundan geçirilir."""
	from tradehub_core.seo_helper.core.policy import apply_for_page

	run = frappe.get_doc("SEO Crawl Run", crawl_run)
	run.db_set({"status": "running", "started_at": now_datetime()}, update_modified=False)
	kapsam = json.loads(run.scope or "{}")
	filters: dict = {}
	routes = kapsam.get("routes")
	if isinstance(routes, list) and routes:
		filters["route"] = ["in", ["/" + str(r).strip("/") for r in routes if isinstance(r, str | int)]]
	if kapsam.get("store"):
		filters["store"] = kapsam["store"]
	pages = frappe.get_all("SEO Page", filters=filters, pluck="name", limit_page_length=2000)
	ok = bulgu = 0
	for p in pages:
		karar = apply_for_page(p)
		ok += 1 if karar["publishable"] else 0
		bulgu += len(karar["findings"])
		for f in karar["findings"]:
			frappe.get_doc(
				{
					"doctype": "SEO Audit Finding",
					"crawl_run": crawl_run,
					"page": p,
					"route": frappe.db.get_value("SEO Page", p, "route"),
					"store": kapsam.get("store"),
					"severity": f["severity"],
					"code": f["code"],
					"message": f["message"],
				}
			).insert(ignore_permissions=True)
	run.db_set(
		{
			"status": "done",
			"finished_at": now_datetime(),
			"pages_total": len(pages),
			"pages_ok": ok,
			"findings": bulgu,
		},
		update_modified=False,
	)
	return {"crawl_run": crawl_run, "pages": len(pages), "ok": ok, "findings": bulgu}
