"""Transcode zamanlama damgaları — `File` üstünde iki alan (TUR-296).

`th_media_transcode_next_at`  : bir sonraki denemenin en erken zamanı. Retry
artık kuyruğa ANINDA geri konmuyor (backoff); süpürücü bu damgaya bakıp
zamanı gelenleri alıyor.

`th_media_transcode_started_at`: mevcut denemenin kuyruğa girme/başlama anı.
Sert kill (RQ timeout, OOM) `except` bloğunu çalıştırmadığı için sayaç artmıyor
ve dosya sonsuza kadar `processing`de kalıyordu; süpürücü bu damgaya bakarak
bırakılmış işi yakalar.

İkisi de `hidden`: operasyonel bilgi, kullanıcıya gösterilen durum
`th_media_video_status`'tur. Boş = "hemen" / "hiç başlamadı" — mevcut kayıtlar
için doğal varsayılan, backfill gerekmiyor.

Idempotent: `create_custom_fields` mevcut alanı yeniden oluşturmaz.
Desen: `v15_9_18_media_transcode_attempts.py`.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_transcode_next_at",
			"label": "TH Media Transcode Next Attempt At",
			"fieldtype": "Datetime",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_transcode_attempts",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_transcode_started_at",
			"label": "TH Media Transcode Started At",
			"fieldtype": "Datetime",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_transcode_next_at",
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
