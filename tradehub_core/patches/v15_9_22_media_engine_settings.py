# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""A1b: `Media Engine Settings` singleton'ını kurar ve varsayılanlarını yazar.

Kritik: `media_pipeline_enabled` **0** yazılır. Dalga A'nın tüm güvencesi bu
satırda — yeni medya boru hattı ürüne bağlansa bile bayrak açılana kadar
sistem bugünkü davranışını birebir sürdürür.

Idempotent: yalnızca `tabSingles`'ta HİÇ satırı olmayan alana varsayılan yazar.
Operatör bayrağı açtıysa yama tekrar koştuğunda değeri geri kapatmaz — bir
migrate'in üretimdeki ayarı sessizce sıfırlaması bu yamanın en tehlikeli
yanlışı olurdu.
"""

from __future__ import annotations

import frappe

DOCTYPE = "Media Engine Settings"

#: Alan -> varsayılan. Bayrakların üçü de KAPALI.
VARSAYILANLAR: dict[str, object] = {
	"media_pipeline_enabled": 0,
	"rendition_on_upload": 0,
	"manifest_api_enabled": 0,
	"active_slots": "",
	"max_renditions_per_asset": 40,
}


def execute() -> dict:
	# Yeni DocType migrate sırasında bu yamadan önce yüklenmemiş olabilir.
	frappe.reload_doc("tradehub_core", "doctype", "media_engine_settings")

	yazilan: list[str] = []
	for alan, varsayilan in VARSAYILANLAR.items():
		if _kayitli_mi(alan):
			continue
		frappe.db.set_single_value(DOCTYPE, alan, varsayilan)
		yazilan.append(alan)

	frappe.db.commit()
	return {"written": yazilan}


def _kayitli_mi(alan: str) -> bool:
	"""Single değerinin `tabSingles`'ta satırı var mı.

	`get_single_value` ile "boş mu" diye bakmak yetmezdi: operatörün bilerek 0
	yaptığı bir bayrak da boş görünür ve yama onu her koşuda yeniden yazardı.
	"""
	# Ham SQL: `Singles` bir DocType değil, Frappe'nin singleton değerlerini
	# tuttuğu sistem tablosudur — `frappe.db.exists("Singles", ...)` burada
	# DAİMA None döner ve yama her koşuda varsayılanı yeniden yazardı
	# (operatörün açtığı bayrağı sessizce kapatırdı). Kullanıcı verisi değil,
	# bu yüzden `frappe.get_list` kuralının kapsamı dışında.
	satir = frappe.db.sql(
		"SELECT 1 FROM `tabSingles` WHERE `doctype` = %s AND `field` = %s LIMIT 1",
		(DOCTYPE, alan),
	)
	return bool(satir)
