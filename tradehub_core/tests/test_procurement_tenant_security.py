"""C3 — Procurement tenant izolasyonu güvenlik testleri.

api/v1/procurement._resolve_tenant_arg davranışını doğrular:
  - Normal user kendi tenant'ını alır
  - Normal user başka tenant verirse PermissionError
  - Super admin verilen tenant'ı seçebilir

Saf-Python unittest; Frappe runtime stub'lanır:

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_procurement_tenant_security
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


class _ValidationError(Exception):
	pass


# Mutable test state: roller ve kullanıcının tenant'ı
_STATE = {"roles": set(), "own_tenant": "SELLER-A"}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe._ = lambda s: s

	def _whitelist(*dargs, **dkw):
		def deco(fn):
			return fn

		# @frappe.whitelist()  → deco; @frappe.whitelist (çıplak) → fn
		if dargs and callable(dargs[0]):
			return dargs[0]
		return deco

	frappe.whitelist = _whitelist
	frappe.session = SimpleNamespace(user="u@test")
	frappe.get_roles = lambda u=None: list(_STATE["roles"])
	frappe.db = SimpleNamespace(get_value=lambda *a, **k: None, commit=lambda: None)
	sys.modules["frappe"]._ = lambda s: s

	# tradehub_core.services.* ve utils.tenant importları için hafif stub'lar
	for mod in (
		"tradehub_core.services.cost_center",
		"tradehub_core.services.supplier_whitelist",
	):
		m = types.ModuleType(mod)
		sys.modules[mod] = m

	tenant_mod = types.ModuleType("tradehub_core.utils.tenant")
	tenant_mod._get_seller_profile_for_user = lambda user: _STATE["own_tenant"]
	sys.modules["tradehub_core.utils.tenant"] = tenant_mod


_install_frappe_stub()

from tradehub_core.api.v1 import procurement as proc  # noqa: E402


class TestResolveTenantArg(unittest.TestCase):
	def setUp(self):
		_STATE["roles"] = {"Buyer"}
		_STATE["own_tenant"] = "SELLER-A"

	def test_normal_user_gets_own_tenant_when_none(self):
		self.assertEqual(proc._resolve_tenant_arg(None), "SELLER-A")

	def test_normal_user_own_tenant_explicit_ok(self):
		self.assertEqual(proc._resolve_tenant_arg("SELLER-A"), "SELLER-A")

	def test_normal_user_foreign_tenant_rejected(self):
		with self.assertRaises(_PermissionError):
			proc._resolve_tenant_arg("SELLER-B")

	def test_super_admin_can_select_tenant(self):
		_STATE["roles"] = {"System Manager"}
		self.assertEqual(proc._resolve_tenant_arg("SELLER-B"), "SELLER-B")

	def test_super_admin_none_means_all(self):
		_STATE["roles"] = {"System Manager"}
		self.assertIsNone(proc._resolve_tenant_arg(None))


if __name__ == "__main__":
	unittest.main()
