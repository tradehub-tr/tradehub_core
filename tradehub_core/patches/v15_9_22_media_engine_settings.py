# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""A1b: `Media Engine Settings` singleton'ını kurar ve varsayılanlarını yazar.

Yeni kurulumda medya işleme, yüklemede türev üretimi ve manifest teslimi
açıktır. Desteklenen slotlar varsayılan olarak etkinleşir; dosya kapsamı ve
özel dosya denetimleri üretim köprüsünde uygulanmaya devam eder.

Idempotent: yalnızca `tabSingles`'ta HİÇ satırı olmayan alana varsayılan yazar.
Operatörün kaydettiği açma/kapatma ve kapsam tercihleri değiştirilmez.
"""

from __future__ import annotations

import frappe

DOCTYPE = "Media Engine Settings"

#: Alan -> yeni kurulum varsayılanı. Kayıtlı tercihler her zaman önceliklidir.
VARSAYILANLAR: dict[str, object] = {
	"media_pipeline_enabled": 1,
	"rendition_on_upload": 1,
	"manifest_api_enabled": 1,
	"active_slots": "*",
	"max_renditions_per_asset": 40,
}


def execute() -> dict:
	# Yeni DocType migrate sırasında bu yamadan önce yüklenmemiş olabilir.
	frappe.reload_doc("tradehub_core", "doctype", "media_engine_settings", force=True)

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
	# (operatörün kapattığı bayrağı sessizce açardı). Kullanıcı verisi değil,
	# bu yüzden `frappe.get_list` kuralının kapsamı dışında.
	satir = frappe.db.sql(
		"SELECT 1 FROM `tabSingles` WHERE `doctype` = %s AND `field` = %s LIMIT 1",
		(DOCTYPE, alan),
	)
	return bool(satir)
