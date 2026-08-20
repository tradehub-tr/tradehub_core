# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-043 (Şerit A) — `Media Usage` DocType'ını kur ve indekslerini garanti et.

NEDEN AYRI BİR YAMA GEREKİYOR
-----------------------------
`bench migrate` yeni DocType JSON'unu zaten yükler. Bu yama iki şey daha yapar
ve ikisi de SESSİZ BAŞARISIZLIĞI kapatır:

1. **Kurulumu DOĞRULAR.** `reload_doc` dosyayı bulamazsa `False` döner ve
   **hata FIRLATMAZ**. Bu depoda tam olarak bu oldu: bir yama `tabSingles`a 29
   değer yazdı, `Patch Log`a "koştu" yazıldı, ama `tabDocType` satırı hiç
   oluşmadı ve iki uç HTTP 500 verdi (`docs/reports/32-faz8-api-kapanis.md`).
   Dönüş değeri kontrol edilir, tablo varlığı ayrıca ölçülür.

2. **Bileşik UNIQUE indeksi kurar.** Frappe DocType JSON'u bileşik indeks ifade
   edemez. `core/usage.py::FrappeUsageBackend.upsert` `on duplicate key update`
   kullanıyor — bu ifade bir UNIQUE kısıt olmadan HİÇBİR ZAMAN tetiklenmez ve
   her yazma yeni satır açar; bağ kaydı sessizce çoğalır ve `is_open=0` yapılan
   bir bağ, aynı dörtlünün açık kopyası yüzünden hâlâ açık görünür. Yani öksüz
   kararı bozulur. Kısıt burada kurulur (`uk_usage_quad`).

`usage_key` BİLEREK unique DEĞİL: kaynak şemanın ölçümü, aynı kısıtı iki kez
ödemenin 419.676 satırda indeksi %49 şişirdiğini gösteriyor (571 MB → 290 MB).

Idempotent: `reload_doc` aynı JSON'u yeniden uygular; indeksler
`information_schema`dan denetlenip yoksa eklenir. İkinci koşumda hiçbir şey
değişmez ve HİÇBİR VERİ YAZILMAZ.
"""

from __future__ import annotations

import frappe
from frappe import _

DOCTYPE: str = "Media Usage"
TABLO: str = "tabMedia Usage"

#: indeks adı → (UNIQUE mi, kolonlar). Kaynak: doctype_specs/_ddl.sql satır 346-352.
INDEKSLER: dict[str, tuple[bool, tuple[str, ...]]] = {
	"ix_asset_open": (False, ("asset", "is_open")),
	"ix_ref": (False, ("ref_doctype", "ref_name")),
	"uk_usage_quad": (True, ("asset", "ref_doctype", "ref_name", "ref_field")),
}


def execute() -> dict:
	if not frappe.reload_doc("tradehub_core", "doctype", "media_usage"):
		frappe.throw(_("Media Usage DocType yüklenemedi — şema dosyası bulunamadı."))

	if not frappe.db.table_exists(DOCTYPE):
		frappe.throw(_("Media Usage DocType kaydı oluştu ama tablosu yok: {0}").format(TABLO))

	eklenen = [ad for ad in INDEKSLER if _indeks_kur(ad)]
	frappe.db.commit()
	return {"doctype": DOCTYPE, "indexes_added": eklenen, "indexes_total": len(INDEKSLER)}


def _mevcut_indeksler() -> set[str]:
	satirlar = frappe.db.sql(
		"""select index_name from information_schema.statistics
		where table_schema = database() and table_name = %s""",
		(TABLO,),
	)
	return {r[0] for r in satirlar}


def _indeks_kur(ad: str) -> bool:
	"""İndeks yoksa ekle. Ekledi ise `True`."""
	if ad in _mevcut_indeksler():
		return False
	tekil, kolonlar = INDEKSLER[ad]
	kolon_metni = ", ".join(f"`{k}`" for k in kolonlar)
	# Tablo/indeks/kolon adlarının hiçbiri kullanıcı girdisinden gelmiyor —
	# hepsi bu modülde sabit. Frappe'nin `add_index`i bileşik UNIQUE ifade
	# edemediği için DDL doğrudan yazılıyor.
	frappe.db.sql(
		f"alter table `{TABLO}` add {'unique ' if tekil else ''}key `{ad}` ({kolon_metni})"
	)
	return True
