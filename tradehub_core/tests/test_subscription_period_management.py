"""BE-3 — Dönem yönetimi + R2/R5 guard testleri; BE-1 — kalan süre devri.

api/v1/subscription.upgrade_subscription_plan:
  - AC-7: status='active' geçişinde current_period_end = start + 1 ay (monthly)
    / 1 yıl (yearly), next_invoice_date set, billing_cycle yazılır,
    cancel_at_period_end sıfırlanır.
  - billing_cycle geriye-uyumlu: verilmezse mevcut kayıt > 'monthly' fallback.
  - Trial başlatmada dönem alanları YAZILMAZ (trial_end yönetir).
  - R2: 'canceled' mağaza Admin Seller Profile Suspended VEYA owner User
    disabled iken self-servis reaktive EDİLEMEZ (417) — AC-14 negatif vakası.

BE-1 — kalan süre devri (Bora kararı a + E1, AC-1..AC-4):
  - Erken yenilemede (eski status='active' + eski current_period_end gelecekte
    + new_plan == mevcut plan) yeni dönem ESKİ bitişten devreder (monthly+yearly).
  - E1: plan değişikliğinde devir YOK; dönemi geçmiş active, TÜM reaktivasyon
    statüleri (past_due/suspended/canceled/expired) ve trial→active'te devir YOK.
  - Devirli yenilemede cancel_at_period_end sıfırlanır + renewal reminder
    bayrakları resetlenir (controller emülasyonu — _Doc.save).
  - Audit context'ine period_carried_over yazılır.
  - E3: devirli dönemde (current_period_start gelecekte) send_renewal_reminders +
    process_paid_lifecycle hiçbir bildirim/status değişikliği üretmez;
    get_seller_access_state devirli yeni bitişi + additive cancel_requested_at döner.

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
			# BE-1 / E3 eklemeleri
			"decisions": [],  # log_decision(**kwargs) kayıtları (audit context assert'i)
			"notifications": [],  # notify(**kwargs) kayıtları (lifecycle no-op assert'i)
			"set_values": [],  # frappe.db.set_value kayıtları
			"enqueued": [],  # frappe.enqueue kayıtları
			# name -> satır: lifecycle get_all/get_value bu havuzdan okur (E3)
			"lifecycle_subs": {},
			"owners": {"SELLER-A": "owner@test"},
		}
	)


class _NSDict(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)


class _Doc(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)

	def save(self, *a, **k):
		# Controller emülasyonu (BE-1): store_subscription.validate'in
		# _reset_renewal_reminders_on_new_period davranışı — current_period_start
		# ESKİ kayda göre DEĞİŞTİYSE renewal/dunning reminder bayrakları sıfırlanır.
		if getattr(self, "_doctype", None) == "Store Subscription":
			old_start = (_STATE["existing_sub"] or {}).get("current_period_start")
			new_start = self.get("current_period_start")
			if new_start and (not old_start or old_start != new_start):
				self.renewal_reminder_7d_sent = 0
				self.renewal_reminder_1d_sent = 0
				self.dunning_reminder_1d_sent = 0
				self.dunning_reminder_3d_sent = 0
				self.dunning_reminder_7d_sent = 0
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
	frappe.logger = lambda *a, **k: SimpleNamespace(info=lambda *a, **k: None)
	frappe.enqueue = lambda method, **kw: _STATE["enqueued"].append((method, kw))

	def _match(row: dict, filters: dict) -> bool:
		"""Lifecycle get_all filtreleri için mini eşleyici (dunning test deseni)."""
		for key, cond in (filters or {}).items():
			val = row.get(key)
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

	def _get_all(doctype, filters=None, fields=None, **kw):
		# E3 — lifecycle job'ları bu havuzdan okur; diğer doctype'lar boş döner.
		if doctype == "Store Subscription":
			return [_NSDict(**dict(s)) for s in _STATE["lifecycle_subs"].values() if _match(s, filters)]
		if doctype == "Admin Seller Profile":
			names = (filters or {}).get("name", ["in", []])[1]
			return [
				_NSDict(name=store, user=user)
				for store, user in _STATE["owners"].items()
				if store in names
			]
		return []

	frappe.get_all = _get_all

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
			# E3 — lifecycle job'ları name (str) ile re-check okur; API filters
			# dict'i ile mevcut satırı okur (her ikisi de aynı stub'dan).
			if isinstance(name, str) and name in _STATE["lifecycle_subs"]:
				row = _STATE["lifecycle_subs"][name]
				if isinstance(fieldname, (list, tuple)):
					return _NSDict(**{f: row.get(f) for f in fieldname})
				return row.get(fieldname)
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

	def _db_set_value(doctype, name, field, value=None, **kw):
		# E3 no-op assert'i: lifecycle bayrak yazarsa burada görünür.
		_STATE["set_values"].append((doctype, name, field, value))
		row = _STATE["lifecycle_subs"].get(name)
		if row is not None and isinstance(field, dict):
			row.update(field)

	frappe.db = SimpleNamespace(
		get_value=_get_value,
		exists=lambda *a, **k: True,
		commit=lambda: None,
		set_value=_db_set_value,
	)

	# for_update kwarg'ı M1 kilitleme düzeltmesiyle geldi — stub kabul edip yok sayar.
	def _get_doc(doctype, name=None, for_update=False, **kwargs):
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
		seed: dict = {}
		if doctype == "Store Subscription":
			# Gerçek get_doc gibi mevcut satırın alanlarıyla dolu gelir — BE-1
			# bayrak-sıfırlama (controller emülasyonu) assert'leri bunu gerektirir.
			seed = {k: v for k, v in (_STATE["existing_sub"] or {}).items() if k != "name"}
		d = _Doc(_doctype=doctype, name=name, flags=SimpleNamespace(), **seed)
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
	utils.get_datetime = lambda d: d if isinstance(d, datetime) else datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
	utils.getdate = lambda d=None: d.date() if isinstance(d, datetime) else d
	utils.cint = lambda v: int(v or 0)
	sys.modules["frappe.utils"] = utils

	audit = types.ModuleType("tradehub_core.audit")
	# BE-1: audit context'indeki period_carried_over assert'i için kayıt tutulur.
	audit.log_decision = lambda **kw: _STATE["decisions"].append(kw) or "AUDIT-1"
	sys.modules["tradehub_core.audit"] = audit

	notify_mod = types.ModuleType("tradehub_core.utils.notify")
	# E3: lifecycle no-op assert'i için bildirimler kaydedilir.
	notify_mod.notify = lambda **kw: _STATE["notifications"].append(kw) or "PN-1"
	sys.modules["tradehub_core.utils.notify"] = notify_mod

	# E3 — lifecycle modülü import'u için stub (gerçek modül SQL çalıştırır).
	sv = types.ModuleType("tradehub_core.services.storefront_visibility")
	sv.hide_store_listings = lambda store=None: None
	sv.restore_store_listings = lambda store=None: None
	sys.modules["tradehub_core.services.storefront_visibility"] = sv


_install_frappe_stub()

from tradehub_core.api.v1 import subscription as sub  # noqa: E402
from tradehub_core.api.v1 import subscription_payment as sub_pay  # noqa: E402
from tradehub_core.services import subscription_lifecycle as lifecycle  # noqa: E402


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


# ---------------------------------------------------------------------------
# BE-1 — kalan süre devri (Bora kararı a + E1) + E3 invariant testleri
# ---------------------------------------------------------------------------

_OLD_END = _NOW + timedelta(days=10)


def _existing_active(plan: str = "PRO", cycle: str = "monthly", **over) -> dict:
	"""Aktif + dönemi süren mevcut Store Subscription satırı (erken yenileme tabanı)."""
	row = {
		"name": "STSUB-1",
		"plan": plan,
		"status": "active",
		"trial_used": 1,
		"billing_cycle": cycle,
		"current_period_start": _NOW - timedelta(days=20),
		"current_period_end": _OLD_END,
		"cancel_at_period_end": 0,
		"renewal_reminder_7d_sent": 0,
		"renewal_reminder_1d_sent": 0,
		"dunning_reminder_1d_sent": 0,
		"dunning_reminder_3d_sent": 0,
		"dunning_reminder_7d_sent": 0,
	}
	row.update(over)
	_STATE["existing_sub"] = row
	return row


def _last_upgrade_decision() -> dict:
	upgrades = [d for d in _STATE["decisions"] if d.get("action") == "subscription.upgrade"]
	assert upgrades, "upgrade audit kaydı bekleniyordu"
	return upgrades[-1]


class TestEarlyRenewalCarryOver(unittest.TestCase):
	"""AC-1..AC-4 + E1 — devir ÜÇLÜ koşulda; aksi TÜM durumlarda now tabanı."""

	def setUp(self):
		_reset_state()
		_as_admin()

	def test_early_renewal_monthly_carries_over(self):
		_existing_active(cycle="monthly")
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.current_period_start, _OLD_END, "Yeni dönem ESKİ bitişten devretmeli")
		self.assertEqual(doc.current_period_end, _add_months(_OLD_END, 1))
		self.assertEqual(doc.next_invoice_date, _add_months(_OLD_END, 1).date())
		self.assertIs(_last_upgrade_decision()["context"]["period_carried_over"], True)

	def test_early_renewal_yearly_carries_over(self):
		_existing_active(cycle="yearly")
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="yearly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.current_period_start, _OLD_END)
		self.assertEqual(doc.current_period_end, _add_months(_OLD_END, 12))
		self.assertIs(_last_upgrade_decision()["context"]["period_carried_over"], True)

	def test_e1_plan_change_no_carry_over(self):
		# E1 — new_plan != mevcut plan → bugünkü davranış korunur (dönem now'dan).
		_existing_active(plan="PRO")
		sub.upgrade_subscription_plan(new_plan="ENTERPRISE", tenant="SELLER-A", billing_cycle="monthly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.current_period_start, _NOW, "Plan değişikliğinde devir YOK (E1)")
		self.assertEqual(doc.current_period_end, _add_months(_NOW, 1))
		self.assertIs(_last_upgrade_decision()["context"]["period_carried_over"], False)

	def test_period_already_past_no_carry_over(self):
		# Dönemi geçmiş active (lifecycle koşusu gecikmiş olabilir) → now tabanı.
		_existing_active(current_period_end=_NOW - timedelta(hours=1))
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.current_period_start, _NOW)
		self.assertIs(_last_upgrade_decision()["context"]["period_carried_over"], False)

	def test_reactivation_statuses_no_carry_over(self):
		# TÜM reaktivasyonlar (past_due/suspended/canceled/expired→active) now
		# tabanı — dönem bitişi gelecekte görünse bile status 'active' değil.
		for status in ("past_due", "suspended", "canceled", "expired"):
			with self.subTest(status=status):
				_reset_state()
				_as_admin()
				_existing_active(status=status)
				sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
				doc = _STATE["last_sub_doc"]
				self.assertEqual(doc.status, "active")
				self.assertEqual(doc.current_period_start, _NOW, f"{status}→active devir almamalı")
				self.assertIs(_last_upgrade_decision()["context"]["period_carried_over"], False)

	def test_trial_to_active_no_carry_over(self):
		# trial→active: devir yok (savunmacı: bayat dönem alanı kalmış olsa bile).
		_existing_active(status="trial")
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.current_period_start, _NOW)
		self.assertIs(_last_upgrade_decision()["context"]["period_carried_over"], False)

	def test_carried_renewal_resets_cancel_flag_and_reminders(self):
		# Devirli yenilemede eski iptal planı taşınmaz + yeni dönemin reminder
		# bayrakları sıfırlanır (controller emülasyonu — _Doc.save).
		_existing_active(
			cancel_at_period_end=1,
			renewal_reminder_7d_sent=1,
			renewal_reminder_1d_sent=1,
			dunning_reminder_1d_sent=1,
		)
		sub.upgrade_subscription_plan(new_plan="PRO", tenant="SELLER-A", billing_cycle="monthly")
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.current_period_start, _OLD_END, "Devir koşulu sağlanmalı (ön şart)")
		self.assertEqual(doc.cancel_at_period_end, 0)
		self.assertEqual(doc.renewal_reminder_7d_sent, 0)
		self.assertEqual(doc.renewal_reminder_1d_sent, 0)
		self.assertEqual(doc.dunning_reminder_1d_sent, 0)

	def test_confirm_early_renewal_carries_over(self):
		# Entegrasyon: aynı planın ödemesi onaylanınca devir confirm yolundan da işler.
		_existing_active(cycle="monthly")
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
		self.assertEqual(doc.status, "active")
		self.assertEqual(doc.current_period_start, _OLD_END)
		self.assertEqual(doc.current_period_end, _add_months(_OLD_END, 1))


class TestCarriedPeriodLifecycleNoOp(unittest.TestCase):
	"""E3 — devirli dönemde (current_period_start gelecekte) lifecycle no-op."""

	def setUp(self):
		_reset_state()

	def _carried_row(self, start: datetime, **over) -> dict:
		row = {
			"name": "STSUB-L1",
			"store": "SELLER-A",
			"plan": "PRO",
			"status": "active",
			"current_period_start": start,
			"current_period_end": _add_months(start, 1),
			"cancel_at_period_end": 0,
			"renewal_reminder_7d_sent": 0,
			"renewal_reminder_1d_sent": 0,
			"dunning_reminder_1d_sent": 0,
			"dunning_reminder_3d_sent": 0,
			"dunning_reminder_7d_sent": 0,
			"suspended_at": None,
			"suspend_source": "manual",
			"cancellation_reason": None,
		}
		row.update(over)
		_STATE["lifecycle_subs"][row["name"]] = row
		return row

	def test_full_paid_lifecycle_noop_on_carried_period(self):
		# Erken yenileme sonrası: start gelecekte, end ~40 gün ileride → hiçbir
		# dal bildirim/status değişikliği/bayrak yazısı üretmemeli (E3).
		self._carried_row(start=_NOW + timedelta(days=10))
		out = lifecycle.process_paid_lifecycle()
		self.assertEqual(out["reminders"]["sent"], 0)
		self.assertEqual(out["finalized"]["canceled_count"], 0)
		self.assertEqual(out["past_due"]["past_due_count"], 0)
		self.assertEqual(out["dunning_reminders"]["sent"], 0)
		self.assertEqual(out["suspended"]["suspended_count"], 0)
		self.assertEqual(out["dunning_expired"]["expired_count"], 0)
		self.assertEqual(_STATE["notifications"], [], "Devirli dönemde bildirim gitmemeli")
		self.assertEqual(_STATE["set_values"], [], "Hiçbir bayrak yazılmamalı")
		self.assertEqual(_STATE["saved"], [], "Hiçbir status geçişi olmamalı")
		self.assertEqual(_STATE["lifecycle_subs"]["STSUB-L1"]["status"], "active")

	def test_no_renewal_reminder_when_old_period_end_imminent(self):
		# Eski dönemin bitişine saatler kala erken yenileme yapıldı: yeni end
		# ~1 ay ileride → sıfırlanmış bayraklara rağmen T-7/T-1 TEKRAR gitmez.
		self._carried_row(start=_NOW + timedelta(hours=12))
		out = lifecycle.send_renewal_reminders()
		self.assertEqual(out["sent"], 0)
		self.assertEqual(_STATE["notifications"], [])


class TestAccessStateCarriedPeriod(unittest.TestCase):
	"""E3 — get_seller_access_state devirli yeni bitişi + cancel_requested_at döner."""

	_CARRIED_START = _NOW + timedelta(days=10)

	def _access_row(self, **over) -> dict:
		row = {
			"name": "STSUB-1",
			"status": "active",
			"plan": "PRO",
			"trial_start": None,
			"trial_end": None,
			"trial_plan": None,
			"trial_used": 1,
			"started_at": _NOW - timedelta(days=50),
			"current_period_start": self._CARRIED_START,
			"current_period_end": _add_months(self._CARRIED_START, 1),
			"cancel_at_period_end": 0,
			"cancel_requested_at": None,
			"billing_cycle": "monthly",
			"canceled_at": None,
			"suspended_at": None,
			"cancellation_reason": None,
		}
		row.update(over)
		_STATE["existing_sub"] = row
		return row

	def setUp(self):
		_reset_state()
		_as_owner()

	def test_access_state_returns_carried_period_end(self):
		self._access_row()
		out = sub.get_seller_access_state()
		self.assertEqual(out["access"], "ok")
		self.assertEqual(out["status"], "active")
		self.assertEqual(out["current_period_end"], _add_months(self._CARRIED_START, 1))

	def test_cancel_requested_at_additive_in_ok_payload(self):
		stamp = datetime(2026, 9, 6, 15, 0, 0)
		self._access_row(cancel_at_period_end=1, cancel_requested_at=stamp)
		out = sub.get_seller_access_state()
		self.assertEqual(out["cancel_requested_at"], stamp)
		self.assertEqual(out["cancel_at_period_end"], 1)

	def test_cancel_requested_at_null_when_no_cancellation(self):
		self._access_row()
		out = sub.get_seller_access_state()
		self.assertIn("cancel_requested_at", out)
		self.assertIsNone(out["cancel_requested_at"])


if __name__ == "__main__":
	unittest.main()
