"""FAZ 1.1 — Tenant isolation hook tests.

tradehub_core/utils/tenant.py içindeki:
  - enforce_seller_isolation_on_insert
  - validate_seller_isolation_on_save
  - _get_seller_profile_for_user
  - _resolve_seller_field_name
  - TENANT_EXEMPT_DOCTYPES davranışı

için unit testler. Frappe runtime'ı stub'lanır; saf-Python unittest:

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_tenant_isolation

Test stratejisi:
  - Happy path: user kendi seller'ı için doc yazar → field set edilir
  - Negative: user başka seller field'ı vererek yazmaya çalışır → PermissionError
  - Edge: user'ın seller'ı yok (admin/buyer) → field'a dokunmaz
  - Edge: System Manager → bypass
  - Edge: exempt doctype (User, Buyer Profile) → skip
  - Edge: seller field'ı olmayan doctype → skip
  - Validate: mevcut doc'un seller_profile değiştirilmesi → PermissionError
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


# ---------------------------------------------------------------------------
# Frappe stub
# ---------------------------------------------------------------------------


def _install_frappe_stub() -> None:
	"""Minimal frappe stub for tenant.py import.

	Diğer test dosyaları kendi stub'ını kurmuş olabilir; idempotent değiliz —
	her import'ta tenant test'lerinin ihtiyaç duyduğu mock'ları (özellikle
	get_meta'nın _MetaStub'ı) override ederiz.
	"""
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	# DB API
	frappe.db = SimpleNamespace(
		get_value=lambda *a, **kw: None,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		has_column=lambda *a, **kw: False,
	)

	# Session
	frappe.session = SimpleNamespace(user="Guest")
	frappe.local = SimpleNamespace()

	# Roles
	frappe.get_roles = lambda u: []

	# Cache
	_cache_store: dict = {}

	class _CacheStub:
		def get_value(self, key):
			return _cache_store.get(key)

		def set_value(self, key, value, expires_in_sec=None):
			_cache_store[key] = value

		def delete_value(self, key):
			_cache_store.pop(key, None)

	frappe.cache = lambda: _CacheStub()

	# Meta — DocType'ların seller_profile/seller field'ı olup olmadığını döner
	_meta_seller_profile = {"Listing", "Order", "Seller Balance", "Seller Review"}
	_meta_seller = {"CRM Lead", "CRM Deal", "Contact"}

	class _MetaStub:
		def __init__(self, doctype):
			self.doctype = doctype

		def has_field(self, fieldname):
			if fieldname == "seller_profile":
				return self.doctype in _meta_seller_profile
			if fieldname == "seller":
				return self.doctype in _meta_seller
			return False

	frappe.get_meta = lambda doctype: _MetaStub(doctype)

	# Error / i18n / exceptions
	class PermissionError(Exception):
		pass

	frappe.PermissionError = PermissionError

	def _throw(msg, exc=Exception):
		raise exc(msg)

	frappe.throw = _throw

	def _(s):
		return s

	frappe._ = _
	frappe.log_error = lambda *a, **kw: None

	# Utils
	frappe.utils = types.ModuleType("frappe.utils")
	frappe.utils.cint = int
	frappe.utils.flt = float
	sys.modules["frappe.utils"] = frappe.utils

	sys.modules["frappe"] = frappe


_install_frappe_stub()

# Test edilecek modülü import et
from tradehub_core.utils import tenant  # noqa: E402

# ---------------------------------------------------------------------------
# Helper'lar
# ---------------------------------------------------------------------------


def _make_doc(doctype: str, name: str = "DOC-001", is_new: bool = True, **fields):
	"""Frappe Document benzeri SimpleNamespace üret."""
	doc = SimpleNamespace(doctype=doctype, name=name, **fields)
	doc.is_new = lambda: is_new
	doc.get = lambda field, default=None: getattr(doc, field, default)
	doc.set = lambda field, value: setattr(doc, field, value)
	return doc


def _set_user_seller_mapping(mapping: dict[str, str]) -> None:
	"""Mock _get_seller_profile_for_user: user → seller_profile."""
	tenant._get_seller_profile_for_user = lambda user=None: mapping.get(
		user or sys.modules["frappe"].session.user
	)


def _reset_cache() -> None:
	"""Test'ler arası cache'i temizle.

	Cache stub'ı her get/set'te yeni instance üretiyor ama store global.
	Şu an pratik için no-op — test'ler arası state taşması bu seviyede
	gözlemlenmedi. Gerekirse stub'ı global store + reset() ile zenginleştir.
	"""
	return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TenantExemptDoctypeTests(unittest.TestCase):
	"""TENANT_EXEMPT_DOCTYPES içindeki doctype'larda hook skip etmeli."""

	def setUp(self):
		_reset_cache()
		_set_user_seller_mapping({"seller-a@x.com": "STORE-A"})
		sys.modules["frappe"].session.user = "seller-a@x.com"
		sys.modules["frappe"].get_roles = lambda u: ["Seller"]

	def test_user_doctype_skipped(self):
		"""User doctype'ı exempt — hook hiç çalışmamalı."""
		doc = _make_doc("User", first_name="Test")
		# Hata fırlatmamalı, field'a dokunmamalı
		tenant.enforce_seller_isolation_on_insert(doc)
		self.assertFalse(hasattr(doc, "seller_profile"))

	def test_buyer_profile_doctype_skipped(self):
		"""Buyer Profile exempt — buyer-scoped, tenant değil."""
		doc = _make_doc("Buyer Profile", display_name="Test Buyer")
		tenant.enforce_seller_isolation_on_insert(doc)
		# Hiçbir field eklenmemeli
		self.assertFalse(hasattr(doc, "seller_profile"))

	def test_brand_doctype_skipped(self):
		"""Brand public catalog — tenant izolasyonundan muaf."""
		doc = _make_doc("Brand", brand_name="Test Brand")
		tenant.enforce_seller_isolation_on_insert(doc)
		self.assertFalse(hasattr(doc, "seller_profile"))


class SellerFieldResolutionTests(unittest.TestCase):
	"""_resolve_seller_field_name doğru field adını döndürmeli."""

	def test_resolves_seller_profile(self):
		self.assertEqual(tenant._resolve_seller_field_name("Listing"), "seller_profile")
		self.assertEqual(tenant._resolve_seller_field_name("Order"), "seller_profile")

	def test_resolves_seller(self):
		self.assertEqual(tenant._resolve_seller_field_name("CRM Lead"), "seller")
		self.assertEqual(tenant._resolve_seller_field_name("Contact"), "seller")

	def test_no_field_returns_none(self):
		self.assertIsNone(tenant._resolve_seller_field_name("Random DocType"))


class EnforceOnInsertHappyPathTests(unittest.TestCase):
	"""Normal akış: user kendi seller'ı için doc yazar."""

	def setUp(self):
		_reset_cache()
		_set_user_seller_mapping({"seller-a@x.com": "STORE-A", "seller-b@x.com": "STORE-B"})
		sys.modules["frappe"].session.user = "seller-a@x.com"
		sys.modules["frappe"].get_roles = lambda u: ["Seller"]

	def test_autoset_when_field_empty(self):
		"""Field boşsa user'ın seller_profile'ı set edilmeli."""
		doc = _make_doc("Listing", seller_profile=None, title="Test")
		tenant.enforce_seller_isolation_on_insert(doc)
		self.assertEqual(doc.seller_profile, "STORE-A")

	def test_allow_when_field_matches_user_seller(self):
		"""Field user'ın seller'ına eşitse OK."""
		doc = _make_doc("Listing", seller_profile="STORE-A", title="Test")
		tenant.enforce_seller_isolation_on_insert(doc)
		self.assertEqual(doc.seller_profile, "STORE-A")  # değişmeden geçer


class EnforceOnInsertCrossSellerTests(unittest.TestCase):
	"""Negatif: user başka satıcının field'ı ile doc yazmaya çalışır."""

	def setUp(self):
		_reset_cache()
		_set_user_seller_mapping({"seller-a@x.com": "STORE-A", "seller-b@x.com": "STORE-B"})
		sys.modules["frappe"].session.user = "seller-a@x.com"
		sys.modules["frappe"].get_roles = lambda u: ["Seller"]

	def test_cross_seller_attempt_rejected(self):
		"""seller-a STORE-B'ye doc yazamaz → PermissionError."""
		doc = _make_doc("Listing", seller_profile="STORE-B", title="Cross")
		PermissionError = sys.modules["frappe"].PermissionError
		with self.assertRaises(PermissionError):
			tenant.enforce_seller_isolation_on_insert(doc)


class EnforceOnInsertAdminBypassTests(unittest.TestCase):
	"""System Manager bypass — explicit veri girer, autoset yok."""

	def setUp(self):
		_reset_cache()
		_set_user_seller_mapping({"admin@x.com": None})
		sys.modules["frappe"].session.user = "admin@x.com"
		sys.modules["frappe"].get_roles = lambda u: ["System Manager"]

	def test_system_manager_no_autoset(self):
		"""System Manager doc oluştursa, field boşsa boş kalır."""
		doc = _make_doc("Listing", seller_profile=None, title="Admin doc")
		tenant.enforce_seller_isolation_on_insert(doc)
		self.assertIsNone(doc.seller_profile)

	def test_system_manager_can_write_any_seller(self):
		"""System Manager herhangi bir seller'a yazabilmeli."""
		doc = _make_doc("Listing", seller_profile="STORE-X", title="Admin override")
		# Hata fırlatmamalı
		tenant.enforce_seller_isolation_on_insert(doc)
		self.assertEqual(doc.seller_profile, "STORE-X")


class EnforceOnInsertNoSellerUserTests(unittest.TestCase):
	"""User'ın seller_profile'ı yok (admin değil, buyer/marketplace user)."""

	def setUp(self):
		_reset_cache()
		_set_user_seller_mapping({"buyer@x.com": None})
		sys.modules["frappe"].session.user = "buyer@x.com"
		sys.modules["frappe"].get_roles = lambda u: ["Buyer"]

	def test_buyer_creating_order_no_autoset(self):
		"""Buyer Order yazıyor — seller_profile field'ı buyer'ın seller'ı YOK,
		controller doldurur. Hook field'a dokunmamalı."""
		doc = _make_doc("Order", seller_profile=None, total=100)
		tenant.enforce_seller_isolation_on_insert(doc)
		self.assertIsNone(doc.seller_profile)

	def test_buyer_with_existing_seller_field_passes_through(self):
		"""Buyer order'a STORE-X seller_profile'ı yazarsa (controller set etti),
		hook'un buyer'ı engellememesi gerek."""
		doc = _make_doc("Order", seller_profile="STORE-X", total=100)
		tenant.enforce_seller_isolation_on_insert(doc)
		self.assertEqual(doc.seller_profile, "STORE-X")


class ValidateOnSaveTests(unittest.TestCase):
	"""validate_seller_isolation_on_save — mevcut doc'un seller_profile değişikliği."""

	def setUp(self):
		_reset_cache()
		_set_user_seller_mapping({"seller-a@x.com": "STORE-A"})
		sys.modules["frappe"].session.user = "seller-a@x.com"
		sys.modules["frappe"].get_roles = lambda u: ["Seller"]

	def test_skip_for_new_doc(self):
		"""Yeni doc → enforce_on_insert ilgileniyor, validate skip eder."""
		doc = _make_doc("Listing", name="LISTING-NEW", is_new=True, seller_profile="STORE-A")
		tenant.validate_seller_isolation_on_save(doc)  # hata yok

	def test_skip_for_exempt_doctype(self):
		"""TENANT_EXEMPT doctype → skip."""
		doc = _make_doc("User", name="USER-001", is_new=False, seller_profile="ANY")
		tenant.validate_seller_isolation_on_save(doc)  # hata yok

	def test_unchanged_seller_profile_allowed(self):
		"""seller_profile değişmemiş → OK."""
		# DB değerini mock'la
		frappe = sys.modules["frappe"]
		original_get_value = frappe.db.get_value
		frappe.db.get_value = lambda doctype, name, field: "STORE-A" if field == "seller_profile" else None

		doc = _make_doc("Listing", name="LISTING-OLD", is_new=False, seller_profile="STORE-A")
		tenant.validate_seller_isolation_on_save(doc)  # hata yok

		frappe.db.get_value = original_get_value

	def test_changed_seller_profile_rejected(self):
		"""seller_profile değişmiş → PermissionError."""
		frappe = sys.modules["frappe"]
		original_get_value = frappe.db.get_value
		frappe.db.get_value = lambda doctype, name, field: "STORE-A" if field == "seller_profile" else None

		doc = _make_doc("Listing", name="LISTING-OLD", is_new=False, seller_profile="STORE-B")
		with self.assertRaises(frappe.PermissionError):
			tenant.validate_seller_isolation_on_save(doc)

		frappe.db.get_value = original_get_value

	def test_system_manager_bypass(self):
		"""System Manager seller_profile değiştirebilir."""
		frappe = sys.modules["frappe"]
		frappe.get_roles = lambda u: ["System Manager"]
		original_get_value = frappe.db.get_value
		frappe.db.get_value = lambda doctype, name, field: "STORE-A" if field == "seller_profile" else None

		doc = _make_doc("Listing", name="LISTING-OLD", is_new=False, seller_profile="STORE-B")
		tenant.validate_seller_isolation_on_save(doc)  # hata yok (admin override)

		frappe.db.get_value = original_get_value
		frappe.get_roles = lambda u: ["Seller"]  # reset


class LegacyAPICompatibilityTests(unittest.TestCase):
	"""Legacy API (get_current_tenant, set_tenant, validate_tenant) aliasları çalışıyor."""

	def setUp(self):
		_reset_cache()
		_set_user_seller_mapping({"seller-a@x.com": "STORE-A"})
		sys.modules["frappe"].session.user = "seller-a@x.com"

	def test_get_current_tenant_returns_seller_profile(self):
		self.assertEqual(tenant.get_current_tenant(), "STORE-A")

	def test_set_tenant_is_noop(self):
		"""set_tenant() artık no-op — hata fırlatmamalı."""
		tenant.set_tenant("STORE-X")  # hata yok
		# Side effect olmamalı (artık session/local tutmuyor)

	def test_has_tenant_field_alias(self):
		"""_has_tenant_field → _doctype_has_seller_field alias çalışır."""
		self.assertTrue(tenant._has_tenant_field("Listing"))
		self.assertFalse(tenant._has_tenant_field("User"))

	def test_validate_tenant_alias(self):
		"""validate_tenant → validate_seller_isolation_on_save alias çalışır."""
		doc = _make_doc("Listing", is_new=True, seller_profile="STORE-A")
		# Yeni doc → skip, hata yok
		tenant.validate_tenant(doc)


if __name__ == "__main__":
	unittest.main()
