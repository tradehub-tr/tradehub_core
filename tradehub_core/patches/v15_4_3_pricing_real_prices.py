# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 4.1.c — Plan fiyatlarını gerçek değerlere çek.

monthly_price = aylık fiyat, yearly_price = yıllık fiyat (örnekte 2 ay bedava).
Önceki force patch yanlış değerlerle set etmişti.
"""

from __future__ import annotations

import frappe

_FLAG_KEY = "tradehub:patch:v15_4_3_pricing_real_prices_applied"

_PRICES = {
	"FREE": {"monthly_price": 0.0, "yearly_price": 0.0},
	"STARTER": {"monthly_price": 39.0, "yearly_price": 399.0},
	"PRO": {"monthly_price": 49.0, "yearly_price": 499.0},
	"ENTERPRISE": {"monthly_price": 0.0, "yearly_price": 0.0},
}


def execute() -> None:
	if frappe.cache().get_value(_FLAG_KEY):
		return

	if not frappe.db.exists("DocType", "Subscription Plan"):
		return

	for plan_code, fields in _PRICES.items():
		plan_name = frappe.db.get_value("Subscription Plan", {"plan_code": plan_code}, "name")
		if not plan_name:
			continue
		for f, v in fields.items():
			frappe.db.set_value("Subscription Plan", plan_name, f, v)

	frappe.db.commit()
	frappe.cache().set_value(_FLAG_KEY, 1)
