# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-042: Kargo firma adlarindaki eksik Turkce karakterleri duzelt (idempotent).

Neden gerekli:
	LOG-025 seed'i firma adlarini aksansiz yazmisti ("Yurtici Kargo",
	"Surat Kargo"). Bunlar KULLANICIYA GOSTERILEN marka adlari — hem operasyon
	panelinde hem storefront kargo secimi ekraninda bu haliyle gorunuyordu.

	Yalniz bilinen ASCII varyantlar duzeltilir; elle degistirilmis bir ad
	varsa dokunulmaz.
"""

from __future__ import annotations

import frappe

# Yalnizca eksik diakritigi olan adlar. Dogru yazilmis olanlara dokunulmaz.
ASCII_TO_DIACRITIC: dict[str, str] = {
	"Yurtici Kargo": "Yurtiçi Kargo",
	"Surat Kargo": "Sürat Kargo",
}


def execute() -> dict:
	"""Bilinen ASCII firma adlarini diakritikli haline cevirir."""
	updated: list[tuple[str, str]] = []

	for ascii_name, correct_name in ASCII_TO_DIACRITIC.items():
		rows = frappe.get_all(
			"Logistics Provider", filters={"provider_name": ascii_name}, pluck="name"
		)
		for provider in rows:
			# db.set_value bilincli: tek gorunen ad alani duzeltiliyor,
			# validate zincirini tetiklemeye gerek yok (migration).
			frappe.db.set_value("Logistics Provider", provider, "provider_name", correct_name)
			updated.append((provider, correct_name))

	frappe.db.commit()
	return {"updated": updated}
