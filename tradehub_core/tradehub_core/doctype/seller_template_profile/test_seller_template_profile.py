# Copyright (c) 2026, TradeHub Team and contributors

import unittest

import frappe


def _ensure_seller() -> str:
	# Administrator için Admin Seller Profile zaten varsa reuse et (test paralelliği)
	existing = frappe.db.get_value("Admin Seller Profile", {"user": "Administrator"}, "name")
	if existing:
		return existing
	name = "TEST-STP-SELLER"
	if not frappe.db.exists("Admin Seller Profile", name):
		frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": "Test STP Satıcı",
				"seller_code": name,
				"user": "Administrator",
				"email": "test-seller@example.com",
			}
		).insert(ignore_permissions=True)
	return name


class TestSellerTemplateProfile(unittest.TestCase):
	def test_happy_path_create(self):
		seller = _ensure_seller()
		fp = "abc123fingerprint-stp"
		if frappe.db.exists("Seller Template Profile", fp):
			frappe.delete_doc("Seller Template Profile", fp, force=1, ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "Seller Template Profile",
				"seller": seller,
				"fingerprint": fp,
				"source_format": "xlsx",
				"mapping_json": '{"SKU":"sku","Ad":"product_name"}',
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, fp)
		doc.delete(ignore_permissions=True)

	def test_missing_fingerprint_raises(self):
		seller = _ensure_seller()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Seller Template Profile",
					"seller": seller,
					"source_format": "csv",
				}
			).insert(ignore_permissions=True)
