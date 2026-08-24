# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-066 — Media Quality Report DocType'ını mevcut sitelere kur."""

from __future__ import annotations

import frappe
from frappe import _

DOCTYPE = "Media Quality Report"


def execute() -> dict[str, str]:
	if not frappe.reload_doc("tradehub_core", "doctype", "media_quality_report"):
		frappe.throw(_("Media Quality Report DocType yüklenemedi."))
	if not frappe.db.table_exists(DOCTYPE):
		frappe.throw(_("Media Quality Report tablosu oluşturulamadı."))
	frappe.db.commit()
	return {"doctype": DOCTYPE, "status": "ready"}
