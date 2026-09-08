# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Store Subscription — BE-1 testleri: geçiş matrisi + iptal bayrağı kuralları +
renewal reminder sıfırlama + R1'li current_period_end backfill patch'i.

Çalıştırma:
	docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests \\
	  --module tradehub_core.tradehub_core.doctype.store_subscription.test_store_subscription
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, get_datetime, now_datetime

from tradehub_core.patches.v15_backfill_current_period_end import execute as run_backfill

_USER_EMAIL = "stsub-test-owner@example.com"
_STORE_PREFIX = "STSUBTEST-"


class TestStoreSubscription(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.plan = frappe.db.get_value("Subscription Plan", {}, "name")
		cls._ensure_user()

	def setUp(self):
		if not self.plan:
			self.skipTest("Seed edilmiş Subscription Plan yok")
		self._cleanup()

	def tearDown(self):
		self._cleanup()

	# --- fixtures ---

	@classmethod
	def _ensure_user(cls, email: str = _USER_EMAIL) -> None:
		if frappe.db.exists("User", email):
			return
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "StSub Test"
		user.send_welcome_email = 0
		user.insert(ignore_permissions=True)

	def _cleanup(self) -> None:
		frappe.db.delete("Store Subscription", {"store": ["like", f"{_STORE_PREFIX}%"]})
		frappe.db.delete("Subscription Payment", {"store": ["like", f"{_STORE_PREFIX}%"]})
		frappe.db.commit()

	def _make_store(self, code: str) -> str:
		name = f"{_STORE_PREFIX}{code}"
		# Admin Seller Profile.user unique — mağaza başına türetilmiş ayrı kullanıcı.
		owner_email = f"stsub-test-{code.lower()}@example.com"
		self._ensure_user(owner_email)
		if not frappe.db.exists("Admin Seller Profile", name):
			profile = frappe.new_doc("Admin Seller Profile")
			profile.seller_code = name
			profile.seller_name = f"StSub Test Mağaza {code}"
			profile.user = owner_email
			profile.email = owner_email
			profile.insert(ignore_permissions=True)
		return name

	def _make_sub(self, code: str, **kwargs) -> Document:
		sub = frappe.new_doc("Store Subscription")
		sub.store = self._make_store(code)
		sub.plan = self.plan
		sub.status = kwargs.pop("status", "active")
		for key, value in kwargs.items():
			sub.set(key, value)
		sub.insert(ignore_permissions=True)
		return sub

	def _make_payment(self, store: str, billing_cycle: str, confirmed_at) -> None:
		payment = frappe.new_doc("Subscription Payment")
		payment.store = store
		payment.plan = self.plan
		payment.billing_cycle = billing_cycle
		payment.status = "confirmed"
		payment.confirmed_at = confirmed_at
		payment.insert(ignore_permissions=True)

	# --- geçiş matrisi (AC-14 dahil) ---

	def test_canceled_to_active_allowed(self):
		"""AC-14: canceled artık terminal değil — aynı satır 'active'e reaktive edilir."""
		sub = self._make_sub("T1")
		sub.status = "canceled"
		sub.save(ignore_permissions=True)
		self.assertIsNotNone(sub.canceled_at)

		sub.reload()
		sub.status = "active"
		sub.save(ignore_permissions=True)
		self.assertEqual(sub.status, "active")

	def test_canceled_to_trial_blocked(self):
		"""canceled'dan yalnız 'active'e çıkılır — trial'a dönüş yok."""
		sub = self._make_sub("T2")
		sub.status = "canceled"
		sub.save(ignore_permissions=True)
		sub.reload()
		sub.status = "trial"
		with self.assertRaises(frappe.ValidationError):
			sub.save(ignore_permissions=True)

	def test_active_to_trial_blocked(self):
		sub = self._make_sub("T3")
		sub.status = "trial"
		with self.assertRaises(frappe.ValidationError):
			sub.save(ignore_permissions=True)

	# --- cancel_at_period_end bayrak kuralları ---

	def test_flag_requires_active_status(self):
		"""Bayrak yalnız status='active' iken 1 olabilir (R3: trial'da iptal yok)."""
		with self.assertRaises(frappe.ValidationError):
			self._make_sub(
				"T4", status="trial", trial_end=add_days(now_datetime(), 7), cancel_at_period_end=1
			)

	def test_flag_ok_when_active(self):
		sub = self._make_sub("T5", cancel_at_period_end=1)
		self.assertEqual(int(sub.cancel_at_period_end), 1)
		self.assertEqual(sub.status, "active")
		self.assertFalse(sub.canceled_at)

	def test_flag_cleared_on_cancel_transition(self):
		"""'canceled'a geçişte bayrak sıfırlanır — reaktivasyona hayalet iptal planı taşınmaz."""
		sub = self._make_sub("T6", cancel_at_period_end=1)
		sub.status = "canceled"
		sub.save(ignore_permissions=True)
		self.assertEqual(int(sub.cancel_at_period_end), 0)
		self.assertIsNotNone(sub.canceled_at)

	# --- renewal reminder bayrakları (AC-9) ---

	def test_renewal_flags_reset_on_new_period(self):
		now = now_datetime()
		sub = self._make_sub("T7", current_period_start=now, current_period_end=add_months(now, 1))
		frappe.db.set_value(
			"Store Subscription",
			sub.name,
			{"renewal_reminder_7d_sent": 1, "renewal_reminder_1d_sent": 1},
			update_modified=False,
		)
		sub.reload()
		sub.current_period_start = add_months(now, 1)
		sub.current_period_end = add_months(now, 2)
		sub.save(ignore_permissions=True)
		self.assertEqual(int(sub.renewal_reminder_7d_sent), 0)
		self.assertEqual(int(sub.renewal_reminder_1d_sent), 0)

	def test_renewal_flags_kept_when_period_unchanged(self):
		now = now_datetime()
		sub = self._make_sub("T8", current_period_start=now, current_period_end=add_months(now, 1))
		frappe.db.set_value(
			"Store Subscription",
			sub.name,
			{"renewal_reminder_7d_sent": 1, "renewal_reminder_1d_sent": 1},
			update_modified=False,
		)
		sub.reload()
		sub.cancellation_note = "dönem değişmedi — bayraklar kalmalı"
		sub.save(ignore_permissions=True)
		self.assertEqual(int(sub.renewal_reminder_7d_sent), 1)
		self.assertEqual(int(sub.renewal_reminder_1d_sent), 1)

	# --- backfill patch (R1) ---

	def _strip_period(self, name: str) -> None:
		"""Backfill öncesi durumu simüle et: dönem alanları hiç yazılmamış."""
		frappe.db.set_value(
			"Store Subscription",
			name,
			{"current_period_start": None, "current_period_end": None},
			update_modified=False,
		)

	def test_backfill_yearly_payment_wins_over_monthly_default(self):
		"""R1 ZORUNLU vaka: sub.billing_cycle bayat default 'monthly', son onaylı ödeme
		'yearly' → dönem uzunluğu ödemeden alınır, sub.billing_cycle senkronlanır."""
		now = now_datetime()
		two_months_ago = add_months(now, -2)
		sub = self._make_sub("B1", started_at=two_months_ago)
		self._strip_period(sub.name)
		self.assertEqual(sub.billing_cycle, "monthly")  # bayat JSON default
		self._make_payment(sub.store, "yearly", two_months_ago)

		run_backfill()

		sub.reload()
		self.assertEqual(sub.billing_cycle, "yearly")  # R1: senkron
		# monthly default kullanılsaydı started_at+1 ay geçmişte kalır, floor'a düşerdi;
		# yearly ile started_at+12 ay gelecekte — dönem gerçek kaynaktan türedi.
		self.assertEqual(get_datetime(sub.current_period_end), get_datetime(add_months(two_months_ago, 12)))
		self.assertGreater(get_datetime(sub.current_period_end), now)

	def test_backfill_fallback_to_sub_cycle_without_payment(self):
		"""Onaylı ödeme yoksa sub.billing_cycle'a düşülür."""
		now = now_datetime()
		ten_days_ago = add_days(now, -10)
		sub = self._make_sub("B2", started_at=ten_days_ago)
		self._strip_period(sub.name)

		run_backfill()

		sub.reload()
		self.assertEqual(sub.billing_cycle, "monthly")
		self.assertEqual(get_datetime(sub.current_period_end), get_datetime(add_months(ten_days_ago, 1)))

	def test_backfill_recomputes_from_confirmed_at_when_past(self):
		"""Türetilen dönem geçmişteyse son onaylı ödemenin onay tarihinden yeniden hesap."""
		now = now_datetime()
		sub = self._make_sub("B3", started_at=add_months(now, -14))
		self._strip_period(sub.name)
		confirmed_at = add_months(now, -2)
		self._make_payment(sub.store, "yearly", confirmed_at)

		run_backfill()

		sub.reload()
		self.assertEqual(get_datetime(sub.current_period_start), get_datetime(confirmed_at))
		self.assertEqual(get_datetime(sub.current_period_end), get_datetime(add_months(confirmed_at, 12)))

	def test_backfill_floor_prevents_instant_past_due(self):
		"""R1 tabanı: her yol geçmişte kalıyorsa now+7 gün — aktif mağaza anında past_due olamaz."""
		now = now_datetime()
		sub = self._make_sub("B4", started_at=add_months(now, -30))
		self._strip_period(sub.name)
		self._make_payment(sub.store, "yearly", add_months(now, -14))  # +12 ay yine geçmişte

		run_backfill()

		sub.reload()
		end = get_datetime(sub.current_period_end)
		self.assertGreater(end, now)
		self.assertLessEqual(end, get_datetime(add_days(now, 8)))

	def test_backfill_idempotent(self):
		"""İkinci koşu hiçbir değeri değiştirmez (current_period_end dolu → filtre dışı)."""
		now = now_datetime()
		sub = self._make_sub("B5", started_at=add_days(now, -10))
		self._strip_period(sub.name)
		self._make_payment(sub.store, "yearly", add_days(now, -10))

		run_backfill()
		sub.reload()
		first_end = get_datetime(sub.current_period_end)
		first_cycle = sub.billing_cycle

		run_backfill()
		sub.reload()
		self.assertEqual(get_datetime(sub.current_period_end), first_end)
		self.assertEqual(sub.billing_cycle, first_cycle)
