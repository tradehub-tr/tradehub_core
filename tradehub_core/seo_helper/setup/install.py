"""Kurulum / migrate — Builder Page Custom Field'ları, roller, varsayılan Domain/Policy.

İdempotent: her migrate'te güvenle koşar (Builder yükseltmesinden sonra da — 14.6).
Builder çekirdek JSON'una DOKUNULMAZ; alanlar Custom Field olarak eklenir.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

BUILDER_PAGE_FIELDS = [
	{
		"fieldname": "seo_section",
		"fieldtype": "Section Break",
		"label": "SEO Helper",
		"insert_after": "canonical_url",
		"collapsible": 1,
	},
	{
		"fieldname": "seo_slug",
		"fieldtype": "Data",
		"label": "SEO Slug",
		"insert_after": "seo_section",
		"description": "Boşsa route'un son parçası",
	},
	{
		"fieldname": "seo_canonical",
		"fieldtype": "Data",
		"label": "SEO Canonical (politika)",
		"insert_after": "seo_slug",
		"options": "URL",
	},
	{
		"fieldname": "seo_robots",
		"fieldtype": "Select",
		"label": "SEO Robots",
		"insert_after": "seo_canonical",
		"options": "\nindex,follow\nnoindex,follow\nnoindex,nofollow\nindex,nofollow",
	},
	{"fieldname": "seo_cb", "fieldtype": "Column Break", "insert_after": "seo_robots"},
	{
		"fieldname": "seo_locale_cluster",
		"fieldtype": "Link",
		"label": "Hreflang Kümesi",
		"options": "SEO Locale Cluster",
		"insert_after": "seo_cb",
	},
	{
		"fieldname": "seo_lang",
		"fieldtype": "Select",
		"label": "SEO Dili",
		"options": "\ntr\nen\nar\nru",
		"insert_after": "seo_locale_cluster",
	},
	{
		"fieldname": "seo_publish_state",
		"fieldtype": "Select",
		"label": "SEO Yayın Durumu",
		"insert_after": "seo_lang",
		"options": "\ndraft\nreview\napproved\nscheduled\npublished\nsuspended\narchived",
	},
]
ROLES = ("SEO Manager", "SEO Editor", "MCP Agent")


# 13.6 — dönüşüm kayıtlarına organik atıf alanları (RFQ / Seller Inquiry / Order)
ATTRIBUTION_FIELDS = [
	{
		"fieldname": "seo_attr_section",
		"fieldtype": "Section Break",
		"label": "SEO Atıf",
		"collapsible": 1,
		"insert_after": None,
	},
	{
		"fieldname": "seo_landing_path",
		"fieldtype": "Data",
		"label": "İniş Sayfası",
		"read_only": 1,
		"insert_after": "seo_attr_section",
	},
	{
		"fieldname": "seo_referrer",
		"fieldtype": "Data",
		"label": "Yönlendiren",
		"read_only": 1,
		"insert_after": "seo_landing_path",
	},
	{
		"fieldname": "seo_utm_source",
		"fieldtype": "Data",
		"label": "UTM Source",
		"read_only": 1,
		"insert_after": "seo_referrer",
	},
	{
		"fieldname": "seo_utm_medium",
		"fieldtype": "Data",
		"label": "UTM Medium",
		"read_only": 1,
		"insert_after": "seo_utm_source",
	},
	{
		"fieldname": "seo_utm_campaign",
		"fieldtype": "Data",
		"label": "UTM Campaign",
		"read_only": 1,
		"insert_after": "seo_utm_medium",
	},
	{
		"fieldname": "seo_is_organic",
		"fieldtype": "Check",
		"label": "Organik",
		"read_only": 1,
		"insert_after": "seo_utm_campaign",
		"in_standard_filter": 1,
	},
	{
		"fieldname": "seo_landing_lang",
		"fieldtype": "Data",
		"label": "İniş Dili",
		"read_only": 1,
		"insert_after": "seo_is_organic",
	},
]


def _attribution_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	hedef = {}
	for dt in ("RFQ", "Seller Inquiry", "Order"):
		if frappe.db.exists("DocType", dt):
			alanlar = [dict(f) for f in ATTRIBUTION_FIELDS]
			alanlar[0]["insert_after"] = None
			hedef[dt] = alanlar
	if hedef:
		create_custom_fields(hedef, ignore_validate=True, update=True)
		frappe.db.sql(
			"update `tabCustom Field` set module='SEO Core' where dt in %(d)s and fieldname like 'seo_%%'",
			{"d": list(hedef)},
		)


def after_install():
	after_migrate()


def after_migrate():
	if frappe.db.exists("DocType", "Builder Page"):
		create_custom_fields({"Builder Page": BUILDER_PAGE_FIELDS}, ignore_validate=True, update=True)
		_attribution_custom_fields()
		frappe.db.sql(
			"update `tabCustom Field` set module='SEO CMS' where dt='Builder Page' and fieldname like 'seo\\_%%' and coalesce(module,'')=''"
		)
	for m in ("SEO Core", "SEO Catalog", "SEO CMS", "SEO Merchant", "SEO Crawler", "SEO Helper", "SEO MCP"):
		if not frappe.db.exists("Module Def", m):  # DocType'sız modül (SEO CMS) migrate'te Module Def almaz
			frappe.get_doc({"doctype": "Module Def", "module_name": m, "app_name": "tradehub_core"}).insert(
				ignore_permissions=True
			)
	for r in ROLES:
		if not frappe.db.exists("Role", r):
			frappe.get_doc({"doctype": "Role", "role_name": r, "desk_access": 1}).insert(
				ignore_permissions=True
			)
	_defaults()
	frappe.db.commit()


def _defaults():
	if not frappe.db.exists("SEO Domain", {"is_primary": 1}):
		from tradehub_core.seo_helper.adapters.tradehub.meta import site_url

		host = site_url().split("://", 1)[-1].strip("/") or "istoc.localhost"
		if not frappe.db.exists("SEO Domain", host):
			frappe.get_doc(
				{
					"doctype": "SEO Domain",
					"host": host,
					"default_lang": "tr",
					"market": "TR",
					"is_primary": 1,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
	if not frappe.db.exists("SEO Policy", "default"):
		frappe.get_doc(
			{
				"doctype": "SEO Policy",
				"policy_key": "default",
				"applies_to": "page",
				"default_robots": "index,follow",
				"canonical_strategy": "self",
				"min_title_len": 10,
				"min_desc_len": 50,
				"index_requires_published": 1,
				"block_ugc_html": 1,
				"priority": 100,
			}
		).insert(ignore_permissions=True)
	s = frappe.get_single("SEO Helper Settings")
	degisti = False
	for f, v in (
		("default_robots", "index,follow"),
		("mcp_call_timeout_sec", 60),
		("mcp_max_retries", 2),
		("mcp_log_retention_days", 90),
		("openai_model", "gpt-4.1-mini"),
		("job_max_attempts", 5),
		("min_title_len", 10),
		("min_desc_len", 50),
		("crawl_user_agent", "iStocSEOHelper/1.0 (+seo-helper)"),
		("crawl_rate_limit_rps", 2),
		("crawl_max_pages", 500),
		("crawl_max_seconds", 1200),
		("crawl_max_mb", 200),
		("crawl_checkpoint_every", 20),
		("crawl_incremental_days", 7),
		("crawl_respect_robots", 1),
		("bot_log_retention_days", 90),
		("gsc_daily_inspection_quota", 2000),
		("gsc_daily_query_quota", 2000),
		("gsc_data_lag_days", 3),
		("gsc_sample_size", 200),
		("board_stale_hours", 36),
		("board_anomaly_pct", 30),
		("board_baseline_days", 7),
	):
		if not s.get(f):
			s.set(f, v)
			degisti = True
	if degisti:
		s.flags.ignore_permissions = True
		s.save()
