# Copyright (c) 2026, TradeHub Team and contributors

"""Seed 40+ System Regex Pattern for adaptive column mapping.

Pattern categories:
- Column Header (Listing field mapping for Excel/CSV)
- SKU Filename (image matcher)
- Price Normalizer
- XML Tag (per-vendor preset)
"""

import frappe

# pattern_name → {target_field, pattern_category, priority, patterns: [(regex, flags)]}
SEED_PATTERNS = [
	# === Column Header — Sales fields ===
	{
		"name": "TH SYS Stok Kodu",
		"target_field": "sku",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bsku\b", "IGNORECASE"),
			(r"\bstok\s*kod", "IGNORECASE,UNICODE"),
			(r"\b(ürün|urun)\s*kod", "IGNORECASE,UNICODE"),
			(r"\b(part|item)\s*no\b", "IGNORECASE"),
			(r"\bmodel\s*kod", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Ürün Adı",
		"target_field": "title",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\b(ürün|urun)\s*ad", "IGNORECASE,UNICODE"),
			(r"\bisim\b", "IGNORECASE,UNICODE"),
			(r"\btitle\b", "IGNORECASE"),
			(r"\bname\b", "IGNORECASE"),
			(r"\bproduct\s*name\b", "IGNORECASE"),
			(r"\bmal\s*ad", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Birim Fiyat",
		"target_field": "base_price",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bfi(y|i)at\b", "IGNORECASE,UNICODE"),
			(r"\bbirim\s*fi(y|i)at\b", "IGNORECASE,UNICODE"),
			(r"\btutar\b", "IGNORECASE"),
			(r"\bprice\b", "IGNORECASE"),
			(r"\bunit\s*price\b", "IGNORECASE"),
			(r"\bsatış\s*fi(y|i)at", "IGNORECASE,UNICODE"),
			(r"\bvergi\s*hariç", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS İndirimli Fiyat",
		"target_field": "selling_price",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bindirim", "IGNORECASE,UNICODE"),
			(r"\bkampanya\s*fi(y|i)at", "IGNORECASE,UNICODE"),
			(r"\bpromosyon", "IGNORECASE"),
			(r"\bdiscount", "IGNORECASE"),
			(r"\bsale\s*price\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Stok Miktarı",
		"target_field": "stock_qty",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bstok\b", "IGNORECASE"),
			(r"\bstock\b", "IGNORECASE"),
			(r"\bmiktar\b", "IGNORECASE,UNICODE"),
			(r"\badet\b", "IGNORECASE,UNICODE"),
			(r"\b(qty|quantity)\b", "IGNORECASE"),
			(r"\bdepo\b", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Min Sipariş",
		"target_field": "min_order_qty",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bmin\s*sipariş", "IGNORECASE,UNICODE"),
			(r"\bminimum\s*sipariş", "IGNORECASE,UNICODE"),
			(r"\bmoq\b", "IGNORECASE"),
			(r"\bmin\s*order", "IGNORECASE"),
			(r"\basgari", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Kategori",
		"target_field": "product_category",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bkategori", "IGNORECASE,UNICODE"),
			(r"\bcategory\b", "IGNORECASE"),
			(r"\btür\b", "IGNORECASE,UNICODE"),
			(r"\bgrup\b", "IGNORECASE,UNICODE"),
			(r"\bsınıf\b", "IGNORECASE,UNICODE"),
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
			(r"\büretici", "IGNORECASE,UNICODE"),
			(r"\bmanufacturer\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Kısa Açıklama",
		"target_field": "short_description",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bkısa\s*açıklama", "IGNORECASE,UNICODE"),
			(r"\bözet\b", "IGNORECASE,UNICODE"),
			(r"\bshort\s*description\b", "IGNORECASE"),
			(r"\bsummary\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Detay Açıklama",
		"target_field": "description",
		"category": "Column Header",
		# Kısa açıklama match'i öncelikli olsun; detay daha düşük öncelikte denensin.
		"priority": 110,
		"patterns": [
			(r"\b(açıklama|aciklama)\b", "IGNORECASE,UNICODE"),
			(r"\bdetay\b", "IGNORECASE,UNICODE"),
			(r"\bdescription\b", "IGNORECASE"),
			(r"\buzun\s*açıklama", "IGNORECASE,UNICODE"),
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
			(r"\bgtin\b", "IGNORECASE"),
			(r"\bean\b", "IGNORECASE"),
			(r"\bupc\b", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Ağırlık",
		"target_field": "weight",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\b(ağırlık|agirlik)\b", "IGNORECASE,UNICODE"),
			(r"\bweight\b", "IGNORECASE"),
			(r"\bkargo\s*ağırlık", "IGNORECASE,UNICODE"),
			(r"\bnet\s*ağırlık", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS Etiketler",
		"target_field": "tags",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\betiket", "IGNORECASE,UNICODE"),
			(r"\btags?\b", "IGNORECASE"),
			(r"\bkeywords\b", "IGNORECASE"),
			(r"\banahtar\s*kelime", "IGNORECASE,UNICODE"),
		],
	},
	{
		"name": "TH SYS İndirim Yüzdesi",
		"target_field": "discount_percentage",
		"category": "Column Header",
		"priority": 100,
		"patterns": [
			(r"\bindirim\s*oran", "IGNORECASE,UNICODE"),
			(r"\bindirim\s*%", "IGNORECASE,UNICODE"),
			(r"\bdiscount\s*percent", "IGNORECASE"),
			(r"\b%\s*indirim", "IGNORECASE,UNICODE"),
		],
	},
	# === XML Tag — Ticimax preset ===
	{
		"name": "TH SYS Ticimax XML — Stok Kodu",
		"target_field": "sku",
		"category": "XML Tag",
		"priority": 200,
		"patterns": [
			(r"^urun\.stokkodu$", "IGNORECASE"),
			(r"^urun\.kod$", "IGNORECASE"),
			(r"^product\.code$", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Ticimax XML — Ürün Adı",
		"target_field": "title",
		"category": "XML Tag",
		"priority": 200,
		"patterns": [
			(r"^urun\.adi$", "IGNORECASE"),
			(r"^urun\.urunadi$", "IGNORECASE"),
			(r"^product\.name$", "IGNORECASE"),
		],
	},
	{
		"name": "TH SYS Ticimax XML — Fiyat",
		"target_field": "base_price",
		"category": "XML Tag",
		"priority": 200,
		"patterns": [
			(r"^urun\.fiyat$", "IGNORECASE"),
			(r"^urun\.satisfiyati$", "IGNORECASE"),
			(r"^product\.price$", "IGNORECASE"),
		],
	},
]


def execute():
	"""Seed System Regex Pattern Library kayıtları."""
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
			# Sistem seed'i; rollback yapma, başarısız pattern'i logla ve devam et.
			frappe.log_error(f"Seed pattern {spec['name']} failed: {e}", "v15_bulk_import_init.03")
	frappe.db.commit()
