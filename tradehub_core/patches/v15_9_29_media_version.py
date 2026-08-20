# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-064 (Şerit A) — `Media Version` DocType'ını kur.

Bu tablo olmadan bir varlığın iki sürümü aynı anda var OLAMAZ; yani "eski sürüm
geçiş boyunca erişilebilir" iddiası ölçülemezdi (`docs/reports/40-t043-kullanim-gc.md`
§7.1). Atomik geçişin ikinci yarısı `Media Asset.active_version` alanıdır ve o
bu tabloya Link verdiği için SIRA ÖNEMLİ: bu yama, `v15_9_30`dan ÖNCE koşar.
Link hedefi henüz yokken alan eklenirse DocType kaydı düşer (v15_9_21'in
ölçtüğü tuzağın aynısı).

`reload_doc` dönüş değeri kontrol edilir — sessizce `False` döner, hata
FIRLATMAZ (bkz. v15_9_25 ve v15_9_28).

Idempotent, veri yazmaz.
"""

from __future__ import annotations

import frappe
from frappe import _

DOCTYPE: str = "Media Version"
TABLO: str = "tabMedia Version"

#: Kaynak: doctype_specs/_ddl.sql satır 381. `version_hash` üzerindeki UNIQUE
#: DocType JSON'unda (`"unique": 1`) tanımlı, burada tekrar edilmiyor.
INDEKSLER: dict[str, tuple[str, ...]] = {
	"ix_asset_active": ("asset", "is_active"),
}


def execute() -> dict:
	if not frappe.reload_doc("tradehub_core", "doctype", "media_version"):
		frappe.throw(_("Media Version DocType yüklenemedi — şema dosyası bulunamadı."))

	if not frappe.db.table_exists(DOCTYPE):
		frappe.throw(_("Media Version DocType kaydı oluştu ama tablosu yok: {0}").format(TABLO))

	eklenen = [ad for ad in INDEKSLER if _indeks_kur(ad)]
	frappe.db.commit()
	return {"doctype": DOCTYPE, "indexes_added": eklenen}


def _indeks_kur(ad: str) -> bool:
	mevcut = {
		r[0]
		for r in frappe.db.sql(
			"""select index_name from information_schema.statistics
			where table_schema = database() and table_name = %s""",
			(TABLO,),
		)
	}
	if ad in mevcut:
		return False
	kolonlar = ", ".join(f"`{k}`" for k in INDEKSLER[ad])
	frappe.db.sql(f"alter table `{TABLO}` add key `{ad}` ({kolonlar})")
	return True
