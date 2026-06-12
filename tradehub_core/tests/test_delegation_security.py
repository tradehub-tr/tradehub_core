"""C2 — Delegation privilege escalation güvenlik testleri.

services.delegation_service içindeki power-role blocklist'ini doğrular:
  - _assert_role_delegatable power-role'leri reddeder
  - create_delegation System Manager için PermissionError fırlatır
  - _assign_role power-role'ü her yolda reddeder (son savunma)

Saf-Python unittest; Frappe runtime stub'lanır:

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_delegation_security
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _PermissionError(Exception):
	pass


class _ValidationError(Exception):
	pass


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe

	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.session = SimpleNamespace(user="seller-owner@test")
	frappe.db = SimpleNamespace(commit=lambda: None, get_value=lambda *a, **k: None)
	frappe.log_error = lambda *a, **k: None

	# frappe import edilen alt modüller
	frappe_module = types.ModuleType("frappe")  # noqa: F841
	# `from frappe import _`
	sys.modules["frappe"]._ = lambda s: s

	# frappe.utils.now_datetime
	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: datetime(2026, 6, 11, 12, 0, 0)
	sys.modules["frappe.utils"] = utils


_install_frappe_stub()

# `from frappe import _` deseni için
import frappe  # noqa: E402

frappe._ = lambda s: s
sys.modules["frappe"]._ = lambda s: s

from tradehub_core.services import delegation_service as ds  # noqa: E402


class TestDelegationRoleBlocklist(unittest.TestCase):
	def test_power_role_rejected_by_guard(self):
		for role in ("System Manager", "Administrator", "Marketplace Admin", "All"):
			with self.assertRaises(_PermissionError, msg=f"{role} reddedilmeliydi"):
				ds._assert_role_delegatable(role)

	def test_normal_role_allowed_by_guard(self):
		# Hata fırlatmamalı
		ds._assert_role_delegatable("Buyer")
		ds._assert_role_delegatable("Seller Staff")

	def test_create_delegation_rejects_power_role(self):
		start = datetime(2026, 6, 11, 12, 0, 0)
		end = start + timedelta(hours=2)
		with self.assertRaises(_PermissionError):
			ds.create_delegation(
				delegator="a@test",
				delegate="b@test",
				role="System Manager",
				tenant=None,
				starts_at=start,
				ends_at=end,
			)

	def test_assign_role_blocks_power_role_last_line(self):
		# _assign_role doğrudan çağrılsa bile power-role reddedilmeli (son savunma).
		with self.assertRaises(_PermissionError):
			ds._assign_role("victim@test", "System Manager")


if __name__ == "__main__":
	unittest.main()
