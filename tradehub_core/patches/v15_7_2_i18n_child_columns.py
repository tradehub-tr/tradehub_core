"""FAZ 7.2 — Teknik özellik + varyant çok-dilliliği: child-table dil kolonları.

Listing Attribute Value (attribute_label, attribute_value) ve Listing Variant Item
(attribute_type, attribute_value, attribute_type_2, attribute_value_2) child
DocType'larına `{field}_tr/_en/_ar/_ru` sufix kolonları ekler.

Kaynak/varsayılan dil PARENT Listing'in content_default_lang'inden gelir.
Backfill: mevcut TR içerik `{field}_tr = {field}`. İdempotent.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tradehub_core.seo.i18n import _LANG_LABEL, CONTENT_CHILD_TRANSLATABLE_FIELDS, CONTENT_LANGS


def _build_custom_fields() -> dict[str, list[dict]]:
	out: dict[str, list[dict]] = {}
	for doctype, fields in CONTENT_CHILD_TRANSLATABLE_FIELDS.items():
		entries: list[dict] = []
		for field, spec in fields.items():
			prev = field
			for lang in CONTENT_LANGS:
				col = f"{field}_{lang}"
				entry = {
					"fieldname": col,
					"label": f"{field} ({_LANG_LABEL[lang]})",
					"fieldtype": spec["fieldtype"],
					"insert_after": prev,
					"translatable": 0,
				}
				if spec.get("length"):
					entry["length"] = spec["length"]
				entries.append(entry)
				prev = col
		out[doctype] = entries
	return out


def _backfill() -> None:
	for doctype, fields in CONTENT_CHILD_TRANSLATABLE_FIELDS.items():
		table = f"tab{doctype}"
		for field in fields:
			tr_col = f"{field}_tr"
			frappe.db.sql(
				f"UPDATE `{table}` SET `{tr_col}` = `{field}` "
				f"WHERE (`{tr_col}` IS NULL OR `{tr_col}` = '') AND `{field}` IS NOT NULL"
			)


def execute() -> dict:
	present = [dt for dt in CONTENT_CHILD_TRANSLATABLE_FIELDS if frappe.db.exists("DocType", dt)]
	if not present:
		return {"skipped": "doctypes_missing"}
	create_custom_fields(_build_custom_fields(), update=True)
	_backfill()
	frappe.db.commit()
	return {"updated": present}
