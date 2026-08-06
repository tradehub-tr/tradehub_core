"""`File` doctype'ına çöp kutusu damgası ekle.

`th_trashed_at` dolu olan dosya çöpe taşınmıştır: fiziksel dosya
`private/media_trash/` altındadır, public URL 404 döner, `File` kaydı durur.
30 gün sonra günlük job hem dosyayı hem kaydı kalıcı siler.

Kayıt silmek yerine damga kullanılmasının sebebi: geri alma. Silme kararı
"kullanılmıyor" taramasına dayanıyor ve o tarama yalnız veritabanını kapsıyor —
frontend'de sabit yazılmış bir görsel yanlışlıkla aday görünebilir.

Idempotent: `create_custom_fields` mevcut alanı yeniden oluşturmaz.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_trashed_at",
			"label": "TH Trashed At",
			"fieldtype": "Datetime",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_original_size",
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
	return {"created": created}
