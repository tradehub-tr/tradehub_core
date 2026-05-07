# Copyright (c) 2026, TR TradeHub and contributors

"""
Satıcı rollerine CRM modülünün tüm doctype'ları için gerekli izinleri ver.

İki kategori:
  1. **Tenant doctype'ları** — Lead/Deal/Org/Contact/Task/Note/Call:
     read + write + create. permlevel 0 ve 1 (close_date/deal_owner gibi
     bazı field'lar permlevel 1'de). Permission Query
     (`crm_*_query_conditions`) bu rollerde satıcıyı kendi seller profile'ına
     kısıtlar — read açık olsa bile başka satıcının kayıtlarını göremez.

  2. **Lookup doctype'ları** — Territory/Status/Source/Reason/Industry/SLA:
     sadece read. Form'larda dropdown master data; tenant'a özel değil.

İki rol de hedefleniyor:
  - "Marketplace Seller" → Frappe Marketplace standart adı
  - "Seller" → tradehub_core'un kendi atadığı (seller_application._approve_application)
  - permissions._is_marketplace_seller her ikisini de kabul ediyor.

Idempotent: zaten eklenmişse skip; her run'da güncel field değerlerini set eder.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

# Tenant doctype'ları — yazma + okuma, permlevel 0 ve 1
TENANT_DOCTYPES = [
	"CRM Lead",
	"CRM Deal",
	"CRM Organization",
	"Contact",
	"CRM Task",
	"FCRM Note",
	"CRM Call Log",
]

# Lookup doctype'ları — sadece okuma, permlevel 0
LOOKUP_DOCTYPES = [
	"CRM Territory",
	"CRM Communication Status",
	"CRM Lead Source",
	"CRM Lead Status",
	"CRM Deal Status",
	"CRM Lost Reason",
	"CRM Industry",
	"CRM Service Level Agreement",
	"CRM Service Day",
	"CRM Holiday",
	"CRM Settings",
]

ROLES = ("Marketplace Seller", "Seller")

TENANT_PERM_FIELDS = {
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

LOOKUP_PERM_FIELDS = {
	"read": 1,
	"write": 0,
	"create": 0,
	"delete": 0,
}


def execute():
	# Tenant: permlevel 0 + 1 (field-level permissions için close_date vb.)
	for dt in TENANT_DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		for role in ROLES:
			if not frappe.db.exists("Role", role):
				continue
			for permlevel in (0, 1):
				_grant(dt, role, permlevel, TENANT_PERM_FIELDS)

	# Lookup: sadece permlevel 0 read
	for dt in LOOKUP_DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		for role in ROLES:
			if not frappe.db.exists("Role", role):
				continue
			_grant(dt, role, 0, LOOKUP_PERM_FIELDS)

	frappe.db.commit()
	frappe.clear_cache()


def _grant(doctype, role, permlevel, perm_fields):
	existing = frappe.db.exists(
		"DocPerm",
		{"parent": doctype, "role": role, "permlevel": permlevel},
	)
	if not existing:
		try:
			add_permission(doctype, role, permlevel=permlevel)
		except Exception:
			frappe.log_error(
				title=f"grant_full_crm_permissions: add {doctype}/{role}/p={permlevel}"
			)
			return

	for field, value in perm_fields.items():
		try:
			update_permission_property(doctype, role, permlevel, field, value)
		except Exception:
			frappe.log_error(
				title=f"grant_full_crm_permissions: update {doctype}/{role}/p={permlevel}/{field}"
			)
