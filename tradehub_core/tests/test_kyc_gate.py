"""Sprint 2.6 (revised) — _ensure_buyer_kyc_verified gate testleri.

Backend gate frontend KycRequiredModal'a `[KYC_<STATE>]` prefix'li mesaj döndürür.
Frontend bu prefix'i regex ile parse edip state-bazlı modal gösterir.

Çalıştırma:
    bench --site dev.localhost run-tests --module tradehub_core.tests.test_kyc_gate
"""

import re
import unittest

import frappe

KYC_PREFIX_RE = re.compile(r"\[KYC_(LOCKED|PENDING|REJECTED|SUSPENDED)\]")


class TestKycGate(unittest.TestCase):
	"""Her state için doğru prefix'li exception."""

	@classmethod
	def setUpClass(cls):
		# Test izolasyonu için tmp user yarat
		cls.tmp_user = "test_kyc_gate@istoc-test.local"
		if not frappe.db.exists("User", cls.tmp_user):
			user = frappe.new_doc("User")
			user.email = cls.tmp_user
			user.first_name = "TestKYCGate"
			user.send_welcome_email = 0
			user.flags.ignore_permissions = True
			user.insert(ignore_permissions=True)
		# User Profile yarat (autoname=field:user)
		if not frappe.db.exists("User Profile", {"user": cls.tmp_user}):
			up = frappe.new_doc("User Profile")
			up.user = cls.tmp_user
			up.full_name = "Test KYC Gate"
			up.account_type = "Individual"
			up.flags.ignore_permissions = True
			up.insert(ignore_permissions=True)
		cls.up_name = frappe.db.get_value("User Profile", {"user": cls.tmp_user}, "name")

	@classmethod
	def tearDownClass(cls):
		# Cleanup
		if cls.up_name:
			frappe.delete_doc("User Profile", cls.up_name, ignore_permissions=True, force=True)
		if frappe.db.exists("User", cls.tmp_user):
			frappe.delete_doc("User", cls.tmp_user, ignore_permissions=True, force=True)
		frappe.db.commit()

	def _set_kyc_status(self, status):
		frappe.db.set_value("User Profile", self.up_name, "kyc_status", status)
		frappe.db.commit()

	def _assert_prefix(self, kyc_status, expected_prefix):
		from tradehub_core.api.cart import _ensure_buyer_kyc_verified

		self._set_kyc_status(kyc_status)
		try:
			_ensure_buyer_kyc_verified(self.tmp_user)
			self.fail(f"kyc_status={kyc_status} ile gate geçti — beklenmedik")
		except frappe.ValidationError as ve:
			msg = str(ve)
			m = KYC_PREFIX_RE.search(msg)
			self.assertIsNotNone(m, f"Prefix yok: {msg}")
			self.assertEqual(
				m.group(1),
				expected_prefix,
				f"kyc_status={kyc_status} → prefix={m.group(1)}, beklenen={expected_prefix}",
			)

	def test_locked_state(self):
		self._assert_prefix("Locked", "LOCKED")

	def test_pending_state(self):
		self._assert_prefix("Pending", "PENDING")

	def test_rejected_state(self):
		self._assert_prefix("Rejected", "REJECTED")

	def test_suspended_state(self):
		self._assert_prefix("Suspended", "SUSPENDED")

	def test_under_review_treated_as_pending(self):
		# 'Under Review' bir alt state olarak PENDING grubunda kabul edilmeli
		self._assert_prefix("Under Review", "PENDING")

	def test_verified_passes(self):
		from tradehub_core.api.cart import _ensure_buyer_kyc_verified

		self._set_kyc_status("Verified")
		# throw etmemeli
		try:
			_ensure_buyer_kyc_verified(self.tmp_user)
		except frappe.ValidationError as ve:
			self.fail(f"Verified kullanıcı için gate throw etti: {ve}")

	def test_null_or_empty_treated_as_locked(self):
		# kyc_status NULL → fallback Locked davranışı
		self._set_kyc_status(None)
		from tradehub_core.api.cart import _ensure_buyer_kyc_verified

		try:
			_ensure_buyer_kyc_verified(self.tmp_user)
			self.fail("kyc_status=NULL ile gate geçti — beklenmedik")
		except frappe.ValidationError as ve:
			msg = str(ve)
			m = KYC_PREFIX_RE.search(msg)
			self.assertIsNotNone(m, "NULL kyc_status için prefix yok")
			# Locked fallback davranışı
			self.assertEqual(m.group(1), "LOCKED")

	def test_guest_returns_silently(self):
		"""Guest kullanıcı için gate sessizce geçer (cart akışı başka yerde guard'lar)."""
		from tradehub_core.api.cart import _ensure_buyer_kyc_verified

		try:
			_ensure_buyer_kyc_verified("Guest")
			# OK — guest için throw beklemiyoruz
		except frappe.ValidationError as ve:
			self.fail(f"Guest için gate throw etti: {ve}")


if __name__ == "__main__":
	unittest.main()
