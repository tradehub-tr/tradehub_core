# Copyright (c) 2026, TradeHub Team and contributors

"""Tradehub Theme Settings override'larindan neumorphic `inset` shadow degerlerini temizle.

Storefront butonlarindaki ice-basik (neumorphic) press efekti tum kod tabanindan
kaldirildi (Emil standardi: press = scale(0.97), inset bevel YOK). Ancak `--btn-shadow`
gibi shadow token'lari admin tarafindan uzaktan tema ile de set edilebiliyor
(get_public_theme -> :root). Bir ortamda admin daha once `inset` iceren bir deger
kaydettiyse, storefront duzeltmesi uzaktan override ile geri ezilirdi.

Bu patch saklanan `overrides` JSON'unu okur ve degeri `inset` iceren her anahtari
DUSURUR — boylece artik temizlenmis `style.css` varsayilani (`--btn-shadow: 0 1px 0 ...`)
gecerli olur. Idempotent: ikinci calismada inset kalmadigi icin no-op doner.
"""

from __future__ import annotations

import json

import frappe

SETTINGS_DOCTYPE = "Tradehub Theme Settings"


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

	# Degeri "inset" iceren her shadow override'ini dusur (case-insensitive).
	cleaned = {k: v for k, v in overrides.items() if not (isinstance(v, str) and "inset" in v.lower())}

	if len(cleaned) == len(overrides):
		return  # inset yok — idempotent no-op

	doc.overrides = json.dumps(cleaned)
	doc.save(ignore_permissions=True)  # on_update "tradehub_public_theme" cache'ini invalide eder
	frappe.db.commit()
