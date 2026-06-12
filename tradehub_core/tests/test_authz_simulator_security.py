"""H5 — Authorization Simulator admin-only testi.

api/v1/authorization_simulator.simulate / simulate_batch yalnız platform admin.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_authz_simulator_security
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


_STATE = {"roles": set()}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: (a[0] if (a and callable(a[0])) else (lambda fn: fn))
	frappe.session = SimpleNamespace(user="u@test")
	frappe.get_roles = lambda u=None: list(_STATE["roles"])

	sim = types.ModuleType("tradehub_core.services.authorization_simulator")
	sim.simulate = lambda **kw: {"decision": "ALLOW"}
	sim.simulate_batch = lambda **kw: [{"decision": "ALLOW"}]
	sys.modules["tradehub_core.services.authorization_simulator"] = sim


_install_frappe_stub()
_FRAPPE_STUB = sys.modules["frappe"]

from tradehub_core.api.v1 import authorization_simulator as asim  # noqa: E402


class TestSimulatorAuth(unittest.TestCase):
	def setUp(self):
		asim.frappe = _FRAPPE_STUB

	def test_non_admin_cannot_simulate(self):
		_STATE["roles"] = {"Buyer", "Seller"}
		with self.assertRaises(_PermissionError):
			asim.simulate(actor="admin@test", action="read", resource_type="User Profile")

	def test_admin_can_simulate(self):
		_STATE["roles"] = {"System Manager"}
		out = asim.simulate(actor="x@test", action="read", resource_type="User Profile")
		self.assertEqual(out["decision"], "ALLOW")

	def test_non_admin_cannot_batch(self):
		_STATE["roles"] = {"Seller"}
		with self.assertRaises(_PermissionError):
			asim.simulate_batch(actor="a@test", action="read", resource_type="Order", resource_names=["O1"])


if __name__ == "__main__":
	unittest.main()
