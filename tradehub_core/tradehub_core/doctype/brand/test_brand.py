import unittest

import frappe


class TestBrand(unittest.TestCase):
	def test_create_brand(self):
		if not frappe.db.exists("Brand", "TEST-BRAND-001"):
			doc = frappe.get_doc(
				{
					"doctype": "Brand",
					"brand_code": "TEST-BRAND-001",
					"brand_name": "Test Brand",
					"official_status": "Unverified",
				}
			)
			doc.insert(ignore_permissions=True)
			self.assertEqual(doc.slug, "test-brand")
			doc.delete(ignore_permissions=True)
