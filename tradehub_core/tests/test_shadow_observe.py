"""Faz 5 — ReBAC shadow gözlem (authz/shadow.py) testleri.

Doğrular:
  - `rebac_shadow_observe` KAPALI iken TAM no-op (rebac reconcile çağrılmaz).
  - Flag AÇIK + name varken pdp._rebac_reconcile doğru argümanlarla çağrılır.
  - name None / doctype boş → no-op.
  - reconcile exception fırlatsa bile observe ASLA fırlatmaz (fail-safe).
  - Örnekleme (rebac_shadow_sample) devreye girer.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_shadow_observe
"""

from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _install_frappe_stub(conf: dict | None = None) -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe
	frappe.conf = SimpleNamespace(get=lambda k, d=None: (conf or {}).get(k, d))
	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None


_install_frappe_stub()

from tradehub_core.authz import shadow  # noqa: E402


class ShadowObserveTests(unittest.TestCase):
	def test_flag_off_is_noop(self):
		_install_frappe_stub({})  # flag yok → kapalı
		with patch("tradehub_core.authz.pdp._rebac_reconcile") as mock_rec:
			shadow.observe("u@x", "Listing", "LST-1", "read", True)
			mock_rec.assert_not_called()

	def test_flag_on_calls_reconcile(self):
		_install_frappe_stub({"rebac_shadow_observe": True})
		with patch("tradehub_core.authz.pdp._rebac_reconcile") as mock_rec:
			shadow.observe("u@x", "Listing", "LST-1", "read", True)
			mock_rec.assert_called_once()
			args = mock_rec.call_args[0]
			# (principal, verb, doctype, name, rbac_allow, ctx)
			self.assertEqual(args[0], "u@x")
			self.assertEqual(args[1], "read")
			self.assertEqual(args[2], "Listing")
			self.assertEqual(args[3], "LST-1")
			self.assertIs(args[4], True)

	def test_no_name_is_noop(self):
		_install_frappe_stub({"rebac_shadow_observe": True})
		with patch("tradehub_core.authz.pdp._rebac_reconcile") as mock_rec:
			shadow.observe("u@x", "Listing", None, "read", True)
			mock_rec.assert_not_called()

	def test_reconcile_exception_is_swallowed(self):
		_install_frappe_stub({"rebac_shadow_observe": True})
		with patch(
			"tradehub_core.authz.pdp._rebac_reconcile", side_effect=RuntimeError("boom")
		):
			# fail-safe: observe hiçbir şekilde fırlatmamalı
			try:
				shadow.observe("u@x", "Order", "ORD-1", "read", False)
			except Exception as e:  # noqa: BLE001
				self.fail(f"observe fırlattı (fail-safe ihlali): {e}")

	def test_sampling_skips(self):
		# sample=1000 + randint hep 2 → örnekleme dışı → reconcile çağrılmaz.
		_install_frappe_stub({"rebac_shadow_observe": True, "rebac_shadow_sample": 1000})
		with patch("tradehub_core.authz.shadow.random.randint", return_value=2), patch(
			"tradehub_core.authz.pdp._rebac_reconcile"
		) as mock_rec:
			shadow.observe("u@x", "Listing", "LST-1", "read", True)
			mock_rec.assert_not_called()

	def test_sampling_hits(self):
		# sample=1000 + randint=1 → örnekleme içinde → reconcile çağrılır.
		_install_frappe_stub({"rebac_shadow_observe": True, "rebac_shadow_sample": 1000})
		with patch("tradehub_core.authz.shadow.random.randint", return_value=1), patch(
			"tradehub_core.authz.pdp._rebac_reconcile"
		) as mock_rec:
			shadow.observe("u@x", "Listing", "LST-1", "read", True)
			mock_rec.assert_called_once()


if __name__ == "__main__":
	unittest.main()
