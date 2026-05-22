# Copyright (c) 2026, TradeHub Team and contributors

"""Seed varyant canonical alanları için regex pattern'leri (T8).

Varyantlı ürün xlsx'inde her satır bir varyantı temsil eder:
- parent_sku: bu varyantın bağlı olduğu master SKU (varyantsız satırlarda boş)
- variant_sku: varyantın benzersiz SKU'su
- variant_axis_1_type/value: birinci eksen (ör. Renk / Kırmızı)
- variant_axis_2_type/value: ikinci eksen (ör. Beden / M) — opsiyonel
- variant_price: varyant özel fiyatı (boşsa parent fiyatı)
- variant_stock: varyant stoku
"""

import frappe

SEED_PATTERNS = [
	{
		"name": "TH SYS Parent SKU",
		"target_field": "parent_sku",
		"category": "Column Header",
		"priority": 50,
		"patterns": [
			(r"\bparent\s*sku\b", "IGNORECASE"),
			(r"\bana\s*sku\b", "IGNORECASE,UNICODE"),
			(r"\büst\s*sku\b", "IGNORECASE,UNICODE"),
			(r"\bmaster\s*sku\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Varyant SKU",
		"target_field": "variant_sku",
		"category": "Column Header",
		"priority": 50,
		"patterns": [
			(r"\bvaryant\s*sku\b", "IGNORECASE,UNICODE"),
			(r"\bvariant\s*sku\b", "IGNORECASE"),
			(r"\bvaryant\s*kod", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Varyant Eksen 1 Tipi",
		"target_field": "variant_axis_1_type",
		"category": "Column Header",
		"priority": 50,
		"patterns": [
			(r"\bvaryant\s*eksen\s*1\s*tip", "IGNORECASE,UNICODE"),
			(r"\bvariant\s*axis\s*1\s*type\b", "IGNORECASE"),
			(r"\beksen\s*1\s*tip", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Varyant Eksen 1 Değeri",
		"target_field": "variant_axis_1_value",
		"category": "Column Header",
		"priority": 50,
		"patterns": [
			(r"\bvaryant\s*eksen\s*1\s*değer", "IGNORECASE,UNICODE"),
			(r"\bvariant\s*axis\s*1\s*value\b", "IGNORECASE"),
			(r"\beksen\s*1\s*değer", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Varyant Eksen 2 Tipi",
		"target_field": "variant_axis_2_type",
		"category": "Column Header",
		"priority": 50,
		"patterns": [
			(r"\bvaryant\s*eksen\s*2\s*tip", "IGNORECASE,UNICODE"),
			(r"\bvariant\s*axis\s*2\s*type\b", "IGNORECASE"),
			(r"\beksen\s*2\s*tip", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Varyant Eksen 2 Değeri",
		"target_field": "variant_axis_2_value",
		"category": "Column Header",
		"priority": 50,
		"patterns": [
			(r"\bvaryant\s*eksen\s*2\s*değer", "IGNORECASE,UNICODE"),
			(r"\bvariant\s*axis\s*2\s*value\b", "IGNORECASE"),
			(r"\beksen\s*2\s*değer", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Varyant Fiyat",
		"target_field": "variant_price",
		"category": "Column Header",
		"priority": 95,  # base_price pattern'lerinden sonra eşleşsin
		"patterns": [
			(r"\bvaryant\s*fi(y|i)at", "IGNORECASE,UNICODE"),
			(r"\bvariant\s*price\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Varyant Stok",
		"target_field": "variant_stock",
		"category": "Column Header",
		"priority": 95,
		"patterns": [
			(r"\bvaryant\s*stok", "IGNORECASE,UNICODE"),
			(r"\bvariant\s*stock\b", "IGNORECASE"),
		],
	},
]


def execute():
	"""Seed varyant pattern'lerini Regex Pattern Library'ye ekle (idempotent)."""
	for spec in SEED_PATTERNS:
		if frappe.db.exists("Regex Pattern Library", {"pattern_name": spec["name"]}):
			continue
		doc = frappe.new_doc("Regex Pattern Library")
		doc.pattern_name = spec["name"]
		doc.target_field = spec["target_field"]
		doc.target_doctype = "Listing"
		doc.scope = "System"
		doc.pattern_category = spec["category"]
		doc.priority = spec["priority"]
		doc.enabled = 1
		for regex, flags in spec["patterns"]:
			doc.append(
				"patterns",
				{
					"regex": regex,
					"flags": flags,
					"enabled": 1,
				},
			)
		try:
			doc.insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(
				f"Seed pattern {spec['name']} failed: {e}",
				"v15_bulk_import_init.09",
			)
	frappe.db.commit()
