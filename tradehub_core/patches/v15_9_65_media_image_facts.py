# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Görsel künyesi (DPI · renk uzayı · alfa) — `File` alanları + geriye dönük doldurma.

Panelin Kalite sekmesi bu üç satırı "—" ile gösteriyordu: kaynak dosyanın
DPI'ı, renk uzayı ve alfası hiçbir yerde saklanmıyordu (`Media Version`
alanları normalize KARARIDIR, dosyadan ölçüm değil). Bu yama:

1. `File` üzerine `th_media_dpi / th_media_colorspace / th_media_alpha /
   th_media_facts` alanlarını açar (idempotent — `create_custom_fields`).
2. Tüm görsel `File` adreslerini ve `ready` görsel türevleri diskten ÖLÇEN
   işi `long` kuyruğuna atar (`media.image_facts.backfill_all`). Dosyalara
   yazılmaz; yalnız okunur. `Media Rendition.output_*` alanları DocType
   JSON'undan gelir (post_model_sync'te hazır).
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_dpi",
			"label": "TH Media DPI",
			"fieldtype": "Int",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_media_height",
			"module": "Tradehub Core",
			"description": "Dosyadan ölçülen DPI; 0 = dosyada DPI kaydı yok.",
		},
		{
			"fieldname": "th_media_colorspace",
			"label": "TH Media Colorspace",
			"fieldtype": "Data",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_media_dpi",
			"module": "Tradehub Core",
			"description": "ICC profil adı (sRGB, Display P3…) ya da profilsiz kip (RGB, CMYK, Gray).",
		},
		{
			"fieldname": "th_media_alpha",
			"label": "TH Media Alpha",
			"fieldtype": "Select",
			"options": "\nyes\nno",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_media_colorspace",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_facts",
			"label": "TH Media Facts Status",
			"fieldtype": "Select",
			"options": "\nok\nunreadable\nmissing",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_media_alpha",
			"module": "Tradehub Core",
		},
	]
}


def execute() -> dict:
	olusan = [a["fieldname"] for a in FIELDS["File"] if not frappe.db.has_column("File", a["fieldname"])]
	create_custom_fields(FIELDS, ignore_validate=True)
	frappe.db.commit()
	try:
		frappe.enqueue(
			"tradehub_core.media.image_facts.backfill_all",
			queue="long",
			timeout=3600,
			job_id="media-image-facts-backfill",
			deduplicate=True,
			enqueue_after_commit=False,
		)
	except Exception:
		# Redis/kuyruk migrate anında ayakta değilse migrate düşmesin; doldurma
		# elle koşulabilir: `bench execute tradehub_core.media.image_facts.backfill_all`.
		frappe.log_error(title="media image facts backfill enqueue", message=frappe.get_traceback())
	return {"created": olusan}
