import frappe
import unittest


class TestProductAttribute(unittest.TestCase):
	def test_create_text_attribute(self):
		if not frappe.db.exists("Product Attribute", "TEST-ATTR-01"):
			doc = frappe.get_doc({
				"doctype": "Product Attribute",
				"attribute_code": "TEST-ATTR-01",
				"attribute_label": "Test Attribute",
				"data_type": "Text",
			})
			doc.insert(ignore_permissions=True)
			doc.delete(ignore_permissions=True)
