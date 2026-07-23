"""
Temel Product Type kayıtlarını oluşturur. Idempotent.
"""

import frappe

DEFAULT_TYPES = [
	{
		"type_code": "PHYSICAL",
		"type_name": "Fiziksel Ürün",
		"is_digital": 0,
		"is_service": 0,
		"requires_shipping": 1,
	},
	{
		"type_code": "DIGITAL",
		"type_name": "Dijital Ürün",
		"is_digital": 1,
		"is_service": 0,
		"requires_shipping": 0,
	},
	{
		"type_code": "SERVICE",
		"type_name": "Hizmet",
		"is_digital": 0,
		"is_service": 1,
		"requires_shipping": 0,
	},
	{
		"type_code": "BUNDLE",
		"type_name": "Paket Ürün",
		"is_digital": 0,
		"is_service": 0,
		"requires_shipping": 1,
	},
	{
		"type_code": "CONFIGURABLE",
		"type_name": "Yapılandırılabilir",
		"is_digital": 0,
		"is_service": 0,
		"requires_shipping": 1,
		"has_variants_default": 1,
	},
]


def execute():
	if not frappe.db.table_exists("Product Type"):
		return

	created = 0
	for rec in DEFAULT_TYPES:
		if frappe.db.exists("Product Type", rec["type_code"]):
			continue
		doc = frappe.new_doc("Product Type")
		for k, v in rec.items():
			doc.set(k, v)
		doc.is_active = 1
		doc.flags.ignore_permissions = True
		try:
			doc.insert(ignore_if_duplicate=True)
			created += 1
		except Exception:
			frappe.log_error(
				title="create_default_product_types",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()
	frappe.logger("patches").info(f"[create_default_product_types] Created {created} Product Type records.")
