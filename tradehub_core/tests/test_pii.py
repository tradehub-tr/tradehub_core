"""FAZ 1.3 — PII helper unit testleri.

tradehub_core.utils.pii içindeki:
  - mask_value (tax_id, iban, phone, email, identity, generic)
  - has_pii_access
  - get_user_max_permlevel
  - get_pii_fieldnames

için saf-Python testler. Frappe stub'lanır.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_pii
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_DB_STATE: dict = {}


def _install_frappe_stub() -> None:
	"""Idempotent frappe stub — diğer test'lerin set ettiğine zarar vermeden override."""
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	# DB API — exists ve get_all'i bizim DB state'imize bağla
	def db_exists(doctype, filters=None):
		key = ("exists", doctype, str(filters))
		return _DB_STATE.get(key, False)

	frappe.db = SimpleNamespace(
		exists=db_exists,
		get_value=lambda *a, **kw: None,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		has_column=lambda *a, **kw: True,
	)

	# get_all
	def get_all(doctype, filters=None, pluck=None, fields=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck, str(fields))
		return _DB_STATE.get(key, [])

	frappe.get_all = get_all

	# Session
	frappe.session = SimpleNamespace(user="seller-a@x.com")

	# Roles — runtime override edilebilir
	frappe.get_roles = lambda u: _DB_STATE.get(("roles", u), [])

	# i18n + exceptions
	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class PermissionError(Exception):
			pass

		frappe.PermissionError = PermissionError
	if not hasattr(frappe, "throw"):

		def _throw(msg, exc=Exception):
			raise exc(msg) if isinstance(exc, type) else Exception(msg)

		frappe.throw = _throw
	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None

	# Utils
	if not hasattr(frappe, "utils"):
		frappe.utils = types.ModuleType("frappe.utils")
		frappe.utils.cint = int
		frappe.utils.flt = float
		sys.modules["frappe.utils"] = frappe.utils


_install_frappe_stub()


def _reset_state() -> None:
	_DB_STATE.clear()
	_install_frappe_stub_force()


def _install_frappe_stub_force() -> None:
	frappe = sys.modules["frappe"]

	def db_exists(doctype, filters=None):
		key = ("exists", doctype, str(filters))
		return _DB_STATE.get(key, False)

	def get_all(doctype, filters=None, pluck=None, fields=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck, str(fields))
		return _DB_STATE.get(key, [])

	frappe.db = SimpleNamespace(
		exists=db_exists,
		get_value=lambda *a, **kw: None,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		has_column=lambda *a, **kw: True,
	)
	frappe.get_all = get_all
	frappe.get_roles = lambda u: _DB_STATE.get(("roles", u), [])


from tradehub_core.utils import pii  # noqa: E402

# ---------------------------------------------------------------------------
# mask_value
# ---------------------------------------------------------------------------


class MaskValueTests(unittest.TestCase):
	def test_empty_returns_empty(self):
		self.assertEqual(pii.mask_value("", "tax_id"), "")
		self.assertEqual(pii.mask_value(None, "tax_id"), "")

	def test_tax_id_last_4(self):
		"""1234567890 → ******7890"""
		self.assertEqual(pii.mask_value("1234567890", "tax_id"), "******7890")

	def test_tax_id_short(self):
		"""123 → *** (kısa değer → tamamı *)"""
		self.assertEqual(pii.mask_value("123", "tax_id"), "***")

	def test_phone_last_4(self):
		"""+905321234567 → *********4567"""
		self.assertEqual(pii.mask_value("+905321234567", "phone"), "*********4567")

	def test_identity_first_3(self):
		"""12345678901 → 123********"""
		self.assertEqual(pii.mask_value("12345678901", "identity"), "123********")

	def test_email(self):
		"""ahmet.yilmaz@firma.com → a***********@firma.com"""
		self.assertEqual(pii.mask_value("ahmet.yilmaz@firma.com", "email"), "a***********@firma.com")

	def test_email_short_local(self):
		"""a@x.com → a***@x.com"""
		self.assertEqual(pii.mask_value("a@x.com", "email"), "a***@x.com")

	def test_email_without_at(self):
		"""@ yoksa generic maskeleme"""
		result = pii.mask_value("notanemail", "email")
		self.assertTrue(result.startswith("n"))
		self.assertTrue(result.endswith("l"))
		self.assertIn("*", result)

	def test_iban(self):
		"""TR120006200012345678901234 → TR12 **** **** **** **** **34"""
		result = pii.mask_value("TR120006200012345678901234", "iban")
		self.assertTrue(result.startswith("TR12"))
		self.assertTrue(result.endswith("**34"))
		self.assertIn("****", result)

	def test_iban_with_spaces(self):
		"""Boşluklu IBAN da çalışmalı"""
		result = pii.mask_value("TR12 0006 2000 1234 5678 9012 34", "iban")
		self.assertTrue(result.startswith("TR12"))
		self.assertTrue(result.endswith("**34"))

	def test_generic(self):
		"""generic — ilk ve son harf görünür, ortası *"""
		self.assertEqual(pii.mask_value("password123", "generic"), "p*********3")

	def test_generic_short(self):
		"""4 harf veya az → tamamı *"""
		self.assertEqual(pii.mask_value("abc", "generic"), "***")
		self.assertEqual(pii.mask_value("abcd", "generic"), "****")

	def test_unknown_kind_falls_back_to_generic(self):
		"""Bilinmeyen kind → generic davranış"""
		self.assertEqual(pii.mask_value("abcdef", "unknown_kind"), "a****f")


# ---------------------------------------------------------------------------
# has_pii_access
# ---------------------------------------------------------------------------


class HasPiiAccessTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_guest_no_access_above_zero(self):
		"""Guest → permlevel 0 evet, üstü hayır."""
		sys.modules["frappe"].session.user = "Guest"
		self.assertTrue(pii.has_pii_access("Guest", "Admin Seller Profile", 0))
		self.assertFalse(pii.has_pii_access("Guest", "Admin Seller Profile", 2))

	def test_system_manager_full_access(self):
		"""System Manager → tüm permlevel'lara erişim."""
		_DB_STATE[("roles", "admin@x.com")] = ["System Manager"]
		self.assertTrue(pii.has_pii_access("admin@x.com", "Admin Seller Profile", 3))

	def test_administrator_full_access(self):
		"""Administrator (literal) → bypass."""
		_DB_STATE[("roles", "Administrator")] = ["Administrator"]
		self.assertTrue(pii.has_pii_access("Administrator", "KYC Verification", 3))

	def test_role_with_explicit_permlevel(self):
		"""Compliance Officer + permlevel 3 → True."""
		_DB_STATE[("roles", "compliance@x.com")] = ["Compliance Officer"]
		# DocPerm exists query — Compliance Officer + permlevel=3 + read=1 var
		_DB_STATE[
			(
				"exists",
				"Custom DocPerm",
				"{'parent': 'KYC Verification', 'role': ['in', ['Compliance Officer']], 'permlevel': 3, 'read': 1}",
			)
		] = "DocPerm-001"

		self.assertTrue(pii.has_pii_access("compliance@x.com", "KYC Verification", 3))

	def test_role_without_permlevel_access(self):
		"""Seller Staff + permlevel 2 (sensitive) → False."""
		_DB_STATE[("roles", "staff@x.com")] = ["Seller"]
		# Yok — DB'de exists yok
		self.assertFalse(pii.has_pii_access("staff@x.com", "Admin Seller Profile", 3))


# ---------------------------------------------------------------------------
# get_user_max_permlevel
# ---------------------------------------------------------------------------


class GetUserMaxPermlevelTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_guest_returns_zero(self):
		sys.modules["frappe"].session.user = "Guest"
		self.assertEqual(pii.get_user_max_permlevel("Guest", "Any"), 0)

	def test_system_manager_returns_high(self):
		_DB_STATE[("roles", "admin@x.com")] = ["System Manager"]
		self.assertEqual(pii.get_user_max_permlevel("admin@x.com", "Any"), 9)


# ---------------------------------------------------------------------------
# get_pii_fieldnames
# ---------------------------------------------------------------------------


class GetPiiFieldnamesTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_returns_unique_fields(self):
		"""DocField + Custom Field + Property Setter'dan toplama."""
		_DB_STATE[
			(
				"get_all",
				"DocField",
				"{'parent': 'KYC Verification', 'permlevel': ['>=', 1]}",
				"fieldname",
				"None",
			)
		] = ["tax_id", "phone"]
		_DB_STATE[
			(
				"get_all",
				"Custom Field",
				"{'dt': 'KYC Verification', 'permlevel': ['>=', 1]}",
				"fieldname",
				"None",
			)
		] = ["bank_iban"]
		_DB_STATE[
			(
				"get_all",
				"Property Setter",
				"{'doc_type': 'KYC Verification', 'property': 'permlevel'}",
				None,
				"['field_name', 'value']",
			)
		] = [
			{"field_name": "identity_document", "value": "3"},
			{"field_name": "address", "value": "1"},
			{"field_name": "tax_id", "value": "2"},  # zaten DocField'da var, dup olmamalı
		]

		result = pii.get_pii_fieldnames("KYC Verification", min_permlevel=1)
		self.assertIn("tax_id", result)
		self.assertIn("phone", result)
		self.assertIn("bank_iban", result)
		self.assertIn("identity_document", result)
		self.assertIn("address", result)
		# Unique
		self.assertEqual(len(result), len(set(result)))


if __name__ == "__main__":
	unittest.main()
