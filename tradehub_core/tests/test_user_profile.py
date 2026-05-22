"""Sprint 2 — User Profile DocType business kuralları (Tier 3.4).

Frappe runtime stub ile pure-python unit tests:

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_user_profile
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

	# DB stub — testler get_value değerlerini override eder
	frappe.db = types.SimpleNamespace(
		get_value=lambda *a, **kw: None,
		set_value=lambda *a, **kw: None,
		sql=lambda *a, **kw: [],
		escape=lambda s: f"'{s}'",
	)

	frappe.session = types.SimpleNamespace(user="Administrator")
	frappe.flags = types.SimpleNamespace()

	# i18n stub
	frappe._ = lambda s: s

	# throw → ValidationError
	def _throw(msg, title=None, exc=None):
		raise _FrappeValidationError(msg)

	frappe.throw = _throw
	frappe.ValidationError = _FrappeValidationError
	frappe.log_error = lambda title=None, message=None: None
	frappe.get_traceback = lambda: ""

	# Document base class — minimum stub
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

	doc_mod.Document = _Document
	sys.modules["frappe.model"] = model_mod
	sys.modules["frappe.model.document"] = doc_mod

	utils_mod = types.ModuleType("frappe.utils")
	utils_mod.now_datetime = lambda: "2026-05-14 12:00:00"
	utils_mod.cint = int
	utils_mod.flt = float

	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = utils_mod


_install_frappe_stub()

import frappe  # noqa: E402
from frappe import _  # noqa: F401, E402

from tradehub_core.tradehub_core.doctype.user_profile.user_profile import UserProfile  # noqa: E402


def _make_profile(**overrides) -> UserProfile:
	defaults = {
		"name": "ali@x.com",
		"user": "ali@x.com",
		"can_buy": 1,
		"can_sell": 0,
		"account_type": "Individual",
		"email_verified": 1,
		"email_verified_at": "2026-05-01 10:00:00",
		"email_verified_method": "otp",
		"member_id": "UP-000001",
		"created_via": "registration",
		"joined_at": "2026-04-01 09:00:00",
		"status": "Active",
		"_is_new": False,
		"_changed_fields": set(),
	}
	defaults.update(overrides)
	return UserProfile(**defaults)


class AccountTypeRulesTests(unittest.TestCase):
	def test_seller_requires_business_account(self):
		"""can_sell=1 + account_type=Individual → ValidationError."""
		profile = _make_profile(can_sell=1, account_type="Individual")
		with self.assertRaises(_FrappeValidationError):
			profile._validate_account_type_for_seller()

	def test_seller_with_business_account_passes(self):
		"""can_sell=1 + account_type=Business → OK (KYB için vergi levhası şart)."""
		profile = _make_profile(can_sell=1, account_type="Business")
		profile._validate_account_type_for_seller()  # raise etmemeli

	def test_business_to_individual_downgrade_forbidden(self):
		"""Mevcut Business kullanıcı Individual'a dönemez (Order fatura tutarlılığı)."""
		profile = _make_profile(account_type="Individual", _is_new=False)
		frappe.db.get_value = lambda dt, name, field: "Business" if field == "account_type" else None
		with self.assertRaises(_FrappeValidationError):
			profile._validate_account_type_no_downgrade()

	def test_individual_to_business_upgrade_allowed(self):
		"""Individual → Business upgrade serbest (KYC tetiklenir)."""
		profile = _make_profile(account_type="Business", _is_new=False)
		frappe.db.get_value = lambda dt, name, field: "Individual" if field == "account_type" else None
		profile._validate_account_type_no_downgrade()  # raise etmemeli

	def test_new_profile_skips_downgrade_check(self):
		"""is_new=True ise old değer DB'de yok, kontrol atlanır."""
		profile = _make_profile(_is_new=True)
		profile._validate_account_type_no_downgrade()  # raise etmemeli


class MemberIdGenerationTests(unittest.TestCase):
	def test_member_id_format_first_record(self):
		"""İlk kayıt için UP-000001 üretilir."""
		profile = _make_profile(member_id="", _is_new=True)
		frappe.db.sql = lambda *a, **kw: []
		generated = profile._generate_member_id()
		self.assertEqual(generated, "UP-000001")
		self.assertRegex(generated, r"^UP-\d{6}$")

	def test_member_id_format_increment(self):
		"""Mevcut UP-000004 sonrası UP-000005 üretilir."""
		profile = _make_profile(_is_new=True, member_id="")
		frappe.db.sql = lambda *a, **kw: [("UP-000004",)]
		generated = profile._generate_member_id()
		self.assertEqual(generated, "UP-000005")
		self.assertRegex(generated, r"^UP-\d{6}$")


class HybridCapabilityTests(unittest.TestCase):
	def test_hybrid_user_buyer_and_seller(self):
		"""can_buy=1 + can_sell=1 + Business → geçerli (hibrit kullanıcı)."""
		profile = _make_profile(can_buy=1, can_sell=1, account_type="Business")
		profile._validate_account_type_for_seller()  # raise etmemeli

	def test_pure_buyer_individual_ok(self):
		"""can_buy=1 + can_sell=0 + Individual → geçerli (varsayılan buyer)."""
		profile = _make_profile(can_buy=1, can_sell=0, account_type="Individual")
		profile._validate_account_type_for_seller()  # raise etmemeli


if __name__ == "__main__":
	unittest.main()
