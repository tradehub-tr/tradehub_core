"""regex_lib integration testleri — pattern library resolver."""

import unittest

try:
	from frappe.tests.utils import FrappeTestCase

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False

if HAS_FRAPPE:
	import frappe

	from tradehub_core.bulk_import import regex_lib


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestRegexLibResolver(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Seed a System pattern for base_price
		if not frappe.db.exists("Regex Pattern Library", {"pattern_name": "TEST System Fiyat"}):
			doc = frappe.new_doc("Regex Pattern Library")
			doc.pattern_name = "TEST System Fiyat"
			doc.target_field = "base_price"
			doc.target_doctype = "Listing"
			doc.scope = "System"
			doc.pattern_category = "Column Header"
			doc.enabled = 1
			doc.priority = 100
			doc.append(
				"patterns",
				{
					"regex": r"\bfi(y|i)at\b",
					"flags": "IGNORECASE",
					"enabled": 1,
				},
			)
			doc.insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		try:
			frappe.delete_doc("Regex Pattern Library", "TEST System Fiyat", force=True)
		except Exception:
			pass
		super().tearDownClass()

	def test_resolve_basic(self):
		mapping = regex_lib.resolve_column_mapping(["Birim Fiyat", "Stok"], seller_profile=None)
		# base_price eşleşmesi olmalı
		self.assertIn("base_price", mapping)
		self.assertEqual(mapping["base_price"], "Birim Fiyat")

	def test_resolve_no_match(self):
		mapping = regex_lib.resolve_column_mapping(["xxx", "yyy"], seller_profile=None)
		self.assertNotIn("base_price", mapping)


if __name__ == "__main__":
	unittest.main()
