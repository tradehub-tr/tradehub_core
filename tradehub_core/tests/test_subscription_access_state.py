"""BE-4 — get_seller_access_state dunning additive genişletme testleri.

api/v1/subscription.get_seller_access_state:
  - AC-1: status='past_due' → OK-şekilli yanıt (access='ok') + in_dunning=1 +
    dunning_grace_end=current_period_end+_DUNNING_SUSPEND_DAYS; is_trial=False.
    _ACCESS_GRANTING_STATUS setine DOKUNULMADI (ayrı dal).
  - AC-5: locked+suspended yanıtına additive suspended_at + dunning_expire_at
    (current_period_end+_DUNNING_EXPIRE_DAYS).
  - AC-8: locked+trial_expired (status=expired) yanıtına additive expired_cause —
    cancellation_reason=='dunning_expired' → 'dunning', aksi 'trial'; reason
    alanı geriye uyumluluk için 'trial_expired' KALIR.
  - Regresyon: mevcut ok (trial/active) + locked (canceled/no_subscription) +
    guest/no_store yanıtlarının alan SETİ değişmedi.

Süre sabitleri BE-3'ün services/subscription_lifecycle.py'ındaki
_DUNNING_SUSPEND_DAYS/_DUNNING_EXPIRE_DAYS'ten lazy import edilir (tek otorite).
BE-3 paralel çalıştığı için burada lifecycle modülü sys.modules'a STUB olarak
konur (14/30 spec değerleriyle) — BE-3 sabitleri yazınca da bu test deterministik
kalır (stub gerçek modülü gölgeler; frappe'siz koşabilsin diye zaten şart).

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_subscription_access_state
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


_NOW = datetime(2026, 9, 14, 12, 0, 0)
_PERIOD_END = datetime(2026, 9, 1, 0, 0, 0)

# Spec değerleri (T+14 suspend / T+30 fesih) — stub lifecycle modülüne yazılır.
_SUSPEND_DAYS = 14
_EXPIRE_DAYS = 30

_STATE: dict = {}


def _reset_state() -> None:
	_STATE.update(
		{
			"user": "owner@test",
			"tenant": "SELLER-A",
			# Store Subscription satırı (dict) veya None
			"sub": None,
		}
	)


class _NSDict(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)


# Endpoint'in get_value ile istediği TÜM alanlar — stub satır bu defaults
# üzerine kurulur ki eksik alan AttributeError üretmesin (gerçek as_dict gibi).
_SUB_DEFAULTS = {
	"status": None,
	"plan": None,
	"trial_start": None,
	"trial_end": None,
	"trial_plan": None,
	"trial_used": 0,
	"started_at": None,
	"current_period_end": None,
	"cancel_at_period_end": 0,
	# BE-1 additive — iptal talebi damgası (BE-3 alanı, ok-payload passthrough).
	"cancel_requested_at": None,
	"billing_cycle": None,
	"canceled_at": None,
	"suspended_at": None,
	"cancellation_reason": None,
}


def _sub_row(**over) -> dict:
	row = dict(_SUB_DEFAULTS)
	row.update(over)
	return row


def _install_stubs() -> None:
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
	frappe.get_roles = lambda u=None: []
	frappe.log_error = lambda *a, **k: None

	def _get_value(doctype, name=None, fieldname=None, as_dict=False, **kw):
		if doctype == "User":
			return _STATE["tenant"]
		if doctype == "Store Subscription":
			sub = _STATE["sub"]
			return _NSDict(**sub) if sub else None
		return None

	frappe.db = SimpleNamespace(get_value=_get_value, exists=lambda *a, **k: True, commit=lambda: None)
	frappe.cache = lambda: SimpleNamespace(delete_keys=lambda *a, **k: None)

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: _NOW
	utils.add_days = lambda d, n: d + timedelta(days=n)
	utils.get_datetime = lambda d: d if isinstance(d, datetime) else datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
	utils.add_months = lambda d, n: d + timedelta(days=30 * n)
	utils.add_years = lambda d, n: d + timedelta(days=365 * n)
	utils.getdate = lambda d=None: d.date() if isinstance(d, datetime) else d
	utils.cint = lambda v: int(v or 0)
	sys.modules["frappe.utils"] = utils

	audit = types.ModuleType("tradehub_core.audit")
	audit.log_decision = lambda *a, **k: "AUDIT-1"
	sys.modules["tradehub_core.audit"] = audit

	# BE-3 paraleli: süre sabitlerinin tek otoritesi lifecycle — burada stub'lanır
	# (gerçek modül frappe'ye bağımlı; sabitler henüz yazılmamış da olabilir).
	lifecycle = types.ModuleType("tradehub_core.services.subscription_lifecycle")
	lifecycle._DUNNING_SUSPEND_DAYS = _SUSPEND_DAYS
	lifecycle._DUNNING_EXPIRE_DAYS = _EXPIRE_DAYS
	sys.modules["tradehub_core.services.subscription_lifecycle"] = lifecycle


_install_stubs()

from tradehub_core.api.v1 import subscription as sub_api  # noqa: E402

# Mevcut sözleşme (BE-3 sonrası) — regresyon: bu alan SETLERİ değişmemeli.
# BE-1: ok-payload'a additive cancel_requested_at eklendi (spec AC-8 additive).
_OK_KEYS = {
	"access",
	"status",
	"plan",
	"is_trial",
	"trial_start",
	"trial_end",
	"started_at",
	"current_period_end",
	"cancel_at_period_end",
	"cancel_requested_at",
	"billing_cycle",
}
_LOCKED_BASE_KEYS = {"access", "status", "reason", "redirect", "can_start_trial"}


class TestPastDueGraceWindow(unittest.TestCase):
	"""AC-1 — past_due artık OK-şekilli döner (hoşgörü penceresi)."""

	def setUp(self):
		_reset_state()
		_STATE["sub"] = _sub_row(
			status="past_due",
			plan="PRO",
			trial_used=1,
			current_period_end=_PERIOD_END,
			cancel_at_period_end="0",
			billing_cycle="monthly",
			started_at=datetime(2026, 8, 1),
		)

	def test_past_due_returns_ok_shape_with_dunning_fields(self):
		out = sub_api.get_seller_access_state()
		self.assertEqual(out["access"], "ok")
		self.assertEqual(out["status"], "past_due")
		self.assertEqual(out["plan"], "PRO")
		self.assertEqual(out["current_period_end"], _PERIOD_END)
		self.assertEqual(out["billing_cycle"], "monthly")
		self.assertEqual(out["cancel_at_period_end"], 0)
		self.assertIs(out["is_trial"], False)
		self.assertEqual(out["in_dunning"], 1)
		self.assertEqual(out["dunning_grace_end"], _PERIOD_END + timedelta(days=_SUSPEND_DAYS))

	def test_past_due_field_set_is_ok_keys_plus_dunning(self):
		out = sub_api.get_seller_access_state()
		self.assertEqual(set(out.keys()), _OK_KEYS | {"in_dunning", "dunning_grace_end"})

	def test_past_due_without_period_end_yields_null_grace_end(self):
		# Kenar: current_period_end boşsa hesap patlamaz, alan None döner.
		_STATE["sub"]["current_period_end"] = None
		out = sub_api.get_seller_access_state()
		self.assertEqual(out["access"], "ok")
		self.assertIsNone(out["dunning_grace_end"])

	def test_access_granting_status_set_untouched(self):
		# past_due OK dalı AYRI — set değişmedi (entitlement/paywall sözleşmesi).
		self.assertEqual(sub_api._ACCESS_GRANTING_STATUS, frozenset({"active", "trial"}))


class TestSuspendedAdditiveFields(unittest.TestCase):
	"""AC-5 — locked+suspended yanıtına suspended_at + dunning_expire_at."""

	def setUp(self):
		_reset_state()
		_STATE["sub"] = _sub_row(
			status="suspended",
			plan="PRO",
			trial_used=1,
			current_period_end=_PERIOD_END,
			suspended_at=datetime(2026, 9, 15, 3, 0, 0),
		)

	def test_suspended_locked_with_additive_fields(self):
		out = sub_api.get_seller_access_state()
		self.assertEqual(out["access"], "locked")
		self.assertEqual(out["reason"], "suspended")
		self.assertEqual(out["status"], "suspended")
		self.assertEqual(out["suspended_at"], datetime(2026, 9, 15, 3, 0, 0))
		self.assertEqual(out["dunning_expire_at"], _PERIOD_END + timedelta(days=_EXPIRE_DAYS))
		self.assertEqual(set(out.keys()), _LOCKED_BASE_KEYS | {"suspended_at", "dunning_expire_at"})

	def test_suspended_without_period_end_yields_null_expire_at(self):
		_STATE["sub"]["current_period_end"] = None
		out = sub_api.get_seller_access_state()
		self.assertIsNone(out["dunning_expire_at"])


class TestExpiredCause(unittest.TestCase):
	"""AC-8 — expired yanıtında expired_cause; reason 'trial_expired' KALIR."""

	def setUp(self):
		_reset_state()
		_STATE["sub"] = _sub_row(status="expired", plan="PRO", trial_used=1)

	def test_dunning_expired_cause(self):
		_STATE["sub"]["cancellation_reason"] = "dunning_expired"
		out = sub_api.get_seller_access_state()
		self.assertEqual(out["access"], "locked")
		self.assertEqual(out["reason"], "trial_expired", "Geriye uyumluluk: reason değişmemeli")
		self.assertEqual(out["expired_cause"], "dunning")

	def test_trial_expired_cause_default(self):
		# cancellation_reason boş VEYA başka değer → 'trial'.
		out = sub_api.get_seller_access_state()
		self.assertEqual(out["expired_cause"], "trial")
		_STATE["sub"]["cancellation_reason"] = "voluntary"
		out = sub_api.get_seller_access_state()
		self.assertEqual(out["expired_cause"], "trial")

	def test_expired_field_set_is_base_plus_cause(self):
		out = sub_api.get_seller_access_state()
		self.assertEqual(set(out.keys()), _LOCKED_BASE_KEYS | {"expired_cause"})


class TestExistingContractRegression(unittest.TestCase):
	"""Mevcut ok/locked yanıtları — alan seti ve değerler DEĞİŞMEDİ."""

	def setUp(self):
		_reset_state()

	def test_active_ok_unchanged(self):
		_STATE["sub"] = _sub_row(
			status="active",
			plan="PRO",
			trial_used=1,
			current_period_end=_PERIOD_END,
			cancel_at_period_end=1,
			billing_cycle="yearly",
			started_at=datetime(2026, 1, 1),
		)
		out = sub_api.get_seller_access_state()
		self.assertEqual(set(out.keys()), _OK_KEYS, "active yanıtına alan eklenmemeli/eksilmemeli")
		self.assertEqual(out["access"], "ok")
		self.assertEqual(out["status"], "active")
		self.assertIs(out["is_trial"], False)
		self.assertEqual(out["cancel_at_period_end"], 1)
		self.assertEqual(out["billing_cycle"], "yearly")

	def test_trial_ok_unchanged(self):
		_STATE["sub"] = _sub_row(
			status="trial",
			plan="PRO",
			trial_used=1,
			trial_start=datetime(2026, 9, 1),
			trial_end=datetime(2026, 9, 15),
		)
		out = sub_api.get_seller_access_state()
		self.assertEqual(set(out.keys()), _OK_KEYS)
		self.assertIs(out["is_trial"], True)
		self.assertEqual(out["trial_end"], datetime(2026, 9, 15))

	def test_canceled_locked_unchanged(self):
		_STATE["sub"] = _sub_row(status="canceled", plan="PRO", trial_used=1, canceled_at=_NOW)
		out = sub_api.get_seller_access_state()
		self.assertEqual(set(out.keys()), _LOCKED_BASE_KEYS | {"canceled_at"})
		self.assertEqual(out["reason"], "canceled")
		self.assertEqual(out["canceled_at"], _NOW)
		self.assertFalse(out["can_start_trial"])

	def test_no_subscription_locked_unchanged(self):
		_STATE["sub"] = None
		out = sub_api.get_seller_access_state()
		self.assertEqual(set(out.keys()), _LOCKED_BASE_KEYS)
		self.assertEqual(out["reason"], "no_subscription")
		self.assertIsNone(out["status"])
		self.assertTrue(out["can_start_trial"])

	def test_guest_and_no_store_unchanged(self):
		sys.modules["frappe"].session.user = "Guest"
		out = sub_api.get_seller_access_state()
		self.assertEqual(out, {"access": "guest", "reason": "not_logged_in"})
		sys.modules["frappe"].session.user = "owner@test"
		_STATE["tenant"] = None
		out = sub_api.get_seller_access_state()
		self.assertEqual(out, {"access": "no_store", "reason": "no_seller_profile"})


if __name__ == "__main__":
	unittest.main()
