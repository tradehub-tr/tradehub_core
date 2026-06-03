"""Admin Seller Profile'a chat_tier custom field ekle.

Premium: buyer her zaman mesajlaşabilir.
Plus: buyer önce rezervasyon yapmalı (Chat Reservation), aktif rezervasyon
penceresi içinde chat açılır.

Mevcut tüm seller'lar varsayılan olarak Premium (akıl etkilenmez); operatör
belirli seller'ları manuel olarak Plus'a alabilir.
"""

import frappe

CUSTOM_FIELDS = [
	{
		"dt": "Admin Seller Profile",
		"fieldname": "chat_tier",
		"label": "Sohbet Tier",
		"fieldtype": "Select",
		"options": "Premium\nPlus",
		"default": "Premium",
		"description": "Premium: sınırsız mesajlaşma. Plus: alıcılar önce rezervasyon yapmalı.",
		# Approval ile ilgili alanların civarına yerleştir; sırası kritik değil
	},
]


def execute():
	if not frappe.db.exists("DocType", "Admin Seller Profile"):
		return
	for cf in CUSTOM_FIELDS:
		_upsert_custom_field(cf)
	frappe.db.commit()


def _upsert_custom_field(spec):
	cf_name = f"{spec['dt']}-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", cf_name):
		return
	doc = frappe.new_doc("Custom Field")
	for k, v in spec.items():
		doc.set(k, v)
	doc.insert(ignore_permissions=True)
