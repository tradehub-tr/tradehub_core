# Copyright (c) 2026, TradeHub Team and contributors

import unittest

import frappe


class TestECARuleLog(unittest.TestCase):
	def test_happy_path_log_insert(self):
		doc = frappe.get_doc(
			{
				"doctype": "ECA Rule Log",
				"reference_doctype": "Listing",
				"reference_name": "LST-TEST-1",
				"event": "before_save",
				"execution_phase": "Seller Phase",
				"status": "success",
				"condition_result": 1,
				"action_executed": 1,
				"execution_time_ms": 12,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.status, "success")
		doc.delete(ignore_permissions=True)

	def test_invalid_status_raises(self):
		with self.assertRaises(frappe.ValidationError):
			doc = frappe.get_doc(
				{
					"doctype": "ECA Rule Log",
					"reference_doctype": "Listing",
					"reference_name": "LST-TEST-2",
					"event": "before_save",
					"status": "success",
				}
			)
			# Status'u doğrudan invalid hale getirip validate'ı tetikle.
			doc.status = "bogus_state"
			doc.insert(ignore_permissions=True)
