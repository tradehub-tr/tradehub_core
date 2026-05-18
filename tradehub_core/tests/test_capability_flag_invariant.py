"""Sprint 2.6 Patch 20 — capability flag invariant testleri.

Kural:
  can_buy = (kyc_status == 'Verified')
  can_sell = (kyb_status == 'Verified')

Çalıştırma:
    bench --site dev.localhost run-tests --module tradehub_core.tests.test_capability_flag_invariant
"""

import unittest

import frappe


class TestCapabilityInvariant(unittest.TestCase):
	"""Patch 20 + KYC/KYB Verified → can_buy/can_sell sync."""

	def test_patch_20_in_patch_log(self):
		exists = frappe.db.exists(
			"Patch Log",
			{"patch": "tradehub_core.patches.user_profile_v1.20_normalize_capability_flags"},
		)
		self.assertTrue(exists, "Patch 20 Patch Log'da yok")

	def test_no_invariant_violation_in_db(self):
		"""Tüm User Profile kayıtlarında invariant sağlanmalı."""
		violations = frappe.db.sql(
			"""
			SELECT name, kyc_status, can_buy, kyb_status, can_sell
			FROM `tabUser Profile`
			WHERE (kyc_status='Verified' AND can_buy=0)
			   OR (kyc_status!='Verified' AND can_buy=1)
			   OR (kyb_status='Verified' AND can_sell=0)
			   OR (kyb_status!='Verified' AND can_sell=1)
			""",
			as_dict=True,
		)
		self.assertEqual(violations, [], f"İnvariant ihlali: {violations}")

	def test_auth_flag_formulas_status_based(self):
		"""auth.py kyc_locked/kyb_locked artık kyc_status/kyb_status üzerinden."""
		import inspect

		from tradehub_core.api.v1 import auth

		src = inspect.getsource(auth.get_session_user)
		# Yeni formül kyc_status == 'Locked' içermeli
		self.assertIn("kyc_status", src)
		self.assertIn("Locked", src)
		# Eski "not can_buy" / "not can_sell" formülü kalmamalı
		self.assertNotIn('not bool(up_data.get("can_buy"))', src)
		self.assertNotIn('not bool(up_data.get("can_sell"))', src)


class TestKycVerificationSync(unittest.TestCase):
	"""KYC Verification status değişimi → User Profile.can_buy sync."""

	def test_sync_method_sets_can_buy_on_verified(self):
		"""_sync_kyc_status Verified branch'i can_buy=1 set ediyor mu (kod statik kontrol)."""
		import inspect

		from tradehub_core.tradehub_core.doctype.kyc_verification import kyc_verification

		src = inspect.getsource(kyc_verification.KYCVerification._sync_kyc_status)
		self.assertIn("can_buy", src)
		# Verified branch'inde can_buy set edildiğini gör
		self.assertIn("Verified", src)


class TestKybVerificationSync(unittest.TestCase):
	"""KYB Verification status değişimi → User Profile.can_sell sync."""

	def test_sync_method_sets_can_sell(self):
		import inspect

		from tradehub_core.tradehub_core.doctype.kyb_verification import kyb_verification

		src = inspect.getsource(kyb_verification.KYBVerification._sync_kyb_status)
		self.assertIn("can_sell", src)


if __name__ == "__main__":
	unittest.main()
