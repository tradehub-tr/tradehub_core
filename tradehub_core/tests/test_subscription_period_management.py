"""BE-3 — Dönem yönetimi + R2/R5 guard testleri.

api/v1/subscription.upgrade_subscription_plan:
  - AC-7: status='active' geçişinde current_period_end = start + 1 ay (monthly)
    / 1 yıl (yearly), next_invoice_date set, billing_cycle yazılır,
    cancel_at_period_end sıfırlanır.
  - billing_cycle geriye-uyumlu: verilmezse mevcut kayıt > 'monthly' fallback.
  - Trial başlatmada dönem alanları YAZILMAZ (trial_end yönetir).
  - R2: 'canceled' mağaza Admin Seller Profile Suspended VEYA owner User
    disabled iken self-servis reaktive EDİLEMEZ (417) — AC-14 negatif vakası.

api/v1/subscription_payment:
  - confirm_subscription_payment ödemenin billing_cycle'ını aktivasyona geçirir.
  - R5: Suspended mağaza create_bank_transfer_request açamaz (417) — AC-13.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_subscription_period_management
"""

from __future__ import annotations

import calendar
import sys
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _PermissionError(Exception):
	pass


class _ValidationError(Exception):
	pass


_NOW = datetime(2026, 9, 8, 12, 0, 0)


def _add_months(d: datetime, n: int) -> datetime:
	month = d.month - 1 + n
	year = d.year + month // 12
	month = month % 12 + 1
	day = min(d.day, calendar.monthrange(year, month)[1])
	return d.replace(year=year, month=month, day=day)


_STATE: dict = {}


def _reset_state() -> None:
	_STATE.update(
		{
			"user": "owner@test",
			"roles": {"System Manager"},
			"is_owner": 0,
			"tenant": "SELLER-A",
			# Mevcut Store Subscription satırı (dict) veya None
			"existing_sub": None,
			"profile": {"status": "Active", "user": "owner@test"},
			"user_enabled": 1,
			"pending_payment_name": None,
			"payment_docs": {},
			"saved": [],  # (op, doctype, status)
			"last_sub_doc": None,
		}
	)


class _NSDict(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)


class _Doc(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)

	def save(self, *a, **k):
		_STATE["saved"].append(("save", getattr(self, "_doctype", "?"), getattr(self, "status", None)))

	def insert(self, *a, **k):
		_STATE["saved"].append(("insert", getattr(self, "_doctype", "?"), getattr(self, "status", None)))


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
	frappe.session = SimpleNamespace(user="owner@test")
	frappe.get_roles = lambda u=None: list(_STATE["roles"])
	frappe.log_error = lambda *a, **k: None
	frappe.get_all = lambda *a, **k: []

	def _only_for(roles, *a, **k):
		allowed = {roles} if isinstance(roles, str) else set(roles)
		if not allowed & _STATE["roles"]:
			raise _PermissionError("only_for")

	frappe.only_for = _only_for

	def _get_value(doctype, name=None, fieldname=None, as_dict=False, **kw):
		if doctype == "User":
			if fieldname == "enabled":
				return _STATE["user_enabled"]
			if fieldname == "tradehub_tenant":
				return _STATE["tenant"]
			return _NSDict(tradehub_tenant=_STATE["tenant"], tradehub_is_owner=_STATE["is_owner"])
		if doctype == "Store Subscription":
			sub = _STATE["existing_sub"]
			return _NSDict(**sub) if sub else None
		if doctype == "Admin Seller Profile":
			profile = _STATE["profile"]
			if fieldname == "status":
				return profile["status"]
			if fieldname == "user":
				return profile["user"]
			return _NSDict(**profile)
		if doctype == "Subscription Payment":
			return _STATE["pending_payment_name"]
		return None

	frappe.db = SimpleNamespace(
		get_value=_get_value,
		exists=lambda *a, **k: True,
		commit=lambda: None,
		set_value=lambda *a, **k: None,
	)

	def _get_doc(doctype, name=None):
		if doctype == "Subscription Plan":
			return _Doc(
				_doctype=doctype,
				name=name,
				is_active=1,
				trial_days=14,
				monthly_price=100.0,
				yearly_price=1000.0,
				currency="EUR",
			)
		if doctype == "Subscription Payment":
			return _STATE["payment_docs"][name]
		d = _Doc(_doctype=doctype, name=name, flags=SimpleNamespace())
		if doctype == "Store Subscription":
			_STATE["last_sub_doc"] = d
		return d

	def _new_doc(doctype):
		d = _Doc(_doctype=doctype, name=f"NEW-{doctype[:5].upper()}-1", flags=SimpleNamespace())
		if doctype == "Store Subscription":
			_STATE["last_sub_doc"] = d
		if doctype == "Subscription Payment":
			d.reference_code = "REF-NEW-1"
		return d

	frappe.get_doc = _get_doc
	frappe.new_doc = _new_doc
	frappe.get_cached_doc = lambda doctype, name=None: _Doc(_doctype=doctype)
	frappe.cache = lambda: SimpleNamespace(delete_keys=lambda *a, **k: None)

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: _NOW
	utils.add_days = lambda d, n: d + timedelta(days=n)
	utils.add_months = _add_months
	utils.add_years = lambda d, n: _add_months(d, 12 * n)
	utils.getdate = lambda d=None: d.date() if isinstance(d, datetime) else d
	utils.cint = lambda v: int(v or 0)
	sys.modules["frappe.utils"] = utils

	audit = types.ModuleType("tradehub_core.audit")
	audit.log_decision = lambda *a, **k: "AUDIT-1"
	sys.modules["tradehub_core.audit"] = audit

	notify_mod = types.ModuleType("tradehub_core.utils.notify")
	notify_mod.notify = lambda *a, **k: None
	sys.modules["tradehub_core.utils.notify"] = notify_mod


_install_frappe_stub()

from tradehub_core.api.v1 import subscription as sub  # noqa: E402
from tradehub_core.api.v1 import subscription_payment as sub_pay  # noqa: E402


def _as_admin() -> None:
	_STATE["roles"] = {"System Manager"}
	_STATE["is_owner"] = 0


def _as_owner() -> None:
	_STATE["roles"] = {"Seller Owner"}
	_STATE["is_owner"] = 1


class TestPeriodFields(unittest.TestCase):
	"""AC-7 — active geçişinde dönem alanları."""

	def setUp(self):
		_reset_state()
		_as_admin()

	def test_monthly_period(self):
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.current_period_start, _NOW)
		self.assertEqual(doc.current_period_end, _add_months(_NOW, 1))
		self.assertEqual(doc.next_invoice_date, _add_months(_NOW, 1).date())
		self.assertEqual(doc.billing_cycle, "monthly")
		self.assertEqual(doc.cancel_at_period_end, 0)

	def test_yearly_period(self):
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="yearly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.current_period_end, _add_months(_NOW, 12))
		self.assertEqual(doc.next_invoice_date, date(2027, 9, 8))
		self.assertEqual(doc.billing_cycle, "yearly")

	def test_invalid_cycle_rejected(self):
		with self.assertRaises(_ValidationError):
			sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="weekly")
		self.assertEqual(_STATE["saved"], [], "Reddedilmeden önce hiçbir kayıt yapılmamalı")

	def test_default_cycle_falls_back_to_existing_record(self):
		# billing_cycle verilmezse mevcut kaydın cycle'ı kullanılır (geriye uyum).
		_STATE["existing_sub"] = {
			"name": "STSUB-1",
			"plan": "PRO",
			"status": "past_due",
			"trial_used": 1,
			"billing_cycle": "yearly",
		}
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.billing_cycle, "yearly")
		self.assertEqual(doc.current_period_end, _add_months(_NOW, 12))

	def test_trial_does_not_write_period_fields(self):
		_as_owner()
		sub.upgrade_subscription_plan(new_plan="PRO", start_trial=True)
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.status, "trial")
		self.assertIsNone(doc.get("current_period_start"), "Trial'da dönem başlangıcı yazılmamalı")
		self.assertIsNone(doc.get("current_period_end"), "Trial'da dönem sonu yazılmamalı")
		self.assertIsNone(doc.get("next_invoice_date"), "Trial'da fatura tarihi yazılmamalı")
		self.assertIsNotNone(doc.get("trial_end"))


class TestReactivationGuard(unittest.TestCase):
	"""R2 — canceled→active reaktivasyon guard'ı (AC-14 + negatif vaka)."""

	def setUp(self):
		_reset_state()
		_as_admin()
		_STATE["existing_sub"] = {
			"name": "STSUB-1",
			"plan": "PRO",
			"status": "canceled",
			"trial_used": 1,
			"billing_cycle": "monthly",
		}

	def test_reactivation_succeeds_when_store_healthy(self):
		# Profil Active + owner enabled → AYNI satır 'active' olur (AC-14).
		out = sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(out["status"], "active")
		self.assertEqual(doc.status, "active")
		self.assertEqual(doc.cancel_at_period_end, 0, "Eski iptal planı reaktivasyona taşınmamalı")
		self.assertEqual(doc.current_period_end, _add_months(_NOW, 1))
		self.assertTrue(any(s[0] == "save" for s in _STATE["saved"]), "Mevcut satır save edilmeli")

	def test_suspended_store_cannot_reactivate(self):
		_STATE["profile"]["status"] = "Suspended"
		with self.assertRaises(_ValidationError):
			sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		self.assertEqual(_STATE["saved"], [], "Guard save'den ÖNCE durdurmalı")

	def test_disabled_owner_cannot_reactivate(self):
		_STATE["user_enabled"] = 0
		with self.assertRaises(_ValidationError):
			sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		self.assertEqual(_STATE["saved"], [])

	def test_guard_only_applies_to_canceled(self):
		# past_due → active geçişi Suspended kontrolüne takılmaz (R2 kapsamı dar).
		_STATE["existing_sub"]["status"] = "past_due"
		_STATE["profile"]["status"] = "Suspended"
		out = sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		self.assertEqual(out["status"], "active")


class TestBankTransferGuardAndConfirm(unittest.TestCase):
	"""R5 — Suspended mağaza havale talebi + confirm'in billing_cycle geçişi."""

	def setUp(self):
		_reset_state()
		_as_owner()

	def test_suspended_store_cannot_create_transfer_request(self):
		_STATE["profile"]["status"] = "Suspended"
		with self.assertRaises(_ValidationError):
			sub_pay.create_bank_transfer_request(plan="PRO", billing_cycle="monthly")
		self.assertEqual(_STATE["saved"], [], "Guard hiçbir kayıt yaratmadan durdurmalı")

	def test_active_store_can_create_transfer_request(self):
		out = sub_pay.create_bank_transfer_request(plan="PRO", billing_cycle="monthly")
		self.assertEqual(out["status"], "pending")
		self.assertEqual(out["billing_cycle"], "monthly")
		self.assertTrue(any(s[:2] == ("insert", "Subscription Payment") for s in _STATE["saved"]))

	def test_confirm_passes_billing_cycle_to_activation(self):
		_as_admin()
		_STATE["payment_docs"]["PAY-1"] = _Doc(
			_doctype="Subscription Payment",
			name="PAY-1",
			status="pending",
			plan="PRO",
			store="SELLER-A",
			billing_cycle="monthly",
			reference_code="REF-1",
			flags=SimpleNamespace(),
		)
		sub_pay.confirm_subscription_payment(payment="PAY-1")
		doc = _STATE["last_sub_doc"]
		self.assertIsNotNone(doc, "Aktivasyon Store Subscription yazmalı")
		self.assertEqual(doc.status, "active")
		self.assertEqual(doc.billing_cycle, "monthly", "Ödemenin cycle'ı aktivasyona taşınmalı (AC-7)")
		self.assertEqual(doc.current_period_end, _add_months(_NOW, 1))


if __name__ == "__main__":
	unittest.main()
