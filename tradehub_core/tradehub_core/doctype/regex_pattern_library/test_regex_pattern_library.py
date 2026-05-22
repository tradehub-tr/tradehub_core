# Copyright (c) 2026, TradeHub Team and contributors

import unittest

import frappe


class TestRegexPatternLibrary(unittest.TestCase):
	def test_happy_path_system_library(self):
		name = "TEST-REGEX-LIB-SYS"
		if frappe.db.exists("Regex Pattern Library", name):
			frappe.delete_doc("Regex Pattern Library", name, force=1, ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "Regex Pattern Library",
				"pattern_name": name,
				"target_field": "sku",
				"target_doctype": "DocType",
				"scope": "System",
				"pattern_category": "Column Header",
				"patterns": [
					{"regex": r"^SKU[-_]?\d+$", "description": "SKU başlığı"},
				],
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.pattern_name, name)
		doc.delete(ignore_permissions=True)

	def test_catastrophic_pattern_raises(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Regex Pattern Library",
					"pattern_name": "TEST-REGEX-LIB-BAD",
					"target_field": "sku",
					"target_doctype": "DocType",
					"scope": "System",
					"pattern_category": "Column Header",
					"patterns": [
						{"regex": r"(.+)+", "description": "Katastrofik"},
					],
				}
			).insert(ignore_permissions=True)
