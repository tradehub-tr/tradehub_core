"""`File` doctype'ına optimizasyon izleme alanlarını ekle.

Neden custom field, neden yeni DocType değil: işaretin kalıcı olması gerekiyor
(Redis TTL'li). İki alan yeterli, ayrı bir tablo açmak envanteri ve kotayı şişirir.

  - `th_optimized_at`  → Kapı 5'in (`already_optimized`) dayanağı. Nesil kaybı
    koruması: dolu olan dosya ikinci kez optimize edilmez.
  - `th_original_size` → "ne kazandık" raporu + geri alma sonrası doğrulama.

İkisi de `hidden=1, read_only=1` — desk formunda gürültü yapmasın; yalnız
`tradehub_core/media/` paketi yazar.

Idempotent: `create_custom_field` mevcut alanı yeniden oluşturmaz.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_optimized_at",
			"label": "TH Optimized At",
			"fieldtype": "Datetime",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "content_hash",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_original_size",
			"label": "TH Original Size",
			"fieldtype": "Int",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_optimized_at",
			"module": "Tradehub Core",
		},
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

	return {"created": created}
