"""C5 — Mobil JWT secret fail-closed testi.

api/mobile_api._jwt_secret:
  - site secret varsa onu döner
  - hiçbir secret yoksa fail-closed (ValidationError) — hardcoded fallback YOK

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_mobile_jwt_secret
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


_CONF: dict = {}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.conf = SimpleNamespace(get=lambda k, default=None: _CONF.get(k, default))
	frappe.whitelist = lambda *a, **k: (a[0] if (a and callable(a[0])) else (lambda fn: fn))
	frappe.utils = types.ModuleType("frappe.utils")
	frappe.utils.add_to_date = lambda *a, **k: None
	frappe.utils.now_datetime = lambda: None
	sys.modules["frappe.utils"] = frappe.utils
	sys.modules["frappe"]._ = lambda s: s

	# rate_limit decorator stub
	rl = types.ModuleType("tradehub_core.api.rate_limit")
	rl.rate_limit = lambda *a, **k: (lambda fn: fn)
	sys.modules["tradehub_core.api.rate_limit"] = rl


_install_frappe_stub()

from tradehub_core.api import mobile_api  # noqa: E402


class TestJwtSecret(unittest.TestCase):
	def setUp(self):
		_CONF.clear()

	def test_returns_site_secret_when_present(self):
		_CONF["encryption_key"] = "site-specific-key-xyz"
		self.assertEqual(mobile_api._jwt_secret(), "site-specific-key-xyz")

	def test_prefers_dedicated_mobile_secret(self):
		_CONF["mobile_jwt_secret"] = "dedicated"
		_CONF["encryption_key"] = "fallback-site"
		self.assertEqual(mobile_api._jwt_secret(), "dedicated")

	def test_fail_closed_when_no_secret(self):
		# Hiçbir secret yoksa ValidationError — hardcoded string DÖNMEZ.
		with self.assertRaises(_ValidationError):
			mobile_api._jwt_secret()

	def test_no_hardcoded_fallback_string(self):
		# Eski güvenlik açığı: literal fallback hiçbir koşulda dönmemeli.
		try:
			val = mobile_api._jwt_secret()
		except _ValidationError:
			val = None
		self.assertNotEqual(val, "tradehub-mobile-jwt-fallback-secret")


if __name__ == "__main__":
	unittest.main()
