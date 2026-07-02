"""FAZ 1.7 — entitlement_snapshot endpoint unit testleri.

tradehub_core.api.v1.entitlement_snapshot içindeki:
  - get_snapshot (guest, buyer, seller akışları)
  - check_feature (fresh check)
  - storefront feature filter (gizli feature'lar sızmaz)

için saf-Python testler.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_entitlement_snapshot
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


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Guest")
	frappe.get_roles = lambda u: _DB.get(("roles", u), [])

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(filters), str(fieldname))
		return _DB.get(key)

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=lambda *a, **kw: False,
		count=lambda *a, **kw: 0,
		escape=lambda s: f"'{s}'",
		has_column=lambda *a, **kw: True,
	)

	# get_cached_doc — entitlement core için
	def get_cached_doc(doctype, name):
		key = ("doc", doctype, name)
		if key not in _DB:
			raise Exception(f"{doctype} '{name}' not found")
		return _DB[key]

	frappe.get_cached_doc = get_cached_doc
	frappe.get_doc = get_cached_doc

	# Cache stub — global dict (test'ler arası reset _reset_state ile)
	_local_cache: dict = {}

	class _CacheStub:
		def get_value(self, key):
			return _local_cache.get(key)

		def set_value(self, key, value, expires_in_sec=None):
			_local_cache[key] = value

		def delete_value(self, key):
			_local_cache.pop(key, None)

	frappe.cache = lambda: _CacheStub()
	# Reset için cache store'a global referans
	_DB["_cache_store_ref"] = _local_cache

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

	# whitelist no-op decorator
	if not hasattr(frappe, "whitelist"):

		def _whitelist(*args, **kwargs):
			def _decorator(fn):
				return fn

			if args and callable(args[0]):
				return args[0]
			return _decorator

		frappe.whitelist = _whitelist

	if not hasattr(frappe, "utils") or not hasattr(frappe.utils, "now_datetime"):
		frappe.utils = types.ModuleType("frappe.utils")
		from datetime import datetime, timedelta

		frappe.utils.cint = int
		frappe.utils.flt = float
		frappe.utils.now_datetime = lambda: datetime(2026, 5, 21, 12, 0, 0)
		frappe.utils.add_days = lambda dt, days: (dt or datetime.now()) + timedelta(days=days)
		frappe.utils.get_url = lambda: "https://test.local"
		sys.modules["frappe.utils"] = frappe.utils
	# add_days / get_url eksikse ekle (diğer test'lerin stub'ı sadece now_datetime
	# set etmiş olabilir)
	if not hasattr(frappe.utils, "add_days"):
		from datetime import timedelta

		frappe.utils.add_days = lambda dt, days: (dt) + timedelta(days=days) if dt else None
	if not hasattr(frappe.utils, "get_url"):
		frappe.utils.get_url = lambda: "https://test.local"


_install_frappe_stub()


def _reset_state() -> None:
	# Cache store referansını sakla (clear sonrası yeniden bağla)
	cache_ref = _DB.get("_cache_store_ref")
	_DB.clear()
	if cache_ref is not None:
		cache_ref.clear()
	# Frappe stub'ını da yeniden kur (cache + db çakışmalarına karşı)
	_install_frappe_stub()


from tradehub_core.api.v1 import entitlement_snapshot as snap  # noqa: E402


class GetSnapshotTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_guest_returns_minimal(self):
		sys.modules["frappe"].session.user = "Guest"
		result = snap.get_snapshot()
		self.assertEqual(result["user"], "Guest")
		self.assertFalse(result["is_buyer"])
		self.assertFalse(result["is_seller"])
		self.assertFalse(result["can_buy"])
		self.assertEqual(result["features"], {})
		self.assertEqual(result["ttl_seconds"], 300)

	def test_buyer_individual_returns_kyc_status(self):
		sys.modules["frappe"].session.user = "buyer@x.com"
		_DB[("roles", "buyer@x.com")] = ["Buyer"]
		_DB[
			(
				"get_value",
				"User Profile",
				"{'user': 'buyer@x.com'}",
				"['account_type', 'kyc_status', 'kyb_status', 'can_buy', 'can_sell']",
			)
		] = {
			"account_type": "Individual",
			"kyc_status": "Verified",
			"kyb_status": None,
			"can_buy": 1,
			"can_sell": 0,
		}

		result = snap.get_snapshot()
		self.assertTrue(result["is_buyer"])
		self.assertFalse(result["is_seller"])
		self.assertEqual(result["kyc_status"], "Verified")
		self.assertTrue(result["can_buy"])

	def test_buyer_business_returns_kyb_status(self):
		sys.modules["frappe"].session.user = "buyer@firma.com"
		_DB[("roles", "buyer@firma.com")] = ["Buyer"]
		_DB[
			(
				"get_value",
				"User Profile",
				"{'user': 'buyer@firma.com'}",
				"['account_type', 'kyc_status', 'kyb_status', 'can_buy', 'can_sell']",
			)
		] = {
			"account_type": "Business",
			"kyc_status": None,
			"kyb_status": "Pending",
			"can_buy": 0,
			"can_sell": 0,
		}

		result = snap.get_snapshot()
		self.assertEqual(result["account_type"], "Business")
		self.assertEqual(result["kyb_status"], "Pending")
		self.assertFalse(result["can_buy"])  # KYB pending → can_buy=0

	def test_seller_returns_plan_and_features(self):
		"""Satıcı snapshot: plan + capability + quota (sadece storefront-safe)."""
		sys.modules["frappe"].session.user = "seller@x.com"
		_DB[("roles", "seller@x.com")] = ["Marketplace Seller", "Seller Owner"]
		_DB[("get_value", "User", "seller@x.com", "tradehub_tenant")] = "STORE-A"

		# Active subscription
		_DB[
			(
				"get_value",
				"Store Subscription",
				"{'store': 'STORE-A', 'status': ['in', ['trial', 'active', 'past_due']]}",
				"name",
			)
		] = "STSUB-001"

		# Subscription doc mock
		sub_doc = SimpleNamespace(
			name="STSUB-001",
			plan="pro",
			status="active",
			trial_end=None,
			current_period_end=None,
		)
		sub_doc.get_effective_capability_flags = lambda: {
			"feature.pim.multi_variant": True,  # storefront-safe (pim.)
			"feature.functional.rfq": True,  # storefront-safe (functional.)
			"feature.store.custom_theme": True,  # storefront-safe (store.)
			"feature.role.profile.seller_co_owner": True,  # GİZLİ (role.) → snapshot'a girmemeli
			"feature.api.access": True,  # storefront-safe (api.)
		}
		sub_doc.get_effective_quota_limits = lambda: {
			"quota.max_products": 5000,
			"quota.max_sub_users": 10,
			"quota.max_co_owners": 1,  # GİZLİ → snapshot'a girmemeli
		}
		_DB[("doc", "Store Subscription", "STSUB-001")] = sub_doc

		# User Profile (boş ama get_value beklediği için)
		_DB[
			(
				"get_value",
				"User Profile",
				"{'user': 'seller@x.com'}",
				"['account_type', 'kyc_status', 'kyb_status', 'can_buy', 'can_sell']",
			)
		] = {}

		result = snap.get_snapshot()
		self.assertTrue(result["is_seller"])
		self.assertEqual(result["tenant"], "STORE-A")
		self.assertEqual(result["plan_code"], "pro")
		self.assertEqual(result["subscription_status"], "active")

		# Storefront-safe features dahil
		self.assertTrue(result["features"]["feature.pim.multi_variant"])
		self.assertTrue(result["features"]["feature.functional.rfq"])
		self.assertTrue(result["features"]["feature.store.custom_theme"])

		# Storefront-safe quotas dahil
		self.assertEqual(result["quotas"]["quota.max_products"], 5000)
		self.assertEqual(result["quotas"]["quota.max_sub_users"], 10)

	def test_seller_role_features_excluded_from_snapshot(self):
		"""feature.role.* gibi gizli flag'ler storefront snapshot'ına sızmamalı."""
		sys.modules["frappe"].session.user = "seller@x.com"
		_DB[("roles", "seller@x.com")] = ["Marketplace Seller"]
		_DB[("get_value", "User", "seller@x.com", "tradehub_tenant")] = "STORE-A"
		_DB[
			(
				"get_value",
				"Store Subscription",
				"{'store': 'STORE-A', 'status': ['in', ['trial', 'active', 'past_due']]}",
				"name",
			)
		] = "STSUB-001"

		sub_doc = SimpleNamespace(
			name="STSUB-001",
			plan="pro",
			status="active",
			trial_end=None,
			current_period_end=None,
		)
		sub_doc.get_effective_capability_flags = lambda: {
			"feature.role.profile.seller_co_owner": True,
			"feature.role.custom_creation": True,
		}
		sub_doc.get_effective_quota_limits = lambda: {"quota.max_co_owners": 1}
		_DB[("doc", "Store Subscription", "STSUB-001")] = sub_doc
		_DB[
			(
				"get_value",
				"User Profile",
				"{'user': 'seller@x.com'}",
				"['account_type', 'kyc_status', 'kyb_status', 'can_buy', 'can_sell']",
			)
		] = {}

		result = snap.get_snapshot()
		self.assertNotIn("feature.role.profile.seller_co_owner", result["features"])
		self.assertNotIn("feature.role.custom_creation", result["features"])
		self.assertNotIn("quota.max_co_owners", result["quotas"])


class FilterTests(unittest.TestCase):
	def test_storefront_features_filter(self):
		"""_filter_for_storefront sadece izin verilen prefix'leri tutar."""
		all_flags = {
			"feature.pim.multi_variant": True,
			"feature.functional.rfq": True,
			"feature.store.custom_theme": True,
			"feature.api.access": True,
			"feature.analytics.basic": True,
			"feature.analytics.advanced": True,  # 'advanced' geçmez — sadece basic match
			"feature.role.profile.x": True,
			"feature.role.custom_creation": True,
			"feature.b2b.cost_center": True,
		}
		result = snap._filter_for_storefront(all_flags)
		self.assertIn("feature.pim.multi_variant", result)
		self.assertIn("feature.functional.rfq", result)
		self.assertIn("feature.store.custom_theme", result)
		self.assertIn("feature.api.access", result)
		self.assertIn("feature.analytics.basic", result)
		# Hassas flag'ler hariç
		self.assertNotIn("feature.role.profile.x", result)
		self.assertNotIn("feature.role.custom_creation", result)
		self.assertNotIn("feature.b2b.cost_center", result)

	def test_storefront_quota_filter(self):
		all_quotas = {
			"quota.max_products": 5000,
			"quota.max_sub_users": 10,
			"quota.max_regions": 4,
			"quota.max_co_owners": 1,  # HARİÇ — Owner-management bilgisi
			"quota.api_rate_limit": 60,  # HARİÇ
		}
		result = snap._filter_quotas_for_storefront(all_quotas)
		self.assertIn("quota.max_products", result)
		self.assertIn("quota.max_sub_users", result)
		self.assertIn("quota.max_regions", result)
		self.assertNotIn("quota.max_co_owners", result)
		self.assertNotIn("quota.api_rate_limit", result)


class CheckFeatureTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_guest_returns_false(self):
		sys.modules["frappe"].session.user = "Guest"
		result = snap.check_feature("feature.pim.multi_variant")
		self.assertFalse(result["has_feature"])
		self.assertEqual(result["reason"], "guest")

	def test_no_tenant_returns_false(self):
		sys.modules["frappe"].session.user = "lonely@x.com"
		# get_value("User", ..., "tradehub_tenant") → None
		# get_value("Admin Seller Profile", ..., "name") → None
		result = snap.check_feature("feature.pim.multi_variant")
		self.assertFalse(result["has_feature"])
		self.assertEqual(result["reason"], "no_tenant")


if __name__ == "__main__":
	unittest.main()
