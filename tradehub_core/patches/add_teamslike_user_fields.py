"""
User doctype'ına TeamsLike entegrasyonu için Custom Field'ler ekle.

Her Frappe seller user'ı ilk chat kullanımında teamslike tarafında bir
staff user olarak provision edilir. Aşağıdaki alanlar bu mapping'i tutar:

- teamslike_user_id        → UUID (string)
- teamslike_password       → random parola (encrypted, sadece System Manager okur)
- teamslike_provisioned_at → ne zaman provision edildi
"""

import frappe

CUSTOM_FIELDS = [
	{
		"dt": "User",
		"fieldname": "teamslike_section",
		"label": "TeamsLike Chat",
		"fieldtype": "Section Break",
		"collapsible": 1,
	},
	{
		"dt": "User",
		"fieldname": "teamslike_user_id",
		"label": "TeamsLike User ID",
		"fieldtype": "Data",
		"insert_after": "teamslike_section",
		"read_only": 1,
		"description": "TeamsLike tarafındaki staff user UUID'si. Otomatik doldurulur.",
	},
	{
		"dt": "User",
		"fieldname": "teamslike_password",
		"label": "TeamsLike Password",
		"fieldtype": "Password",
		"insert_after": "teamslike_user_id",
		"description": "Otomatik üretilen random parola; teamslike /v1/auth/login için kullanılır.",
	},
	{
		"dt": "User",
		"fieldname": "teamslike_provisioned_at",
		"label": "TeamsLike Provision Tarihi",
		"fieldtype": "Datetime",
		"insert_after": "teamslike_password",
		"read_only": 1,
	},
]


def execute():
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
