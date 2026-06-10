"""FAZ A — Seller Value Mapping'e scope kolonu (System / Seller Override).

`scope` standart DocType alanı olarak eklendi; bench migrate kolonu açar. Bu patch
mevcut (scope'suz) kayıtları "Seller Override" olarak backfill eder — eski tüm
kayıtlar satıcıya özeldi. İdempotent: kolon yoksa veya boş kayıt yoksa no-op.
"""

from __future__ import annotations

import frappe


def execute():
	# has_column DocType adını bekler; "tab" önekli isim ikinci kez prefix'lenip
	# tabtab... aranmasına ve TableMissingError'a yol açar.
	if not frappe.db.table_exists("Seller Value Mapping"):
		return
	if not frappe.db.has_column("Seller Value Mapping", "scope"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabSeller Value Mapping`
		SET scope = 'Seller Override'
		WHERE scope IS NULL OR scope = ''
		"""
	)
	frappe.db.commit()
