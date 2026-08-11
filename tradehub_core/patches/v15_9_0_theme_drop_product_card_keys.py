# Copyright (c) 2026, TradeHub Team and contributors

"""Tradehub Theme Settings override'larindan urun karti token'larini temizle.

Admin panelindeki "Urun Kartlari" sekmesi kaldirildi: storefront kart
redesign'lari sonrasi bu token'larin cogunun sitede karsiligi kalmamisti
(.pc-topdeals / .pc-topranking / .hot-products olu, .product-card koku artik
DOM'a basilmiyor). _PRODUCT_CARD_KEYS whitelist'ten cikarildigi icin, bir
ortamda daha once kaydedilmis urun karti override'i varsa bir sonraki
save_theme_settings cagrisi validate'te patlardi.

Bu patch saklanan `overrides` JSON'undan kaldirilan anahtar ailelerini
(--card-*, --product-card-*, --product-title/image/lens-*, --pc-*,
--topdeals-card-*, --topranking-card-*, --tailored-*) dusurur.
Idempotent: ikinci calismada eslesen anahtar kalmadigi icin no-op doner.
"""

from __future__ import annotations

import json

import frappe

SETTINGS_DOCTYPE = "Tradehub Theme Settings"

# Kaldirilan aileler — eski _PRODUCT_CARD_KEYS kumesinin prefix karsiligi.
_REMOVED_PREFIXES = (
	"--card-",
	"--product-card-",
	"--product-title-",
	"--product-image-",
	"--product-lens-",
	"--pc-",
	"--topdeals-card-",
	"--topdeals-price-",
	"--topdeals-badge-",
	"--topranking-card-",
	"--tailored-",
)


def execute() -> None:
	try:
		doc = frappe.get_single(SETTINGS_DOCTYPE)
	except frappe.DoesNotExistError:
		return

	try:
		overrides = json.loads(doc.overrides or "{}")
	except (TypeError, ValueError):
		return
	if not isinstance(overrides, dict):
		return

	cleaned = {k: v for k, v in overrides.items() if not str(k).startswith(_REMOVED_PREFIXES)}

	if len(cleaned) == len(overrides):
		return  # urun karti override'i yok — idempotent no-op

	doc.overrides = json.dumps(cleaned)
	doc.save(ignore_permissions=True)  # on_update "tradehub_public_theme" cache'ini invalide eder
	frappe.db.commit()
