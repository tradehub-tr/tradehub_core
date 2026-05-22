"""ECA validators — role-aware whitelist testleri."""

import unittest

from tradehub_core.eca.validators import (
	filter_doc_for_seller,
	is_action_allowed,
	is_field_visible,
	is_field_writable,
)


class TestActionAllowed(unittest.TestCase):
	def test_seller_field_update_allowed(self):
		self.assertTrue(is_action_allowed("field_update", "Seller"))

	def test_seller_custom_script_denied(self):
		self.assertFalse(is_action_allowed("custom_script", "Seller"))

	def test_seller_create_document_denied(self):
		self.assertFalse(is_action_allowed("create_document", "Seller"))

	def test_admin_all_allowed(self):
		for action in ("field_update", "email", "webhook", "reject_row", "create_document", "custom_script"):
			self.assertTrue(is_action_allowed(action, "System Manager"))


class TestFieldVisible(unittest.TestCase):
	def test_seller_sees_title(self):
		self.assertTrue(is_field_visible("title", "Seller"))

	def test_seller_blocked_from_admin_field(self):
		self.assertFalse(is_field_visible("admin_review_flag", "Seller"))

	def test_admin_sees_everything(self):
		self.assertTrue(is_field_visible("admin_review_flag", "System Manager"))


class TestFieldWritable(unittest.TestCase):
	def test_seller_writes_price(self):
		self.assertTrue(is_field_writable("base_price", "Seller"))

	def test_seller_blocked_from_status(self):
		self.assertFalse(is_field_writable("status", "Seller"))

	def test_seller_blocked_from_seller_profile(self):
		self.assertFalse(is_field_writable("seller_profile", "Seller"))


class TestFilterDocForSeller(unittest.TestCase):
	def test_strips_admin_fields(self):
		doc = {
			"title": "Solvent",
			"sku": "ABC-001",
			"admin_review_flag": 1,
			"internal_score": 0.5,
		}
		filtered = filter_doc_for_seller(doc)
		self.assertIn("title", filtered)
		self.assertIn("sku", filtered)
		self.assertNotIn("admin_review_flag", filtered)
		self.assertNotIn("internal_score", filtered)


if __name__ == "__main__":
	unittest.main()
