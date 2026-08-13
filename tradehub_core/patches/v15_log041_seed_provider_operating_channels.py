# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-041: Logistics Provider -> isletim kanali eslemesini doldur (idempotent).

Neden gerekli:
	`Provider Operating Channel` child tablosu TUR-104 ile acildi ama hic
	doldurulmadi (0 kayit). Bos oldugu surece "hangi saglayici hangi kanalda
	calisiyor" sorusu cevapsiz kaliyor ve TUR-104'un "tasima yontemi ile isletim
	kanali bagimsizdir" kriteri yalniz yapisal olarak saglaniyor, veriyle degil.

Esleme kurali (uydurma degil, seed'in kendi verisinden turetildi):
	LOG-025 ile seed edilen 8 saglayicinin tamami `provider_type = "Kargo"`
	olarak yaziliyor — hepsi kargo firmasi. Dolayisiyla hepsi CARGO kanalinda
	calisir.

	Diger 4 kanal (WAREHOUSE / COURIER / SELLER_VEHICLE / BUYER_PICKUP) bilincli
	olarak BOS birakildi: bu kanallar bir kargo firmasi araciligi gerektirmez
	(ambar teslim, saticinin kendi araci, alicinin gelip almasi). Bir ambar veya
	kurye firmasi katalogu eklendiginde bu patch degil, YENI bir patch yazilir.
"""

from __future__ import annotations

import frappe

CARGO_CHANNEL_CODE = "CARGO"
CARGO_PROVIDER_TYPE = "Kargo"


def execute() -> dict:
	"""Kargo tipi saglayicilari CARGO kanaliyla eslestirir."""
	frappe.reload_doc("tradehub_core", "doctype", "provider_operating_channel")
	frappe.reload_doc("tradehub_core", "doctype", "logistics_provider")

	if not frappe.db.exists("Shipping Channel", CARGO_CHANNEL_CODE):
		frappe.log_error(
			f"{CARGO_CHANNEL_CODE} kanali bulunamadi — LOG-024 calismamis olabilir",
			"v15_log041_seed_provider_operating_channels",
		)
		return {"error": "channel_missing"}

	channel_name = frappe.db.get_value("Shipping Channel", CARGO_CHANNEL_CODE, "channel_name")

	linked: list[str] = []
	already_linked: list[str] = []

	providers = frappe.get_all(
		"Logistics Provider",
		filters={"provider_type": CARGO_PROVIDER_TYPE},
		pluck="name",
	)
	for provider_name in providers:
		doc = frappe.get_doc("Logistics Provider", provider_name)
		if any(row.shipping_channel == CARGO_CHANNEL_CODE for row in (doc.operating_channels or [])):
			already_linked.append(provider_name)
			continue

		doc.append(
			"operating_channels",
			{"shipping_channel": CARGO_CHANNEL_CODE, "channel_name": channel_name},
		)
		# Sistem migration'i, kullanici akisi degil
		doc.save(ignore_permissions=True)
		linked.append(provider_name)

	frappe.db.commit()
	return {"linked": linked, "already_linked": already_linked}
