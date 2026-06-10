"""FAZ B — Regex Pattern Library'ye match_count (Int) kullanım sayacı ekle.

`match_count` standart DocType alanı olarak eklendi (read_only, default 0); bench
migrate kolonu açar. Bu patch mevcut kayıtlarda NULL sayaçları 0'a backfill eder.
İdempotent: kolon yoksa no-op, zaten 0 olanlar etkilenmez.
"""

from __future__ import annotations

import frappe


def execute():
	# has_column DocType adını bekler; "tab" önekli isim ikinci kez prefix'lenip
	# tabtab... aranmasına ve TableMissingError'a yol açar.
	if not frappe.db.table_exists("Regex Pattern Library"):
		return
	if not frappe.db.has_column("Regex Pattern Library", "match_count"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabRegex Pattern Library`
		SET match_count = 0
		WHERE match_count IS NULL
		"""
	)
	frappe.db.commit()
