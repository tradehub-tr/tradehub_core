# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-024: Shipping Channel seed verileri (idempotent).

TARIHCE — Shipping Method seed'i KALDIRILDI (Faz A.6):
	Bu patch ilk surumunde 5 kanalin her biri icin ayni adla bir Shipping Method
	kaydi da uretiyordu (Kargo->CARGO, Ambar->WAREHOUSE, ...). Bu, TUR-104'un
	"tasima yontemi ile isletim kanali BAGIMSIZDIR" kabul kriterini veri
	duzeyinde cignemisti: yontem ve kanal birebir kopya haline gelmisti.

	Kanal = isin hangi kanaldan yurudugu (Kargo / Ambar / Kurye / Satici Araci /
	Alici Teslim Alma). Yontem = satisa sunulan somut tasima secenegi
	("Standart Kargo 1-3 gun" gibi) ve bir kanala BAGLANIR.

	Uretilmis 5 kopya kayit LOG-040 ile pasiflestiriliyor. Gercek Shipping Method
	katalogu bir urun karari oldugu icin burada seed EDILMIYOR.
"""

from __future__ import annotations

import frappe

from tradehub_core.logistics.seed import SHIPPING_CHANNELS

# Seed "code" -> Türkçe aksanlı görünen ad (seed "name" anahtarı aksansız, doc.name ile çakışır)
CHANNEL_DISPLAY_NAMES: dict[str, str] = {
	"CARGO": "Kargo",
	"WAREHOUSE": "Ambar",
	"COURIER": "Kurye",
	"SELLER_VEHICLE": "Satıcı Aracı",
	"BUYER_PICKUP": "Alıcı Teslim Alma",
}


def execute() -> None:
	"""Shipping Channel kayitlarini olusturur (idempotent)."""
	# Yeni DocType henuz migrate edilmemis olabilir
	frappe.reload_doc("tradehub_core", "doctype", "shipping_channel")

	for row in SHIPPING_CHANNELS:
		channel_code = row["code"]
		# Idempotent -- zaten varsa dokunma (autoname field:channel_code)
		if frappe.db.exists("Shipping Channel", channel_code):
			continue
		doc = frappe.new_doc("Shipping Channel")
		# seed dict'inde "name" anahtari doc.name ile cakisir -- alan alan atama yapiyoruz
		doc.channel_name = CHANNEL_DISPLAY_NAMES[channel_code]
		doc.channel_code = channel_code
		doc.is_active = 1
		doc.insert(ignore_permissions=True)  # Sistem migration'i, kullanici akisi degil

	frappe.db.commit()
