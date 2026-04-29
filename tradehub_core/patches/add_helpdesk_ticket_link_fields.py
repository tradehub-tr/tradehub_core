# Copyright (c) 2024, TR TradeHub and contributors

"""
HD Ticket'a marketplace bağlantı alanları ekle (Custom Field).

Mevcut create_ticket akışında order_ref açıklama metni içine yazılıyordu;
bu patch ile structured Link field'lar geliyor:

- related_order      → Order
- related_rfq        → RFQ
- related_listing    → Listing

Frappe Custom Field idempotent değil; var olanı insert_after değişikliğinde
hata vermeden geçer. Yeni alan adları (`related_*`) HD Ticket'ta önceden
tanımsızdı.
"""

import frappe

CUSTOM_FIELDS = [
	{
		"dt": "HD Ticket",
		"fieldname": "related_order",
		"label": "İlişkili Sipariş",
		"fieldtype": "Link",
		"options": "Order",
		"insert_after": "ticket_type",
		"description": "Bu talep belirli bir siparişle ilgiliyse seç.",
	},
	{
		"dt": "HD Ticket",
		"fieldname": "related_rfq",
		"label": "İlişkili Teklif (RFQ)",
		"fieldtype": "Link",
		"options": "RFQ",
		"insert_after": "related_order",
		"description": "Bu talep bir RFQ ile ilgiliyse seç.",
	},
	{
		"dt": "HD Ticket",
		"fieldname": "related_listing",
		"label": "İlişkili Ürün",
		"fieldtype": "Link",
		"options": "Listing",
		"insert_after": "related_rfq",
		"description": "Bu talep belirli bir ürünle ilgiliyse seç.",
	},
]


def execute():
	for cf in CUSTOM_FIELDS:
		_upsert_custom_field(cf)
	frappe.db.commit()


def _upsert_custom_field(spec):
	# Custom Field doctype'ında name kompozit: "{dt}-{fieldname}"
	cf_name = f"{spec['dt']}-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", cf_name):
		return
	doc = frappe.new_doc("Custom Field")
	for k, v in spec.items():
		doc.set(k, v)
	doc.insert(ignore_permissions=True)
