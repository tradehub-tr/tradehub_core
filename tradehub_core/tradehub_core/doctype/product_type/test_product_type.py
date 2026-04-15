import frappe
import unittest


class TestProductType(unittest.TestCase):
	def test_create(self):
		if not frappe.db.exists("Product Type", "TEST-PT-01"):
			doc = frappe.get_doc({
				"doctype": "Product Type",
				"type_code": "TEST-PT-01",
				"type_name": "Test Product Type",
			})
			doc.insert(ignore_permissions=True)
			doc.delete(ignore_permissions=True)
