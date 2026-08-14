"""Video async transcode durum alanı — `File.th_media_video_status` (TUR-296/297).

WP2: sunucu görsel yolunu WebP'ye garanti çevirirken, video yüklemeleri
async ffmpeg transcode'una alınıyor (`media/transcode.py`). Panelin "işleniyor
/ hazır / başarısız" rozeti gösterebilmesi için durumun açık bir alanda
tutulması gerekiyor — `th_media_state` (TUR-138) farklı bir eksen (aktif/
arşiv/çöp), video işleme durumunu KARIŞTIRMAMAK için ayrı alan.

Boş değer = video değil ya da henüz kuyruğa alınmamış (mevcut dosyalar için
varsayılan davranış — geriye dönük hiçbir video "processing" görünmez).

Idempotent: `create_custom_fields` mevcut alanı yeniden oluşturmaz.
Desen: `v15_9_15_media_metadata_fields.py`.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_video_status",
			"label": "TH Media Video Status",
			"fieldtype": "Select",
			"options": "\nprocessing\nready\nfailed",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_height",
			"module": "Tradehub Core",
		},
	]
}


def execute() -> dict:
	# `has_column` DOCTYPE adı ister, tablo adı değil — "tab" önekini kendisi
	# ekliyor.
	olusan = [
		alan["fieldname"]
		for alan in FIELDS["File"]
		if not frappe.db.has_column("File", alan["fieldname"])
	]
	create_custom_fields(FIELDS, ignore_validate=True)
	frappe.db.commit()
	return {"created": olusan}
