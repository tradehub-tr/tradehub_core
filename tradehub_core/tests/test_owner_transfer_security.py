"""H4 — Owner Transfer reject yetki testi.

services.owner_transfer.reject:
  - İlgisiz kullanıcı reddedemez (PermissionError)
  - current_owner / proposed_owner / admin reddedebilir

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_owner_transfer_security
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


_STATE = {"user": "stranger@test", "roles": set()}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.session = SimpleNamespace(user=_STATE["user"])
	frappe.get_roles = lambda u=None: list(_STATE["roles"])
	frappe.log_error = lambda *a, **k: None

	class _Doc(SimpleNamespace):
		def save(self, *a, **k):
			_STATE["saved"] = True

	def _get_doc(doctype, name=None):
		return _Doc(
			name=name,
			status="awaiting_owner_confirm",
			current_owner="owner@test",
			proposed_owner="newowner@test",
			rejection_reason="",
		)

	frappe.get_doc = _get_doc
	frappe.db = SimpleNamespace(commit=lambda: None)

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: "2026-06-11"
	sys.modules["frappe.utils"] = utils


_install_frappe_stub()
_FRAPPE_STUB = sys.modules["frappe"]

from tradehub_core.services import owner_transfer as ot  # noqa: E402


class TestRejectAuth(unittest.TestCase):
	def setUp(self):
		ot.frappe = _FRAPPE_STUB
		_STATE["saved"] = False
		# _audit içindeki audit importunu no-op'la
		ot._audit = lambda *a, **k: None

	def _set_user(self, user, roles=()):
		_STATE["user"] = user
		_STATE["roles"] = set(roles)
		ot.frappe.session.user = user

	def test_stranger_cannot_reject(self):
		self._set_user("stranger@test", roles=["Buyer"])
		with self.assertRaises(_PermissionError):
			ot.reject("OTR-1", "no")
		self.assertFalse(_STATE["saved"], "Reddedilmeden önce kayıt olmamalı")

	def test_proposed_owner_can_reject(self):
		self._set_user("newowner@test", roles=["Seller"])
		ot.reject("OTR-1", "vazgeçtim")
		self.assertTrue(_STATE["saved"])

	def test_current_owner_can_reject(self):
		self._set_user("owner@test", roles=["Seller Owner"])
		ot.reject("OTR-1", "iptal")
		self.assertTrue(_STATE["saved"])

	def test_admin_can_reject(self):
		self._set_user("admin@test", roles=["System Manager"])
		ot.reject("OTR-1", "admin")
		self.assertTrue(_STATE["saved"])


if __name__ == "__main__":
	unittest.main()
