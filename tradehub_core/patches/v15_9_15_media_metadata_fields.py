"""Satıcı medya üstverisi için `File` alanları.

Ekranda başlık, alternatif metin, açıklama, etiket, favori ve çözünürlük
alanları vardı ama hiçbirinin arka tarafta karşılığı yoktu: kullanıcı yazıyor,
sayfa yenilenince kayboluyordu. Bu yama alanları açar.

Alanlar KAYIT düzeyinde: aynı görsel iki mağazaya birden ait olabildiği için
her mağaza kendi alternatif metnini yazabilmeli (bkz. `media/metadata.py`).

Idempotent: `create_custom_fields` mevcut alanı yeniden oluşturmaz.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_title",
			"label": "TH Media Title",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_state",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_alt",
			"label": "TH Media Alt Text",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_title",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_description",
			"label": "TH Media Description",
			"fieldtype": "Small Text",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_alt",
			"module": "Tradehub Core",
		},
		{
			# Virgülle ayrılmış. Alt tablo açılmadı: etiket sayısı küçük ve
			# sorgu ihtiyacı "içinde geçiyor mu" düzeyinde.
			"fieldname": "th_media_tags",
			"label": "TH Media Tags",
			"fieldtype": "Data",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_description",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_favorite",
			"label": "TH Media Favorite",
			"fieldtype": "Check",
			"default": "0",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_tags",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_width",
			"label": "TH Media Width",
			"fieldtype": "Int",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_media_favorite",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_height",
			"label": "TH Media Height",
			"fieldtype": "Int",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_media_width",
			"module": "Tradehub Core",
		},
	]
}

# Etiket ve favori üzerinden süzme yapılacak; ikisi de indekssiz tam tarama
# olurdu.
INDEXES: tuple[tuple[str, list[str]], ...] = (
	("File", ["th_media_favorite"]),
)


def execute() -> dict:
	# `has_column` DOCTYPE adı ister, tablo adı değil — "tab" önekini kendisi
	# ekliyor.
	olusan = [
		alan["fieldname"]
		for alan in FIELDS["File"]
		if not frappe.db.has_column("File", alan["fieldname"])
	]
	create_custom_fields(FIELDS, ignore_validate=True)

	for doctype, kolonlar in INDEXES:
		try:
			frappe.db.add_index(doctype, kolonlar)
		except Exception:
			# İndeks zaten varsa MariaDB hata verir; yamanın tekrar
			# çalışabilmesi bundan daha önemli.
			pass

	frappe.db.commit()
	return {"created": olusan}
