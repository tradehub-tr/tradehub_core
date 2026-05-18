"""Sprint 2.6 — KYC Verification controller business kuralları.

Frappe runtime stub ile pure-python unit tests:
	cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_kyc_verification
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _FrappeValidationError(Exception):
	pass


def _install_frappe_stub() -> None:
	if "frappe" in sys.modules:
		return

	frappe = types.ModuleType("frappe")
	frappe.db = types.SimpleNamespace(
		get_value=lambda *a, **kw: None,
		set_value=lambda *a, **kw: None,
		sql=lambda *a, **kw: [],
		escape=lambda s: f"'{s}'",
	)
	frappe.session = types.SimpleNamespace(user="Administrator")
	frappe.flags = types.SimpleNamespace()
	frappe._ = lambda s: s

	def _throw(msg, title=None, exc=None):
		raise _FrappeValidationError(msg)

	frappe.throw = _throw
	frappe.ValidationError = _FrappeValidationError
	frappe.log_error = lambda title=None, message=None: None
	frappe.get_traceback = lambda: ""

	model_mod = types.ModuleType("frappe.model")
	doc_mod = types.ModuleType("frappe.model.document")

	class _Document:
		def __init__(self, **kw):
			for k, v in kw.items():
				setattr(self, k, v)

		def is_new(self):
			return getattr(self, "_is_new", True)

		def has_value_changed(self, fieldname):
			return getattr(self, "_changed_fields", set()).__contains__(fieldname)

		def get_doc_before_save(self):
			return None

		def db_set(self, field, value, update_modified=True):
			setattr(self, field, value)

	doc_mod.Document = _Document
	sys.modules["frappe.model"] = model_mod
	sys.modules["frappe.model.document"] = doc_mod

	utils_mod = types.ModuleType("frappe.utils")
	utils_mod.now_datetime = lambda: "2026-05-15 12:00:00"
	utils_mod.cint = int
	utils_mod.flt = float

	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = utils_mod


_install_frappe_stub()


from tradehub_core.tradehub_core.doctype.kyc_verification.kyc_verification import (  # noqa: E402
	KYCVerification,
	_validate_tckn,
	_validate_vkn,
)


def _make_kyc(**overrides) -> KYCVerification:
	defaults = {
		"name": "KYC-00001",
		"user": "test@example.com",
		"account_type": "Individual",
		"status": "Pending",
		"identity_document": "/files/kimlik.pdf",
		"tax_id": "12345678901",
		"phone": "+90 555 555 55 55",
		"email_field": "test@example.com",
		"address": "Test adres",
		"billing_address": "Test fatura",
		"company_name": "",
		"rejection_reason": "",
		"rejection_category": "",
		"_is_new": False,
		"_changed_fields": set(),
	}
	defaults.update(overrides)
	return KYCVerification(**defaults)


class VKNValidationTests(unittest.TestCase):
	"""Kurumsal hesap için VKN (10-11 hane, format only)."""

	def test_vkn_10_digits_valid(self):
		_validate_vkn("1234567890")  # raise etmemeli

	def test_vkn_11_digits_valid(self):
		_validate_vkn("12345678901")  # raise etmemeli

	def test_vkn_9_digits_fails(self):
		with self.assertRaises(_FrappeValidationError):
			_validate_vkn("123456789")

	def test_vkn_12_digits_fails(self):
		with self.assertRaises(_FrappeValidationError):
			_validate_vkn("123456789012")

	def test_vkn_non_numeric_fails(self):
		with self.assertRaises(_FrappeValidationError):
			_validate_vkn("123456789A")


class TCKNValidationTests(unittest.TestCase):
	"""Bireysel hesap için TCKN (11 hane + mod-10 algoritma)."""

	def test_valid_tckn_passes(self):
		# Geçerli TCKN örneği (algoritmaya uygun)
		_validate_tckn("12345678950")  # 1+3+5+7+9=25; 2+4+6+8=20; (25*7-20)%10=5; sum(:10)%10=5

	def test_tckn_starts_with_zero_fails(self):
		with self.assertRaises(_FrappeValidationError):
			_validate_tckn("01234567890")

	def test_tckn_too_short_fails(self):
		with self.assertRaises(_FrappeValidationError):
			_validate_tckn("1234567890")

	def test_tckn_too_long_fails(self):
		with self.assertRaises(_FrappeValidationError):
			_validate_tckn("123456789012")

	def test_tckn_invalid_checksum_fails(self):
		# 11 hane ama mod-10 algoritması fail eder
		with self.assertRaises(_FrappeValidationError):
			_validate_tckn("12345678901")


class RequiredFieldsTests(unittest.TestCase):
	"""Sprint 2.6 — Bireysel + Kurumsal ortak zorunlu alanlar."""

	def test_individual_with_all_required_passes(self):
		"""Bireysel: tax_id+phone+address+billing_address+identity yeterli, company_name yok."""
		doc = _make_kyc(account_type="Individual", company_name="", tax_id="12345678950")
		doc._validate_required_fields()  # raise etmemeli

	def test_individual_missing_phone_fails(self):
		doc = _make_kyc(account_type="Individual", phone="")
		with self.assertRaises(_FrappeValidationError):
			doc._validate_required_fields()

	def test_individual_missing_address_fails(self):
		doc = _make_kyc(account_type="Individual", address="")
		with self.assertRaises(_FrappeValidationError):
			doc._validate_required_fields()

	def test_business_requires_company_name(self):
		doc = _make_kyc(account_type="Business", company_name="")
		with self.assertRaises(_FrappeValidationError):
			doc._validate_required_fields()

	def test_business_with_all_required_passes(self):
		doc = _make_kyc(account_type="Business", company_name="ACME Ltd")
		doc._validate_required_fields()  # raise etmemeli


class IdentityDocumentTests(unittest.TestCase):
	def test_missing_identity_fails(self):
		doc = _make_kyc(identity_document="")
		with self.assertRaises(_FrappeValidationError):
			doc._validate_identity_document()

	def test_unsupported_extension_fails(self):
		doc = _make_kyc(identity_document="/files/kimlik.exe")
		with self.assertRaises(_FrappeValidationError):
			doc._validate_identity_document()

	def test_pdf_extension_passes(self):
		doc = _make_kyc(identity_document="/files/kimlik.pdf")
		doc._validate_identity_document()  # raise etmemeli

	def test_jpg_extension_passes(self):
		doc = _make_kyc(identity_document="/files/kimlik.jpg")
		doc._validate_identity_document()  # raise etmemeli


class RejectionReasonTests(unittest.TestCase):
	def test_rejected_without_reason_fails(self):
		doc = _make_kyc(status="Rejected", rejection_reason="", rejection_category="")
		with self.assertRaises(_FrappeValidationError):
			doc._validate_rejection_reason()

	def test_rejected_short_reason_fails(self):
		doc = _make_kyc(status="Rejected", rejection_reason="kısa", rejection_category="Re-submit")
		with self.assertRaises(_FrappeValidationError):
			doc._validate_rejection_reason()

	def test_rejected_with_full_reason_passes(self):
		doc = _make_kyc(
			status="Rejected",
			rejection_reason="Belge bulanık, yeniden çekip yükleyin lütfen.",
			rejection_category="Re-submit",
		)
		doc._validate_rejection_reason()  # raise etmemeli

	def test_rejected_without_category_fails(self):
		doc = _make_kyc(
			status="Rejected",
			rejection_reason="Belge bulanık, yeniden çekip yükleyin lütfen.",
			rejection_category="",
		)
		with self.assertRaises(_FrappeValidationError):
			doc._validate_rejection_reason()


if __name__ == "__main__":
	unittest.main()
