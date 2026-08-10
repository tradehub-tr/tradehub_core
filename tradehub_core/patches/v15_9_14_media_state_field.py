"""`File` doctype'ına medya yaşam döngüsü durumu ekle (TUR-138).

Durum önce ayrı damgalardan türetiliyordu (`th_trashed_at`, `th_optimized_at`).
Bu alan durumu açık hâle getirir; damgalar KALDIRILMAZ — onlar "ne zaman"
sorusunu cevaplıyor, bu alan "şu an hangi durumda" sorusunu.

Değerler: Active · Archived · Trashed
`Deleted` burada saklanmaz — kaydı olmayan dosyanın durumu da olmaz, o bilgi
denetim kaydında (`media.delete`) yaşar.

Idempotent: `create_custom_fields` mevcut alanı yeniden oluşturmaz, backfill
yalnız boş alanlara dokunur.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tradehub_core.media.states import STORED_STATES, backfill

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_state",
			"label": "TH Media State",
			"fieldtype": "Select",
			"options": "\n".join(("", *STORED_STATES)),
			"default": "",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_trashed_at",
			"module": "Tradehub Core",
		}
	]
}


def execute() -> dict:
	created = [
		f["fieldname"]
		for f in FIELDS["File"]
		if not frappe.db.exists("Custom Field", {"dt": "File", "fieldname": f["fieldname"]})
	]
	create_custom_fields(FIELDS, ignore_validate=True)
	frappe.db.commit()

	# Sık filtrelenen kolon — indekssiz bırakmak envanter sorgusunu yavaşlatır.
	try:
		frappe.db.add_index("File", ["th_media_state"])
	except Exception:
		frappe.log_error(title="media state index failed", message=frappe.get_traceback())

	result = backfill()
	return {"created": created, **result}
