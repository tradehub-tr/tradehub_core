"""Faz 5 — ReBAC enforce (union-grant) katmanı testleri.

`permissions._apply_rebac`'in davranışını doğrular:
  - shadow modda: RBAC kararı DEĞİŞMEZ (ReBAC grant verse bile).
  - enforce modda: RBAC ∪ ReBAC — RBAC deny + ReBAC grant → ALLOW (union, yalnız
    genişletir); RBAC allow → allow (ReBAC'a gerek yok); RBAC deny + ReBAC deny/None
    → deny.
  - fail-safe: herhangi bir hata → RBAC kararı geçerli (lock-out yok).

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_rebac_enforce
"""

from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe
	frappe.db = SimpleNamespace(
		get_value=lambda *a, **kw: None,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		has_column=lambda *a, **kw: False,
	)
	frappe.session = SimpleNamespace(user="Guest")
	frappe.local = SimpleNamespace()
	frappe.get_roles = lambda u: []
	frappe.get_all = lambda *a, **kw: []
	frappe.cache = lambda: SimpleNamespace(
		get_value=lambda k: None, set_value=lambda *a, **kw: None, delete_value=lambda k: None
	)
	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None
	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class _PE(Exception):
			pass

		frappe.PermissionError = _PE
	futils = sys.modules.get("frappe.utils")
	if futils is None:
		futils = types.ModuleType("frappe.utils")
		sys.modules["frappe.utils"] = futils
	futils.flt = lambda v, precision=None: float(v or 0)
	frappe.utils = futils


_install_frappe_stub()

from tradehub_core import permissions  # noqa: E402

_IS_ENF = "tradehub_core.authz.enforcement.is_enforced"
_DECIDE = "tradehub_core.authz.pdp._rebac_decide"


class RebacEnforceTests(unittest.TestCase):
	def setUp(self):
		# F6 request-scoped memo frappe.local'da tutulur; production'da istek-başına
		# temizlenir ama testler frappe.local'ı paylaşır → her testte sıfırla.
		import frappe

		frappe.local._rebac_enforce_memo = {}

	def _apply(self, rbac_result, enforced, rebac_decision):
		doc = SimpleNamespace(name="ORD-1")
		with patch(_IS_ENF, return_value=enforced), patch(_DECIDE, return_value=rebac_decision):
			return permissions._apply_rebac(doc, "read", "u@x", "Order", rbac_result)

	def test_shadow_never_changes_decision(self):
		# Enforce KAPALI → ReBAC grant verse bile RBAC kararı geçerli.
		self.assertTrue(self._apply(True, False, False))
		self.assertFalse(self._apply(False, False, True))

	def test_enforce_rbac_allow_stays_allow(self):
		# RBAC allow → allow (ReBAC değerlendirilmez).
		self.assertTrue(self._apply(True, True, None))

	def test_enforce_union_grant(self):
		# RBAC deny + ReBAC grant + enforce → union ile ALLOW.
		self.assertTrue(self._apply(False, True, True))

	def test_enforce_rebac_deny_stays_deny(self):
		# RBAC deny + ReBAC deny/None → deny (union genişletmez).
		self.assertFalse(self._apply(False, True, False))
		self.assertFalse(self._apply(False, True, None))

	def test_failsafe_on_error_keeps_rbac(self):
		# is_enforced patlarsa → RBAC kararı korunur (fail-safe, lock-out yok).
		doc = SimpleNamespace(name="ORD-1")
		with patch(_IS_ENF, side_effect=RuntimeError("boom")):
			self.assertFalse(permissions._apply_rebac(doc, "read", "u", "Order", False))
			self.assertTrue(permissions._apply_rebac(doc, "read", "u", "Order", True))

	def test_abac_deny_not_overridden_by_union(self):
		"""GÜVENLİK: ABAC regülatif deny (suspended sub/KYC/AML) ReBAC union ile
		AŞILAMAZ — ReBAC grant verse bile ABAC-deny'li istek reddedilir."""
		doc = SimpleNamespace(name="ORD-1")
		with patch(_IS_ENF, return_value=True), patch(_DECIDE, return_value=True), patch.object(
			permissions, "_abac_deny", return_value=True
		):
			# rbac_result=False (ABAC-deny), ReBAC grant → yine de DENY kalmalı.
			self.assertFalse(permissions._apply_rebac(doc, "write", "u@x", "Order", False))

	def test_no_abac_deny_allows_union(self):
		"""ABAC engel yoksa union normal çalışır (regresyon koruması)."""
		doc = SimpleNamespace(name="ORD-1")
		with patch(_IS_ENF, return_value=True), patch(_DECIDE, return_value=True), patch.object(
			permissions, "_abac_deny", return_value=False
		):
			self.assertTrue(permissions._apply_rebac(doc, "read", "u@x", "Order", False))

	def test_no_name_returns_rbac(self):
		# name yoksa (doctype-seviyesi) ReBAC atlanır.
		doc = SimpleNamespace(name=None)
		with patch(_IS_ENF, return_value=True), patch(_DECIDE, return_value=True):
			self.assertFalse(permissions._apply_rebac(doc, "read", "u", "Order", False))


if __name__ == "__main__":
	unittest.main()
