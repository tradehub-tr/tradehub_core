"""C8 — Ödemesiz plan yükseltme güvenlik testi.

api/v1/subscription.upgrade_subscription_plan:
  - Mağaza sahibi start_trial=False (ücretli active) ile çağırırsa PermissionError
  - Mağaza sahibi start_trial=True (trial) ile çağırabilir
  - Platform admin ücretli aktivasyon yapabilir

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_subscription_upgrade_security
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


_STATE = {
	"user": "owner@test",
	"roles": {"Seller Owner"},
	"is_owner": 1,
	"tenant": "SELLER-A",
	"saved": [],  # save/insert çağrıları
	"existing_sub": None,  # None → yeni insert yolu; _Row → mevcut Store Subscription satırı
}


class _Row(SimpleNamespace):
	"""frappe.db.get_value(as_dict=True) dönüşünü taklit eder (attr + .get erişimi)."""

	def get(self, k, default=None):
		return getattr(self, k, default)


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: a[0] if (a and callable(a[0])) else (lambda fn: fn)
	frappe.session = SimpleNamespace(user=_STATE["user"])
	frappe.get_roles = lambda u=None: list(_STATE["roles"])
	frappe.log_error = lambda *a, **k: None

	def _get_value(doctype, name=None, fieldname=None, as_dict=False, **kw):
		if doctype == "User":
			return SimpleNamespace(tradehub_tenant=_STATE["tenant"], tradehub_is_owner=_STATE["is_owner"])
		if doctype == "Store Subscription":
			return _STATE["existing_sub"]  # None → yeni insert yolu
		return None

	def _exists(doctype, name=None):
		return True  # Admin Seller Profile + Subscription Plan var say

	class _Doc(SimpleNamespace):
		def get(self, k, default=None):
			return getattr(self, k, default)

		def save(self, *a, **k):
			_STATE["saved"].append(("save", getattr(self, "status", None)))

		def insert(self, *a, **k):
			_STATE["saved"].append(("insert", getattr(self, "status", None)))

	def _get_doc(doctype, name=None):
		if doctype == "Subscription Plan":
			return _Doc(is_active=1, trial_days=14, name=name)
		# Store Subscription doc
		d = _Doc(name=name, flags=SimpleNamespace())
		return d

	def _new_doc(doctype):
		return _Doc(flags=SimpleNamespace(), name="NEW-SUB-1")

	frappe.db = SimpleNamespace(
		get_value=_get_value, exists=_exists, commit=lambda: None, set_value=lambda *a, **k: None
	)
	frappe.get_doc = _get_doc
	frappe.new_doc = _new_doc
	frappe.cache = lambda: SimpleNamespace(delete_keys=lambda *a, **k: None)

	utils = types.ModuleType("frappe.utils")
	utils.add_days = lambda d, n: d
	utils.add_months = lambda d, n: d
	utils.add_years = lambda d, n: d
	utils.getdate = lambda d=None: d
	utils.get_datetime = lambda d=None: d
	utils.cint = lambda v: int(v or 0)
	utils.now_datetime = lambda: "2026-06-11"
	sys.modules["frappe.utils"] = utils

	audit = types.ModuleType("tradehub_core.audit")
	audit.log_decision = lambda *a, **k: "AUDIT-1"
	sys.modules["tradehub_core.audit"] = audit


_install_frappe_stub()

from tradehub_core.api.v1 import subscription as sub  # noqa: E402


class TestUpgradeGuard(unittest.TestCase):
	def setUp(self):
		_STATE["roles"] = {"Seller Owner"}
		_STATE["is_owner"] = 1
		_STATE["tenant"] = "SELLER-A"
		_STATE["saved"] = []
		_STATE["existing_sub"] = None

	def test_owner_paid_activation_rejected(self):
		# start_trial=False → ücretli active → reddedilmeli
		with self.assertRaises(_PermissionError):
			sub.upgrade_subscription_plan(new_plan="ENTERPRISE", start_trial=False)
		self.assertEqual(_STATE["saved"], [], "Reddedilmeden önce hiçbir kayıt yapılmamalı")

	def test_owner_trial_allowed(self):
		# start_trial=True → trial → izin verilmeli (insert status=trial)
		sub.upgrade_subscription_plan(new_plan="ENTERPRISE", start_trial=True)
		self.assertTrue(any(s[1] == "trial" for s in _STATE["saved"]), "Trial aktivasyonu yapılmalı")

	def test_owner_trial_used_start_trial_rejected(self):
		# K1 payment bypass — trial hakkı kullanılmış (trial_used=1) owner
		# start_trial=1 geçse bile "1 mağaza = 1 trial" düşürmesi nihai hedefi
		# 'active' yapar → guard nihai hedefe bakar → PermissionError, kayıt YOK.
		_STATE["existing_sub"] = _Row(
			name="SUB-1",
			plan="BASIC",
			status="expired",
			trial_used=1,
			billing_cycle="monthly",
			current_period_end=None,
		)
		with self.assertRaises(_PermissionError):
			sub.upgrade_subscription_plan(new_plan="ENTERPRISE", start_trial=1)
		self.assertEqual(_STATE["saved"], [], "Bypass reddedilmeli; abonelik DEĞİŞMEMELİ")

	def test_owner_trial_unused_start_trial_allowed(self):
		# trial_used=0 → mevcut davranış korunur: start_trial=1 trial başlatır.
		_STATE["existing_sub"] = _Row(
			name="SUB-1",
			plan="BASIC",
			status="expired",
			trial_used=0,
			billing_cycle="monthly",
			current_period_end=None,
		)
		sub.upgrade_subscription_plan(new_plan="ENTERPRISE", start_trial=1)
		self.assertTrue(any(s[1] == "trial" for s in _STATE["saved"]), "Trial başlatılabilmeli")

	def test_platform_admin_paid_activation_allowed(self):
		_STATE["roles"] = {"System Manager"}
		_STATE["is_owner"] = 0
		sub.upgrade_subscription_plan(new_plan="ENTERPRISE", tenant="SELLER-A", start_trial=False)
		self.assertTrue(
			any(s[1] == "active" for s in _STATE["saved"]), "Admin ücretli aktivasyon yapabilmeli"
		)

	def test_platform_admin_paid_activation_with_existing_sub_allowed(self):
		# confirm_subscription_payment yolu regresyonsuz: admin (only_for ile
		# System Manager/Marketplace Admin) mevcut trial_used=1 kaydı start_trial=0
		# ile ücretli 'active'e geçirebilmeli — guard nihai hedefe baksa da admin muaf.
		_STATE["roles"] = {"Marketplace Admin"}
		_STATE["is_owner"] = 0
		_STATE["existing_sub"] = _Row(
			name="SUB-1",
			plan="BASIC",
			status="past_due",
			trial_used=1,
			billing_cycle="monthly",
			current_period_end=None,
		)
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", start_trial=0)
		self.assertTrue(
			any(s[1] == "active" for s in _STATE["saved"]), "Admin mevcut kaydı aktive edebilmeli"
		)


if __name__ == "__main__":
	unittest.main()
