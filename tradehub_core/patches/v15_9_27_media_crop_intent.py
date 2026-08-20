# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-041/T-082 — `Media Crop Intent` + `Media Crop Override` DocType'larını kur.

Şema kaynağı `tradehub_core/media/pipeline/doctype_specs/` altındaki iki spec.
`v15_9_21` dört çekirdek DocType'ı kurmuştu ve "diğer 12'si bu dalgada
KURULMAZ" diyordu; bu yama o listeden ikisini alır — kırpma stüdyosunun
kaydetme ucunu açan tek eksik parça.

NEDEN AYRI BİR YAMA — `bench migrate` JSON'ları zaten yükler
------------------------------------------------------------
İki şey için:

  1. **Yükleme sırasını garantiler.** `Media Crop Intent.overrides` bir Table
     alanıdır ve `Media Crop Override`a bağlıdır; child önce yüklenmezse
     parent'ın Link/Table hedefi yokken DocType kaydı düşer. Alfabetik sırada
     `media_crop_intent` (i) `media_crop_override`dan (o) ÖNCE gelir — yani
     migrate'in doğal sırası tam da yanlış olan sıradır.
  2. **Kurulumu DOĞRULAR.** `v15_9_21` ile aynı disiplin: tablo gerçekten
     oluşmadıysa yama patlar, "migrate geçti ama tablo yok" sessizce üretime
     çıkmaz.

SESSİZ BAŞARISIZLIK KORUMASI
----------------------------
`frappe.reload_doc` dosyayı BULAMAZSA `False` döner, **hata FIRLATMAZ**. Bu
tam olarak bir kez oldu: `v15_9_25` `Media Storage Settings` için `tabSingles`a
29 değer yazdı, `Patch Log`a "koştu" yazıldı, ama `tabDocType` satırı hiç
oluşmadı ve iki whitelist ucu HTTP 500 verdi (`docs/reports/32-faz8-api-kapanis.md`).
`v15_9_25` bundan sonra dönüş değerini kontrol etmeye başladı; bu yama aynı
korumayı DOĞUŞTAN taşır — hem `reload_doc` dönüşü hem tablo varlığı sınanır.

İDEMPOTENT
----------
`reload_doc` her koşuda aynı JSON'u yeniden okur ve uygular; veri yazılmaz,
mevcut niyet kayıtlarına dokunulmaz. İkinci koşuda hiçbir şey değişmez.

BAYRAK NOTU
-----------
Bu yama yalnız ŞEMA kurar. `Media Engine Settings` bayrakları değiştirilmez;
kapalı bayrakla bu tablolara hat tarafından hiçbir şey yazılmaz. Kırpma
stüdyosunun kendi uçları (`api/media_crop.py`) bayraktan bağımsızdır — kullanıcı
niyeti bir hat çıktısı değil, kullanıcı verisidir.
"""

from __future__ import annotations

import frappe
from frappe import _

#: Yükleme sırası: önce child (Table hedefi), sonra parent.
_DOCTYPES: tuple[tuple[str, str], ...] = (
	("media_crop_override", "Media Crop Override"),
	("media_crop_intent", "Media Crop Intent"),
)


def execute() -> dict:
	"""İki DocType'ı yükler; hem `reload_doc` dönüşünü hem tabloyu doğrular."""
	yuklenemedi: list[str] = []
	for dizin, ad in _DOCTYPES:
		# DİKKAT — dönüş değeri KONTROL EDİLMELİ; `reload_doc` şema dosyasını
		# bulamazsa sessizce False döner (v15_9_25 emsali, modül başlığı).
		if not frappe.reload_doc("tradehub_core", "doctype", dizin, force=True):
			yuklenemedi.append(ad)

	if yuklenemedi:
		frappe.throw(
			_("Kırpma DocType şeması yüklenemedi: {0}. JSON dosyalarını ve modül adını (Tradehub Core) kontrol edin.").format(
				", ".join(yuklenemedi)
			)
		)

	eksik: list[str] = [ad for _dizin, ad in _DOCTYPES if not frappe.db.table_exists(ad)]
	if eksik:
		# `reload_doc` True dönse bile tablo oluşmamış olabilir (ör. şema
		# hatası). Sessiz geçmek en kötü sonuç: ilk yazmada uç 500 verir.
		frappe.throw(
			_("Kırpma DocType tabloları oluşmadı: {0}.").format(", ".join(eksik))
		)

	frappe.db.commit()
	return {"loaded": [ad for _dizin, ad in _DOCTYPES], "missing": eksik}
