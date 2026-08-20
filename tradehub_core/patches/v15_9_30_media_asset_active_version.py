# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-064 (Şerit A) — `Media Asset.active_version` kolonunu kur ve ÖLÇ.

ÖLÇÜLEN SAPMA (2026-08-19, istoc.localhost)
-------------------------------------------
Üç ayrı rapor "şemada var, kurulu tabloda yok" diyordu. Yeniden ölçüldüğünde
ayrım daha keskin çıktı ve raporlar iki farklı dosyayı "şema" diye
karıştırıyordu:

  * `media/pipeline/doctype_specs/media_asset.json`  → TASARIM belgesi.
    `active_version` ve `source` var, `asset_key`/`source_file` yok.
  * `tradehub_core/doctype/media_asset/media_asset.json` → KURULU DocType.
    `asset_key`/`source_file` var, `active_version` YOKTU.
  * `tabMedia Asset` (canlı tablo) → KURULU JSON ile BİREBİR aynıydı.

Yani ayrışma "JSON ile tablo arasında" değil, "tasarım belgesi ile kurulu
DocType arasında"ydı ve üç sapmasının üçü de kurulu JSON'un `$comment`ında
GEREKÇESİYLE yazılıydı. Bu yama o üç sapmadan YALNIZ birini kapatır —
`active_version` — çünkü diğer ikisi (`slot_key` Data, `source_file` Link→File)
bilinçli ve hâlâ geçerli: `Media Policy` ve `Media Source` kurulmadı.

Yama ne yapar: DocType'ı yeniden yükler ve kolonun GERÇEKTEN oluştuğunu
`information_schema`dan doğrular. "JSON'da doğru ≠ canlıda etkin" — bu depoda
KYC/KYB `status` alanı JSON'da permlevel 4 iken canlı `tabDocField`da 1'di ve
ikinci güvenlik katmanı sessizce düşmüştü. Aynı hataya düşmemek için alanın
permlevel'i de canlı `tabDocField`dan ölçülür.

Idempotent, veri yazmaz.
"""

from __future__ import annotations

import frappe
from frappe import _

DOCTYPE: str = "Media Asset"
#: `has_column`/`table_exists` DOCTYPE adı ister, tablo adı DEĞİL
#: (ölçüldü: `has_column("tabMedia Asset", ...)` `TableMissingError` fırlattı,
#: çünkü Frappe başına ikinci bir `tab` ekliyor). Tablo adı yalnız insan
#: okuyacak mesajlarda geçer.
TABLO: str = "tabMedia Asset"
ALAN: str = "active_version"

#: Alanın canlıda taşıması GEREKEN nitelikler. JSON'a değil, `tabDocField`e
#: bakılır — iddia ile gerçek arasındaki fark tam burada ölçülür.
BEKLENEN: dict[str, object] = {"fieldtype": "Link", "options": "Media Version", "permlevel": 1}


def execute() -> dict:
	# Link hedefi kurulu olmalı; değilse DocType kaydı sessizce düşer.
	if not frappe.db.exists("DocType", "Media Version"):
		frappe.throw(
			_("Media Version DocType kurulu değil — v15_9_29 bu yamadan ÖNCE koşmalı.")
		)

	if not frappe.reload_doc("tradehub_core", "doctype", "media_asset"):
		frappe.throw(_("Media Asset DocType yüklenemedi — şema dosyası bulunamadı."))

	if not frappe.db.has_column(DOCTYPE, ALAN):
		frappe.throw(
			_("Media Asset.{0} kolonu oluşmadı — DocType yüklendi ama tablo güncellenmedi.").format(
				ALAN
			)
		)

	olculen = frappe.db.get_value(
		"DocField",
		{"parent": DOCTYPE, "fieldname": ALAN},
		["fieldtype", "options", "permlevel"],
		as_dict=True,
	)
	if not olculen:
		frappe.throw(_("Media Asset.{0} `tabDocField`de yok.").format(ALAN))

	sapma = {
		k: {"beklenen": v, "olculen": olculen.get(k)}
		for k, v in BEKLENEN.items()
		if _normal(k, olculen.get(k)) != v
	}
	if sapma:
		frappe.throw(
			_("Media Asset.{0} canlıda beklenenden farklı: {1}").format(ALAN, frappe.as_json(sapma))
		)

	frappe.db.commit()
	return {"doctype": DOCTYPE, "column": ALAN, "measured": dict(olculen)}


def _normal(alan: str, deger: object) -> object:
	"""`permlevel` boş gelirse 0'dır — Frappe 0'ı bazen NULL olarak saklar."""
	if alan == "permlevel":
		return int(deger or 0)
	return deger
