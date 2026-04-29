# Copyright (c) 2024, TR TradeHub and contributors

"""
CRM modülü doctype'larına `seller` Link field ekle (Custom Field).

Marketplace mantığı: bir CRM kaydının (Lead/Deal/Org/Contact/Task/Note/Call)
hangi mağazaya (Admin Seller Profile) ait olduğu burada saklanır. Permission
query bu alana göre filtreleyerek satıcının yalnız kendi kayıtlarını görmesini
sağlar.

Frappe CRM kendi `lead_owner`/`deal_owner` (User) field'larını korur — bu
"kim takip ediyor" demek; `seller` ise "hangi mağazaya ait" demektir. Bir
mağazanın N user'ı varsa hepsi aynı seller bağlamını paylaşır.

Idempotent: zaten varsa skip.
"""

import frappe

CUSTOM_FIELDS = [
	{
		"dt": "CRM Lead",
		"fieldname": "seller",
		"label": "Satıcı (Mağaza)",
		"fieldtype": "Link",
		"options": "Admin Seller Profile",
		"insert_after": "lead_owner",
		"description": "Bu lead hangi mağazanın havuzunda. Boşsa Marketplace Admin havuzu.",
		"in_standard_filter": 1,
	},
	{
		"dt": "CRM Deal",
		"fieldname": "seller",
		"label": "Satıcı (Mağaza)",
		"fieldtype": "Link",
		"options": "Admin Seller Profile",
		"insert_after": "deal_owner",
		"description": "Bu deal hangi mağazanın hattında.",
		"in_standard_filter": 1,
	},
	{
		"dt": "CRM Organization",
		"fieldname": "seller",
		"label": "Satıcı (Mağaza)",
		"fieldtype": "Link",
		"options": "Admin Seller Profile",
		"insert_after": "organization_name",
		"description": "Bu kurum hangi mağazanın müşteri kaydında.",
		"in_standard_filter": 1,
	},
	{
		"dt": "Contact",
		"fieldname": "seller",
		"label": "Satıcı (Mağaza)",
		"fieldtype": "Link",
		"options": "Admin Seller Profile",
		"insert_after": "company_name",
		"description": "Bu kişi hangi mağazanın iletişim listesinde.",
	},
	{
		"dt": "CRM Task",
		"fieldname": "seller",
		"label": "Satıcı (Mağaza)",
		"fieldtype": "Link",
		"options": "Admin Seller Profile",
		"insert_after": "assigned_to",
		"description": "Bu görev hangi mağazaya ait.",
		"in_standard_filter": 1,
	},
	{
		"dt": "FCRM Note",
		"fieldname": "seller",
		"label": "Satıcı (Mağaza)",
		"fieldtype": "Link",
		"options": "Admin Seller Profile",
		"insert_after": "title",
		"description": "Bu not hangi mağaza bağlamında.",
	},
	{
		"dt": "CRM Call Log",
		"fieldname": "seller",
		"label": "Satıcı (Mağaza)",
		"fieldtype": "Link",
		"options": "Admin Seller Profile",
		"insert_after": "reference_doctype",
		"description": "Bu çağrı kaydı hangi mağazaya ait.",
	},
]


def execute():
	for spec in CUSTOM_FIELDS:
		_upsert(spec)
	frappe.db.commit()


def _upsert(spec):
	cf_name = f"{spec['dt']}-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", cf_name):
		return
	# Hedef DocType var mı (Frappe CRM kurulu mu) — yoksa sessizce skip et.
	# Bu patch tradehub_core'da ama CRM app dependency yok; eksikse uyar.
	if not frappe.db.exists("DocType", spec["dt"]):
		frappe.log_error(
			title="add_seller_to_crm_doctypes",
			message=f"DocType yok: {spec['dt']} — atlandı.",
		)
		return
	doc = frappe.new_doc("Custom Field")
	for k, v in spec.items():
		doc.set(k, v)
	doc.insert(ignore_permissions=True)
