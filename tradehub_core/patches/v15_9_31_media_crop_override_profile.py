# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-041 (Şerit A) — `Media Crop Override.profile` Link → Data.

ÖLÇÜLEN KIRIK (2026-08-19, istoc.localhost)
-------------------------------------------
`overrides` ile kırpma niyeti UÇTAN UCA KAYDEDİLEMİYORDU. İki taraf iki farklı
değer bekliyordu ve ikisini birden karşılayan bir değer YOKTU:

    Media Crop Override.profile   Link → Media Profile
    Media Profile docname         "product.image:w1920"   (autoname: field:profile_key)
    pipeline/api/crop.py:472      {p.profile_key ...}  →  "w1920"

`p` bir `image/render.py::RenditionProfile` ve `profile_key` özelliği slot
politikasındaki `profiles[].name`i döndürüyor — yani KISA ad. Kullanıcı
`"w1920"` yazarsa `_parse_overrides` kabul eder ama Link doğrulaması düşer;
`"product.image:w1920"` yazarsa Link geçer ama `_parse_overrides` "bu slotta
tanımlı bir profil değil" der. Her iki yazımda da satır yazılamıyordu.

NEDEN LİNK DEĞİL DATA — ve neden `api/crop.py` değiştirilmedi
-------------------------------------------------------------
Docname'i kısa ada çevirmek İMKÂNSIZ: docname global tekil olmak zorunda, ama
politika adları slotlar arası çakışıyor (`w128` hem `brand.logo` hem
`seller.logo` politikasında var). `api/crop.py`'yi docname'e çevirmek ise o
modülü slot→docname eşlemesine, dolayısıyla `frappe`ye bağlardı; modül SAF
kalmak zorunda (`@frappe.whitelist()` yok kuralı) ve bugün yalnız politika
JSON'larını okuyor.

Kalan tek yol, değeri taşıyan alanı politika adına çevirmek. Bu kararın emsali
AYNI GÜN `Media Rendition.profile` için verildi ve gerekçesi o alanın
`description`ında yazılı. Kısa ad burada TEK ANLAMLIDIR: satırın hangi slotta
olduğu `Media Crop Intent.asset` → `Media Asset.slot_key` üzerinden zaten belli.

VERİ GÖÇÜ GEREKMİYOR — ÖLÇÜLDÜ
------------------------------
`tabMedia Crop Override` 0 satır, `tabMedia Crop Intent` 0 satır (2026-08-19).
Yani çevrilecek değer yok. Yama yine de satır sayar ve boş değilse DURUR:
dolu bir tabloda Link docname'lerini kısa ada indirgemek kayıpsız değildir
(`product.image:w1920` → `w1920` geri döndürülemez) ve bunu sessizce yapmak,
kullanıcının çizdiği kadrajı yanlış profile bağlamak olurdu.

Idempotent: alan zaten Data ise yama yalnız ölçüp döner.
"""

from __future__ import annotations

import frappe
from frappe import _

DOCTYPE: str = "Media Crop Override"
TABLO: str = "tabMedia Crop Override"
ALAN: str = "profile"


def execute() -> dict:
	oncesi = frappe.db.get_value(
		"DocField", {"parent": DOCTYPE, "fieldname": ALAN}, ["fieldtype", "options"], as_dict=True
	)

	satir = frappe.db.count(DOCTYPE) if frappe.db.table_exists(DOCTYPE) else 0
	if satir and (oncesi or {}).get("fieldtype") == "Link":
		# Dolu tabloda kayıplı dönüşüm SESSİZCE yapılmaz.
		frappe.throw(
			_(
				"{0} tablosunda {1} satır var ve `profile` hâlâ Link. Docname → politika adı "
				"dönüşümü kayıpsız değildir; elle göç yazılmadan bu yama koşamaz."
			).format(TABLO, satir)
		)

	if not frappe.reload_doc("tradehub_core", "doctype", "media_crop_override"):
		frappe.throw(_("Media Crop Override DocType yüklenemedi — şema dosyası bulunamadı."))

	sonrasi = frappe.db.get_value(
		"DocField", {"parent": DOCTYPE, "fieldname": ALAN}, ["fieldtype", "options"], as_dict=True
	)
	if not sonrasi or sonrasi.get("fieldtype") != "Data":
		# "JSON'da doğru ≠ canlıda etkin" — iddia `tabDocField`den ölçülür.
		frappe.throw(
			_("Media Crop Override.profile canlıda hâlâ {0}.").format(
				(sonrasi or {}).get("fieldtype")
			)
		)
	if sonrasi.get("options"):
		frappe.throw(
			_("Media Crop Override.profile Data oldu ama `options` temizlenmedi: {0}").format(
				sonrasi.get("options")
			)
		)

	frappe.db.commit()
	return {"before": dict(oncesi or {}), "after": dict(sonrasi), "rows": satir}
