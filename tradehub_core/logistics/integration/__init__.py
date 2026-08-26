# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Kargo entegrasyon altyapısı — maskeleme + entegrasyon logu (09-BE / A paketi).

İki katman:

	masking.py  saf fonksiyonlar, Frappe bağımlılığı YOK
	log.py      `Carrier Integration Log` DocType'ına yazan katman

Maskeleme MERKEZİDİR: `write_integration_log` gövdeleri, başlıkları VE hata
metinlerini (`log.py::MASKED_LOG_FIELDS`) yazmadan önce maskeler; çağıran bunu
atlayamaz. DocType controller'ı `before_insert`'te aynı alan listesiyle bir kez
daha maskeler (derinlemesine savunma).

Maskeleme iki katmanlıdır ve SIRA ÖNEMLİDİR:

	1. DEĞER-TABANLI redaksiyon (`secret_values`) — biçimden bağımsız, birincil.
	   İstek zaten bizim kurduğumuz istektir; sırların DEĞERİ bilinir, bu yüzden
	   onları aramak anahtar adını tahmin etmekten güvenlidir.
	2. ANAHTAR denylist'i — değer bilinmediğinde (taşıyıcı YANITI) tek savunma.
	   JSON / querystring / XML-element / XML-öznitelik biçimlerini ve TR+EN,
	   camelCase adları kapsar.
"""
