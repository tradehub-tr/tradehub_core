# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-133 (Şerit A) — `/metrics` scrape sırrını `site_config.json`da hazırla.

Prometheus AYRI BİR SUNUCUDA koşuyor ve Frappe oturumu açamaz; uç bu yüzden
`Authorization: Bearer <site_config.media_metrics_token>` bekliyor
(`api/observability.py` modül başlığı: `?token=` sorgu parametresi neden
reddedildi).

NEDEN SIRRI YAMA ÜRETİYOR
-------------------------
Uç FAIL-CLOSED yazıldı: sır yapılandırılmamışsa oturumsuz her istek 403 alır.
Bu güvenli ama kullanılamaz bir durumdur ve "geçici olarak açalım" baskısı
tam olarak böyle doğar. Yama güçlü bir sır üretip yalnız `site_config.json`a
yazar — yani sırrı yalnız o dosyayı okuyabilen kişi görür.

MEVCUT DEĞERE DOKUNULMAZ. Operatörün bilinçli olarak koyduğu bir sırrı bir
`migrate`in döndürmesi, bu yamanın yapabileceği en tehlikeli şey olurdu
(v15_9_22 / v15_9_25 emsali) — ve döndürseydi scrape sessizce 403 almaya
başlar, `up` serisi 0'a düşer, kimse fark etmezdi.

SIR HİÇBİR YERE YAZILMAZ: ne dönüş değerine, ne log'a, ne hata mesajına.
Dönen tek şey sırrın ÜRETİLİP üretilmediği.
"""

from __future__ import annotations

import frappe

ANAHTAR: str = "media_metrics_token"

#: 32 bayt entropi. Frappe'nin `generate_hash`i `secrets.token_hex` tabanlıdır.
UZUNLUK: int = 64


def execute() -> dict:
	if frappe.conf.get(ANAHTAR):
		return {"key": ANAHTAR, "generated": False, "reason": "zaten yapılandırılmış"}

	from frappe.installer import update_site_config  # noqa: PLC0415

	update_site_config(ANAHTAR, frappe.generate_hash(length=UZUNLUK))
	# Değer DÖNDÜRÜLMEZ ve LOG'LANMAZ — `Patch Log`da saklanacak bir sır değil.
	return {"key": ANAHTAR, "generated": True}
