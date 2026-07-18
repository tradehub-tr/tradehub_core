# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seed platform_overview dashboard widgets into the Dashboard Widget DocType.

Idempotent: every widget is addressed by a stable composite key
(dashboard_key + title). If a widget with the same key exists it is skipped;
otherwise it is inserted. Running the patch twice has no additional effect.
"""

import json

import frappe

DASHBOARD_KEY = "platform_overview"


PLATFORM_WIDGETS = [
	# ── KPI Row 1 ──
	{
		"title": "GMV",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 10,
		"icon": "fas fa-lira-sign",
		"icon_bg_class": "bg-brand-100 dark:bg-brand-500/10",
		"icon_color_class": "text-brand-600",
		"source_doctype": "Order",
		"aggregation": "sum",
		"metric_field": "total",
		"date_field": "order_date",
		"is_currency": 1,
		"period_scoped": 1,
		"compare_previous": 1,
		"filters_json": json.dumps([["status", "!=", "İptal Edildi"]]),
	},
	{
		"title": "Sipariş",
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
	},
	{
		"title": "Tamamlanan Ödeme",
		"subtitle": "Başarıyla tamamlanmış ödeme adedi",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 40,
		"icon": "fas fa-circle-check",
		"icon_bg_class": "bg-teal-100 dark:bg-teal-500/10",
		"icon_color_class": "text-teal-500",
		"source_doctype": "Payment Transaction",
		"aggregation": "count",
		"date_field": "transaction_date",
		"period_scoped": 1,
		"filters_json": json.dumps([["status", "in", ["Tamamlandı", "Eşleşti"]]]),
	},
	# ── KPI Row 2 (Actionable) ──
	{
		"title": "Onay Bekleyen Başvuru",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 110,
		"icon": "fas fa-file-lines",
		"icon_bg_class": "bg-amber-100 dark:bg-amber-500/10",
		"icon_color_class": "text-amber-500",
		"source_doctype": "Seller Application",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "in", ["Submitted", "Under Review"]]]),
		"config_json": json.dumps(
			{
				"action_link": {"to": "/app/Seller Application", "label": "Başvurulara git →"},
			}
		),
	},
	{
		"title": "Açık RFQ",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 120,
		"icon": "fas fa-handshake",
		"icon_bg_class": "bg-indigo-100 dark:bg-indigo-500/10",
		"icon_color_class": "text-indigo-500",
		"source_doctype": "RFQ",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "in", ["Pending", "Approved"]]]),
	},
	{
		"title": "Toplam Kullanıcı",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 130,
		"icon": "fas fa-users",
		"icon_bg_class": "bg-brand-100 dark:bg-brand-500/10",
		"icon_color_class": "text-brand-600",
		# Sprint 2 sonrası canonical: User Profile = marketplace kullanıcı entity.
		# User + user_type filtresi sadece Frappe Desk erişimi olanları sayıyordu
		# (alıcılar Website User olduğu için sayıma girmiyordu).
		"source_doctype": "User Profile",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "=", "Active"]]),
	},
	{
		"title": "Aktif Satıcı",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 140,
		"icon": "fas fa-store",
		"icon_bg_class": "bg-rose-100 dark:bg-rose-500/10",
		"icon_color_class": "text-rose-500",
		"source_doctype": "Admin Seller Profile",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "=", "Active"]]),
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
						"label": "Satıcı Başvuruları",
						"to": "/app/Seller Application",
						"icon": "fas fa-file-lines",
						"icon_class": "bg-amber-100 dark:bg-amber-500/10 text-amber-500",
						"source_doctype": "Seller Application",
					},
					{
						"label": "Satıcı Profilleri",
						"to": "/app/Admin Seller Profile",
						"icon": "fas fa-store",
						"icon_class": "bg-emerald-100 dark:bg-emerald-500/10 text-emerald-500",
						"source_doctype": "Admin Seller Profile",
					},
					{
						# Sprint 2 sonrası: Buyer Profile deprecated; canonical User Profile.
						# can_buy=1 → KYC Verified alıcılar (operasyonel alıcı tabanı).
						"label": "Alıcı Profilleri",
						"to": "/app/User Profile?can_buy=1",
						"icon": "fas fa-user",
						"icon_class": "bg-blue-100 dark:bg-blue-500/10 text-blue-500",
						"source_doctype": "User Profile",
						"filters": [["can_buy", "=", 1]],
					},
					{
						"label": "Kullanıcılar",
						"to": "/app/User Profile",
						"icon": "fas fa-users",
						"icon_class": "bg-brand-100 dark:bg-brand-500/10 text-brand-600",
						"source_doctype": "User Profile",
					},
				],
			}
		),
	},
	# ── GMV Trend + Top Sellers ──
	{
		"title": "GMV Trendi",
		"subtitle": "Döneme göre ciro ve sipariş hareketi",
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
	},
	{
		"title": "En Çok Satan Satıcılar",
		"subtitle": "İlk 10",
		"widget_type": "bar_chart",
		"size": "md",
		"position": 310,
		"source_doctype": "Order",
		"aggregation": "sum",
		"metric_field": "total",
		"date_field": "order_date",
		"group_by_field": "seller",
		"result_limit": 10,
		"is_currency": 1,
		"period_scoped": 1,
		"filters_json": json.dumps([["status", "!=", "İptal Edildi"], ["seller", "is", "set"]]),
	},
	# ── Onboarding Funnel + Status Breakdown ──
	{
		"title": "Satıcı Onboarding Funnel",
		"subtitle": "Kullanıcıdan aktif satıcıya dönüşüm",
		"widget_type": "funnel_chart",
		"size": "lg",
		"position": 400,
		"period_scoped": 0,
		"config_json": json.dumps(
			{
				"stages": [
					{
						"key": "users",
						"label": "Kullanıcı",
						"doctype": "User Profile",
						"filters": [["status", "=", "Active"]],
					},
					{
						"key": "applications",
						"label": "Başvuru",
						"doctype": "Seller Application",
						"filters": [],
					},
					{
						"key": "under_review",
						"label": "İnceleniyor",
						"doctype": "Seller Application",
						"filters": [["status", "=", "Under Review"]],
					},
					{
						"key": "approved",
						"label": "Onaylandı",
						"doctype": "Seller Application",
						"filters": [["status", "=", "Approved"]],
					},
					{
						"key": "active",
						"label": "Aktif Satıcı",
						"doctype": "Admin Seller Profile",
						"filters": [["status", "=", "Active"]],
					},
				],
			}
		),
	},
	{
		"title": "Başvuru Durumları",
		"subtitle": "Satıcı başvurularının durum dağılımı",
		"widget_type": "status_breakdown",
		"size": "lg",
		"position": 410,
		"source_doctype": "Seller Application",
		"group_by_field": "status",
		"period_scoped": 0,
		"config_json": json.dumps(
			{
				"labels": {
					"Draft": "Taslak",
					"Submitted": "Gönderildi",
					"Under Review": "İnceleniyor",
					"Approved": "Onaylandı",
					"Rejected": "Reddedildi",
				},
				"colors": {
					"Draft": "text-gray-400",
					"Submitted": "text-blue-500",
					"Under Review": "text-indigo-500",
					"Approved": "text-emerald-500",
					"Rejected": "text-red-500",
				},
			}
		),
	},
]


def execute():
	"""Seed widgets idempotently."""
	for spec in PLATFORM_WIDGETS:
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
		return  # Idempotent: skip if already seeded

	doc = frappe.new_doc("Dashboard Widget")
	doc.dashboard_key = DASHBOARD_KEY
	doc.is_enabled = 1
	for field, value in spec.items():
		doc.set(field, value)
	doc.insert(ignore_permissions=True)
