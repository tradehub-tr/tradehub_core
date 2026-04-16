# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seed seller_overview dashboard widgets.

Widgets scope to the current seller via config_json.scope_field and the
"__me__" sentinel sent by the frontend — the engine resolves it to the
user's Admin Seller Profile name.

Idempotent: addressed by (dashboard_key, title).
"""

import json

import frappe

DASHBOARD_KEY = "seller_overview"


SELLER_WIDGETS = [
	# ── KPI Row 1 ──
	{
		"title": "Kendi Cirom",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 10,
		"icon": "fas fa-lira-sign",
		"icon_bg_class": "bg-violet-100 dark:bg-violet-500/10",
		"icon_color_class": "text-violet-500",
		"source_doctype": "Order",
		"aggregation": "sum",
		"metric_field": "total",
		"date_field": "order_date",
		"is_currency": 1,
		"period_scoped": 1,
		"compare_previous": 1,
		"filters_json": json.dumps([["status", "!=", "İptal Edildi"]]),
		"config_json": json.dumps({"scope_field": "seller"}),
	},
	{
		"title": "Sipariş Sayım",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 20,
		"icon": "fas fa-shopping-bag",
		"icon_bg_class": "bg-blue-100 dark:bg-blue-500/10",
		"icon_color_class": "text-blue-500",
		"source_doctype": "Order",
		"aggregation": "count",
		"date_field": "order_date",
		"period_scoped": 1,
		"compare_previous": 1,
		"filters_json": json.dumps([["status", "!=", "İptal Edildi"]]),
		"config_json": json.dumps({"scope_field": "seller"}),
	},
	{
		"title": "Ortalama Sepet",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 30,
		"icon": "fas fa-receipt",
		"icon_bg_class": "bg-emerald-100 dark:bg-emerald-500/10",
		"icon_color_class": "text-emerald-500",
		"source_doctype": "Order",
		"aggregation": "avg",
		"metric_field": "total",
		"date_field": "order_date",
		"is_currency": 1,
		"period_scoped": 1,
		"compare_previous": 1,
		"filters_json": json.dumps([["status", "!=", "İptal Edildi"]]),
		"config_json": json.dumps({"scope_field": "seller"}),
	},
	{
		"title": "Ortalama Puanım",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 40,
		"icon": "fas fa-star",
		"icon_bg_class": "bg-amber-100 dark:bg-amber-500/10",
		"icon_color_class": "text-amber-500",
		"source_doctype": "Seller Review",
		"aggregation": "avg",
		"metric_field": "rating",
		"period_scoped": 0,
		"config_json": json.dumps({"scope_field": "seller"}),
	},
	# ── KPI Row 2 (Actionable) ──
	{
		"title": "Hazırlanacak Sipariş",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 110,
		"icon": "fas fa-box",
		"icon_bg_class": "bg-orange-100 dark:bg-orange-500/10",
		"icon_color_class": "text-orange-500",
		"source_doctype": "Order",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "=", "Onaylanıyor"]]),
		"config_json": json.dumps(
			{
				"scope_field": "seller",
				"action_link": {"to": "/seller-orders", "label": "Siparişlere git →"},
			}
		),
	},
	{
		"title": "Kargodaki Siparişler",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 120,
		"icon": "fas fa-truck-fast",
		"icon_bg_class": "bg-indigo-100 dark:bg-indigo-500/10",
		"icon_color_class": "text-indigo-500",
		"source_doctype": "Order",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "=", "Kargoda"]]),
		"config_json": json.dumps({"scope_field": "seller"}),
	},
	{
		"title": "Toplam Ürünüm",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 130,
		"icon": "fas fa-cube",
		"icon_bg_class": "bg-emerald-100 dark:bg-emerald-500/10",
		"icon_color_class": "text-emerald-500",
		"source_doctype": "Listing",
		"aggregation": "count",
		"period_scoped": 0,
		"config_json": json.dumps({"scope_field": "seller_profile"}),
	},
	{
		"title": "Toplam Yorum",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 140,
		"icon": "fas fa-comments",
		"icon_bg_class": "bg-rose-100 dark:bg-rose-500/10",
		"icon_color_class": "text-rose-500",
		"source_doctype": "Seller Review",
		"aggregation": "count",
		"period_scoped": 0,
		"config_json": json.dumps({"scope_field": "seller"}),
	},
	# ── Quick Access ──
	{
		"title": "Hızlı Erişim",
		"subtitle": "Sık kullanılan yönetim sayfaları",
		"widget_type": "quick_links",
		"size": "full",
		"position": 200,
		"config_json": json.dumps(
			{
				"links": [
					{
						"label": "Siparişlerim",
						"to": "/seller-orders",
						"icon": "fas fa-bag-shopping",
						"icon_class": "bg-blue-100 dark:bg-blue-500/10 text-blue-500",
						"source_doctype": "Order",
						"scope_field": "seller",
					},
					{
						"label": "Ürünlerim",
						"to": "/seller-listings",
						"icon": "fas fa-cube",
						"icon_class": "bg-emerald-100 dark:bg-emerald-500/10 text-emerald-500",
						"source_doctype": "Listing",
						"scope_field": "seller_profile",
					},
					{
						"label": "Kategorilerim",
						"to": "/seller-categories",
						"icon": "fas fa-folder-tree",
						"icon_class": "bg-violet-100 dark:bg-violet-500/10 text-violet-500",
					},
					{
						"label": "Mağaza Düzeni",
						"to": "/storefront-layout",
						"icon": "fas fa-store",
						"icon_class": "bg-amber-100 dark:bg-amber-500/10 text-amber-500",
					},
				],
			}
		),
	},
	# ── Ciro Trendi + Sipariş Durumlarım ──
	{
		"title": "Ciro Trendim",
		"subtitle": "Döneme göre ciro hareketi",
		"widget_type": "line_chart",
		"size": "xl",
		"position": 300,
		"source_doctype": "Order",
		"aggregation": "sum",
		"metric_field": "total",
		"date_field": "order_date",
		"date_bucket": "auto",
		"is_currency": 1,
		"period_scoped": 1,
		"filters_json": json.dumps([["status", "!=", "İptal Edildi"]]),
		"config_json": json.dumps({"scope_field": "seller"}),
	},
	{
		"title": "Sipariş Durumlarım",
		"subtitle": "Aktif dönemdeki dağılım",
		"widget_type": "donut_chart",
		"size": "md",
		"position": 310,
		"source_doctype": "Order",
		"group_by_field": "status",
		"date_field": "order_date",
		"period_scoped": 1,
		"config_json": json.dumps({"scope_field": "seller"}),
	},
	# ── Puan Dağılımı ──
	{
		"title": "Müşteri Puan Dağılımı",
		"subtitle": "Aldığım yorumların puan bazlı dağılımı",
		"widget_type": "bar_chart",
		"size": "full",
		"position": 400,
		"source_doctype": "Seller Review",
		"group_by_field": "rating",
		"period_scoped": 0,
		"config_json": json.dumps({"scope_field": "seller"}),
	},
]


def execute():
	"""Seed seller widgets idempotently."""
	for spec in SELLER_WIDGETS:
		_upsert_widget(spec)
	frappe.db.commit()


def _upsert_widget(spec):
	title = spec["title"]
	existing = frappe.db.get_value(
		"Dashboard Widget",
		{"dashboard_key": DASHBOARD_KEY, "title": title},
		"name",
	)
	if existing:
		return

	doc = frappe.new_doc("Dashboard Widget")
	doc.dashboard_key = DASHBOARD_KEY
	doc.is_enabled = 1
	for field, value in spec.items():
		doc.set(field, value)
	doc.insert(ignore_permissions=True)
