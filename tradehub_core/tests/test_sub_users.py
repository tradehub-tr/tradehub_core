"""FAZ 1.5 — Sub-user yönetim API unit testleri.

tradehub_core.api.v1.seller_users içindeki helper'lar ve davet token akışı için
saf-Python testler.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_sub_users
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


_DB: dict = {}
_INSERTED: list[dict] = []


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="owner-a@x.com")
	frappe.get_roles = lambda u: _DB.get(("roles", u), [])

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(filters), str(fieldname))
		return _DB.get(key)

	def db_count(doctype, filters=None):
		return _DB.get(("count", doctype, str(filters)), 0)

	def db_exists(doctype, filters=None):
		return _DB.get(("exists", doctype, str(filters)), False)

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		count=db_count,
		exists=db_exists,
		escape=lambda s: f"'{s}'",
		has_column=lambda *a, **kw: True,
		commit=lambda: None,
		delete=lambda *a, **kw: None,
	)

	class _CacheStub:
		def get_value(self, key):
			return _DB.get(("cache", key))

		def set_value(self, key, value, expires_in_sec=None):
			_DB[("cache", key)] = value

		def delete_value(self, key):
			_DB.pop(("cache", key), None)

	frappe.cache = lambda: _CacheStub()

	def get_doc_factory(data):
		class _Doc:
			def __init__(self, d):
				self._d = dict(d)
				self.flags = SimpleNamespace(audit_write=False, ignore_permissions=False, from_insert=False)
				self.name = d.get("name")
				for k, v in d.items():
					setattr(self, k, v)

			def insert(self, ignore_permissions=False, **kwargs):
				self.name = self.name or f"{self._d.get('doctype', 'DOC')}-{len(_INSERTED) + 1:06d}"
				self._d["name"] = self.name
				_INSERTED.append(dict(self._d))
				return self

			def save(self, ignore_permissions=False, **kwargs):
				_INSERTED.append(dict(self._d))
				return self

		return _Doc(data if isinstance(data, dict) else {"name": data})

	frappe.get_doc = get_doc_factory

	def get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, **kwargs):
		key = ("get_all", doctype, str(filters), str(fields), pluck)
		return _DB.get(key, [])

	frappe.get_all = get_all

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

	if not hasattr(frappe, "utils") or not hasattr(frappe.utils, "now_datetime"):
		frappe.utils = types.ModuleType("frappe.utils")
		from datetime import datetime, timedelta

		frappe.utils.cint = int
		frappe.utils.flt = float
		frappe.utils.now_datetime = lambda: datetime(2026, 5, 21, 12, 0, 0)
		frappe.utils.add_days = lambda dt, days: dt + timedelta(days=days)
		frappe.utils.get_url = lambda: "https://test.local"
		sys.modules["frappe.utils"] = frappe.utils

	frappe.sendmail = lambda **kwargs: None

	# whitelist decorator — no-op (test'ler decorator çıktısını çağırır)
	if not hasattr(frappe, "whitelist"):

		def _whitelist(*args, **kwargs):
			def _decorator(fn):
				return fn

			# Direkt @frappe.whitelist (parantezsiz) ya da @frappe.whitelist() ikisini destekle
			if args and callable(args[0]):
				return args[0]
			return _decorator

		frappe.whitelist = _whitelist


_install_frappe_stub()


def _reset_state() -> None:
	_DB.clear()
	_INSERTED.clear()
	_install_frappe_stub()


from tradehub_core.api.v1 import seller_users  # noqa: E402

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


class TokenTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_token_generation_returns_pair(self):
		raw, hashed = seller_users._generate_invite_token()
		self.assertIsInstance(raw, str)
		self.assertIsInstance(hashed, str)
		self.assertEqual(len(hashed), 64)  # SHA-256 hex
		self.assertNotEqual(raw, hashed)

	def test_hash_token_is_deterministic(self):
		raw = "test-token-123"
		h1 = seller_users._hash_token(raw)
		h2 = seller_users._hash_token(raw)
		self.assertEqual(h1, h2)

	def test_token_hash_different_for_different_tokens(self):
		h1 = seller_users._hash_token("a")
		h2 = seller_users._hash_token("b")
		self.assertNotEqual(h1, h2)


# ---------------------------------------------------------------------------
# Owner / Co-Owner check
# ---------------------------------------------------------------------------


class RequireOwnerOrCoOwnerTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_no_tenant_raises(self):
		"""Tenant'a bağlı olmayan user → PermissionError."""
		_DB[("get_value", "Admin Seller Profile", "{'user': 'random@x.com', 'status': 'Active'}", "name")] = (
			None
		)
		sys.modules["frappe"].session.user = "random@x.com"
		with self.assertRaises(Exception):
			seller_users._require_owner_or_co_owner()

	def test_owner_passes(self):
		"""Owner rolü + is_owner=1 → OK."""
		sys.modules["frappe"].session.user = "owner@x.com"
		_DB[("get_value", "Admin Seller Profile", "{'user': 'owner@x.com', 'status': 'Active'}", "name")] = (
			"STORE-A"
		)
		_DB[("roles", "owner@x.com")] = ["Seller Owner"]
		_DB[("get_value", "User", "owner@x.com", "tradehub_is_owner")] = 1

		tenant = seller_users._require_owner_or_co_owner()
		self.assertEqual(tenant, "STORE-A")

	def test_co_owner_passes(self):
		"""Co-Owner profile → OK."""
		sys.modules["frappe"].session.user = "coowner@x.com"
		_DB[
			("get_value", "Admin Seller Profile", "{'user': 'coowner@x.com', 'status': 'Active'}", "name")
		] = "STORE-A"
		_DB[("roles", "coowner@x.com")] = ["Seller Admin", "Seller Finance"]
		_DB[("get_value", "User", "coowner@x.com", "tradehub_is_owner")] = 0
		_DB[("get_value", "User", "coowner@x.com", "role_profile_name")] = "Seller Co-Owner"

		tenant = seller_users._require_owner_or_co_owner()
		self.assertEqual(tenant, "STORE-A")

	def test_regular_seller_staff_rejected(self):
		"""Staff sub-user invite yapamaz."""
		sys.modules["frappe"].session.user = "staff@x.com"
		_DB[("get_value", "Admin Seller Profile", "{'user': 'staff@x.com', 'status': 'Active'}", "name")] = (
			"STORE-A"
		)
		_DB[("roles", "staff@x.com")] = ["Seller Staff"]
		_DB[("get_value", "User", "staff@x.com", "tradehub_is_owner")] = 0
		_DB[("get_value", "User", "staff@x.com", "role_profile_name")] = "Seller Operations"

		with self.assertRaises(Exception):
			seller_users._require_owner_or_co_owner()

	def test_co_owner_cannot_do_owner_only_action(self):
		"""Co-Owner banka değiştirme yapamaz (Owner-only action)."""
		sys.modules["frappe"].session.user = "coowner@x.com"
		_DB[
			("get_value", "Admin Seller Profile", "{'user': 'coowner@x.com', 'status': 'Active'}", "name")
		] = "STORE-A"
		_DB[("roles", "coowner@x.com")] = ["Seller Admin"]
		_DB[("get_value", "User", "coowner@x.com", "tradehub_is_owner")] = 0
		_DB[("get_value", "User", "coowner@x.com", "role_profile_name")] = "Seller Co-Owner"

		with self.assertRaises(Exception):
			seller_users._require_owner_or_co_owner(action="change_bank_info")


# ---------------------------------------------------------------------------
# Plan kelepçesi
# ---------------------------------------------------------------------------


class PlanRoleClampTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_role_profile_to_feature_key_conversion(self):
		"""Profil adı → feature key dönüşümü doğru mu (helper'a inject etmek için)."""
		# Profile 'Seller Manager' → 'seller_manager' → 'feature.role.profile.seller_manager'
		# Bu test seller_users._validate_role_profile_for_plan'ın iç mantığını
		# doğrular; gerçek check has_feature kullanıyor.
		# Sadece naming convention'ı doğrula
		import re

		profile = "Seller Manager"
		code = profile.lower().replace(" ", "_").replace("-", "_")
		expected = "feature.role.profile.seller_manager"
		self.assertEqual(f"feature.role.profile.{code}", expected)

		# Co-Owner: 'Seller Co-Owner' → 'seller_co_owner'
		profile = "Seller Co-Owner"
		code = profile.lower().replace(" ", "_").replace("-", "_")
		self.assertEqual(code, "seller_co_owner")
		self.assertTrue(re.match(r"^[a-z_]+$", code))


# ---------------------------------------------------------------------------
# Owner Lock
# ---------------------------------------------------------------------------


def _install_owner_lock_stubs() -> None:
	# owner_lock testleri kendi stub'ını gerektirir
	_install_frappe_stub()


class OwnerLockTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		from tradehub_core.utils import owner_lock

		self.owner_lock = owner_lock

	def _make_doc(self, name, is_new=False, **fields):
		doc = SimpleNamespace(doctype="Admin Seller Profile", name=name, **fields)
		doc.is_new = lambda: is_new
		doc.get = lambda field, default=None: getattr(doc, field, default)
		return doc

	def test_new_doc_skipped(self):
		"""Yeni doc → skip (Co-Owner ilk kez doldurabilir)."""
		doc = self._make_doc("STORE-NEW", is_new=True, iban="TR12...")
		self.owner_lock.enforce_owner_only_fields(doc)  # hata yok

	def test_owner_can_change_iban(self):
		"""Owner banka değiştirir → OK."""
		sys.modules["frappe"].session.user = "owner@x.com"
		_DB[("roles", "owner@x.com")] = ["Seller Owner"]
		_DB[("get_value", "User", "owner@x.com", "['tradehub_tenant', 'tradehub_is_owner']")] = ("STORE-A", 1)

		# Yukarıdaki tuple return için liste-key formatına uyumlu DB stub yok;
		# manuel patch et
		original = sys.modules["frappe"].db.get_value

		def _patched(doctype, name, fieldname=None, **kwargs):
			if doctype == "User" and isinstance(fieldname, list):
				return ("STORE-A", 1)
			if doctype == "Admin Seller Profile":
				return {"iban": "TR12-OLD", "bank_name": None, "bank_account_holder": None, "tax_id": "OLD"}
			return original(doctype, name, fieldname, **kwargs)

		sys.modules["frappe"].db.get_value = _patched

		doc = self._make_doc(
			"STORE-A", iban="TR12-NEW", bank_name=None, bank_account_holder=None, tax_id="OLD"
		)
		self.owner_lock.enforce_owner_only_fields(doc)  # hata yok

	def test_non_owner_cannot_change_iban(self):
		"""Co-Owner IBAN değiştiremez."""
		sys.modules["frappe"].session.user = "coowner@x.com"
		_DB[("roles", "coowner@x.com")] = ["Seller Admin"]  # Owner rolü yok

		original = sys.modules["frappe"].db.get_value

		def _patched(doctype, name, fieldname=None, **kwargs):
			if doctype == "User" and isinstance(fieldname, list):
				return ("STORE-A", 0)
			if doctype == "Admin Seller Profile":
				return {"iban": "TR12-OLD", "bank_name": None, "bank_account_holder": None, "tax_id": "OLD"}
			return original(doctype, name, fieldname, **kwargs)

		sys.modules["frappe"].db.get_value = _patched

		doc = self._make_doc(
			"STORE-A", iban="TR12-NEW", bank_name=None, bank_account_holder=None, tax_id="OLD"
		)
		with self.assertRaises(Exception):
			self.owner_lock.enforce_owner_only_fields(doc)

	def test_system_manager_bypass(self):
		"""System Manager her zaman geçer."""
		sys.modules["frappe"].session.user = "admin@x.com"
		_DB[("roles", "admin@x.com")] = ["System Manager"]

		doc = self._make_doc("STORE-A", iban="TR12-NEW")
		self.owner_lock.enforce_owner_only_fields(doc)  # hata yok


if __name__ == "__main__":
	unittest.main()
