# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""LOG-034: Shipment Exception Code seed verileri (idempotent)."""

from __future__ import annotations

import frappe

from tradehub_core.logistics.seed import EXCEPTION_CODES

# code -> (severity, exception_category, is_retriable, suggested_action)
# Severity'nin TEK KAYNAGI bu tablo (seed.py yalniz code+label tasir).
# Tarihsel esleme kurali: critical->Critical, high->Warning, medium->Warning, low->Info
EXCEPTION_META: dict[str, tuple[str, str, int, str]] = {
	"ADDR_NOT_FOUND": ("Warning", "Address", 1, "Alıcıdan adres teyidi alın, düzeltme sonrası yeniden dene"),
	"RECIPIENT_ABSENT": ("Warning", "Recipient", 1, "Sonraki gün yeniden dağıtım dene"),
	"REFUSED": ("Warning", "Recipient", 0, "İade sürecini başlat"),
	"DAMAGED": ("Critical", "Package", 0, "Hasar tutanağı + satıcıya bildirim"),
	"CUSTOMS_HOLD": ("Warning", "Customs", 1, "Gümrük evraklarını kontrol et"),
	"WRONG_ADDRESS": ("Warning", "Address", 1, "Doğru adresi al, yönlendirme talep et"),
	"SIZE_EXCEED": ("Warning", "Package", 0, "Farklı servis/kanal ile yeniden gönder"),
	"WEATHER": ("Info", "Weather", 1, "Bekle; SLA'ya gecikme notu düş"),
}


def execute() -> None:
	"""Shipment Exception Code kayitlarini olusturur (idempotent)."""
	# Yeni DocType henuz migrate edilmemis olabilir
	frappe.reload_doc("tradehub_core", "doctype", "shipment_exception_code")

	for row in EXCEPTION_CODES:
		exception_code = row["code"]
		# Idempotent -- zaten varsa dokunma (autoname field:exception_code)
		if frappe.db.exists("Shipment Exception Code", exception_code):
			continue
		severity, category, is_retriable, suggested_action = EXCEPTION_META[exception_code]
		doc = frappe.new_doc("Shipment Exception Code")
		doc.exception_name = row["label"]
		doc.exception_code = exception_code
		doc.severity = severity
		doc.exception_category = category
		doc.is_retriable = is_retriable
		doc.suggested_action = suggested_action
		doc.insert(ignore_permissions=True)  # Sistem migration'i, kullanici akisi degil

	frappe.db.commit()
