"""Public seller-shop product API contract tests (no Frappe runtime required)."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

_CALLS: list[dict] = []


def _install_stubs() -> None:
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.whitelist = lambda *args, **kwargs: (
		args[0] if args and callable(args[0]) else lambda fn: fn
	)

	def get_all(doctype, **kwargs):
		_CALLS.append({"doctype": doctype, **kwargs})
		return [
			{
				"name": "LISTING-2",
				"title": "Second",
				"primary_image": "/files/two.webp",
				"selling_price": 20,
				"base_price": 25,
				"min_order_qty": 2,
				"category": "SELLER-CAT",
				"product_category": "PLATFORM-CAT",
				"currency": "TRY",
				"view_count": 1,
				"order_count": 4,
				"creation": "2026-01-01 00:00:00",
				"b2b_enabled": 0,
			}
		]

	frappe.get_all = get_all
	frappe.db = SimpleNamespace(
		exists=lambda doctype, name: doctype == "Admin Seller Profile" and name == "SELLER-1",
		count=lambda doctype, filters: 17,
	)
	sys.modules["frappe"] = frappe

	utils = types.ModuleType("frappe.utils")
	utils.getdate = lambda value: value
	utils.nowdate = lambda: "2026-01-01"
	sys.modules["frappe.utils"] = utils

	input_module = types.ModuleType("tradehub_core.api._input")
	input_module.safe_float = lambda value, **kwargs: float(value)
	sys.modules["tradehub_core.api._input"] = input_module

	rate_limit = types.ModuleType("tradehub_core.api.rate_limit")
	rate_limit.rate_limit = lambda *args, **kwargs: lambda fn: fn
	sys.modules["tradehub_core.api.rate_limit"] = rate_limit


_install_stubs()
from tradehub_core.api import seller  # noqa: E402


class TestSellerProductsContract(unittest.TestCase):
	def setUp(self) -> None:
		_CALLS.clear()

	def test_platform_category_and_price_sort_are_server_side_and_paginated(self):
		result = seller.get_seller_products(
			"SELLER-1",
			category="PLATFORM-CAT",
			category_type="platform",
			page="2",
			page_size="2",
			sort_by="selling_price",
			sort_dir="asc",
		)

		query = _CALLS[0]
		self.assertEqual(query["filters"], {
			"seller_profile": "SELLER-1",
			"status": "Active",
			"product_category": "PLATFORM-CAT",
		})
		self.assertEqual(query["limit_start"], 2)
		self.assertEqual(query["limit_page_length"], 2)
		self.assertEqual(query["order_by"], "selling_price asc, name asc")
		self.assertEqual(result["total"], 17)

	def test_existing_seller_category_filter_and_stable_default_sort_are_preserved(self):
		seller.get_seller_products("SELLER-1", category="SELLER-CAT")

		query = _CALLS[0]
		self.assertEqual(query["filters"]["category"], "SELLER-CAT")
		self.assertNotIn("product_category", query["filters"])
		self.assertEqual(query["order_by"], "creation desc, name desc")

	def test_unknown_sort_and_invalid_pagination_fall_back_to_safe_defaults(self):
		seller.get_seller_products(
			"SELLER-1", page="not-a-page", page_size="9999", sort_by="DROP TABLE", sort_dir="sideways"
		)

		query = _CALLS[0]
		self.assertEqual(query["limit_start"], 0)
		self.assertEqual(query["limit_page_length"], 100)
		self.assertEqual(query["order_by"], "creation desc, name desc")

	def test_existing_storefront_sort_aliases_map_to_whitelisted_columns(self):
		seller.get_seller_products("SELLER-1", sort="best_selling")
		self.assertEqual(_CALLS[0]["order_by"], "order_count desc, name desc")

		_CALLS.clear()
		seller.get_seller_products("SELLER-1", sort="price_desc")
		self.assertEqual(_CALLS[0]["order_by"], "selling_price desc, name desc")


if __name__ == "__main__":
	unittest.main()
