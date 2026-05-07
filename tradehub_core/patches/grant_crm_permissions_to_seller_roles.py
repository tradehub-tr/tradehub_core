# Copyright (c) 2024, TR TradeHub and contributors

"""
Satıcı rollerine 7 CRM doctype'ı için read/write/create izni ver.

Frappe Role Permission Manager API kullanılıyor — DocPerm child table'a
ekler. Permission Query (`crm_*_query_conditions`) bu rollerde satıcıyı kendi
seller profile'ına kısıtlar; yani read izni verseniz bile satıcı yalnız
kendi kayıtlarını görür.

İki rol de hedefleniyor çünkü:
  - Frappe Marketplace standart rol adı "Marketplace Seller"
  - tradehub_core'da Seller Application onayı `Seller` rolünü atıyor
    (seller_application._approve_application + seed_demo_data)
  - permissions._is_marketplace_seller her ikisini de kabul ediyor

Idempotent: zaten eklenmişse skip.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

CRM_DOCTYPES = [
	"CRM Lead",
	"CRM Deal",
	"CRM Organization",
	"Contact",
	"CRM Task",
	"FCRM Note",
	"CRM Call Log",
]

ROLES = ("Marketplace Seller", "Seller")

PERM_FIELDS = {
	"read": 1,
	"write": 1,
	"create": 1,
	"delete": 0,  # silme yok — soft revisions
	"submit": 0,
	"cancel": 0,
	"amend": 0,
	"export": 0,
	"share": 0,
	"print": 0,
	"email": 0,
	"report": 0,
}


def execute():
	for dt in CRM_DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		for role in ROLES:
			if not frappe.db.exists("Role", role):
				continue
			_grant(dt, role)

	frappe.db.commit()
	frappe.clear_cache()


def _grant(doctype, role):
	# Halihazırda DocPerm var mı? Aynı role için level=0 kontrol.
	existing = frappe.db.exists(
		"DocPerm",
		{"parent": doctype, "role": role, "permlevel": 0},
	)
	if not existing:
		# add_permission yeni DocPerm satırı ekler
		try:
			add_permission(doctype, role, permlevel=0)
		except Exception:
			frappe.log_error(title=f"grant_seller_crm_permissions: add {doctype}/{role}")
			return

	# Her bir izin alanını set et
	for field, value in PERM_FIELDS.items():
		try:
			update_permission_property(doctype, role, 0, field, value)
		except Exception:
			frappe.log_error(title=f"grant_seller_crm_permissions: update {doctype}/{role}/{field}")
