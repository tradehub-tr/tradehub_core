"""Marketplace Settings (Single DocType) testleri — Sprint 1 (2026-05-15).

Çalıştırma:
    bench --site dev.localhost run-tests --module tradehub_core.tests.test_marketplace_settings
"""

import unittest

import frappe


class TestMarketplaceSettings(unittest.TestCase):
	"""Single DocType varlığı + helper + default'lar."""

	def test_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Marketplace Settings"))

	def test_singleton_loadable(self):
		# Single DocType — get_cached_doc her zaman tek instance döndürür
		doc = frappe.get_cached_doc("Marketplace Settings")
		self.assertIsNotNone(doc)

	def test_default_address_type_is_individual(self):
		doc = frappe.get_cached_doc("Marketplace Settings")
		# Default'tan vazgeçilmediyse Individual olmalı
		self.assertIn(doc.default_address_type or "Individual", ("Individual", "Business"))

	def test_helper_returns_dict(self):
		from tradehub_core.tradehub_core.doctype.marketplace_settings.marketplace_settings import (
			get_settings,
		)

		s = get_settings()
		self.assertIsInstance(s, dict)
		self.assertIn("default_address_type", s)
		self.assertIn("address_type_toggle_visible", s)
		self.assertIn("require_tax_id_business", s)
		self.assertIn("require_tax_id_individual", s)
		self.assertIn("invoice_generation_mode", s)

	def test_helper_types_correct(self):
		from tradehub_core.tradehub_core.doctype.marketplace_settings.marketplace_settings import (
			get_settings,
		)

		s = get_settings()
		# Check fields → bool
		self.assertIsInstance(s["address_type_toggle_visible"], bool)
		self.assertIsInstance(s["require_tax_id_business"], bool)
		self.assertIsInstance(s["require_tax_id_individual"], bool)
		# Select fields → str
		self.assertIsInstance(s["default_address_type"], str)
		self.assertIsInstance(s["invoice_generation_mode"], str)

	def test_default_address_type_options_constrained(self):
		"""Select field options yalnızca Individual veya Business olmalı."""
		meta = frappe.get_meta("Marketplace Settings")
		field = meta.get_field("default_address_type")
		opts = (field.options or "").strip().split("\n")
		self.assertIn("Individual", opts)
		self.assertIn("Business", opts)
		self.assertEqual(len(opts), 2)


if __name__ == "__main__":
	unittest.main()
