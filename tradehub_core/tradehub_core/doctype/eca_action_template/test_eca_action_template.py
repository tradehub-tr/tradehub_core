# Copyright (c) 2026, TradeHub Team and contributors

import unittest

import frappe


class TestECAActionTemplate(unittest.TestCase):
	def test_happy_path_field_update_template(self):
		name = "TEST-ACT-FU"
		if frappe.db.exists("ECA Action Template", name):
			frappe.delete_doc("ECA Action Template", name, force=1, ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "ECA Action Template",
				"template_name": name,
				"action_type": "field_update",
				"field_updates": '[{"fieldname":"status","value":"Active"}]',
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.template_name, name)
		doc.delete(ignore_permissions=True)

	def test_missing_template_name_raises(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "ECA Action Template",
					"action_type": "field_update",
				}
			).insert(ignore_permissions=True)
