# Copyright (c) 2026, TradeHub Team and contributors

"""Nav etiketi "Pattern'lerim" -> "Eslestirmelerim" (Sutun + Deger katmanlarini kapsar).

v15_6_2 seed patch'i skip-if-exists oldugundan onceden seed edilmis kaydin
label'ini guncellemez. Bu patch idempotent olarak TH Module Registry kaydinin
label'ini spec ile hizalar.
"""

import frappe

_MODULE_KEY = "seller.products.toplu.patternler"
_NEW_LABEL = "Eşleştirmelerim"


def execute():
	if not frappe.db.exists("TH Module Registry", _MODULE_KEY):
		return
	# Idempotent: yalniz eski label'i guncelle, manuel degisikligi ezme riski yok
	# cunku yeni label spec'le ayni.
	if frappe.db.get_value("TH Module Registry", _MODULE_KEY, "label") != _NEW_LABEL:
		frappe.db.set_value("TH Module Registry", _MODULE_KEY, "label", _NEW_LABEL)
		frappe.db.commit()
