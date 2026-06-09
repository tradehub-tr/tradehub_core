"""Demo içerik çevirilerini (en/ar/ru) suffix kolonlarına backfill et.

Çeviriler VERİ olduğu için git/app deploy ile taşınmaz; bu patch app'e gömülü
`patches/data/content_translations.json` haritasını kullanıp kaynak (TR) base
kolon değerini eşleştirerek `{field}_{lang}` kolonlarını doldurur.

İdempotent: yalnızca BOŞ suffix kolonu (`{base}_en` null/boş) doldurulur —
mevcut çeviri ezilmez, patch tekrar koşarsa no-op olur. Yalnızca haritadaki
kaynak metinle eşleşen kayıtlar çevrilir (demo seti); gerçek/farklı içerik
etkilenmez (eşleşmez → dokunulmaz).
"""

import json
import os

import frappe

# section -> (doctype, [base_field, ...])
_MAP: dict[str, tuple[str, list[str]]] = {
	"listing_title": ("Listing", ["title"]),
	"listing_short_description": ("Listing", ["short_description"]),
	"listing_description": ("Listing", ["description"]),
	"listing_selling_point": ("Listing", ["selling_point"]),
	"attr_label": ("Listing Attribute Value", ["attribute_label"]),
	"attr_value": ("Listing Attribute Value", ["attribute_value"]),
	"variant_type": ("Listing Variant Item", ["attribute_type", "attribute_type_2"]),
	"variant_value": ("Listing Variant Item", ["attribute_value", "attribute_value_2"]),
	"category_name": ("Product Category", ["category_name"]),
}

_LANGS = ("en", "ar", "ru")


def execute() -> None:
	path = frappe.get_app_path("tradehub_core", "patches", "data", "content_translations.json")
	if not os.path.exists(path):
		frappe.logger().warning("v15_7_3: content_translations.json bulunamadı, atlanıyor")
		return

	with open(path, encoding="utf-8") as f:
		data = json.load(f)

	total = 0
	for section, (doctype, base_fields) in _MAP.items():
		smap = data.get(section) or {}
		if not smap:
			continue
		for base in base_fields:
			# Suffix kolonları yoksa (patch sırası/şema farkı) atla.
			if not frappe.db.has_column(doctype, f"{base}_en"):
				continue
			for source, tr in smap.items():
				set_parts: list[str] = []
				vals: list[str] = []
				for lang in _LANGS:
					value = tr.get(lang)
					if not value or not frappe.db.has_column(doctype, f"{base}_{lang}"):
						continue
					set_parts.append(f"`{base}_{lang}` = %s")
					vals.append(value)
				if not set_parts:
					continue
				# Kaynak TR eşleşen + henüz çevrilmemiş (en boş) satırları doldur.
				frappe.db.sql(
					f"UPDATE `tab{doctype}` SET {', '.join(set_parts)} "
					f"WHERE `{base}` = %s AND (`{base}_en` IS NULL OR `{base}_en` = '')",
					(*vals, source),
				)
				total += frappe.db.sql("SELECT ROW_COUNT()")[0][0] or 0

	frappe.db.commit()
	frappe.logger().info(f"v15_7_3 içerik çeviri backfill: {total} satır güncellendi")
