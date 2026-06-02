import unittest

import frappe

from tradehub_core.api.search import unified_suggest


class TestUnifiedSuggest(unittest.TestCase):
	def test_empty_q_returns_empty_groups(self):
		result = unified_suggest("")
		self.assertEqual(result, {"products": [], "categories": [], "brands": [], "sellers": []})

	def test_too_short_q_returns_empty(self):
		result = unified_suggest("a")
		self.assertEqual(result["products"], [])
		self.assertEqual(result["categories"], [])
		self.assertEqual(result["brands"], [])
		self.assertEqual(result["sellers"], [])

	def test_too_long_q_returns_empty(self):
		result = unified_suggest("x" * 65)
		self.assertEqual(result, {"products": [], "categories": [], "brands": [], "sellers": []})

	def test_result_has_four_groups(self):
		result = unified_suggest("test")
		self.assertIn("products", result)
		self.assertIn("categories", result)
		self.assertIn("brands", result)
		self.assertIn("sellers", result)

	def test_products_schema(self):
		result = unified_suggest("a" * 2)  # min length, likely matches many titles
		self.assertIsInstance(result["products"], list)
		for p in result["products"]:
			self.assertIn("id", p)
			self.assertIn("name", p)
			self.assertIn("image", p)

	def test_categories_schema(self):
		result = unified_suggest("a" * 2)
		self.assertIsInstance(result["categories"], list)
		for c in result["categories"]:
			self.assertIn("name", c)
			self.assertIn("slug", c)

	def test_brands_schema(self):
		result = unified_suggest("a" * 2)
		self.assertIsInstance(result["brands"], list)
		for b in result["brands"]:
			self.assertIn("code", b)
			self.assertIn("name", b)
			self.assertIn("slug", b)

	def test_sellers_schema(self):
		result = unified_suggest("a" * 2)
		self.assertIsInstance(result["sellers"], list)
		for s in result["sellers"]:
			self.assertIn("id", s)
			self.assertIn("name", s)
			self.assertIn("slug", s)

	def test_cache_hit_returns_same_object(self):
		frappe.cache.delete_value("search:unified:test_cache:5")
		r1 = unified_suggest("test_cache")
		r2 = unified_suggest("test_cache")
		self.assertEqual(r1, r2)

	def test_limit_per_group_caps_results(self):
		result = unified_suggest("a" * 2, limit_per_group=2)
		self.assertLessEqual(len(result["products"]), 2)
		self.assertLessEqual(len(result["categories"]), 2)
		self.assertLessEqual(len(result["brands"]), 2)
		self.assertLessEqual(len(result["sellers"]), 2)
