"""H11 — get_customer_detail PII ilişki kapısı testi.

api/seller.get_customer_detail:
  - İlişki yoksa (sipariş/inquiry/ticket=0) User PII döndürmez (user=None)
  - İlişki varsa (en az 1 sipariş) User PII döner

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_get_customer_detail_pii
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _ValidationError(Exception):
	pass


class _PermissionError(Exception):
	pass


class _DoesNotExistError(Exception):
	pass


# Test senaryosu: order_count ve inquiries/tickets sayısı
_SCENARIO = {"order_count": 0, "inquiries": [], "tickets": []}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.ValidationError = _ValidationError
	frappe.PermissionError = _PermissionError
	frappe.DoesNotExistError = _DoesNotExistError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: a[0] if (a and callable(a[0])) else (lambda fn: fn)
	frappe.session = SimpleNamespace(user="seller@test")

	def _get_value(doctype, name=None, fieldname=None, as_dict=False, **kw):
		if doctype == "User":
			return SimpleNamespace(
				name=name, full_name="Müşteri Adı", email=name, mobile_no="555", creation=None
			)
		if doctype == "Admin Seller Profile":
			return "SELLER-A"  # _get_my_seller_profile için
		return None

	def _sql(query, params=None, as_dict=False):
		q = " ".join(query.split())
		if "COUNT(*) AS order_count" in q:
			return [
				{
					"order_count": _SCENARIO["order_count"],
					"total_revenue": 0,
					"last_order_date": None,
					"first_order_date": None,
				}
			]
		if "FROM `tabOrder`" in q:  # sipariş listesi
			return [{"name": "O1"}] * _SCENARIO["order_count"]
		if "tabHD Ticket" in q:
			return list(_SCENARIO["tickets"])
		return []

	frappe.db = SimpleNamespace(get_value=_get_value, sql=_sql)
	frappe.get_all = lambda *a, **k: list(_SCENARIO["inquiries"])


_install_frappe_stub()
_FRAPPE_STUB = sys.modules["frappe"]

for _mod in ("tradehub_core.utils.tenant",):
	m = types.ModuleType(_mod)
	m._get_seller_profile_for_user = lambda user: "SELLER-A"
	sys.modules.setdefault(_mod, m)

from tradehub_core.api import seller  # noqa: E402


class TestCustomerDetailPII(unittest.TestCase):
	def setUp(self):
		seller.frappe = _FRAPPE_STUB
		seller._get_my_seller_profile = lambda: ("SELLER-A", "seller@test")
		_SCENARIO["order_count"] = 0
		_SCENARIO["inquiries"] = []
		_SCENARIO["tickets"] = []

	def test_no_relationship_hides_pii(self):
		out = seller.get_customer_detail("victim@example.com")
		self.assertIsNone(out["user"], "İlişki yokken User PII döndürülmemeli")

	def test_with_order_returns_pii(self):
		_SCENARIO["order_count"] = 2
		out = seller.get_customer_detail("real-customer@example.com")
		self.assertIsNotNone(out["user"], "İlişki varken PII dönmeli")
		self.assertEqual(out["user"].full_name, "Müşteri Adı")

	def test_with_inquiry_returns_pii(self):
		_SCENARIO["inquiries"] = [{"name": "INQ1"}]
		out = seller.get_customer_detail("inquirer@example.com")
		self.assertIsNotNone(out["user"], "Inquiry ilişkisi varken PII dönmeli")


if __name__ == "__main__":
	unittest.main()
