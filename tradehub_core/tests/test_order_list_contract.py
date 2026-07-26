"""Buyer order list filtering/pagination contract without a Frappe runtime."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

CALLS = []
ORDERS = [
	{"name": "ORD-2", "order_date": "2026-02-02", "seller": "SELLER-2", "status": "Onaylanıyor", "total": 20},
	{"name": "ORD-3", "order_date": "2026-02-03", "seller": "SELLER-3", "status": "Kargoda", "total": 30},
	{"name": "ORD-TARGET", "order_date": "2026-02-01", "seller": "SELLER-1", "status": "Tamamlandı", "total": 10},
]
ITEMS = [
	{"parent": "ORD-2", "product_name": "Hedef ürün", "idx": 1},
	{"parent": "ORD-3", "product_name": "Diğer ürün", "idx": 1},
	{"parent": "ORD-TARGET", "product_name": "Başka", "idx": 1},
]


def _install_stubs():
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.whitelist = lambda *args, **kwargs: args[0] if args and callable(args[0]) else lambda fn: fn
	frappe.AuthenticationError = PermissionError
	frappe.DoesNotExistError = LookupError
	frappe.session = SimpleNamespace(user="buyer@example.test")
	frappe.throw = lambda message, exc=Exception: (_ for _ in ()).throw(exc(message))

	def get_list(doctype, **kwargs):
		CALLS.append({"method": "get_list", "doctype": doctype, **kwargs})
		return [dict(order) for order in ORDERS]

	def get_all(doctype, **kwargs):
		CALLS.append({"method": "get_all", "doctype": doctype, **kwargs})
		if doctype == "Admin Seller Profile":
			return [
				{"name": "SELLER-1", "seller_name": "Sipariş adı eşleşen"},
				{"name": "SELLER-2", "seller_name": "Diğer satıcı"},
				{"name": "SELLER-3", "seller_name": "Hedef satıcı"},
			]
		if doctype == "Order Item":
			return [dict(item) for item in ITEMS]
		return []

	frappe.get_list = get_list
	frappe.get_all = get_all
	frappe.db = SimpleNamespace(get_value=lambda *args, **kwargs: 1)
	sys.modules["frappe"] = frappe
	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value: int(value or 0)
	utils.flt = lambda value, precision=2: round(float(value or 0), precision)
	utils.getdate = lambda value: value
	sys.modules["frappe.utils"] = utils
	cart = types.ModuleType("tradehub_core.api.cart")
	cart.DEFERRED_PAYMENT_METHODS = set()
	sys.modules["tradehub_core.api.cart"] = cart
	guards = types.ModuleType("tradehub_core.utils.auth_guards")
	guards.require_verified_email = lambda fn: fn
	sys.modules["tradehub_core.utils.auth_guards"] = guards
	notify = types.ModuleType("tradehub_core.utils.notify")
	notify.notify = lambda **kwargs: None
	sys.modules["tradehub_core.utils.notify"] = notify
	stock = types.ModuleType("tradehub_core.utils.stock")
	stock.deduct_stock_for_order = lambda *args: None
	stock.release_stock_for_order = lambda *args: None
	sys.modules["tradehub_core.utils.stock"] = stock


_install_stubs()
from tradehub_core.api import order  # noqa: E402


class TestOrderListContract(unittest.TestCase):
	def setUp(self):
		CALLS.clear()

	def test_searches_order_seller_and_item_before_pagination_with_stable_counts(self):
		result = order.get_my_orders(search="hedef", page=1, page_size=1)

		# ORD-3 seller and ORD-2 item match; date desc puts ORD-3 first.
		self.assertEqual([row["order_number"] for row in result["orders"]], ["ORD-3"])
		self.assertEqual(result["total"], 2)
		self.assertEqual(result["status_counts"], {"Delivering": 1, "Confirming": 1})
		query = next(call for call in CALLS if call["method"] == "get_list")
		self.assertEqual(query["order_by"], "order_date desc, name desc")
		self.assertEqual(query["page_length"], 0)
		self.assertEqual(len([call for call in CALLS if call["doctype"] == "Order Item"]), 1)

	def test_selected_status_filters_after_shared_counts_and_before_pagination(self):
		result = order.get_my_orders(search="hedef", status="confirming", page=1, page_size=20)

		self.assertEqual([row["order_number"] for row in result["orders"]], ["ORD-2"])
		self.assertEqual(result["total"], 1)
		self.assertEqual(result["status_counts"], {"Delivering": 1, "Confirming": 1})


if __name__ == "__main__":
	unittest.main()
