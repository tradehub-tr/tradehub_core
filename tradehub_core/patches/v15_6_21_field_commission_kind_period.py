# Copyright (c) 2026, TR TradeHub and contributors
"""Faz B — mevcut Field Commission kayıtlarına kind/period_key backfill.

- kind boşsa 'Satış' (eski kayıtların hepsi tekil satıştı).
- period_key boşsa oluşturma ayından (aylık varsayım: 'YYYY-MM').
"""

import frappe


def execute():
	if not frappe.db.table_exists("Field Commission"):
		return
	frappe.db.sql(
		"""UPDATE `tabField Commission` SET kind = %s WHERE kind IS NULL OR kind = ''""",
		("Satış",),
	)
	# values geçilmediği için '%Y-%m' literal olarak MySQL'e gider (frappe.db.sql
	# values boşken % formatlaması yapmaz).
	frappe.db.sql(
		"""UPDATE `tabField Commission` SET period_key = DATE_FORMAT(creation, '%Y-%m')
		WHERE period_key IS NULL OR period_key = ''"""
	)
	frappe.db.commit()
