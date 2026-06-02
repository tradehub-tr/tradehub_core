# Copyright (c) 2026, TradeHub Team and contributors

import unittest

import frappe


class TestRegexPatternEntry(unittest.TestCase):
	def test_happy_path_attached_to_library(self):
		name = "TEST-REGEX-ENTRY-OK"
		if frappe.db.exists("Regex Pattern Library", name):
			frappe.delete_doc("Regex Pattern Library", name, force=1, ignore_permissions=True)
		parent = frappe.get_doc(
			{
				"doctype": "Regex Pattern Library",
				"pattern_name": name,
				"target_field": "sku",
				"target_doctype": "DocType",
				"scope": "System",
				"pattern_category": "Column Header",
				"patterns": [{"regex": r"^[A-Z]+-\d+$", "description": "Basit SKU"}],
			}
		).insert(ignore_permissions=True)
		self.assertEqual(parent.patterns[0].regex, r"^[A-Z]+-\d+$")
		parent.delete(ignore_permissions=True)

	def test_invalid_regex_compile_raises(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Regex Pattern Library",
					"pattern_name": "TEST-REGEX-ENTRY-BAD",
					"target_field": "sku",
					"target_doctype": "DocType",
					"scope": "System",
					"pattern_category": "Column Header",
					"patterns": [{"regex": "([unclosed", "description": "Bozuk"}],
				}
			).insert(ignore_permissions=True)
