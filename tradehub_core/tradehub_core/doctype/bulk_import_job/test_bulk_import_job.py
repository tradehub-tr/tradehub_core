# Copyright (c) 2026, TradeHub Team and contributors

import unittest

import frappe


def _ensure_seller() -> str:
	name = "TEST-BIJ-SELLER"
	if not frappe.db.exists("Admin Seller Profile", name):
		frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": "Test BIJ Satıcı",
				"seller_code": name,
				"user": "Administrator",
				"email": "test-seller@example.com",
			}
		).insert(ignore_permissions=True)
	return name


class TestBulkImportJob(unittest.TestCase):
	def test_happy_path_create(self):
		seller = _ensure_seller()
		doc = frappe.get_doc(
			{
				"doctype": "Bulk Import Job",
				"seller_profile": seller,
				"data_file": "/files/test.xlsx",
				"file_format": "xlsx",
				"update_mode": "insert_only",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("BIJ-"))
		self.assertEqual(doc.status, "Queued")
		doc.delete(ignore_permissions=True)

	def test_invalid_file_format_raises(self):
		seller = _ensure_seller()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Bulk Import Job",
					"seller_profile": seller,
					"data_file": "/files/test.zzz",
					"file_format": "zzz",
				}
			).insert(ignore_permissions=True)
