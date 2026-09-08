"""BE-4 — Ücretli abonelik lifecycle job testleri (services/subscription_lifecycle).

process_paid_lifecycle üç dalı:
  - send_renewal_reminders: T-7/T-1, idempotent cascade bayraklar (AC-9 — job 3
    kez koşunca dönem başına tek bildirim), copy iki varyant (yenileme / iptal planlı).
  - finalize_cancellations: active + cancel_at_period_end=1 + dönem sonu geçmiş →
    'canceled' (state machine save; canceled_at + bayrak sıfırlama controller'da),
    fesih bildirimi + HIGH audit + entitlement cache flush (AC-8, AC-11).
  - expire_paid_periods: bayrak=0 + dönem sonu geçmiş → 'past_due' + bildirim (AC-8).

Sıra: finalize past_due'dan önce; her kayıtta işlem öncesi status re-check.
Job toplamı idempotent: ikinci koşuda hiçbir kayıt değişmez.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_subscription_paid_lifecycle
"""

from __future__ import annotations

import copy
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _ValidationError(Exception):
	pass


_NOW = datetime(2026, 9, 8, 12, 0, 0)

_STATE: dict = {}


def _reset_state() -> None:
	_STATE.update(
		{
			# name -> Store Subscription satırı (dict — get_doc/save bu dict'i mutasyona uğratır)
			"subs": {},
			# store -> owner user (Admin Seller Profile.user)
			"owners": {"SELLER-A": "owner@test"},
			# re-check race simülasyonu: name -> {status, cancel_at_period_end} override
			"recheck_override": {},
			"notifications": [],  # notify(**kwargs) kayıtları
			"decisions": [],  # log_decision(**kwargs) kayıtları
			"flushed_keys": [],  # cache().delete_keys(prefix) kayıtları
			"saves": [],  # (name, status)
		}
	)


class _NSDict(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)


class _SubDoc:
	"""Store Subscription doc stub'ı — save() controller davranışını taklit eder:
	'canceled' geçişinde canceled_at set + cancel_at_period_end sıfırlanır (BE-1)."""

	def __init__(self, data: dict):
		self.__dict__["_d"] = data

	def __getattr__(self, k):
		try:
			return self.__dict__["_d"][k]
		except KeyError:
			raise AttributeError(k) from None

	def __setattr__(self, k, v):
		self.__dict__["_d"][k] = v

	def save(self, *a, **k):
		d = self.__dict__["_d"]
		if d.get("status") == "canceled":
			if not d.get("canceled_at"):
				d["canceled_at"] = _NOW
			d["cancel_at_period_end"] = 0
		_STATE["saves"].append((d["name"], d.get("status")))


def _match(sub: dict, filters: dict) -> bool:
	for key, cond in (filters or {}).items():
		val = sub.get(key)
		if isinstance(cond, list):
			op = cond[0]
			if op == "<":
				if val is None or not (val < cond[1]):
					return False
			elif op == "is":  # ["is", "set"]
				if not val:
					return False
			elif op == "in":
				if val not in cond[1]:
					return False
			else:
				raise AssertionError(f"stub desteklemiyor: {op}")
		elif isinstance(cond, int):
			if int(val or 0) != cond:
				return False
		elif val != cond:
			return False
	return True


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.log_error = lambda *a, **k: None
	frappe.logger = lambda *a, **k: SimpleNamespace(info=lambda *a, **k: None)
	frappe.cache = lambda: SimpleNamespace(delete_keys=lambda prefix: _STATE["flushed_keys"].append(prefix))

	def _get_all(doctype, filters=None, fields=None, **kw):
		if doctype == "Store Subscription":
			return [_NSDict(**dict(s)) for s in _STATE["subs"].values() if _match(s, filters)]
		if doctype == "Admin Seller Profile":
			names = (filters or {}).get("name", ["in", []])[1]
			return [
				_NSDict(name=store, user=user)
				for store, user in _STATE["owners"].items()
				if store in names
			]
		return []

	frappe.get_all = _get_all

	def _db_get_value(doctype, name=None, fieldname=None, as_dict=False, **kw):
		if doctype != "Store Subscription":
			return None
		sub = _STATE["subs"].get(name)
		if sub is None:
			return None
		merged = {**sub, **_STATE["recheck_override"].get(name, {})}
		if isinstance(fieldname, (list, tuple)):
			return _NSDict(**{f: merged.get(f) for f in fieldname})
		return merged.get(fieldname)

	def _db_set_value(doctype, name, field, value=None, update_modified=True, **kw):
		sub = _STATE["subs"].get(name)
		if sub is not None and isinstance(field, dict):
			sub.update(field)

	frappe.db = SimpleNamespace(get_value=_db_get_value, set_value=_db_set_value, commit=lambda: None)
	frappe.get_doc = lambda doctype, name=None: _SubDoc(_STATE["subs"][name])

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: _NOW
	utils.get_datetime = lambda d: d if isinstance(d, datetime) else datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
	utils.cint = lambda v: int(v or 0)
	sys.modules["frappe.utils"] = utils

	audit = types.ModuleType("tradehub_core.audit")
	audit.log_decision = lambda **kw: _STATE["decisions"].append(kw) or "ADL-1"
	sys.modules["tradehub_core.audit"] = audit

	notify_mod = types.ModuleType("tradehub_core.utils.notify")
	notify_mod.notify = lambda **kw: _STATE["notifications"].append(kw) or "PN-1"
	sys.modules["tradehub_core.utils.notify"] = notify_mod


_install_frappe_stub()

from tradehub_core.services import subscription_lifecycle as lifecycle  # noqa: E402


def _sub(
	name: str = "STSUB-1",
	status: str = "active",
	period_end: datetime | None = None,
	cancel: int = 0,
	r7: int = 0,
	r1: int = 0,
	store: str = "SELLER-A",
) -> dict:
	row = {
		"name": name,
		"store": store,
		"plan": "PRO",
		"status": status,
		"current_period_end": period_end,
		"cancel_at_period_end": cancel,
		"renewal_reminder_7d_sent": r7,
		"renewal_reminder_1d_sent": r1,
		"canceled_at": None,
	}
	_STATE["subs"][name] = row
	return row


class TestRenewalReminders(unittest.TestCase):
	"""AC-9 — T-7/T-1 hatırlatmaları, dönem başına en fazla 1'er kez."""

	def setUp(self):
		_reset_state()

	def test_t7_reminder_sent_once_across_three_runs(self):
		_sub(period_end=_NOW + timedelta(days=5))
		for _ in range(3):
			lifecycle.send_renewal_reminders()
		self.assertEqual(len(_STATE["notifications"]), 1, "Job 3 kez koşunca tek bildirim (AC-9)")
		self.assertEqual(_STATE["subs"]["STSUB-1"]["renewal_reminder_7d_sent"], 1)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["renewal_reminder_1d_sent"], 0)
		self.assertIn("yenilenecek", _STATE["notifications"][0]["title"])

	def test_t1_cascade_sets_both_flags(self):
		# T-7 hiç gitmemişken T-1 penceresine girildi → yalnız T-1 gider, iki bayrak set.
		_sub(period_end=_NOW + timedelta(hours=12))
		out = lifecycle.send_renewal_reminders()
		self.assertEqual(out["sent"], 1)
		self.assertEqual(len(_STATE["notifications"]), 1, "Cascade: geç T-7 ayrıca gönderilmez")
		self.assertIn("yarın", _STATE["notifications"][0]["title"])
		self.assertEqual(_STATE["subs"]["STSUB-1"]["renewal_reminder_7d_sent"], 1)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["renewal_reminder_1d_sent"], 1)

	def test_cancel_scheduled_copy_variant(self):
		_sub(period_end=_NOW + timedelta(days=5), cancel=1)
		lifecycle.send_renewal_reminders()
		msg = _STATE["notifications"][0]["message"]
		self.assertIn("sona erecek", msg)
		self.assertIn("geri alabilirsiniz", msg)
		self.assertIn("13.09.2026", msg, "Gerçek current_period_end tarihi copy'de olmalı")

	def test_expired_period_gets_no_reminder(self):
		# Dönem sonu geçmiş → reminder değil finalize/past_due dalının işi.
		_sub(period_end=_NOW - timedelta(hours=1))
		out = lifecycle.send_renewal_reminders()
		self.assertEqual(out["sent"], 0)
		self.assertEqual(_STATE["notifications"], [])

	def test_flags_set_even_without_owner(self):
		# Owner çözülemese de bayrak set edilir (sonsuz retry olmasın — trial deseni).
		_sub(period_end=_NOW + timedelta(days=5), store="SELLER-GHOST")
		out = lifecycle.send_renewal_reminders()
		self.assertEqual(out["sent"], 1)
		self.assertEqual(_STATE["notifications"], [])
		self.assertEqual(_STATE["subs"]["STSUB-1"]["renewal_reminder_7d_sent"], 1)


class TestFinalizeCancellations(unittest.TestCase):
	"""AC-8/AC-11 — dönem sonu + iptal planı → canceled + bildirim + audit + flush."""

	def setUp(self):
		_reset_state()

	def test_due_cancellation_finalized(self):
		_sub(period_end=_NOW - timedelta(hours=2), cancel=1)
		out = lifecycle.finalize_cancellations()
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual(out["canceled_count"], 1)
		self.assertEqual(row["status"], "canceled")
		self.assertEqual(row["canceled_at"], _NOW, "canceled_at controller'da otomatik set edilmeli")
		self.assertEqual(row["cancel_at_period_end"], 0, "Bayrak canceled geçişinde sıfırlanmalı")
		self.assertEqual(len(_STATE["notifications"]), 1, "Fesih günü bildirimi gitmeli (AC-11)")
		self.assertEqual(len(_STATE["decisions"]), 1)
		self.assertEqual(_STATE["decisions"][0]["severity"], "HIGH")
		self.assertEqual(_STATE["decisions"][0]["rule_id"], "auth.subscription_cancellation")
		self.assertIn("tradehub:entitlement:", _STATE["flushed_keys"], "Entitlement cache flush şart")

	def test_recheck_skips_record_revoked_mid_flight(self):
		# get_all bayrak=1 gördü ama işlem anında revoke edilmiş (re-check deseni).
		_sub(period_end=_NOW - timedelta(hours=2), cancel=1)
		_STATE["recheck_override"]["STSUB-1"] = {"cancel_at_period_end": 0}
		out = lifecycle.finalize_cancellations()
		self.assertEqual(out["canceled_count"], 0)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "active", "Revoke edilen kayıt feshedilmemeli")
		self.assertEqual(_STATE["saves"], [])
		self.assertEqual(_STATE["notifications"], [])

	def test_future_period_end_not_finalized(self):
		_sub(period_end=_NOW + timedelta(days=3), cancel=1)
		out = lifecycle.finalize_cancellations()
		self.assertEqual(out["canceled_count"], 0)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "active")

	def test_idempotent_second_run(self):
		_sub(period_end=_NOW - timedelta(hours=2), cancel=1)
		lifecycle.finalize_cancellations()
		out2 = lifecycle.finalize_cancellations()
		self.assertEqual(out2["canceled_count"], 0)
		self.assertEqual(len(_STATE["saves"]), 1)
		self.assertEqual(len(_STATE["notifications"]), 1)


class TestExpirePaidPeriods(unittest.TestCase):
	"""AC-8 — dönem sonu + bayrak=0 → past_due + bildirim."""

	def setUp(self):
		_reset_state()

	def test_due_period_goes_past_due(self):
		_sub(period_end=_NOW - timedelta(hours=2))
		out = lifecycle.expire_paid_periods()
		self.assertEqual(out["past_due_count"], 1)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "past_due")
		self.assertEqual(len(_STATE["notifications"]), 1)
		self.assertIn("ödeme", _STATE["notifications"][0]["title"].lower())
		self.assertIn("tradehub:entitlement:", _STATE["flushed_keys"])
		# Güvenlik denetimi eki: erişim kesen past_due geçişi de audit'e yazılır
		# (finalize ile tutarlı HIGH — ADL skalasında MEDIUM yok).
		self.assertEqual(len(_STATE["decisions"]), 1)
		decision = _STATE["decisions"][0]
		self.assertEqual(decision["decision"], "ALLOW")
		self.assertEqual(decision["severity"], "HIGH")
		self.assertEqual(decision["rule_id"], "auth.subscription_lifecycle")
		self.assertEqual(decision["context"]["new_status"], "past_due")

	def test_cancel_flagged_record_left_to_finalize(self):
		# Bayrak=1 + dönem sonu geçmiş → bu dalın işi DEĞİL (çift işleme önlemi).
		_sub(period_end=_NOW - timedelta(hours=2), cancel=1)
		out = lifecycle.expire_paid_periods()
		self.assertEqual(out["past_due_count"], 0)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "active")

	def test_idempotent_second_run(self):
		_sub(period_end=_NOW - timedelta(hours=2))
		lifecycle.expire_paid_periods()
		out2 = lifecycle.expire_paid_periods()
		self.assertEqual(out2["past_due_count"], 0)
		self.assertEqual(len(_STATE["saves"]), 1)


class TestProcessPaidLifecycle(unittest.TestCase):
	"""Uçtan uca sıra + toplu idempotency (ikinci koşuda hiçbir kayıt değişmez)."""

	def setUp(self):
		_reset_state()
		_STATE["owners"]["SELLER-B"] = "owner-b@test"
		_STATE["owners"]["SELLER-C"] = "owner-c@test"
		_sub("STSUB-CANCEL", period_end=_NOW - timedelta(hours=1), cancel=1, store="SELLER-A")
		_sub("STSUB-PASTDUE", period_end=_NOW - timedelta(hours=1), store="SELLER-B")
		_sub("STSUB-REMIND", period_end=_NOW + timedelta(days=3), store="SELLER-C")

	def test_branches_and_order(self):
		out = lifecycle.process_paid_lifecycle()
		self.assertEqual(out["reminders"]["sent"], 1)
		self.assertEqual(out["finalized"]["canceled_subscriptions"], ["STSUB-CANCEL"])
		self.assertEqual(out["past_due"]["past_due_subscriptions"], ["STSUB-PASTDUE"])
		self.assertEqual(
			_STATE["subs"]["STSUB-CANCEL"]["status"],
			"canceled",
			"Finalize önce koşmalı — iptal planlı kayıt past_due'ya DÜŞMEMELİ",
		)
		self.assertEqual(_STATE["subs"]["STSUB-PASTDUE"]["status"], "past_due")
		self.assertEqual(_STATE["subs"]["STSUB-REMIND"]["status"], "active")
		self.assertEqual(len(_STATE["notifications"]), 3)

	def test_whole_job_idempotent(self):
		lifecycle.process_paid_lifecycle()
		snapshot = copy.deepcopy(_STATE["subs"])
		saves_before = len(_STATE["saves"])
		notif_before = len(_STATE["notifications"])

		out2 = lifecycle.process_paid_lifecycle()

		self.assertEqual(_STATE["subs"], snapshot, "İkinci koşuda hiçbir kayıt değişmemeli")
		self.assertEqual(len(_STATE["saves"]), saves_before)
		self.assertEqual(len(_STATE["notifications"]), notif_before)
		self.assertEqual(out2["reminders"]["sent"], 0)
		self.assertEqual(out2["finalized"]["canceled_count"], 0)
		self.assertEqual(out2["past_due"]["past_due_count"], 0)


if __name__ == "__main__":
	unittest.main()
