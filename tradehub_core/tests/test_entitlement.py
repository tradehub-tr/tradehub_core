"""FAZ 1.2 — Entitlement (L0) unit testleri.

tradehub_core.entitlement.core içindeki:
  - has_feature
  - within_quota
  - check_feature_or_throw
  - check_quota_or_throw
  - get_active_subscription
  - cache invalidation

için saf-Python testler. Frappe stub'lanır.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_entitlement
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


_DB_STATE: dict = {}
_CACHE_STORE: dict = {}


def _install_frappe_stub() -> None:
	"""Frappe stub kur ya da mevcut stub'ı entitlement test'i için override et.

	Diğer test dosyaları (test_tenant_isolation) kendi stub'ını kurduysa
	burada frappe modülü zaten var. O zaman SADECE bu testler için gereken
	db/cache/get_cached_doc fonksiyonlarını override ederiz; diğer test'lerin
	ihtiyaçlarını bozmayalım diye.
	"""
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe
		# İlk install — devamı aşağıda

	# DB
	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = (doctype, str(filters), str(fieldname))
		return _DB_STATE.get(key)

	def db_count(doctype, filters=None):
		key = ("count", doctype, str(filters))
		return _DB_STATE.get(key, 0)

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		count=db_count,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
	)

	# Session
	frappe.session = SimpleNamespace(user="seller-a@x.com")
	frappe.local = SimpleNamespace()

	# Cache
	class _CacheStub:
		def get_value(self, key):
			return _CACHE_STORE.get(key)

		def set_value(self, key, value, expires_in_sec=None):
			_CACHE_STORE[key] = value

		def delete_value(self, key):
			_CACHE_STORE.pop(key, None)

	frappe.cache = lambda: _CacheStub()

	# get_cached_doc — Subscription Plan + Store Subscription mock döner
	def get_cached_doc(doctype, name):
		key = ("doc", doctype, name)
		if key not in _DB_STATE:
			raise Exception(f"{doctype} '{name}' not found")
		return _DB_STATE[key]

	frappe.get_cached_doc = get_cached_doc
	frappe.get_doc = get_cached_doc

	# Get all (for invalidate_plan_cache)
	def get_all(doctype, filters=None, pluck=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB_STATE.get(key, [])

	frappe.get_all = get_all

	# Utils — diğer stub'larla uyumlu olsun diye yeniden set
	if not hasattr(frappe, "utils") or not hasattr(frappe.utils, "now_datetime"):
		frappe.utils = types.ModuleType("frappe.utils")
		frappe.utils.cint = int
		frappe.utils.flt = float
		frappe.utils.now_datetime = lambda: None
		sys.modules["frappe.utils"] = frappe.utils

	# Roles — sadece yoksa ekle (test_tenant'ın override'ını bozma)
	if not hasattr(frappe, "get_roles"):
		frappe.get_roles = lambda u: []

	# Exceptions — yoksa ekle
	if not hasattr(frappe, "PermissionError"):

		class PermissionError(Exception):
			pass

		frappe.PermissionError = PermissionError

	if not hasattr(frappe, "throw"):

		def _throw(msg, exc=Exception):
			raise exc(msg) if isinstance(exc, type) else Exception(msg)

		frappe.throw = _throw

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s

	if not hasattr(frappe, "logger"):

		def _logger():
			return SimpleNamespace(info=lambda *a, **kw: None, error=lambda *a, **kw: None)

		frappe.logger = _logger

	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None

	# get_meta — diğer test'lerin _MetaStub'ını ezme; yoksa minimal stub kur
	if not hasattr(frappe, "get_meta"):

		class _MinimalMeta:
			def __init__(self, doctype):
				self.doctype = doctype

			def has_field(self, fieldname):
				return False

		frappe.get_meta = lambda doctype: _MinimalMeta(doctype)


_install_frappe_stub()

from tradehub_core.entitlement import core as ent_core  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers — DB mock
# ---------------------------------------------------------------------------


def _reset_state():
	"""Her test başında state'i temizle ve stub'ı zorla reinstall et.

	Diğer test dosyaları (test_tenant_isolation) import edildiyse frappe.db,
	frappe.cache, frappe.get_cached_doc mock'larını override etmiş olabilirler.
	Stub'ı her test'te reinstall ederek izolasyonu garanti ediyoruz.
	"""
	_DB_STATE.clear()
	_CACHE_STORE.clear()
	_install_frappe_stub_force()


def _install_frappe_stub_force():
	"""Test_entitlement'ın db/cache/get_cached_doc mock'larını zorla override et."""
	frappe = sys.modules.get("frappe")
	if frappe is None:
		_install_frappe_stub()
		return

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = (doctype, str(filters), str(fieldname))
		return _DB_STATE.get(key)

	def db_count(doctype, filters=None):
		key = ("count", doctype, str(filters))
		return _DB_STATE.get(key, 0)

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		count=db_count,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
	)

	class _CacheStub:
		def get_value(self, key):
			return _CACHE_STORE.get(key)

		def set_value(self, key, value, expires_in_sec=None):
			_CACHE_STORE[key] = value

		def delete_value(self, key):
			_CACHE_STORE.pop(key, None)

	frappe.cache = lambda: _CacheStub()

	def get_cached_doc(doctype, name):
		key = ("doc", doctype, name)
		if key not in _DB_STATE:
			raise Exception(f"{doctype} '{name}' not found")
		return _DB_STATE[key]

	frappe.get_cached_doc = get_cached_doc
	frappe.get_doc = get_cached_doc

	def get_all(doctype, filters=None, pluck=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB_STATE.get(key, [])

	frappe.get_all = get_all


def _make_subscription(store: str, plan: str, status: str = "active"):
	"""Mock Store Subscription doc döner."""
	sub_name = f"STSUB-{store}"
	# get_value('Store Subscription', {store, status in trial,active}, 'name')
	_DB_STATE[
		(
			"Store Subscription",
			f"{{'store': '{store}', 'status': ['in', ['trial', 'active']]}}",
			"name",
		)
	] = sub_name

	sub_doc = SimpleNamespace(
		name=sub_name,
		store=store,
		plan=plan,
		status=status,
		trial_end=None,
		current_period_end=None,
	)

	# get_effective_capability_flags & quota_limits için plan'a referans
	plan_key = ("doc", "Subscription Plan", plan)
	if plan_key not in _DB_STATE:
		_DB_STATE[plan_key] = SimpleNamespace(
			name=plan,
			get_capability_flags=lambda: {},
			get_quota_limits=lambda: {},
		)

	# Effective methods sub_doc'a bağla
	def _eff_caps():
		plan_doc = _DB_STATE[plan_key]
		return dict(plan_doc.get_capability_flags())

	def _eff_quotas():
		plan_doc = _DB_STATE[plan_key]
		return dict(plan_doc.get_quota_limits())

	sub_doc.get_effective_capability_flags = _eff_caps
	sub_doc.get_effective_quota_limits = _eff_quotas

	_DB_STATE[("doc", "Store Subscription", sub_name)] = sub_doc
	return sub_doc


def _set_plan_capabilities(plan: str, flags: dict):
	plan_key = ("doc", "Subscription Plan", plan)
	if plan_key not in _DB_STATE:
		_DB_STATE[plan_key] = SimpleNamespace(name=plan)
	plan_doc = _DB_STATE[plan_key]
	plan_doc.get_capability_flags = lambda flags=flags: flags
	if not hasattr(plan_doc, "get_quota_limits"):
		plan_doc.get_quota_limits = lambda: {}


def _set_plan_quotas(plan: str, quotas: dict):
	plan_key = ("doc", "Subscription Plan", plan)
	if plan_key not in _DB_STATE:
		_DB_STATE[plan_key] = SimpleNamespace(name=plan)
	plan_doc = _DB_STATE[plan_key]
	plan_doc.get_quota_limits = lambda quotas=quotas: quotas
	if not hasattr(plan_doc, "get_capability_flags"):
		plan_doc.get_capability_flags = lambda: {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class HasFeatureTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_no_subscription_returns_false(self):
		"""Subscription yoksa hiçbir feature açık değil."""
		self.assertFalse(ent_core.has_feature("STORE-A", "feature.pim.multi_variant"))

	def test_feature_enabled(self):
		"""Plan'da feature=True ise has_feature True."""
		_make_subscription("STORE-A", "pro")
		_set_plan_capabilities("pro", {"feature.pim.multi_variant": True})
		self.assertTrue(ent_core.has_feature("STORE-A", "feature.pim.multi_variant"))

	def test_feature_disabled(self):
		"""Plan'da feature=False ise has_feature False."""
		_make_subscription("STORE-A", "free")
		_set_plan_capabilities("free", {"feature.pim.multi_variant": False})
		self.assertFalse(ent_core.has_feature("STORE-A", "feature.pim.multi_variant"))

	def test_feature_not_in_plan(self):
		"""Plan'da tanımsız feature → False."""
		_make_subscription("STORE-A", "free")
		_set_plan_capabilities("free", {})
		self.assertFalse(ent_core.has_feature("STORE-A", "feature.unknown"))

	def test_empty_args(self):
		self.assertFalse(ent_core.has_feature("", "feature.x"))
		self.assertFalse(ent_core.has_feature("STORE-A", ""))


class WithinQuotaTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_no_subscription_returns_false(self):
		"""Subscription yoksa kota kontrolü her zaman False (deny)."""
		self.assertFalse(ent_core.within_quota("STORE-A", "quota.max_products", 0))

	def test_under_limit_allows(self):
		"""current < limit → True."""
		_make_subscription("STORE-A", "starter")
		_set_plan_quotas("starter", {"quota.max_products": 500})
		self.assertTrue(ent_core.within_quota("STORE-A", "quota.max_products", 100))
		self.assertTrue(ent_core.within_quota("STORE-A", "quota.max_products", 499))

	def test_at_limit_denies(self):
		"""current == limit → False (sınır dahil, eşit veya üstü)."""
		_make_subscription("STORE-A", "starter")
		_set_plan_quotas("starter", {"quota.max_products": 500})
		self.assertFalse(ent_core.within_quota("STORE-A", "quota.max_products", 500))
		self.assertFalse(ent_core.within_quota("STORE-A", "quota.max_products", 501))

	def test_unlimited(self):
		"""limit == -1 → her zaman True (sınırsız, Enterprise)."""
		_make_subscription("STORE-A", "enterprise")
		_set_plan_quotas("enterprise", {"quota.max_products": -1})
		self.assertTrue(ent_core.within_quota("STORE-A", "quota.max_products", 10_000_000))

	def test_disabled(self):
		"""limit == 0 → her zaman False (devre dışı, Free planda API gibi)."""
		_make_subscription("STORE-A", "free")
		_set_plan_quotas("free", {"quota.api_rate_limit": 0})
		self.assertFalse(ent_core.within_quota("STORE-A", "quota.api_rate_limit", 0))
		self.assertFalse(ent_core.within_quota("STORE-A", "quota.api_rate_limit", 1))

	def test_quota_not_in_plan(self):
		"""Plan'da tanımsız kota → False (deny)."""
		_make_subscription("STORE-A", "free")
		_set_plan_quotas("free", {})
		self.assertFalse(ent_core.within_quota("STORE-A", "quota.unknown", 0))


class CheckOrThrowTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_check_feature_passes_silently(self):
		_make_subscription("STORE-A", "pro")
		_set_plan_capabilities("pro", {"feature.pim.multi_variant": True})
		# Hata yok
		ent_core.check_feature_or_throw("STORE-A", "feature.pim.multi_variant")

	def test_check_feature_throws_when_missing(self):
		_make_subscription("STORE-A", "free")
		_set_plan_capabilities("free", {"feature.pim.multi_variant": False})
		with self.assertRaises(ent_core.EntitlementError):
			ent_core.check_feature_or_throw("STORE-A", "feature.pim.multi_variant")

	def test_check_quota_passes_silently(self):
		_make_subscription("STORE-A", "starter")
		_set_plan_quotas("starter", {"quota.max_products": 500})
		ent_core.check_quota_or_throw("STORE-A", "quota.max_products", 100)

	def test_check_quota_throws_at_limit(self):
		_make_subscription("STORE-A", "free")
		_set_plan_quotas("free", {"quota.max_products": 50})
		with self.assertRaises(ent_core.EntitlementError):
			ent_core.check_quota_or_throw("STORE-A", "quota.max_products", 50)


class CacheTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_invalidate_store_cache(self):
		_make_subscription("STORE-A", "pro")
		_set_plan_capabilities("pro", {"feature.pim.multi_variant": True})

		# İlk çağrı → cache miss + write
		self.assertTrue(ent_core.has_feature("STORE-A", "feature.pim.multi_variant"))
		self.assertIn("tradehub:entitlement:capabilities:STORE-A", _CACHE_STORE)

		# Invalidate
		ent_core.invalidate_store_cache("STORE-A")
		self.assertNotIn("tradehub:entitlement:capabilities:STORE-A", _CACHE_STORE)

	def test_cache_hit_skips_db(self):
		"""İkinci çağrı cache'ten okumalı."""
		_make_subscription("STORE-A", "pro")
		_set_plan_capabilities("pro", {"feature.pim.multi_variant": True})

		ent_core.has_feature("STORE-A", "feature.pim.multi_variant")
		# Mock plan'ı boşalt; cache hit varsa hala True dönmeli
		_set_plan_capabilities("pro", {})
		self.assertTrue(ent_core.has_feature("STORE-A", "feature.pim.multi_variant"))


if __name__ == "__main__":
	unittest.main()
