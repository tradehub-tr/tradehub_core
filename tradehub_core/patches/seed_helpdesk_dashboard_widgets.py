# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seed helpdesk widgets onto platform_overview + seller_overview dashboards.

Helpdesk yanıt akışı backend tarafında olgunlaştı (in-app + e-posta) — bu
patch ile destek operasyonu KPI'ları admin'in/satıcının ana sayfasına
düşüyor. Permission query satıcıyı kendi team'ine kısıtladığından seller
widget'ları için ek scope_field gerekmez; HD Ticket count otomatik
satıcının ticket'larıyla filtrelenir.

Idempotent: (dashboard_key, title) kompozit anahtarıyla skip edilir.
"""

import json

import frappe

PLATFORM_KEY = "platform_overview"
SELLER_KEY = "seller_overview"


# Platform Support — System Manager / Support Manager / Agent Manager rolleri
# tüm ticket'ları görür.
PLATFORM_WIDGETS = [
	{
		"title": "Açık Destek Talebi",
		"subtitle": "Müşteri yanıtı bekleyen veya yeni açılan talepler",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 150,
		"icon": "fas fa-life-ring",
		"icon_bg_class": "bg-cyan-100 dark:bg-cyan-500/10",
		"icon_color_class": "text-cyan-500",
		"source_doctype": "HD Ticket",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "in", ["Open", "Replied"]]]),
		"config_json": json.dumps(
			{
				"action_link": {
					"to": "/helpdesk/tickets",
					"label": "Tüm taleplere git →",
				}
			}
		),
	},
	{
		"title": "Yanıt Bekleyen Talep",
		"subtitle": "Müşteri yanıt verdi, ajan beklemede",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 160,
		"icon": "fas fa-reply",
		"icon_bg_class": "bg-amber-100 dark:bg-amber-500/10",
		"icon_color_class": "text-amber-500",
		"source_doctype": "HD Ticket",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "=", "Open"]]),
		"config_json": json.dumps(
			{
				"action_link": {
					"to": "/helpdesk/tickets?tab=Open",
					"label": "Yanıtla →",
				}
			}
		),
	},
]


# Satıcı paneli — permission query agent'ı kendi team'iyle kısıtlar; ek
# filtreye gerek yok.
SELLER_WIDGETS = [
	{
		"title": "Açık Talebim",
		"subtitle": "Mağazama gelen aktif destek talepleri",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 150,
		"icon": "fas fa-life-ring",
		"icon_bg_class": "bg-cyan-100 dark:bg-cyan-500/10",
		"icon_color_class": "text-cyan-500",
		"source_doctype": "HD Ticket",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "in", ["Open", "Replied"]]]),
		"config_json": json.dumps(
			{
				"action_link": {
					"to": "/helpdesk/tickets",
					"label": "Taleplerime git →",
				}
			}
		),
	},
	{
		"title": "Yanıt Bekleyen Talebim",
		"subtitle": "Müşteri yanıt yazdı; benden yanıt bekleniyor",
		"widget_type": "kpi_single",
		"size": "sm",
		"position": 160,
		"icon": "fas fa-reply",
		"icon_bg_class": "bg-amber-100 dark:bg-amber-500/10",
		"icon_color_class": "text-amber-500",
		"source_doctype": "HD Ticket",
		"aggregation": "count",
		"period_scoped": 0,
		"filters_json": json.dumps([["status", "=", "Open"]]),
		"config_json": json.dumps(
			{
				"action_link": {
					"to": "/helpdesk/tickets?tab=Open",
					"label": "Yanıtla →",
				}
			}
		),
	},
]


def execute():
	for spec in PLATFORM_WIDGETS:
		_upsert_widget(PLATFORM_KEY, spec)
	for spec in SELLER_WIDGETS:
		_upsert_widget(SELLER_KEY, spec)
	frappe.db.commit()


def _upsert_widget(dashboard_key, spec):
	title = spec["title"]
	existing = frappe.db.get_value(
		"Dashboard Widget",
		{"dashboard_key": dashboard_key, "title": title},
		"name",
	)
	if existing:
		return

	doc = frappe.new_doc("Dashboard Widget")
	doc.dashboard_key = dashboard_key
	doc.is_enabled = 1
	for field, value in spec.items():
		doc.set(field, value)
	doc.insert(ignore_permissions=True)
