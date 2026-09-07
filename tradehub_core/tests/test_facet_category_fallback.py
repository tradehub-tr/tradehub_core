"""Boş sonuçta kategori facet'i tüm ağaca düşer (fallback_categories=1).

Kategori/aramada hiç ürün yoksa listeleme "Bu ürünler de ilginizi çekebilir" ile
tüm ürünleri gösterir; sidebar kategori ağacı da boş kalmamalı — tüm kategoriler
gelir, seçili (boş) kategori 0 sayımla ağaçta işaretli kalır ki oradan başka
kategoriye geçilebilsin. Yalnız ilk yüklemede istenir; filtre değişimindeki facet
yenilemesi bu bayrağı göndermez (sayımlar 0'a düşer, ağaç yerinde kalır).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.listing import get_filter_facets


def _cats(res):
	return res["data"]["categories"]

_TUZ = "fcf"


class TestFacetCategoryFallback(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		root = frappe.get_doc(
			{
				"doctype": "Product Category",
				"external_id": f"{_TUZ}-root",
				"category_name": f"{_TUZ} Kök",
				"url_slug": f"{_TUZ}-kok",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		cls.empty = frappe.get_doc(
			{
				"doctype": "Product Category",
				"external_id": f"{_TUZ}-bos",
				"category_name": f"{_TUZ} Boş",
				"parent_product_category": root.name,
				"url_slug": f"{_TUZ}-bos",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		frappe.cache.delete_keys("facets:*")

	def test_without_flag_empty_category_returns_no_categories(self):
		res = get_filter_facets(category=f"{_TUZ}-bos")
		self.assertEqual(_cats(res), [])

	def test_with_flag_returns_all_categories_and_marks_current_with_zero(self):
		res = get_filter_facets(category=f"{_TUZ}-bos", fallback_categories=1)
		cats = _cats(res)
		self.assertGreater(len(cats), 0)
		current = [c for c in cats if c["id"] == self.empty.name]
		self.assertEqual(len(current), 1)
		self.assertEqual(current[0]["count"], 0)
		self.assertEqual(current[0]["slug"], f"{_TUZ}-bos")
		self.assertEqual([p["slug"] for p in current[0]["path"]], [f"{_TUZ}-kok"])
		# Diğerleri gerçek sayımla gelir
		self.assertTrue(any(c["count"] > 0 for c in cats))

	def test_with_flag_unknown_query_returns_all_categories_without_injection(self):
		res = get_filter_facets(query="zzqq-hicbir-sey-yok", fallback_categories=1)
		self.assertGreater(len(_cats(res)), 0)
		self.assertTrue(all(c["count"] > 0 for c in _cats(res)))

	def test_flag_is_noop_when_results_exist(self):
		a = _cats(get_filter_facets(query="a"))
		b = _cats(get_filter_facets(query="a", fallback_categories=1))
		self.assertEqual(a, b)
