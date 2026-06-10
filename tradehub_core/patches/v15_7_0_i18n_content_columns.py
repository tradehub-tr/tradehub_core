"""FAZ 7 — Dinamik içerik çok-dilliliği: dil-sufix kolonları.

Kategori + ürün ana metinlerini (category_name, description, title,
short_description, selling_point) çok-dilli yapmak için her alana
`{field}_tr/_en/_ar/_ru` sufix kolonları + kayıt başına `content_default_lang`
(kaynak/varsayılan dil) custom field'ları ekler.

Model:
  - base kolon (title, category_name...) korunur; controller `validate`'te
    `{field}_{content_default_lang}` değerine senkronlanır (legacy okuyucu + arama).
  - eksik diller resolve_content_field ile default dile fallback eder.

Backfill: mevcut TR içerik `{field}_tr = {field}`; `content_default_lang = 'tr'`.

İdempotent (create_custom_fields update=True + koşullu UPDATE).
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tradehub_core.seo.i18n import (
	_LANG_LABEL,
	CONTENT_LANGS,
	CONTENT_TRANSLATABLE_FIELDS,
)

_LANG_OPTIONS = "\n".join(CONTENT_LANGS)
_PRIMARY = {"Listing": "title", "Product Category": "category_name"}


def _build_custom_fields() -> dict[str, list[dict]]:
	out: dict[str, list[dict]] = {}
	for doctype, fields in CONTENT_TRANSLATABLE_FIELDS.items():
		entries: list[dict] = []
		# Kaynak/varsayılan dil seçici — birincil alandan sonra.
		entries.append(
			{
				"fieldname": "content_default_lang",
				"label": "İçerik Varsayılan Dili",
				"fieldtype": "Select",
				"options": _LANG_OPTIONS,
				"default": "tr",
				"reqd": 1,
				"insert_after": _PRIMARY[doctype],
				"description": (
					"Bu kaydın kaynak/varsayılan içerik dili. Çevirisi olmayan "
					"diller bu dile fallback eder; bu dil zorunludur."
				),
			}
		)
		# Her alan için 4 dil sufix kolonu (chain insert_after).
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
	for doctype, fields in CONTENT_TRANSLATABLE_FIELDS.items():
		table = f"tab{doctype}"
		# content_default_lang boşsa tr.
		frappe.db.sql(
			f"UPDATE `{table}` SET content_default_lang = 'tr' "
			f"WHERE content_default_lang IS NULL OR content_default_lang = ''"
		)
		# {field}_tr boşsa base kolondan kopyala (mevcut içerik TR).
		for field in fields:
			tr_col = f"{field}_tr"
			frappe.db.sql(
				f"UPDATE `{table}` SET `{tr_col}` = `{field}` "
				f"WHERE (`{tr_col}` IS NULL OR `{tr_col}` = '') AND `{field}` IS NOT NULL"
			)


def execute() -> dict:
	present = [dt for dt in CONTENT_TRANSLATABLE_FIELDS if frappe.db.exists("DocType", dt)]
	if not present:
		return {"skipped": "doctypes_missing"}

	create_custom_fields(_build_custom_fields(), update=True)
	_backfill()
	frappe.db.commit()
	return {"updated": present}
