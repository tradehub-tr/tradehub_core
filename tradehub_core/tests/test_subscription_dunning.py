"""BE-3 — Dunning lifecycle job testleri (services/subscription_lifecycle).

Üç yeni dal (Faz C dilim 1):
  - send_dunning_reminders: T+1/T+3/T+7, idempotent cascade bayraklar (AC-2 —
    job 3 kez koşunca aşama başına tek bildirim); copy'de hoşgörü bitişi
    (current_period_end + 14g) + action_url='/abonelik'.
  - suspend_delinquent_subscriptions: past_due + T+14 geçmiş → 'suspended' +
    suspend_source='dunning' + hide_store_listings enqueue(long, after_commit) +
    bildirim + HIGH audit + cache flush (AC-3/AC-4). D4b: bayraksız kayıt
    suspend EDİLMEZ; ilk hatırlatması aynı koşuda giden kayıt da bekler.
  - expire_dunning_subscriptions: suspended + suspend_source='dunning' +
    suspended_at dolu + T+30 geçmiş → 'expired' + cancellation_reason=
    'dunning_expired' (AC-7). D1 negatif: manuel suspend YAKALANMAZ.

Ek: expire_paid_periods T+0 copy'sine hoşgörü bitişi (AC-12), tam job ikinci
koşu no-op (AC-11) ve mevcut dalların (T-7/T-1, finalize, past_due) regresyonu.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_subscription_dunning
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
			# re-check race simülasyonu: name -> field override
			"recheck_override": {},
			"notifications": [],  # notify(**kwargs) kayıtları
			"decisions": [],  # log_decision(**kwargs) kayıtları
			"flushed_keys": [],  # cache().delete_keys(prefix) kayıtları
			"saves": [],  # (name, status)
			"enqueued": [],  # (fn, kwargs) — frappe.enqueue kayıtları
		}
	)


class _NSDict(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)


class _SubDoc:
	"""Store Subscription doc stub'ı — save() controller davranışını taklit eder:
	'canceled' geçişinde canceled_at + bayrak sıfırlama (BE-1), 'suspended'
	girişinde suspended_at damgası, suspended'dan HER çıkışta suspended_at
	temizleme + suspend_source='manual' default'u (BE-2 / D1)."""

	def __init__(self, data: dict):
		self.__dict__["_d"] = data
		self.__dict__["_old_status"] = data.get("status")

	def __getattr__(self, k):
		try:
			return self.__dict__["_d"][k]
		except KeyError:
			raise AttributeError(k) from None

	def __setattr__(self, k, v):
		self.__dict__["_d"][k] = v

	def save(self, *a, **k):
		d = self.__dict__["_d"]
		old_status = self.__dict__["_old_status"]
		if d.get("status") == "canceled":
			if not d.get("canceled_at"):
				d["canceled_at"] = _NOW
			d["cancel_at_period_end"] = 0
		if d.get("status") == "suspended" and not d.get("suspended_at"):
			d["suspended_at"] = _NOW
		if old_status == "suspended" and d.get("status") != "suspended":
			d["suspended_at"] = None
			d["suspend_source"] = "manual"
		_STATE["saves"].append((d["name"], d.get("status")))
		self.__dict__["_old_status"] = d.get("status")


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
	frappe.enqueue = lambda method, **kw: _STATE["enqueued"].append((method, kw))

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

	# BE-1 modül stub'ı — lifecycle hide_store_listings'i yalnız enqueue eder,
	# çalıştırmaz; stub identity assert'i için yeter (gerçek modül SQL çalıştırır).
	sv = types.ModuleType("tradehub_core.services.storefront_visibility")
	sv.hide_store_listings = lambda store=None: None
	sv.restore_store_listings = lambda store=None: None
	sys.modules["tradehub_core.services.storefront_visibility"] = sv


_install_frappe_stub()

from tradehub_core.services import subscription_lifecycle as lifecycle  # noqa: E402

# Stub modülden — lifecycle'ın enqueue ettiği fonksiyonla identity karşılaştırması için.
from tradehub_core.services.storefront_visibility import hide_store_listings  # noqa: E402


def _sub(
	name: str = "STSUB-1",
	status: str = "past_due",
	period_end: datetime | None = None,
	cancel: int = 0,
	r7: int = 0,
	r1: int = 0,
	d1: int = 0,
	d3: int = 0,
	d7: int = 0,
	suspended_at: datetime | None = None,
	suspend_source: str = "manual",
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
		"dunning_reminder_1d_sent": d1,
		"dunning_reminder_3d_sent": d3,
		"dunning_reminder_7d_sent": d7,
		"suspended_at": suspended_at,
		"suspend_source": suspend_source,
		"cancellation_reason": None,
		"canceled_at": None,
	}
	_STATE["subs"][name] = row
	return row


class TestDunningReminders(unittest.TestCase):
	"""AC-2 — T+1/T+3/T+7 hatırlatmaları, aşama başına en fazla 1'er kez."""

	def setUp(self):
		_reset_state()

	def test_t1_reminder_sent_once_across_three_runs(self):
		_sub(period_end=_NOW - timedelta(days=2))
		for _ in range(3):
			lifecycle.send_dunning_reminders()
		self.assertEqual(len(_STATE["notifications"]), 1, "Job 3 kez koşunca tek bildirim (AC-2)")
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual(row["dunning_reminder_1d_sent"], 1)
		self.assertEqual(row["dunning_reminder_3d_sent"], 0)
		self.assertEqual(row["dunning_reminder_7d_sent"], 0)

	def test_t7_cascade_sets_all_flags(self):
		# Hiç hatırlatma gitmemişken T+7 penceresine girildi (deploy senaryosu) →
		# yalnız en gecikmiş aşama gider, üç bayrak birden set (cascade).
		_sub(period_end=_NOW - timedelta(days=10))
		out = lifecycle.send_dunning_reminders()
		self.assertEqual(out["sent"], 1)
		self.assertEqual(len(_STATE["notifications"]), 1, "Cascade: geç T+1/T+3 ayrıca gönderilmez")
		self.assertIn("Son hatırlatma", _STATE["notifications"][0]["title"])
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual(
			(row["dunning_reminder_1d_sent"], row["dunning_reminder_3d_sent"], row["dunning_reminder_7d_sent"]),
			(1, 1, 1),
		)

	def test_t3_cascade_sets_t1_flag(self):
		_sub(period_end=_NOW - timedelta(days=4))
		lifecycle.send_dunning_reminders()
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual(len(_STATE["notifications"]), 1)
		self.assertIn("3 gündür", _STATE["notifications"][0]["title"])
		self.assertEqual((row["dunning_reminder_1d_sent"], row["dunning_reminder_3d_sent"]), (1, 1))
		self.assertEqual(row["dunning_reminder_7d_sent"], 0)

	def test_copy_contains_grace_end_and_action_url(self):
		# period_end 06.09 → hoşgörü bitişi = period_end + 14g = 20.09.2026 (spec copy).
		_sub(period_end=datetime(2026, 9, 6, 12, 0, 0))
		lifecycle.send_dunning_reminders()
		notif = _STATE["notifications"][0]
		self.assertIn("ödemenizi", notif["message"])
		self.assertIn("20.09.2026", notif["message"], "Erişim bitişi = current_period_end + 14 gün")
		self.assertEqual(notif["action_url"], "/abonelik")

	def test_under_one_day_overdue_no_reminder(self):
		# T+0 bildirimi expire_paid_periods'un işi; T+1'den önce dunning hatırlatması yok.
		_sub(period_end=_NOW - timedelta(hours=6))
		out = lifecycle.send_dunning_reminders()
		self.assertEqual(out["sent"], 0)
		self.assertEqual(_STATE["notifications"], [])

	def test_only_past_due_status_processed(self):
		_sub(name="STSUB-ACTIVE", status="active", period_end=_NOW - timedelta(days=5))
		_sub(name="STSUB-SUSP", status="suspended", period_end=_NOW - timedelta(days=5))
		out = lifecycle.send_dunning_reminders()
		self.assertEqual(out["sent"], 0)
		self.assertEqual(_STATE["notifications"], [])

	def test_flags_set_even_without_owner(self):
		# Owner çözülemese de bayrak set edilir (sonsuz retry olmasın — mevcut desen).
		_sub(period_end=_NOW - timedelta(days=2), store="SELLER-GHOST")
		out = lifecycle.send_dunning_reminders()
		self.assertEqual(out["sent"], 1)
		self.assertEqual(_STATE["notifications"], [])
		self.assertEqual(_STATE["subs"]["STSUB-1"]["dunning_reminder_1d_sent"], 1)

	def test_first_reminded_lists_only_previously_flagless(self):
		_sub(name="STSUB-FRESH", period_end=_NOW - timedelta(days=10))  # bayraksız
		_sub(name="STSUB-SEEN", period_end=_NOW - timedelta(days=4), d1=1)  # T+1 zaten gitmiş
		out = lifecycle.send_dunning_reminders()
		self.assertEqual(out["sent"], 2)
		self.assertEqual(out["first_reminded"], ["STSUB-FRESH"], "Yalnız önceden bayraksız kayıt (D4b köprüsü)")


class TestSuspendDelinquent(unittest.TestCase):
	"""AC-3/AC-4 + D4b — T+14 geçmiş past_due → suspended + vitrin gizleme."""

	def setUp(self):
		_reset_state()

	def test_overdue_with_prior_reminder_suspended(self):
		_sub(period_end=_NOW - timedelta(days=15), d1=1)
		out = lifecycle.suspend_delinquent_subscriptions()
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual(out["suspended_count"], 1)
		self.assertEqual(row["status"], "suspended")
		self.assertEqual(row["suspend_source"], "dunning", "D1 işareti save ÖNCESİ yazılmalı")
		self.assertEqual(row["suspended_at"], _NOW, "suspended_at controller'da otomatik damgalanmalı")
		# Vitrin gizleme enqueue — BE-1 sözleşmesi (long + commit sonrası).
		self.assertEqual(len(_STATE["enqueued"]), 1)
		fn, kwargs = _STATE["enqueued"][0]
		self.assertIs(fn, hide_store_listings)
		self.assertEqual(kwargs["store"], "SELLER-A")
		self.assertEqual(kwargs["queue"], "long")
		self.assertTrue(kwargs["enqueue_after_commit"])
		# Bildirim + HIGH audit + cache flush.
		self.assertEqual(len(_STATE["notifications"]), 1)
		self.assertIn("askıya alındı", _STATE["notifications"][0]["title"])
		self.assertEqual(len(_STATE["decisions"]), 1)
		decision = _STATE["decisions"][0]
		self.assertEqual(decision["action"], "subscription.dunning_suspended")
		self.assertEqual(decision["rule_id"], "auth.subscription_lifecycle")
		self.assertEqual(decision["severity"], "HIGH")
		self.assertIn("tradehub:entitlement:", _STATE["flushed_keys"])

	def test_d4b_flagless_record_not_suspended(self):
		# D4b katman 1: hiç hatırlatılmamış kayıt uyarısız askıya alınmaz.
		_sub(period_end=_NOW - timedelta(days=20))
		out = lifecycle.suspend_delinquent_subscriptions()
		self.assertEqual(out["suspended_count"], 0)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "past_due")
		self.assertEqual(_STATE["saves"], [])
		self.assertEqual(_STATE["enqueued"], [])
		self.assertEqual(_STATE["notifications"], [])

	def test_d4b_first_reminded_this_run_waits_next_run(self):
		# D4b katman 2: bayraklar set ama İLK hatırlatma aynı koşuda gitti → bekle.
		_sub(period_end=_NOW - timedelta(days=20), d1=1, d3=1, d7=1)
		out = lifecycle.suspend_delinquent_subscriptions(first_reminded=["STSUB-1"])
		self.assertEqual(out["suspended_count"], 0)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "past_due")

	def test_under_suspend_window_not_touched(self):
		_sub(period_end=_NOW - timedelta(days=10), d1=1, d3=1)
		out = lifecycle.suspend_delinquent_subscriptions()
		self.assertEqual(out["suspended_count"], 0)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "past_due")

	def test_recheck_skips_record_paid_mid_flight(self):
		# get_all past_due gördü ama işlem anında ödeme onaylanmış (re-check deseni).
		_sub(period_end=_NOW - timedelta(days=15), d1=1)
		_STATE["recheck_override"]["STSUB-1"] = {"status": "active"}
		out = lifecycle.suspend_delinquent_subscriptions()
		self.assertEqual(out["suspended_count"], 0)
		self.assertEqual(_STATE["saves"], [])
		self.assertEqual(_STATE["enqueued"], [])

	def test_idempotent_second_run(self):
		_sub(period_end=_NOW - timedelta(days=15), d1=1)
		lifecycle.suspend_delinquent_subscriptions()
		out2 = lifecycle.suspend_delinquent_subscriptions()
		self.assertEqual(out2["suspended_count"], 0)
		self.assertEqual(len(_STATE["saves"]), 1)
		self.assertEqual(len(_STATE["notifications"]), 1)
		self.assertEqual(len(_STATE["enqueued"]), 1)


class TestExpireDunning(unittest.TestCase):
	"""AC-7 + D1 — T+30 geçmiş dunning-suspended → expired; manuel suspend dışarıda."""

	def setUp(self):
		_reset_state()

	def test_dunning_suspended_expired_after_window(self):
		_sub(
			period_end=_NOW - timedelta(days=35),
			status="suspended",
			suspend_source="dunning",
			suspended_at=_NOW - timedelta(days=21),
		)
		out = lifecycle.expire_dunning_subscriptions()
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual(out["expired_count"], 1)
		self.assertEqual(row["status"], "expired")
		self.assertEqual(row["cancellation_reason"], "dunning_expired")
		self.assertIsNone(row["suspended_at"], "suspended'dan çıkışta controller temizler (BE-2)")
		self.assertEqual(row["suspend_source"], "manual", "Çıkışta default'a döner (D1)")
		self.assertEqual(len(_STATE["notifications"]), 1, "Fesih bildirimi gitmeli")
		self.assertIn("sona erdi", _STATE["notifications"][0]["title"])
		self.assertEqual(len(_STATE["decisions"]), 1)
		decision = _STATE["decisions"][0]
		self.assertEqual(decision["action"], "subscription.dunning_expired")
		self.assertEqual(decision["severity"], "HIGH")
		self.assertEqual(decision["context"]["cancellation_reason"], "dunning_expired")
		self.assertIn("tradehub:entitlement:", _STATE["flushed_keys"])

	def test_d1_manual_suspend_never_expired(self):
		# D1 NEGATİF: admin'in Desk'ten manuel suspend ettiği mağaza 30 günü
		# geçse de otomatik feshin TAMAMEN dışında kalır (süresiz kilit niyeti).
		_sub(
			period_end=_NOW - timedelta(days=40),
			status="suspended",
			suspend_source="manual",
			suspended_at=_NOW - timedelta(days=40),
		)
		out = lifecycle.expire_dunning_subscriptions()
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual(out["expired_count"], 0)
		self.assertEqual(row["status"], "suspended")
		self.assertEqual(row["suspend_source"], "manual")
		self.assertEqual(_STATE["saves"], [])
		self.assertEqual(_STATE["notifications"], [])

	def test_under_expire_window_not_touched(self):
		_sub(
			period_end=_NOW - timedelta(days=20),
			status="suspended",
			suspend_source="dunning",
			suspended_at=_NOW - timedelta(days=6),
		)
		out = lifecycle.expire_dunning_subscriptions()
		self.assertEqual(out["expired_count"], 0)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "suspended")

	def test_missing_suspended_at_not_touched(self):
		# suspended_at dolu şartı sorgu filtresinde (spec) — boşsa dokunulmaz.
		_sub(period_end=_NOW - timedelta(days=35), status="suspended", suspend_source="dunning")
		out = lifecycle.expire_dunning_subscriptions()
		self.assertEqual(out["expired_count"], 0)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "suspended")

	def test_recheck_skips_source_flip_mid_flight(self):
		_sub(
			period_end=_NOW - timedelta(days=35),
			status="suspended",
			suspend_source="dunning",
			suspended_at=_NOW - timedelta(days=21),
		)
		_STATE["recheck_override"]["STSUB-1"] = {"suspend_source": "manual"}
		out = lifecycle.expire_dunning_subscriptions()
		self.assertEqual(out["expired_count"], 0)
		self.assertEqual(_STATE["saves"], [])

	def test_idempotent_second_run(self):
		_sub(
			period_end=_NOW - timedelta(days=35),
			status="suspended",
			suspend_source="dunning",
			suspended_at=_NOW - timedelta(days=21),
		)
		lifecycle.expire_dunning_subscriptions()
		out2 = lifecycle.expire_dunning_subscriptions()
		self.assertEqual(out2["expired_count"], 0)
		self.assertEqual(len(_STATE["saves"]), 1)
		self.assertEqual(len(_STATE["notifications"]), 1)


class TestExistingBranchesRegression(unittest.TestCase):
	"""Mevcut dalların regresyonu: T-7/T-1, finalize, past_due + AC-12 copy eki."""

	def setUp(self):
		_reset_state()

	def test_t7_renewal_reminder_sent_once(self):
		_sub(status="active", period_end=_NOW + timedelta(days=5))
		for _ in range(3):
			lifecycle.send_renewal_reminders()
		self.assertEqual(len(_STATE["notifications"]), 1)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["renewal_reminder_7d_sent"], 1)

	def test_t1_renewal_cascade(self):
		_sub(status="active", period_end=_NOW + timedelta(hours=12))
		lifecycle.send_renewal_reminders()
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual((row["renewal_reminder_7d_sent"], row["renewal_reminder_1d_sent"]), (1, 1))

	def test_finalize_cancellation(self):
		_sub(status="active", period_end=_NOW - timedelta(hours=2), cancel=1)
		out = lifecycle.finalize_cancellations()
		row = _STATE["subs"]["STSUB-1"]
		self.assertEqual(out["canceled_count"], 1)
		self.assertEqual(row["status"], "canceled")
		self.assertEqual(row["cancel_at_period_end"], 0)

	def test_past_due_transition_with_grace_copy(self):
		# AC-12: T+0 bildirimi korunur, copy'ye 'erişiminiz X tarihine kadar sürer'
		# eklenir (X = period_end + 14g); geçiş başına en fazla 1 bildirim.
		_sub(status="active", period_end=datetime(2026, 9, 8, 10, 0, 0))
		out = lifecycle.expire_paid_periods()
		self.assertEqual(out["past_due_count"], 1)
		self.assertEqual(_STATE["subs"]["STSUB-1"]["status"], "past_due")
		self.assertEqual(len(_STATE["notifications"]), 1)
		msg = _STATE["notifications"][0]["message"]
		self.assertIn("08.09.2026", msg, "Dönem sonu tarihi copy'de kalmalı")
		self.assertIn("Erişiminiz 22.09.2026 tarihine kadar sürer", msg, "Hoşgörü bitişi eklenmeli (AC-12)")
		out2 = lifecycle.expire_paid_periods()
		self.assertEqual(out2["past_due_count"], 0)
		self.assertEqual(len(_STATE["notifications"]), 1, "Geçiş başına en fazla 1 bildirim")


class TestProcessPaidLifecycleDunning(unittest.TestCase):
	"""AC-11 — tam job sırası, D4b ilk-koşu emniyeti ve ikinci koşu no-op."""

	def _fixtures(self):
		for i, store in enumerate(["B", "C", "D", "E", "F", "G"], start=1):
			_STATE["owners"][f"SELLER-{store}"] = f"owner-{i}@test"
		_sub("STSUB-CANCEL", status="active", period_end=_NOW - timedelta(hours=1), cancel=1, store="SELLER-A")
		_sub("STSUB-PASTDUE", status="active", period_end=_NOW - timedelta(hours=1), store="SELLER-B")
		_sub("STSUB-REMIND", status="active", period_end=_NOW + timedelta(days=3), store="SELLER-C")
		_sub("STSUB-DUNREM", period_end=_NOW - timedelta(days=2), store="SELLER-D")
		_sub("STSUB-SUSPEND", period_end=_NOW - timedelta(days=20), d1=1, d3=1, d7=1, store="SELLER-E")
		_sub(
			"STSUB-EXPIRE",
			status="suspended",
			period_end=_NOW - timedelta(days=35),
			suspend_source="dunning",
			suspended_at=_NOW - timedelta(days=21),
			store="SELLER-F",
		)
		_sub(
			"STSUB-MANUAL",
			status="suspended",
			period_end=_NOW - timedelta(days=40),
			suspend_source="manual",
			suspended_at=_NOW - timedelta(days=40),
			store="SELLER-G",
		)

	def setUp(self):
		_reset_state()
		self._fixtures()

	def test_all_branches_single_run(self):
		out = lifecycle.process_paid_lifecycle()
		subs = _STATE["subs"]
		self.assertEqual(out["reminders"]["sent"], 1)
		self.assertEqual(out["finalized"]["canceled_subscriptions"], ["STSUB-CANCEL"])
		self.assertEqual(out["past_due"]["past_due_subscriptions"], ["STSUB-PASTDUE"])
		self.assertEqual(out["dunning_reminders"]["sent"], 1)
		self.assertEqual(out["suspended"]["suspended_subscriptions"], ["STSUB-SUSPEND"])
		self.assertEqual(out["dunning_expired"]["expired_subscriptions"], ["STSUB-EXPIRE"])
		self.assertEqual(subs["STSUB-DUNREM"]["status"], "past_due", "Hatırlatma statüyü değiştirmez")
		self.assertEqual(subs["STSUB-SUSPEND"]["suspend_source"], "dunning")
		self.assertEqual(subs["STSUB-EXPIRE"]["cancellation_reason"], "dunning_expired")
		self.assertEqual(subs["STSUB-MANUAL"]["status"], "suspended", "D1: manuel suspend feshe yakalanmaz")
		# 6 bildirim: T-7, fesih, T+0 past_due, dunning T+1, askı, dunning fesih.
		self.assertEqual(len(_STATE["notifications"]), 6)

	def test_d4b_flagless_record_first_run_reminded_not_suspended(self):
		# Deploy senaryosu: T+14'ü çoktan geçmiş ama hiç hatırlatılmamış kayıt —
		# ilk koşuda suspend EDİLMEZ, hatırlatma alır; ikinci koşu askıya alır.
		_reset_state()
		_sub("STSUB-LEGACY", period_end=_NOW - timedelta(days=25))
		out1 = lifecycle.process_paid_lifecycle()
		row = _STATE["subs"]["STSUB-LEGACY"]
		self.assertEqual(row["status"], "past_due", "İlk koşu: suspend YOK (D4b)")
		self.assertEqual(out1["dunning_reminders"]["sent"], 1)
		self.assertEqual(out1["suspended"]["suspended_count"], 0)
		self.assertEqual(len(_STATE["notifications"]), 1)
		self.assertIn("Son hatırlatma", _STATE["notifications"][0]["title"], "En gecikmiş aşama gider")
		self.assertEqual(_STATE["enqueued"], [])

		out2 = lifecycle.process_paid_lifecycle()
		self.assertEqual(out2["suspended"]["suspended_subscriptions"], ["STSUB-LEGACY"])
		self.assertEqual(_STATE["subs"]["STSUB-LEGACY"]["status"], "suspended")
		self.assertEqual(len(_STATE["enqueued"]), 1, "Vitrin gizleme ikinci koşuda enqueue edilir")

	def test_whole_job_second_run_noop(self):
		lifecycle.process_paid_lifecycle()
		snapshot = copy.deepcopy(_STATE["subs"])
		saves_before = len(_STATE["saves"])
		notif_before = len(_STATE["notifications"])
		enqueued_before = len(_STATE["enqueued"])

		out2 = lifecycle.process_paid_lifecycle()

		self.assertEqual(_STATE["subs"], snapshot, "İkinci koşuda hiçbir kayıt değişmemeli")
		self.assertEqual(len(_STATE["saves"]), saves_before)
		self.assertEqual(len(_STATE["notifications"]), notif_before)
		self.assertEqual(len(_STATE["enqueued"]), enqueued_before)
		self.assertEqual(out2["reminders"]["sent"], 0)
		self.assertEqual(out2["finalized"]["canceled_count"], 0)
		self.assertEqual(out2["past_due"]["past_due_count"], 0)
		self.assertEqual(out2["dunning_reminders"]["sent"], 0)
		self.assertEqual(out2["suspended"]["suspended_count"], 0)
		self.assertEqual(out2["dunning_expired"]["expired_count"], 0)


if __name__ == "__main__":
	unittest.main()
