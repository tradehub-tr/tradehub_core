"""Faz 7 — Break-glass (acil süper-erişim) unit testleri.

frappe.cache + audit stub'lanır → gerçek Frappe gerektirmez; CI authz gate'inde koşar.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

_CACHE: dict = {}
_ROLES: dict = {}
_AUDIT: list = []


class _Cache:
	def get_value(self, k):
		return _CACHE.get(k)

	def set_value(self, k, v, expires_in_sec=None):
		_CACHE[k] = v

	def delete_value(self, k):
		_CACHE.pop(k, None)


def _install() -> None:
	f = sys.modules.get("frappe") or types.ModuleType("frappe")
	f.__path__ = []
	f.cache = lambda: _Cache()
	f.get_roles = lambda u: _ROLES.get(u, [])
	f.session = types.SimpleNamespace(user="admin@x")
	f._ = lambda s: s

	class PermissionError(Exception):
		pass

	f.PermissionError = PermissionError

	def _throw(msg, exc=Exception):
		raise exc(msg) if isinstance(exc, type) else Exception(msg)

	f.throw = _throw
	sys.modules["frappe"] = f

	audit = types.ModuleType("tradehub_core.audit")
	audit.__path__ = []
	logmod = types.ModuleType("tradehub_core.audit.log")
	logmod.log_decision = lambda **k: _AUDIT.append(k)
	audit.log = logmod
	sys.modules["tradehub_core.audit"] = audit
	sys.modules["tradehub_core.audit.log"] = logmod


_install()

from tradehub_core.authz import break_glass as bg  # noqa: E402


class BreakGlassTests(unittest.TestCase):
	def setUp(self):
		_CACHE.clear()
		_ROLES.clear()
		_AUDIT.clear()
		_install()

	def test_activate_requires_eligible_role(self):
		_ROLES["u@x"] = ["Buyer"]
		with self.assertRaises(Exception):
			bg.activate("u@x", reason="incident")

	def test_activate_requires_reason(self):
		_ROLES["adm@x"] = ["System Manager"]
		with self.assertRaises(Exception):
			bg.activate("adm@x", reason="  ")

	def test_activate_sets_session_and_high_audit(self):
		_ROLES["adm@x"] = ["Platform Admin"]
		r = bg.activate("adm@x", reason="prod incident", duration_minutes=15)
		self.assertEqual(r["minutes"], 15)
		self.assertTrue(bg.is_active("adm@x"))
		self.assertEqual(bg.reason_for("adm@x"), "prod incident")
		self.assertTrue(
			any(
				a.get("rule_id") == "break_glass.activate" and a.get("severity") == "HIGH"
				for a in _AUDIT
			)
		)

	def test_administrator_is_eligible(self):
		bg.activate("Administrator", reason="x")
		self.assertTrue(bg.is_active("Administrator"))

	def test_duration_capped_at_max(self):
		_ROLES["adm@x"] = ["System Manager"]
		r = bg.activate("adm@x", reason="x", duration_minutes=99999)
		self.assertEqual(r["minutes"], 240)

	def test_deactivate_clears_session(self):
		_ROLES["adm@x"] = ["System Manager"]
		bg.activate("adm@x", reason="x")
		bg.deactivate("adm@x")
		self.assertFalse(bg.is_active("adm@x"))

	def test_inactive_by_default(self):
		self.assertFalse(bg.is_active("nobody@x"))
		self.assertFalse(bg.is_active(None))


if __name__ == "__main__":
	unittest.main()
