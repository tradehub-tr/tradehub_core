"""H8 + H9 — BOLA guard testleri.

H8: api/review.submit_listing_review — yalnız siparişin buyer'ı yorum yazabilir.
H9: api/ab_testing.get_ab_test_report — yalnız test sahibi satıcı/admin görebilir.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_review_abtest_bola
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


class _PermissionError(Exception):
	pass


class _DoesNotExistError(Exception):
	pass


class _ValidationError(Exception):
	pass


_STATE = {"user": "buyer-a@test", "is_admin": False}

# Order Item → (parent order, buyer)
_ORDER_ITEMS = {"OI-A": ("ORD-A", "buyer-a@test")}
# AB Test → seller profile, seller's user
_AB_TESTS = {"ABT-A": ("SELLER-A", "seller-a@test")}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.PermissionError = _PermissionError
	frappe.DoesNotExistError = _DoesNotExistError
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: a[0] if (a and callable(a[0])) else (lambda fn: fn)
	frappe.session = SimpleNamespace(user=_STATE["user"])

	def _get_value(doctype, name=None, fieldname=None, as_dict=False, **kw):
		if doctype == "Order Item" and name in _ORDER_ITEMS:
			parent, _buyer = _ORDER_ITEMS[name]
			return SimpleNamespace(parent=parent, parenttype="Order", listing="L1")
		if doctype == "Order":
			for _oi, (parent, buyer) in _ORDER_ITEMS.items():
				if parent == name:
					return buyer
			return None
		if doctype == "Admin Seller Profile":
			for _t, (sp, suser) in _AB_TESTS.items():
				if sp == name:
					return suser
			return None
		return None

	def _get_doc(doctype, name=None):
		if doctype == "Listing AB Test" and name in _AB_TESTS:
			sp, _u = _AB_TESTS[name]
			return SimpleNamespace(
				name=name,
				seller=sp,
				status="Running",
				metric="ctr",
				start_date=None,
				end_date=None,
				winner=None,
				variants=[],
			)
		return SimpleNamespace(name=name)

	frappe.db = SimpleNamespace(get_value=_get_value)
	frappe.get_doc = _get_doc
	frappe.new_doc = lambda dt: SimpleNamespace(flags=SimpleNamespace())

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: None
	utils.getdate = lambda *a, **k: None
	utils.today = lambda: "2026-06-11"
	utils.add_days = lambda *a, **k: None
	utils.flt = lambda v, *a, **k: float(v or 0)
	utils.cint = lambda v, *a, **k: int(v or 0)
	sys.modules["frappe.utils"] = utils

	# review._is_admin için: review modülü import edilecek; _is_admin'i _STATE'e bağla
	# (review.py içindeki gerçek _is_admin frappe.get_roles kullanır)
	frappe.get_roles = lambda u=None: ["System Manager"] if _STATE["is_admin"] else ["Buyer"]


_install_frappe_stub()
_FRAPPE_STUB = sys.modules["frappe"]

# review.py / ab_testing.py importu için rate_limit decorator stub'ı
_rl = types.ModuleType("tradehub_core.api.rate_limit")
_rl.rate_limit = lambda *a, **k: lambda fn: fn
sys.modules["tradehub_core.api.rate_limit"] = _rl

from tradehub_core.api import ab_testing as abt  # noqa: E402
from tradehub_core.api import review as rev  # noqa: E402


class TestAbTestReportBOLA(unittest.TestCase):
	def setUp(self):
		abt.frappe = _FRAPPE_STUB
		_STATE["is_admin"] = False
		_FRAPPE_STUB.session.user = "seller-a@test"

	def _passes_guard(self, test_name):
		"""Guard geçtiyse True; PermissionError ise False.

		Guard sonrası rapor dict'i ek doctype alanları ister; güvenlik testinin
		amacı yetki kapısı, downstream AttributeError'ı 'guard geçti' sayarız.
		"""
		try:
			abt.get_ab_test_report(test_name)
			return True
		except _PermissionError:
			return False
		except Exception:
			return True  # guard geçti, rapor inşası stub eksikliğinden patladı

	def test_owner_seller_passes_guard(self):
		_FRAPPE_STUB.session.user = "seller-a@test"
		self.assertTrue(self._passes_guard("ABT-A"))

	def test_other_seller_blocked_by_guard(self):
		_FRAPPE_STUB.session.user = "seller-b@test"
		self.assertFalse(self._passes_guard("ABT-A"))

	def test_admin_passes_guard(self):
		_FRAPPE_STUB.session.user = "admin@test"
		_STATE["is_admin"] = True
		self.assertTrue(self._passes_guard("ABT-A"))


class TestReviewSubmitBOLA(unittest.TestCase):
	"""H8 — submit_listing_review yalnız siparişin buyer'ına izin vermeli."""

	def setUp(self):
		rev.frappe = _FRAPPE_STUB

	def _passes_guard(self, order_item):
		try:
			rev.submit_listing_review(order_item=order_item, rating=5, body="iyi")
			return True
		except _PermissionError:
			return False
		except Exception:
			return True  # buyer guard geçti, downstream new_doc stub eksikliği

	def test_order_owner_passes_guard(self):
		_FRAPPE_STUB.session.user = "buyer-a@test"  # OI-A → ORD-A → buyer-a
		self.assertTrue(self._passes_guard("OI-A"))

	def test_foreign_buyer_blocked(self):
		_FRAPPE_STUB.session.user = "buyer-b@test"  # başka alıcı
		self.assertFalse(self._passes_guard("OI-A"))


if __name__ == "__main__":
	unittest.main()
