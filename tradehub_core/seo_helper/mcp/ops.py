"""MCP operasyonu (14.6): maliyet/kota izleme, araç günlüğü saklama, anahtar rotasyonu."""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime

from tradehub_core.seo_helper.core.permissions import get_doc_or_deny, require_store_access
from tradehub_core.seo_helper.mcp.auth import generate_key


@frappe.whitelist()
def create_client(
	client_name: str,
	role: str = "seo_agent",
	scopes: str = "page:read,page:draft,metadata:suggest,translation:draft,audit:run,audit:read",
	store: str | None = None,
	monthly_token_budget: int = 0,
) -> dict:
	"""Anahtar YALNIZ bu cevapta döner (MOGEM-665 client_secret deseni)."""
	store = require_store_access(store, "write") or None
	key, prefix, h = generate_key()
	doc = frappe.get_doc(
		{
			"doctype": "MCP Client",
			"client_name": client_name,
			"role": role,
			"scopes": scopes,
			"store": store,
			"enabled": 1,
			"api_key_prefix": prefix,
			"api_key_hash": h,
			"key_rotated_at": now_datetime(),
			"monthly_token_budget": monthly_token_budget,
		}
	).insert(ignore_permissions=True)
	return {"client": doc.name, "api_key": key, "prefix": prefix}


@frappe.whitelist()
def rotate_key(client: str) -> dict:
	doc = get_doc_or_deny("MCP Client", client)
	require_store_access(doc.store, "write")
	key, prefix, h = generate_key()
	doc.db_set({"api_key_prefix": prefix, "api_key_hash": h, "key_rotated_at": now_datetime()})
	return {"client": doc.name, "api_key": key, "prefix": prefix}


@frappe.whitelist()
def disable_client(client: str) -> dict:
	doc = get_doc_or_deny("MCP Client", client)
	require_store_access(doc.store, "write")
	doc.db_set({"enabled": 0, "api_key_hash": ""})
	return {"ok": True}


@frappe.whitelist()
def usage(client: str | None = None, store: str | None = None) -> dict:
	store = require_store_access(store, "read") or None
	filters = {"creation": [">=", frappe.utils.get_first_day(now_datetime())]}
	if client:
		filters["client"] = client
	if store:
		filters["store"] = store
	rows = frappe.get_all(
		"MCP Tool Call",
		filters=filters,
		fields=[
			"tool",
			"count(name) as calls",
			"sum(cost_tokens_in+cost_tokens_out) as tokens",
			"sum(cost_usd) as usd",
			"sum(result='error') as errors",
			"sum(result='denied') as denied",
		],
		group_by="tool",
	)
	return {"month": rows, "budget": frappe.get_cached_doc("SEO Helper Settings").mcp_monthly_token_budget}


def purge_tool_call_log() -> dict:
	"""Saklama süresi (Settings.mcp_log_retention_days) dolan araç çağrıları silinir; taslaklar kalır."""
	gun = int(frappe.get_cached_doc("SEO Helper Settings").mcp_log_retention_days or 90)
	esik = add_to_date(now_datetime(), days=-gun)
	adlar = frappe.get_all(
		"MCP Tool Call", filters={"creation": ["<", esik]}, pluck="name", limit_page_length=5000
	)
	for n in adlar:
		frappe.delete_doc("MCP Tool Call", n, ignore_permissions=True, force=True)
	return {"purged": len(adlar), "older_than_days": gun}


def daily_cost_snapshot() -> dict:
	toplam = frappe.db.sql(
		"select coalesce(sum(cost_usd),0), coalesce(sum(cost_tokens_in+cost_tokens_out),0), count(*) from `tabMCP Tool Call` where creation >= date_format(now(), '%Y-%m-01')"
	)[0]
	s = frappe.get_cached_doc("SEO Helper Settings")
	uyari = []
	for c in frappe.get_all(
		"MCP Client",
		filters={"enabled": 1},
		fields=["name", "key_rotated_at", "monthly_token_budget", "tokens_used_month"],
	):
		if (
			s.mcp_key_rotation_days
			and c.key_rotated_at
			and c.key_rotated_at < add_to_date(now_datetime(), days=-int(s.mcp_key_rotation_days))
		):
			uyari.append(f"{c.name}: anahtar {s.mcp_key_rotation_days} günden eski")
		if c.monthly_token_budget and int(c.tokens_used_month or 0) >= 0.9 * int(c.monthly_token_budget):
			uyari.append(f"{c.name}: token bütçesi %90")
	if uyari:
		frappe.log_error(title="MCP operasyon uyarısı", message="\n".join(uyari))
	return {
		"month_usd": float(toplam[0]),
		"month_tokens": int(toplam[1]),
		"month_calls": int(toplam[2]),
		"warnings": uyari,
	}


def reset_monthly_quotas() -> dict:
	frappe.db.sql("update `tabMCP Client` set tokens_used_month = 0, calls_month = 0")
	return {"reset": True}
