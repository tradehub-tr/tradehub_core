# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-039: Logistics Provider.country alanini Link: Country'ye tasi (idempotent).

Neden gerekli:
	TUR-102 "ulke/bolge genisleme alanlari" maddesi ulke alaninin referansli
	olmasini istiyor, ama alan serbest `Data` olarak acilmis ve LOG-025 seed'i
	icine Turkce metin yazmisti ("Türkiye", "ABD", "Almanya"). Frappe'nin
	standart `Country` DocType'i kayitlari INGILIZCE adlandiriyor
	(`Turkey`, `United States`, `Germany`), dolayisiyla alan Link'e cevrildiginde
	mevcut 8 satirin tamami gecersiz referansa dusuyordu.

	Bu patch mevcut degerleri eslemeyle duzeltir. Eslenemeyen bir deger kalirsa
	ALANI BOSALTMAZ — sessiz veri kaybi yerine log'a yazip degeri oldugu gibi
	birakir (bkz. docs/LOGISTICS-ARCHITECTURE.md §6.1).
"""

from __future__ import annotations

import frappe

# Eski serbest-metin deger -> Frappe Country kayit adi
LEGACY_TO_COUNTRY: dict[str, str] = {
	"Türkiye": "Turkey",
	"Turkiye": "Turkey",
	"TR": "Turkey",
	"ABD": "United States",
	"US": "United States",
	"USA": "United States",
	"Almanya": "Germany",
	"DE": "Germany",
}


def execute() -> dict:
	"""Mevcut Logistics Provider satirlarini gecerli Country referansina cevirir."""
	frappe.reload_doc("tradehub_core", "doctype", "logistics_provider")

	updated: list[tuple[str, str, str]] = []
	already_valid: list[str] = []
	unmapped: list[tuple[str, str]] = []

	rows = frappe.get_all("Logistics Provider", fields=["name", "country"])
	for row in rows:
		current = (row.country or "").strip()
		if not current:
			continue

		# Zaten gecerli bir Country kaydina isaret ediyorsa dokunma (idempotent)
		if frappe.db.exists("Country", current):
			already_valid.append(row.name)
			continue

		target = LEGACY_TO_COUNTRY.get(current)
		if not target or not frappe.db.exists("Country", target):
			unmapped.append((row.name, current))
			continue

		# db.set_value bilincli: yalniz tek alan duzeltiliyor, validate zincirini
		# tetiklemeye gerek yok (migration).
		frappe.db.set_value("Logistics Provider", row.name, "country", target)
		updated.append((row.name, current, target))

	if unmapped:
		frappe.log_error(
			f"Country eslemesi bulunamayan Logistics Provider satirlari: {unmapped}"
			" — deger DEGISTIRILMEDI, elle duzeltilmeli",
			"v15_log039_logistics_provider_country_link",
		)

	frappe.db.commit()
	return {"updated": updated, "already_valid": already_valid, "unmapped": unmapped}
