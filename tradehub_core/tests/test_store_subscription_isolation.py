"""H14 — Store Subscription permission_query_conditions + has_permission testi.

permissions.store_subscription_query_conditions / store_subscription_has_permission:
  - Guest → 1=0
  - Admin → "" (tüm) / has_permission True
  - Seller → kendi store filtresi; başka store reddi; yazma admin-only

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_store_subscription_isolation
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

_STATE = {"full_access": set(), "seller_profile": {}}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe._ = lambda s: s
	frappe.db = SimpleNamespace(escape=lambda s: "'" + str(s).replace("'", "''") + "'")
	frappe.session = SimpleNamespace(user="x")
	frappe.get_roles = lambda u=None: []

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v, *a, **k: float(v or 0)
	utils.cint = lambda v, *a, **k: int(v or 0)
	utils.now_datetime = lambda: None
	utils.getdate = lambda *a, **k: None
	sys.modules["frappe.utils"] = utils


_install_frappe_stub()
_FRAPPE_STUB = sys.modules["frappe"]

# İzolasyon: başka bir test `tradehub_core.utils.tenant`'ı eksik stub'lamış olabilir
# (_has_tenant_field yok). Gerçek modüller minimal frappe stub'ı altında import edilir.
for _m in ("tradehub_core.permissions", "tradehub_core.utils.tenant", "tradehub_core.utils"):
	sys.modules.pop(_m, None)

from tradehub_core import permissions as perm  # noqa: E402


class TestStoreSubscriptionIsolation(unittest.TestCase):
	def setUp(self):
		perm.frappe = _FRAPPE_STUB
		# Yardımcıları test kontrolüne bağla
		perm._is_platform_full_access = lambda user: user in _STATE["full_access"]
		perm._get_seller_profile_name = lambda user: _STATE["seller_profile"].get(user)
		perm._doc_field = lambda doc, f: getattr(doc, f, None)
		_STATE["full_access"] = set()
		_STATE["seller_profile"] = {"seller-a@test": "SELLER-A", "seller-b@test": "SELLER-B"}

	# --- query conditions ---
	def test_guest_blocked(self):
		self.assertEqual(perm.store_subscription_query_conditions("Guest"), "1=0")

	def test_admin_sees_all(self):
		_STATE["full_access"] = {"admin@test"}
		self.assertEqual(perm.store_subscription_query_conditions("admin@test"), "")

	def test_seller_scoped_to_own_store(self):
		cond = perm.store_subscription_query_conditions("seller-a@test")
		self.assertIn("SELLER-A", cond)
		self.assertIn("`tabStore Subscription`.`store`", cond)

	def test_user_without_store_blocked(self):
		self.assertEqual(perm.store_subscription_query_conditions("nobody@test"), "1=0")

	# --- has_permission ---
	def test_seller_can_read_own(self):
		doc = SimpleNamespace(store="SELLER-A")
		self.assertTrue(perm.store_subscription_has_permission(doc, "read", "seller-a@test"))

	def test_seller_cannot_read_other(self):
		doc = SimpleNamespace(store="SELLER-B")
		self.assertFalse(perm.store_subscription_has_permission(doc, "read", "seller-a@test"))

	def test_seller_cannot_write_even_own(self):
		doc = SimpleNamespace(store="SELLER-A")
		self.assertFalse(perm.store_subscription_has_permission(doc, "write", "seller-a@test"))

	def test_admin_can_write(self):
		_STATE["full_access"] = {"admin@test"}
		doc = SimpleNamespace(store="SELLER-A")
		self.assertTrue(perm.store_subscription_has_permission(doc, "write", "admin@test"))


if __name__ == "__main__":
	unittest.main()
