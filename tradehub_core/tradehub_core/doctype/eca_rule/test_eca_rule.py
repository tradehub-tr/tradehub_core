# Copyright (c) 2026, TradeHub Team and contributors

import unittest

import frappe


def _ensure_seller() -> str:
	# Administrator için Admin Seller Profile zaten varsa reuse et (test paralelliği)
	existing = frappe.db.get_value("Admin Seller Profile", {"user": "Administrator"}, "name")
	if existing:
		return existing
	name = "TEST-ECA-SELLER"
	if not frappe.db.exists("Admin Seller Profile", name):
		frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": "Test ECA Satıcı",
				"seller_code": name,
				"user": "Administrator",
				"email": "test-seller@example.com",
			}
		).insert(ignore_permissions=True)
	return name


class TestECARule(unittest.TestCase):
	def test_happy_path_seller_rule(self):
		seller = _ensure_seller()
		name = "TEST-ECA-RULE-HAPPY"
		if frappe.db.exists("ECA Rule", name):
			frappe.delete_doc("ECA Rule", name, force=1, ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "ECA Rule",
				"rule_name": name,
				"reference_doctype": "Listing",
				"event": "before_save",
				"rule_scope": "Per-Seller",
				"seller_profile": seller,
				"owner_role": "Seller",
				"priority": 500,
				"condition": "True",
				"action_type": "field_update",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.execution_phase, "Seller Phase")
		doc.delete(ignore_permissions=True)

	def test_seller_with_forbidden_action_raises(self):
		seller = _ensure_seller()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "ECA Rule",
					"rule_name": "TEST-ECA-RULE-FORBID",
					"reference_doctype": "Listing",
					"event": "before_save",
					"rule_scope": "Per-Seller",
					"seller_profile": seller,
					"owner_role": "Seller",
					"priority": 500,
					"condition": "True",
					"action_type": "custom_script",
				}
			).insert(ignore_permissions=True)
