# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""
Seed default CRM Lead Source records — TradeHub B2B marketplace tipik kaynakları.

Lead "Kaynak" dropdown'unu (ilk kurulumda boş gelir) doldurur. Admin Frappe
Desk → CRM Lead Source üzerinden bu kayıtları silebilir veya yenisini ekleyebilir.

Idempotent: lead_source name unique → var olanları atlar.
"""

import frappe

DEFAULTS = [
	"Web Sitesi",
	"Pazaryeri Sorgu",
	"Fuar / Etkinlik",
	"Telefon",
	"Mevcut Müşteri Tavsiyesi",
	"Reklam",
	"Sosyal Medya",
	"LinkedIn",
	"WhatsApp",
	"E-posta Kampanyası",
	"Soğuk E-posta",
	"Diğer",
]


def execute():
	# Frappe CRM app henüz kurulmamış olabilir — DocType yoksa skip
	if not frappe.db.table_exists("CRM Lead Source"):
		return
	for source in DEFAULTS:
		if frappe.db.exists("CRM Lead Source", source):
			continue
		doc = frappe.new_doc("CRM Lead Source")
		doc.source_name = source
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
