"""
Kategori bazlı satış sıralaması (Best Sellers Rank) testleri.

    docker exec istocc-dev-backend-1 bench --site tradehub.localhost \
        run-tests --module tradehub_core.tests.test_category_ranks
"""

import unittest.mock as mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import listing as li


class TestCategoryRanks(FrappeTestCase):
	def setUp(self):
		# Redis cache testler arası rollback edilmez — ilgili anahtarları temizle.
		frappe.cache.delete_keys("cat_rank")
		frappe.cache.delete_keys("pc_desc")
		self.sector = self._cat("BSR Sektör", None)
		self.group = self._cat("BSR Grup", self.sector)
		self.leaf = self._cat("BSR Yaprak", self.group)

	def _cat(self, name, parent):
		doc = frappe.get_doc(
			{
				"doctype": "Product Category",
				"category_name": name,
				"parent_product_category": parent,
				"is_active": 1,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)
		return doc.name

	def test_chain_order_level_and_rank_math(self):
		listing = frappe._dict({"product_category": self.leaf, "order_count": 5})

		def fake_count(doctype, filters):
			# order_count list filtresi ("higher" sorgusu) → 2; aksi halde total → 10
			return 2 if isinstance(filters.get("order_count"), list) else 10

		with (
			mock.patch.object(li, "_get_category_descendants", side_effect=lambda c: [c]),
			mock.patch.object(li.frappe.db, "count", side_effect=fake_count),
		):
			ranks = li._get_category_ranks(listing)

		# Yapraktan sektöre sıralı
		self.assertEqual(
			[r["category_name"] for r in ranks],
			["BSR Yaprak", "BSR Grup", "BSR Sektör"],
		)
		self.assertEqual([r["level"] for r in ranks], [0, 1, 2])
		for r in ranks:
			self.assertEqual(r["rank"], 3)  # 2 higher + 1
			self.assertEqual(r["total"], 10)

	def test_zero_sales_still_ranked(self):
		listing = frappe._dict({"product_category": self.leaf, "order_count": 0})

		def fake_count(doctype, filters):
			# Hiç kimse 0'dan fazla satmıyorsa higher=0 → rank 1
			return 0 if isinstance(filters.get("order_count"), list) else 3

		with (
			mock.patch.object(li, "_get_category_descendants", side_effect=lambda c: [c]),
			mock.patch.object(li.frappe.db, "count", side_effect=fake_count),
		):
			ranks = li._get_category_ranks(listing)

		self.assertEqual(ranks[0]["rank"], 1)
		self.assertEqual(ranks[0]["total"], 3)

	def test_no_category_returns_empty(self):
		listing = frappe._dict({"product_category": None, "order_count": 5})
		self.assertEqual(li._get_category_ranks(listing), [])
