# Copyright (c) 2026, TradeHub Team and contributors

"""Seed ek regex pattern'leri — T1 (marketplace temel) + T2 (envanter/kargo).

Bunlar `03_seed_regex_patterns.py`'a EK olarak çalışır; mevcut pattern'lere
dokunmadan yeni canonical alanları otomatik mapping'e dahil eder.
"""

import frappe

SEED_PATTERNS = [
	# ── T1 Marketplace temel ──────────────────────────────────────
	{
		"name": "TH SYS Para Birimi",
		"target_field": "currency",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bpara\s*birimi\b", "IGNORECASE,UNICODE"),
			(r"\bcurrency\b", "IGNORECASE"),
			(r"\bdöviz\b", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Durum (Yeni/2.El)",
		"target_field": "condition",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\b(ürün\s*)?durum(u|)\b", "IGNORECASE,UNICODE"),
			(r"\bcondition\b", "IGNORECASE"),
			(r"\bkullan(ı|i)m\s*durumu\b", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Stok Birimi",
		"target_field": "stock_uom",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bstok\s*birim", "IGNORECASE,UNICODE"),
			(r"\bbirim\b", "IGNORECASE,UNICODE"),
			(r"\b(uom|unit)\b", "IGNORECASE"),
			(r"\bölçü\s*birim", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Listeleme Tipi",
		"target_field": "listing_type",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\blisteleme\s*tip", "IGNORECASE,UNICODE"),
			(r"\blisting\s*type\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Marka",
		"target_field": "brand",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bmarka\b", "IGNORECASE,UNICODE"),
			(r"\bbrand\b", "IGNORECASE"),
			(r"\b(üretici|uretici)\b", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Kategori",
		"target_field": "category",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bkategori\b", "IGNORECASE,UNICODE"),
			(r"\bcategory\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Platform Kategorisi",
		"target_field": "product_category",
		"category": "Column Header",
		"priority": 90,  # 'kategori' önce eşleşmesin diye düşük
		"patterns": [
			(r"\bplatform\s*kategori", "IGNORECASE,UNICODE"),
			(r"\b(ürün|urun)\s*kategori", "IGNORECASE,UNICODE"),
			(r"\bproduct\s*category\b", "IGNORECASE"),
		],
	},
	# ── T2 Envanter / kargo ──────────────────────────────────────
	{
		"name": "TH SYS Max Sipariş",
		"target_field": "max_order_qty",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bmax(imum)?\s*sipariş", "IGNORECASE,UNICODE"),
			(r"\bmax(imum)?\s*order", "IGNORECASE"),
			(r"\b(en\s*çok|enfazla|en\s*fazla)\s*sipariş", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Düşük Stok Eşiği",
		"target_field": "low_stock_threshold",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bdüşük\s*stok", "IGNORECASE,UNICODE"),
			(r"\bkritik\s*stok", "IGNORECASE,UNICODE"),
			(r"\blow\s*stock\b", "IGNORECASE"),
			(r"\bstok\s*uyar(ı|i)", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS MOQ Katı Zorunlu mu",
		"target_field": "sell_in_moq_multiples",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bmoq\s*kat", "IGNORECASE,UNICODE"),
			(r"\bkat(ı|i)\s*sipariş", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Stok Takibi",
		"target_field": "track_inventory",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bstok\s*takib(i|)\b", "IGNORECASE,UNICODE"),
			(r"\btrack\s*inventory\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Stoktan Az Sipariş İzni",
		"target_field": "allow_backorders",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bbackorder", "IGNORECASE"),
			(r"\bön\s*sipariş", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Ücretsiz Kargo",
		"target_field": "is_free_shipping",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bücretsiz\s*kargo\b", "IGNORECASE,UNICODE"),
			(r"\bfree\s*shipping\b", "IGNORECASE"),
			(r"\bkargo\s*bedava\b", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Kargo Ağırlığı",
		"target_field": "shipping_weight",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bkargo\s*ağ(ı|i)rl", "IGNORECASE,UNICODE"),
			(r"\bshipping\s*weight\b", "IGNORECASE"),
			(r"\bdesi\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Ürün Ağırlığı",
		"target_field": "weight",
		"category": "Column Header",
		"priority": 90,
		"patterns": [
			(r"\bağ(ı|i)rl(ı|i)k\b", "IGNORECASE,UNICODE"),
			(r"\bweight\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Sevk Ülkesi",
		"target_field": "ships_from_country",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bsevk\s*ülke", "IGNORECASE,UNICODE"),
			(r"\bships?\s*from\s*country\b", "IGNORECASE"),
			(r"\bgönderi\s*ülke", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Sevk Şehri",
		"target_field": "ships_from_city",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			# Türkçe iyelik ekiyle 'şehri' → 'şehir'in son-ünlüsü düşer; her ikisini de yakala.
			(r"\bsevk\s*şeh(ir|ri)", "IGNORECASE,UNICODE"),
			(r"\bships?\s*from\s*city\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Hazırlık Süresi",
		"target_field": "handling_days",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bhaz(ı|i)rl(ı|i)k\s*(süre|gün)", "IGNORECASE,UNICODE"),
			(r"\bhandling\s*days?\b", "IGNORECASE"),
			(r"\btedarik\s*süre", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Menşei Ülke",
		"target_field": "country_of_origin",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bmenşei?\b", "IGNORECASE,UNICODE"),
			(r"\bcountry\s*of\s*origin\b", "IGNORECASE"),
			(r"\bürün\s*ülke", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Video URL",
		"target_field": "video_url",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bvideo\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Barkod",
		"target_field": "barcode",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bbarkod\b", "IGNORECASE,UNICODE"),
			(r"\bbarcode\b", "IGNORECASE"),
			(r"\b(ean|gtin|upc)\b", "IGNORECASE"),
		],
	},
]


def execute():
	"""Seed ek System Regex Pattern Library kayıtları (idempotent)."""
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
				"v15_bulk_import_init.08",
			)
	frappe.db.commit()
