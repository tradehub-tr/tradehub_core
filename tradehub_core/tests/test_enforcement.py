"""Faz 5 — ReBAC enforcement config (mode + kill-switch) unit testleri.

frappe.conf stub'lanır → gerçek Frappe gerektirmez; CI authz gate'inde koşar.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


def _install(conf: dict) -> None:
	f = sys.modules.get("frappe") or types.ModuleType("frappe")
	f.conf = types.SimpleNamespace(get=lambda k, d=None: conf.get(k, d))
	sys.modules["frappe"] = f


_install({})

from tradehub_core.authz import enforcement  # noqa: E402


class EnforcementModeTests(unittest.TestCase):
	def test_default_is_shadow(self):
		_install({})
		self.assertEqual(enforcement.enforcement_mode("Order"), "shadow")
		self.assertFalse(enforcement.is_enforced("Order"))

	def test_enforce_configured_per_doctype(self):
		_install({"rebac_enforcement": {"Order": "enforce"}})
		self.assertTrue(enforcement.is_enforced("Order"))
		self.assertFalse(enforcement.is_enforced("Listing"))  # konfigüre değil → shadow

	def test_kill_switch_overrides_enforce(self):
		_install({"rebac_enforcement": {"Order": "enforce"}, "rebac_kill_switch": True})
		self.assertTrue(enforcement.kill_switch_on())
		self.assertFalse(enforcement.is_enforced("Order"))  # kill-switch → shadow

	def test_invalid_mode_falls_to_shadow(self):
		_install({"rebac_enforcement": {"Order": "bogus"}})
		self.assertEqual(enforcement.enforcement_mode("Order"), "shadow")

	def test_none_doctype_is_shadow(self):
		_install({"rebac_enforcement": {"Order": "enforce"}})
		self.assertEqual(enforcement.enforcement_mode(None), "shadow")

	def test_conf_read_error_fails_safe_shadow(self):
		# frappe.conf.get patlarsa → enforce ETME (shadow), kill_switch → True (güvenli)
		f = sys.modules["frappe"]

		def _boom(*a, **k):
			raise RuntimeError("conf yok")

		f.conf = types.SimpleNamespace(get=_boom)
		self.assertTrue(enforcement.kill_switch_on())  # okunamıyorsa güvenli taraf
		self.assertEqual(enforcement.enforcement_mode("Order"), "shadow")


if __name__ == "__main__":
	unittest.main()
