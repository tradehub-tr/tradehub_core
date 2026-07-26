"""Favorites listing-summary contract tests without a Frappe runtime."""

from __future__ import annotations

import datetime
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

CALLS = []


def _install_stubs():
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.whitelist = lambda *args, **kwargs: args[0] if args and callable(args[0]) else lambda fn: fn
	frappe.PermissionError = PermissionError
	frappe.session = SimpleNamespace(user="buyer@example.test")

	def get_all(doctype, **kwargs):
		CALLS.append({"doctype": doctype, **kwargs})
		if doctype == "Buyer Favorite List":
			return []
		if doctype == "Buyer Favorite Item":
			return [
				{"listing": "LISTING-OUT", "list_ids": '["default"]', "creation": datetime.datetime(2026, 1, 2)},
				{"listing": "LISTING-LIVE", "list_ids": '["team"]', "creation": datetime.datetime(2026, 1, 1)},
				{"listing": "LISTING-MISSING", "list_ids": None, "creation": datetime.datetime(2025, 12, 31)},
			]
		if doctype == "Listing":
			return [
				{"name": "LISTING-LIVE", "category_name": "Ofis", "seller_profile": "SELLER-1", "supplier_display_name": "", "status": "Active", "available_qty": 7, "stock_qty": 12, "selling_price": 100, "discount_percentage": 15, "currency": "TRY"},
				{"name": "LISTING-OUT", "category_name": "Mobilya", "seller_profile": "SELLER-2", "supplier_display_name": "Mağaza adı", "status": "Out of Stock", "available_qty": 5, "stock_qty": 12, "selling_price": 50, "discount_percentage": 0, "currency": "USD"},
			]
		if doctype == "Admin Seller Profile":
			return [
				{"name": "SELLER-1", "seller_name": "Doğrulanmış", "user": "verified@example.test", "country": "Turkey"},
				{"name": "SELLER-2", "seller_name": "Diğer", "user": "plain@example.test", "country": "Germany"},
			]
		if doctype == "Has Role":
			return ["verified@example.test"]
		return []

	frappe.get_all = get_all
	frappe.db = SimpleNamespace()
	frappe.log_error = lambda *args, **kwargs: None
	sys.modules["frappe"] = frappe
	utils = types.ModuleType("frappe.utils")
	utils.get_datetime = lambda value: value
	sys.modules["frappe.utils"] = utils


_install_stubs()
from tradehub_core.api import favorites  # noqa: E402


class TestFavoritesListingSummary(unittest.TestCase):
	def setUp(self):
		CALLS.clear()

	def test_batch_summary_preserves_favorite_order_and_marks_inaccessible_as_null(self):
		result = favorites.get_my_favorites()

		self.assertEqual([item["id"] for item in result["items"]], ["LISTING-OUT", "LISTING-LIVE", "LISTING-MISSING"])
		summary = result["listing_summary"]
		self.assertIsNone(summary["LISTING-MISSING"])
		self.assertEqual(summary["LISTING-LIVE"]["category"], "Ofis")
		self.assertEqual(summary["LISTING-LIVE"]["supplier"], {"name": "Doğrulanmış", "verified": True, "country": "Turkey"})
		self.assertEqual(summary["LISTING-LIVE"]["stock_qty"], 7)
		self.assertTrue(summary["LISTING-LIVE"]["in_stock"])
		self.assertEqual(summary["LISTING-LIVE"]["current_price"], 85.0)
		self.assertEqual(summary["LISTING-LIVE"]["currency"], "TRY")
		self.assertEqual(summary["LISTING-OUT"]["stock_qty"], 0)
		self.assertFalse(summary["LISTING-OUT"]["in_stock"])

		listing_call = next(call for call in CALLS if call["doctype"] == "Listing")
		self.assertEqual(listing_call["filters"], {"name": ["in", ["LISTING-OUT", "LISTING-LIVE", "LISTING-MISSING"]], "storefront_visible": 1})
		self.assertEqual(len([call for call in CALLS if call["doctype"] == "Listing"]), 1)
		self.assertEqual(len([call for call in CALLS if call["doctype"] == "Admin Seller Profile"]), 1)
		self.assertEqual(len([call for call in CALLS if call["doctype"] == "Has Role"]), 1)


if __name__ == "__main__":
	unittest.main()
