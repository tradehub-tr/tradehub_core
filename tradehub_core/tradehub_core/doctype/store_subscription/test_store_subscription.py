# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Store Subscription — BE-1 testleri: geçiş matrisi + iptal bayrağı kuralları +
renewal reminder sıfırlama + R1'li current_period_end backfill patch'i.
BE-3 (AC-8) eki: cancel_requested_at dönem sonu finalize'ında korunur (tarihsel iz).
K2+M2 eki: merkezi vitrin senkronu — operasyonel→non-operasyonel geçişte hide,
non-operasyonel→active geçişte restore enqueue (expired/canceled dahil).

Çalıştırma:
	docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests \\
	  --module tradehub_core.tradehub_core.doctype.store_subscription.test_store_subscription
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, get_datetime, now_datetime

from tradehub_core.patches.v15_backfill_current_period_end import execute as run_backfill
from tradehub_core.services.storefront_visibility import hide_store_listings, restore_store_listings

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

	def test_cancel_requested_at_preserved_after_finalize(self):
		"""BE-3 / AC-8: dönem sonunda 'canceled'a geçişte (finalize) cancel_requested_at
		TEMİZLENMEZ — bayrak sıfırlanırken talep tarihi tarihsel iz olarak kalır."""
		requested_at = now_datetime()
		sub = self._make_sub("T9", cancel_at_period_end=1, cancel_requested_at=requested_at)
		self.assertEqual(get_datetime(sub.cancel_requested_at), get_datetime(requested_at))

		# finalize_cancellations ile aynı yol: state machine üzerinden doc.save.
		sub.status = "canceled"
		sub.save(ignore_permissions=True)
		self.assertEqual(int(sub.cancel_at_period_end), 0, "Bayrak finalize'da sıfırlanmalı")
		self.assertEqual(
			get_datetime(sub.cancel_requested_at),
			get_datetime(requested_at),
			"cancel_requested_at finalize'da KORUNMALI (tarihsel iz)",
		)

		sub.reload()
		self.assertEqual(get_datetime(sub.cancel_requested_at), get_datetime(requested_at))

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

	# --- dunning: geçiş matrisi + suspended alanları (BE-2 / D1 / D2) ---

	@contextmanager
	def _patched_enqueue(self):
		"""frappe.enqueue'yu yakala (D2 testleri) — gerçek kuyruk/worker'a iş gitmez."""
		calls: list[dict] = []
		original_enqueue = frappe.enqueue

		def _capture(method, **kwargs):
			calls.append({"method": method, "kwargs": kwargs})

		frappe.enqueue = _capture
		try:
			yield calls
		finally:
			frappe.enqueue = original_enqueue

	def _restore_calls(self, calls: list[dict]) -> list[dict]:
		return [c for c in calls if c["method"] is restore_store_listings]

	def _hide_calls(self, calls: list[dict]) -> list[dict]:
		return [c for c in calls if c["method"] is hide_store_listings]

	def test_suspended_to_expired_allowed(self):
		"""AC-7: suspended→expired geçişi state machine'e eklendi (T+30 dunning feshi)."""
		sub = self._make_sub("S1")
		sub.status = "suspended"
		sub.save(ignore_permissions=True)
		sub.reload()
		sub.status = "expired"
		sub.save(ignore_permissions=True)
		self.assertEqual(sub.status, "expired")

	def test_suspended_to_trial_blocked(self):
		"""suspended'dan yalnız active/canceled/expired'a çıkılır — trial'a dönüş yok."""
		sub = self._make_sub("S2")
		sub.status = "suspended"
		sub.save(ignore_permissions=True)
		sub.reload()
		sub.status = "trial"
		with self.assertRaises(frappe.ValidationError):
			sub.save(ignore_permissions=True)

	def test_suspended_to_past_due_blocked(self):
		"""suspended→past_due geçişi yok — hoşgörü penceresine geri dönüş tanımsız."""
		sub = self._make_sub("S3")
		sub.status = "suspended"
		sub.save(ignore_permissions=True)
		sub.reload()
		sub.status = "past_due"
		with self.assertRaises(frappe.ValidationError):
			sub.save(ignore_permissions=True)

	def test_expired_to_suspended_blocked(self):
		"""expired'dan suspended'a geçiş tanımsız kalır (yalnız active/canceled)."""
		sub = self._make_sub("S4")
		sub.status = "expired"
		sub.save(ignore_permissions=True)
		sub.reload()
		sub.status = "suspended"
		with self.assertRaises(frappe.ValidationError):
			sub.save(ignore_permissions=True)

	def test_suspended_at_stamped_on_suspend(self):
		"""'suspended'a geçişte suspended_at otomatik now damgalanır; kaynak default 'manual'."""
		sub = self._make_sub("S5")
		self.assertFalse(sub.suspended_at)
		sub.status = "suspended"
		sub.save(ignore_permissions=True)
		self.assertTrue(sub.suspended_at)
		self.assertEqual(sub.suspend_source, "manual")

	def test_suspend_source_dunning_not_overridden_by_validate(self):
		"""D1: lifecycle job'ı suspend ederken suspend_source='dunning' yazar — validate ezmemeli."""
		sub = self._make_sub("S6")
		sub.status = "suspended"
		sub.suspend_source = "dunning"
		sub.save(ignore_permissions=True)
		sub.reload()
		self.assertEqual(sub.suspend_source, "dunning")
		self.assertTrue(sub.suspended_at)

	def test_suspension_marks_cleared_on_exit_to_active(self):
		"""D1: suspended→active çıkışında suspended_at temizlenir, suspend_source 'manual'a döner."""
		sub = self._make_sub("S7")
		sub.status = "suspended"
		sub.suspend_source = "dunning"
		sub.save(ignore_permissions=True)
		sub.reload()
		with self._patched_enqueue():
			sub.status = "active"
			sub.save(ignore_permissions=True)
		self.assertFalse(sub.suspended_at)
		self.assertEqual(sub.suspend_source, "manual")

	def test_suspension_marks_cleared_on_exit_to_expired(self):
		"""Çıkış temizliği yalnız active'e özgü değil — suspended→expired'da da uygulanır."""
		sub = self._make_sub("S8")
		sub.status = "suspended"
		sub.suspend_source = "dunning"
		sub.save(ignore_permissions=True)
		sub.reload()
		sub.status = "expired"
		sub.save(ignore_permissions=True)
		self.assertFalse(sub.suspended_at)
		self.assertEqual(sub.suspend_source, "manual")

	def test_dunning_flags_reset_on_new_period(self):
		"""AC-2: yeni dönemde (current_period_start değişimi) dunning bayrakları sıfırlanır."""
		now = now_datetime()
		sub = self._make_sub("S9", current_period_start=now, current_period_end=add_months(now, 1))
		frappe.db.set_value(
			"Store Subscription",
			sub.name,
			{
				"dunning_reminder_1d_sent": 1,
				"dunning_reminder_3d_sent": 1,
				"dunning_reminder_7d_sent": 1,
			},
			update_modified=False,
		)
		sub.reload()
		sub.current_period_start = add_months(now, 1)
		sub.current_period_end = add_months(now, 2)
		sub.save(ignore_permissions=True)
		self.assertEqual(int(sub.dunning_reminder_1d_sent), 0)
		self.assertEqual(int(sub.dunning_reminder_3d_sent), 0)
		self.assertEqual(int(sub.dunning_reminder_7d_sent), 0)

	def test_dunning_flags_kept_when_period_unchanged(self):
		"""Dönem değişmeden dunning bayrakları sıfırlanmaz — cascade idempotency bozulmaz."""
		now = now_datetime()
		sub = self._make_sub("S10", current_period_start=now, current_period_end=add_months(now, 1))
		frappe.db.set_value(
			"Store Subscription",
			sub.name,
			{"dunning_reminder_1d_sent": 1, "dunning_reminder_3d_sent": 1},
			update_modified=False,
		)
		sub.reload()
		sub.cancellation_note = "dönem değişmedi — dunning bayrakları kalmalı"
		sub.save(ignore_permissions=True)
		self.assertEqual(int(sub.dunning_reminder_1d_sent), 1)
		self.assertEqual(int(sub.dunning_reminder_3d_sent), 1)

	def test_restore_enqueued_on_suspended_to_active(self):
		"""D2: suspended→active GERÇEK geçişinde restore_store_listings enqueue edilir."""
		sub = self._make_sub("S11")
		sub.status = "suspended"
		sub.save(ignore_permissions=True)
		sub.reload()
		with self._patched_enqueue() as calls:
			sub.status = "active"
			sub.save(ignore_permissions=True)
		restore_calls = self._restore_calls(calls)
		self.assertEqual(len(restore_calls), 1)
		kwargs = restore_calls[0]["kwargs"]
		self.assertEqual(kwargs.get("store"), sub.store)
		self.assertEqual(kwargs.get("queue"), "long")
		self.assertTrue(kwargs.get("enqueue_after_commit"))

	def test_no_restore_enqueue_on_plain_active_save(self):
		"""D2 negatif: active→active save'de (geçiş yok) restore enqueue EDİLMEZ."""
		sub = self._make_sub("S12")
		with self._patched_enqueue() as calls:
			sub.cancellation_note = "status geçişi yok"
			sub.save(ignore_permissions=True)
		self.assertEqual(self._restore_calls(calls), [])

	def test_no_restore_enqueue_on_suspended_save_without_transition(self):
		"""D2 negatif: suspended kalarak yapılan save restore tetiklemez."""
		sub = self._make_sub("S13")
		sub.status = "suspended"
		sub.save(ignore_permissions=True)
		sub.reload()
		with self._patched_enqueue() as calls:
			sub.cancellation_note = "hala suspended"
			sub.save(ignore_permissions=True)
		self.assertEqual(self._restore_calls(calls), [])

	# --- K2 + M2: merkezi vitrin senkronu (operasyonel ↔ non-operasyonel) ---

	def test_hide_enqueued_on_active_to_canceled(self):
		"""K2: iptal (hesap silme / dönem-sonu finalize yolu) vitrini KAPATIR."""
		sub = self._make_sub("V1")
		with self._patched_enqueue() as calls:
			sub.status = "canceled"
			sub.save(ignore_permissions=True)
		hide_calls = self._hide_calls(calls)
		self.assertEqual(len(hide_calls), 1)
		kwargs = hide_calls[0]["kwargs"]
		self.assertEqual(kwargs.get("store"), sub.store)
		self.assertEqual(kwargs.get("queue"), "long")
		self.assertTrue(kwargs.get("enqueue_after_commit"))

	def test_hide_enqueued_on_active_to_expired(self):
		"""K2: dönem bitişi feshi (expire_paid_periods yolu) vitrini KAPATIR."""
		sub = self._make_sub("V2")
		with self._patched_enqueue() as calls:
			sub.status = "expired"
			sub.save(ignore_permissions=True)
		self.assertEqual(len(self._hide_calls(calls)), 1)

	def test_hide_enqueued_on_trial_to_expired(self):
		"""K2: trial bitişi vitrini KAPATIR (expire_trials yolu)."""
		sub = self._make_sub("V3", status="trial", trial_end=add_days(now_datetime(), -1))
		with self._patched_enqueue() as calls:
			sub.status = "expired"
			sub.save(ignore_permissions=True)
		self.assertEqual(len(self._hide_calls(calls)), 1)

	def test_hide_enqueued_on_past_due_to_suspended(self):
		"""Merkezileşme: dunning suspend geçişi controller'dan da hide enqueue eder
		(job'ın kendi enqueue'su ayrıca kalır — hide idempotent, çift enqueue zararsız)."""
		sub = self._make_sub("V4")
		sub.status = "past_due"
		sub.save(ignore_permissions=True)
		sub.reload()
		with self._patched_enqueue() as calls:
			sub.status = "suspended"
			sub.save(ignore_permissions=True)
		self.assertEqual(len(self._hide_calls(calls)), 1)

	def test_no_hide_enqueue_on_suspended_to_expired(self):
		"""Non-op → non-op (T+30 dunning feshi): vitrin zaten kapalı, enqueue YOK."""
		sub = self._make_sub("V5")
		sub.status = "suspended"
		sub.save(ignore_permissions=True)
		sub.reload()
		with self._patched_enqueue() as calls:
			sub.status = "expired"
			sub.save(ignore_permissions=True)
		self.assertEqual(self._hide_calls(calls), [])
		self.assertEqual(self._restore_calls(calls), [])

	def test_restore_enqueued_on_expired_to_active(self):
		"""M2 ANA VAKA: dunning-expire sonrası ödeme (expired→active) vitrini GERİ AÇAR."""
		sub = self._make_sub("V6")
		sub.status = "expired"
		sub.save(ignore_permissions=True)
		sub.reload()
		with self._patched_enqueue() as calls:
			sub.status = "active"
			sub.save(ignore_permissions=True)
		restore_calls = self._restore_calls(calls)
		self.assertEqual(len(restore_calls), 1)
		kwargs = restore_calls[0]["kwargs"]
		self.assertEqual(kwargs.get("store"), sub.store)
		self.assertEqual(kwargs.get("queue"), "long")
		self.assertTrue(kwargs.get("enqueue_after_commit"))

	def test_restore_enqueued_on_canceled_to_active(self):
		"""M2: reaktivasyon (canceled→active, AC-14) vitrini GERİ AÇAR."""
		sub = self._make_sub("V7")
		sub.status = "canceled"
		sub.save(ignore_permissions=True)
		sub.reload()
		with self._patched_enqueue() as calls:
			sub.status = "active"
			sub.save(ignore_permissions=True)
		self.assertEqual(len(self._restore_calls(calls)), 1)

	def test_no_enqueue_on_trial_to_active(self):
		"""Operasyonel-içi geçiş: vitrin hiç kapanmadı → restore da hide da enqueue edilmez."""
		sub = self._make_sub("V8", status="trial", trial_end=add_days(now_datetime(), 7))
		with self._patched_enqueue() as calls:
			sub.status = "active"
			sub.save(ignore_permissions=True)
		self.assertEqual(self._restore_calls(calls), [])
		self.assertEqual(self._hide_calls(calls), [])

	def test_no_enqueue_on_active_to_past_due(self):
		"""Operasyonel-içi geçiş (hoşgörü penceresi): vitrin AÇIK kalır, enqueue YOK."""
		sub = self._make_sub("V9")
		with self._patched_enqueue() as calls:
			sub.status = "past_due"
			sub.save(ignore_permissions=True)
		self.assertEqual(self._restore_calls(calls), [])
		self.assertEqual(self._hide_calls(calls), [])

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
