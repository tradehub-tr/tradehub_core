"""Zararlı içerik taraması alanları — `File` üstünde dört alan (TUR-125).

`th_media_scan_status`      : pending | clean | infected | failed. Panelin
rozet gösterebilmesi ve karantina filtresinin çalışabilmesi için açık alan.
Yaşam döngüsü durumundan (`th_media_state`) ve video iş durumundan
(`th_media_video_status`) AYRI eksen — üçünü tek alana sıkıştırmak her yeni iş
türünde durum sözlüğünü çarpardı.

`th_media_scan_attempts`    : bu iş için harcanan deneme hakkı.
`th_media_scan_next_at`     : planlı bir sonraki denemenin en erken zamanı.
`th_media_scan_started_at`  : mevcut denemenin başlama anı — sert kill (RQ
zaman aşımı, OOM) `except` bloğunu çalıştırmadığı için sayaç artmıyor ve dosya
`pending`de asılı kalıyordu; süpürücü bu damgaya bakarak bırakılmış işi bulur.

Son üçü `hidden`: operasyonel bilgi, kullanıcıya gösterilen durum
`th_media_scan_status`'tur.

**Backfill YOK.** Mevcut 5.150 kaydın durumu BOŞ kalır ve boş "hiç
taranmadı" demektir — `clean` yazmak taranmamış dosyaları taranmış gibi
gösterirdi, bu alanın en tehlikeli yanlışı. Geriye dönük tarama
`media.av.backfill_pending` ile parça parça, elle tetiklenir; hepsini tek turda
kuyruğa boşaltmak kuyruğu saatlerce meşgul ederdi.

Idempotent: `create_custom_fields` mevcut alanı yeniden oluşturmaz.
Desen: `v15_9_19_media_transcode_schedule.py`.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tradehub_core.media.av import STORED_SCAN_STATUSES

FIELDS: dict[str, list[dict]] = {
	"File": [
		{
			"fieldname": "th_media_scan_status",
			"label": "TH Media Scan Status",
			"fieldtype": "Select",
			"options": "\n".join(("", *STORED_SCAN_STATUSES)),
			"default": "",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "th_media_transcode_started_at",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_scan_attempts",
			"label": "TH Media Scan Attempts",
			"fieldtype": "Int",
			"default": "0",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_scan_status",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_scan_next_at",
			"label": "TH Media Scan Next Attempt At",
			"fieldtype": "Datetime",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_scan_attempts",
			"module": "Tradehub Core",
		},
		{
			"fieldname": "th_media_scan_started_at",
			"label": "TH Media Scan Started At",
			"fieldtype": "Datetime",
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "th_media_scan_next_at",
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

	# Süpürücü her 5 dakikada bir `th_media_scan_status = 'pending'` sorgusu
	# atıyor; indekssiz bırakmak 4.000+ satırlık tabloda her turda tam tarama
	# demekti. `th_media_state` yamasında da aynı gerekçeyle index eklenmişti.
	try:
		frappe.db.add_index("File", ["th_media_scan_status"])
	except Exception:
		frappe.log_error(title="media scan index failed", message=frappe.get_traceback())

	return {"created": olusan}
