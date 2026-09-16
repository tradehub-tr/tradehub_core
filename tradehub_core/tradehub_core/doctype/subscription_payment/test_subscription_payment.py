# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Subscription Payment — M3 testleri: durum geçiş matrisi + terminal dondurma.

Korunan mevcut akışlar (regresyon):
  * create_bank_transfer_request pending kayıtta amount/plan/cycle tazeler (AC-5)
    → pending'de finansal alanlar serbest kalmalı.
  * Backfill patch'i + test fixture'ları doğrudan status='confirmed' insert eder
    → yeni kayıtta geçiş kontrolü yok.
  * identity.py hesap silme akışı pending→rejected yazar (db.set_value ile
    validate'siz; geçiş yine de tabloda tanımlı).

Çalıştırma:
	docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests \\
	  --module tradehub_core.tradehub_core.doctype.subscription_payment.test_subscription_payment
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

_USER_EMAIL = "spay-test-owner@example.com"
_STORE_PREFIX = "SPAYTEST-"


class TestSubscriptionPayment(FrappeTestCase):
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

	# --- fixtures (test_store_subscription deseni) ---

	@classmethod
	def _ensure_user(cls, email: str = _USER_EMAIL) -> None:
		if frappe.db.exists("User", email):
			return
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "SPay Test"
		user.send_welcome_email = 0
		user.insert(ignore_permissions=True)

	def _cleanup(self) -> None:
		frappe.db.delete("Subscription Payment", {"store": ["like", f"{_STORE_PREFIX}%"]})
		frappe.db.commit()

	def _make_store(self, code: str) -> str:
		name = f"{_STORE_PREFIX}{code}"
		# Admin Seller Profile.user unique — mağaza başına türetilmiş ayrı kullanıcı.
		owner_email = f"spay-test-{code.lower()}@example.com"
		self._ensure_user(owner_email)
		if not frappe.db.exists("Admin Seller Profile", name):
			profile = frappe.new_doc("Admin Seller Profile")
			profile.seller_code = name
			profile.seller_name = f"SPay Test Mağaza {code}"
			profile.user = owner_email
			profile.email = owner_email
			profile.insert(ignore_permissions=True)
		return name

	def _make_payment(self, code: str, status: str = "pending", **kwargs) -> Document:
		payment = frappe.new_doc("Subscription Payment")
		payment.store = self._make_store(code)
		payment.plan = self.plan
		payment.billing_cycle = kwargs.pop("billing_cycle", "yearly")
		payment.amount = kwargs.pop("amount", 7188.0)
		payment.currency = kwargs.pop("currency", "EUR")
		payment.status = status
		for key, value in kwargs.items():
			payment.set(key, value)
		payment.insert(ignore_permissions=True)
		return payment

	def _second_plan(self) -> str | None:
		"""Plan dondurma testi için farklı bir plan (yoksa None → skip)."""
		rows = frappe.get_all("Subscription Plan", filters={"name": ["!=", self.plan]}, limit_page_length=1)
		return rows[0].name if rows else None

	# --- geçiş matrisi ---

	def test_pending_to_confirmed_allowed(self):
		payment = self._make_payment("T1")
		payment.status = "confirmed"
		payment.save(ignore_permissions=True)
		self.assertEqual(payment.status, "confirmed")

	def test_pending_to_rejected_allowed(self):
		"""identity.py hesap silme akışıyla aynı geçiş — kırılmamalı."""
		payment = self._make_payment("T2")
		payment.status = "rejected"
		payment.rejection_reason = "account_deleted"
		payment.save(ignore_permissions=True)
		self.assertEqual(payment.status, "rejected")

	def test_pending_to_canceled_allowed(self):
		"""'canceled' şemadaki Desk seçeneği — pending'den erişilebilir kalır."""
		payment = self._make_payment("T3")
		payment.status = "canceled"
		payment.save(ignore_permissions=True)
		self.assertEqual(payment.status, "canceled")

	def test_confirmed_to_pending_blocked(self):
		"""M3 çekirdek vaka: confirmed→pending geri açma = tek havaleye iki dönem."""
		payment = self._make_payment("T4", status="confirmed")
		payment.status = "pending"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_confirmed_to_rejected_blocked(self):
		payment = self._make_payment("T5", status="confirmed")
		payment.status = "rejected"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_rejected_to_pending_blocked(self):
		payment = self._make_payment("T6", status="rejected")
		payment.status = "pending"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_rejected_to_confirmed_blocked(self):
		payment = self._make_payment("T7", status="rejected")
		payment.status = "confirmed"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_canceled_to_pending_blocked(self):
		"""canceled da terminal — geri açma yok, yeni talep yeni kayıt."""
		payment = self._make_payment("T8", status="canceled")
		payment.status = "pending"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_direct_confirmed_insert_allowed(self):
		"""Yeni kayıtta geçiş kontrolü yok — backfill/test fixture yolu korunur
		(bkz. test_store_subscription._make_payment: doğrudan confirmed insert)."""
		payment = self._make_payment("T9", status="confirmed")
		self.assertEqual(payment.status, "confirmed")

	# --- terminal dondurma ---

	def test_confirmed_amount_frozen(self):
		payment = self._make_payment("F1", status="confirmed")
		payment.amount = 990.0
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_confirmed_currency_frozen(self):
		payment = self._make_payment("F2", status="confirmed")
		payment.currency = "USD"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_confirmed_billing_cycle_frozen(self):
		payment = self._make_payment("F3", status="confirmed", billing_cycle="yearly")
		payment.billing_cycle = "monthly"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_confirmed_reference_code_frozen(self):
		payment = self._make_payment("F4", status="confirmed")
		payment.reference_code = f"{payment.reference_code}-X"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_confirmed_store_frozen(self):
		payment = self._make_payment("F5", status="confirmed")
		payment.store = self._make_store("F5B")
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_confirmed_plan_frozen(self):
		other_plan = self._second_plan()
		if not other_plan:
			self.skipTest("İkinci Subscription Plan yok — plan dondurma testi atlandı")
		payment = self._make_payment("F6", status="confirmed")
		payment.plan = other_plan
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_confirmed_notes_editable(self):
		"""notes dondurma DIŞI — finansal etkisi olmayan açıklama alanı."""
		payment = self._make_payment("F7", status="confirmed")
		payment.notes = "havale dekontu arşivlendi"
		payment.save(ignore_permissions=True)
		payment.reload()
		self.assertEqual(payment.notes, "havale dekontu arşivlendi")

	def test_confirmed_noop_save_allowed(self):
		"""Alan değişmeden save (örn. Desk'te kaydet) throw etmemeli."""
		payment = self._make_payment("F8", status="confirmed")
		payment.reload()
		payment.save(ignore_permissions=True)  # değişiklik yok — geçmeli
		self.assertEqual(payment.status, "confirmed")

	def test_rejected_amount_frozen(self):
		payment = self._make_payment("F9", status="rejected")
		payment.amount = 1.0
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_rejected_reason_editable(self):
		"""rejection_reason dondurma DIŞI — admin ret gerekçesini sonradan
		düzeltebilmeli (finansal etki yok; track_changes izi tutar)."""
		payment = self._make_payment("F10", status="rejected", rejection_reason="ilk gerekçe")
		payment.rejection_reason = "düzeltilmiş gerekçe"
		payment.save(ignore_permissions=True)
		payment.reload()
		self.assertEqual(payment.rejection_reason, "düzeltilmiş gerekçe")

	def test_pending_financial_fields_free(self):
		"""AC-5 regresyon: create_bank_transfer_request bekleyen talebin
		amount/plan/cycle/currency alanlarını tazeler — pending'de serbest."""
		payment = self._make_payment("F11", amount=5990.0, billing_cycle="yearly")
		payment.amount = 7188.0
		payment.billing_cycle = "monthly"
		payment.currency = "EUR"
		payment.save(ignore_permissions=True)
		payment.reload()
		self.assertEqual(float(payment.amount), 7188.0)
		self.assertEqual(payment.billing_cycle, "monthly")
		self.assertEqual(payment.status, "pending")

	def test_confirm_transition_save_may_set_audit_fields(self):
		"""confirm API deseni: pending→confirmed geçiş save'i confirmed_at/by yazar
		— dondurma ancak SONRAKİ save'lerde devreye girer."""
		payment = self._make_payment("F12")
		payment.status = "confirmed"
		payment.confirmed_by = "Administrator"
		payment.save(ignore_permissions=True)
		self.assertEqual(payment.status, "confirmed")

		# Artık terminal: finansal alan değişimi bloklu.
		payment.reload()
		payment.amount = 1.0
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	# --- before_insert korunumu ---

	def test_reference_code_autogenerated(self):
		payment = self._make_payment("R1")
		self.assertTrue(payment.reference_code)
		self.assertTrue(payment.reference_code.startswith(f"ISTOC-{payment.store}-"))
		self.assertTrue(payment.requested_at)
