"""MOGEM-617/T-144 deterministik canary ve yüzde rollout alanları."""

from __future__ import annotations

import frappe

DOCTYPE = "Media Engine Settings"


def execute() -> None:
	frappe.reload_doc("tradehub_core", "doctype", "media_engine_settings")
	if not _kayitli_mi("rollout_percent"):
		# Ana şalter zaten fail-safe kapalıdır. Daha önce bilinçli açılmış bir
		# kurulum migrate sonrası sessizce `%0`a düşmesin; geriye uyum `%100`.
		frappe.db.set_single_value(DOCTYPE, "rollout_percent", 100)
	if not _kayitli_mi("rollout_stores"):
		frappe.db.set_single_value(DOCTYPE, "rollout_stores", "")


def _kayitli_mi(field: str) -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM `tabSingles` WHERE `doctype` = %s AND `field` = %s LIMIT 1",
			(DOCTYPE, field),
		)
	)
