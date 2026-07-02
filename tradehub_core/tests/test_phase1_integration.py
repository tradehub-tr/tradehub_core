"""FAZ 1.8 — Phase 1 cross-cutting integration tests.

7 alt-fazda üretilen tüm bileşenlerin birbirine bağlandığı senaryolar:

  1. Cross-tenant attempt → tenant.py REJECT + audit log HIGH severity
  2. Entitlement quota → cache → invalidation flow
  3. Owner-only field değişiklik teşebbüsü → Owner lock + audit
  4. Sub-user invite → plan kelepçesi + audit role_change log
  5. Storefront snapshot → storefront-safe filter doğrulanıyor

Bu testler tek tek modüllerin testleri (test_tenant_isolation, test_audit, vb.)
yetmeyince devreye girer — modüller arası kontrat'ı doğrular.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_phase1_integration
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
# Frappe stub — integration için zengin mock'lar
# ---------------------------------------------------------------------------


_DB: dict = {}
_AUDIT_LOGS: list[dict] = []  # log_decision/log_role_change/log_override yazdıkları


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

	def db_count(doctype, filters=None):
		return _DB.get(("count", doctype, str(filters)), 0)

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		count=db_count,
		exists=lambda doctype, filters=None: _DB.get(("exists", doctype, str(filters)), False),
		escape=lambda s: f"'{s}'",
		has_column=lambda *a, **kw: True,
		commit=lambda: None,
		delete=lambda *a, **kw: None,
	)

	class _CacheStub:
		_store: dict = {}

		def get_value(self, key):
			return self._store.get(key)

		def set_value(self, key, value, expires_in_sec=None):
			self._store[key] = value

		def delete_value(self, key):
			self._store.pop(key, None)

	# Cache STORE'u stub class-level — integration test'leri tek test runu için
	frappe.cache = lambda: _CacheStub()
	_DB["_cache_store"] = _CacheStub._store

	# get_doc — audit log helper'ları için audit_write flag kontrolü
	def get_doc_factory(data):
		class _Doc:
			def __init__(self, d):
				self._d = dict(d)
				self.flags = SimpleNamespace(audit_write=False, ignore_permissions=False)
				self.name = d.get("name")
				for k, v in d.items():
					if not k.startswith("_"):
						setattr(self, k, v)

			def insert(self, ignore_permissions=False, **kwargs):
				if "Log" in self._d.get("doctype", ""):
					if not getattr(self.flags, "audit_write", False):
						raise Exception("Audit log doğrudan yazılamaz")
				self.name = self.name or f"{self._d.get('doctype', 'DOC')}-{len(_AUDIT_LOGS) + 1:06d}"
				_AUDIT_LOGS.append(dict(self._d))
				return self

		if isinstance(data, dict):
			return _Doc(data)
		return _Doc({"name": data, "doctype": "Unknown"})

	frappe.get_doc = get_doc_factory

	def get_cached_doc(doctype, name):
		key = ("cached_doc", doctype, name)
		if key in _DB:
			return _DB[key]
		raise Exception(f"{doctype} '{name}' not found")

	frappe.get_cached_doc = get_cached_doc

	def get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, **kwargs):
		key = ("get_all", doctype, str(filters), str(fields), pluck)
		return _DB.get(key, [])

	frappe.get_all = get_all

	# Meta — tenant.py için seller_profile field detection
	_meta_seller_profile = {
		"Listing",
		"Order",
		"Seller Balance",
		"Seller Review",
		"Listing Review",
		"Listing Question",
	}
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

	# Exceptions + i18n
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

	if not hasattr(frappe, "logger"):
		frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None)

	if not hasattr(frappe, "utils") or not hasattr(frappe.utils, "now_datetime"):
		frappe.utils = types.ModuleType("frappe.utils")
		from datetime import datetime, timedelta

		frappe.utils.cint = int
		frappe.utils.flt = float
		frappe.utils.now_datetime = lambda: datetime(2026, 5, 21, 12, 0, 0)
		frappe.utils.add_days = lambda dt, days: (dt or datetime.now()) + timedelta(days=days)
		frappe.utils.get_url = lambda: "https://test.local"
		sys.modules["frappe.utils"] = frappe.utils

	if not hasattr(frappe, "whitelist"):

		def _whitelist(*args, **kwargs):
			def _decorator(fn):
				return fn

			if args and callable(args[0]):
				return args[0]
			return _decorator

		frappe.whitelist = _whitelist


_install_frappe_stub()


def _reset_state() -> None:
	# Cache store'u koru, geri kalanı sil
	cache_store = _DB.get("_cache_store")
	_DB.clear()
	_AUDIT_LOGS.clear()
	if cache_store is not None:
		cache_store.clear()
		_DB["_cache_store"] = cache_store
	_install_frappe_stub()


# Modülleri burada import et — stub kurulduktan sonra
from tradehub_core.entitlement import core as ent_core  # noqa: E402
from tradehub_core.utils import owner_lock, tenant  # noqa: E402


def _make_doc(doctype: str, name: str = "DOC-001", is_new: bool = True, **fields):
	doc = SimpleNamespace(doctype=doctype, name=name, **fields)
	doc.is_new = lambda: is_new
	doc.get = lambda field, default=None: getattr(doc, field, default)
	doc.set = lambda field, value: setattr(doc, field, value)
	doc.flags = SimpleNamespace()
	return doc


def _setup_seller(
	user: str, tenant_name: str, is_owner: bool = False, role_profile: str = "Seller Full Access"
):
	"""Kullanıcı + tenant + rol mapping kur."""
	_DB[("roles", user)] = ["Seller", "Seller Owner" if is_owner else "Seller Admin"]
	_DB[("get_value", "Admin Seller Profile", "{'user': '" + user + "', 'status': 'Active'}", "name")] = (
		tenant_name
	)
	_DB[("get_value", "User", user, "tradehub_is_owner")] = 1 if is_owner else 0
	_DB[("get_value", "User", user, "role_profile_name")] = role_profile


def _setup_subscription(
	tenant_name: str, plan: str, capability_flags: dict, quota_limits: dict, status: str = "active"
):
	"""Tenant için aktif subscription + plan doc mock'u."""
	sub_name = f"STSUB-{tenant_name}"
	_DB[
		(
			"get_value",
			"Store Subscription",
			"{'store': '" + tenant_name + "', 'status': ['in', ['trial', 'active', 'past_due']]}",
			"name",
		)
	] = sub_name

	sub_doc = SimpleNamespace(
		name=sub_name,
		plan=plan,
		status=status,
		trial_end=None,
		current_period_end=None,
	)
	sub_doc.get_effective_capability_flags = lambda flags=capability_flags: dict(flags)
	sub_doc.get_effective_quota_limits = lambda quotas=quota_limits: dict(quotas)
	_DB[("cached_doc", "Store Subscription", sub_name)] = sub_doc


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class CrossTenantWithAuditTests(unittest.TestCase):
	"""FAZ 1.1 + 1.4 + 1.7 chain: Cross-tenant attempt → tenant reject → HIGH audit log."""

	def setUp(self):
		_reset_state()
		# tenant modülünün original _get_seller_profile_for_user fonksiyonunu sakla
		self._original_get_seller = tenant._get_seller_profile_for_user

	def tearDown(self):
		# Diğer test dosyalarını (test_sub_users) bozmamak için restore
		tenant._get_seller_profile_for_user = self._original_get_seller

	def test_cross_tenant_attempt_rejected_with_high_audit(self):
		"""Satıcı A, Satıcı B için Listing yazmaya çalışır → reddedilir + HIGH log."""
		_setup_seller("seller-a@x.com", "STORE-A")
		_setup_seller("seller-b@x.com", "STORE-B")
		sys.modules["frappe"].session.user = "seller-a@x.com"

		# A, B'nin seller_profile'ına işaret eden Listing yazmaya çalışır
		doc = _make_doc("Listing", seller_profile="STORE-B", title="Cross attempt")

		# Mock _get_seller_profile_for_user — A'nın seller'ı STORE-A
		tenant._get_seller_profile_for_user = lambda user=None: (
			"STORE-A" if (user or "seller-a@x.com") == "seller-a@x.com" else "STORE-B"
		)

		PermissionError = sys.modules["frappe"].PermissionError
		with self.assertRaises(PermissionError):
			tenant.enforce_seller_isolation_on_insert(doc)

		# Audit log yazılmış mı?
		high_logs = [
			log
			for log in _AUDIT_LOGS
			if log.get("severity") == "HIGH" and "cross_tenant" in log.get("rule_id", "")
		]
		self.assertGreaterEqual(len(high_logs), 1, "HIGH severity audit log oluşmadı")
		self.assertEqual(high_logs[0]["actor"], "seller-a@x.com")


class EntitlementWithAuditTests(unittest.TestCase):
	"""FAZ 1.2 + 1.4 chain: Entitlement DENY → audit log L0."""

	def setUp(self):
		_reset_state()

	def test_quota_exceeded_logs_audit(self):
		"""Free plan satıcısı kota aşımı → EntitlementError + ADL DENY/L0 kaydı."""
		_setup_subscription(
			"STORE-FREE",
			"free",
			capability_flags={"feature.pim.basic_product": True},
			quota_limits={"quota.max_products": 50},
		)
		sys.modules["frappe"].session.user = "free-owner@x.com"

		# Cache'i temizle ki get_active_subscription DB'ye gitsin
		ent_core.invalidate_store_cache("STORE-FREE")

		# 50. ürün → quota exhausted (current >= limit)
		with self.assertRaises(ent_core.EntitlementError):
			ent_core.check_quota_or_throw(
				"STORE-FREE", "quota.max_products", 50, action_description="Yeni ürün"
			)

		# Audit log
		deny_logs = [
			log
			for log in _AUDIT_LOGS
			if log.get("decision") == "DENY" and "quota.max_products" in log.get("rule_id", "")
		]
		self.assertGreaterEqual(len(deny_logs), 1, "Quota DENY audit log eksik")
		self.assertEqual(deny_logs[0]["layer"], "L0")

	def test_feature_check_passes_silently_no_log(self):
		"""Feature aktif → log yazılmaz (sadece DENY'ler log'lanır)."""
		_setup_subscription(
			"STORE-PRO",
			"pro",
			capability_flags={"feature.pim.multi_variant": True},
			quota_limits={},
		)
		sys.modules["frappe"].session.user = "pro-owner@x.com"
		ent_core.invalidate_store_cache("STORE-PRO")

		# Hata yok
		ent_core.check_feature_or_throw("STORE-PRO", "feature.pim.multi_variant")

		# Audit log YAZILMAMALI (ALLOW path)
		feature_logs = [log for log in _AUDIT_LOGS if "feature.pim.multi_variant" in log.get("rule_id", "")]
		self.assertEqual(len(feature_logs), 0, "ALLOW path log üretmemeli")


class OwnerLockWithAuditTests(unittest.TestCase):
	"""FAZ 1.5 + 1.4 chain: Co-Owner banka değiştirme teşebbüsü → reject + HIGH log."""

	def setUp(self):
		_reset_state()

	def test_non_owner_iban_change_rejected_with_audit(self):
		"""Co-Owner IBAN değiştiremez + HIGH severity log."""
		sys.modules["frappe"].session.user = "coowner@x.com"
		# Co-Owner: Seller Admin var ama Seller Owner yok
		_DB[("roles", "coowner@x.com")] = ["Seller Admin", "Seller Finance"]

		# get_value("User", ..., ["tradehub_tenant", "tradehub_is_owner"])
		original_get_value = sys.modules["frappe"].db.get_value

		def patched_get_value(doctype, name, fieldname=None, **kwargs):
			if doctype == "User" and isinstance(fieldname, list):
				return ("STORE-A", 0)  # tenant=STORE-A, is_owner=0
			if doctype == "Admin Seller Profile" and isinstance(fieldname, list):
				return {"iban": "TR12-OLD", "bank_name": None, "bank_account_holder": None, "tax_id": "OLD"}
			return original_get_value(doctype, name, fieldname, **kwargs)

		sys.modules["frappe"].db.get_value = patched_get_value

		doc = _make_doc(
			"Admin Seller Profile",
			name="STORE-A",
			is_new=False,
			iban="TR99-NEW",
			bank_name=None,
			bank_account_holder=None,
			tax_id="OLD",
		)

		PermissionError = sys.modules["frappe"].PermissionError
		with self.assertRaises(PermissionError):
			owner_lock.enforce_owner_only_fields(doc)

		# Audit log
		high_logs = [
			log
			for log in _AUDIT_LOGS
			if log.get("severity") == "HIGH" and "owner_only_field" in log.get("rule_id", "")
		]
		self.assertGreaterEqual(len(high_logs), 1, "Owner-lock HIGH log eksik")
		self.assertEqual(high_logs[0]["object_doctype"], "Admin Seller Profile")
		self.assertIn("iban", str(high_logs[0].get("context", "")))


class PlanCacheInvalidationTests(unittest.TestCase):
	"""FAZ 1.2 chain: Plan değişimi → cache invalidate → yeni feature flag yansır."""

	def setUp(self):
		_reset_state()

	def test_plan_upgrade_invalidates_cache(self):
		"""Free → Pro yükseltme: cache invalidate sonrası multi_variant aktive."""
		_setup_subscription(
			"STORE-X",
			"free",
			capability_flags={"feature.pim.multi_variant": False},
			quota_limits={"quota.max_products": 50},
		)

		# İlk çağrı — Free
		self.assertFalse(ent_core.has_feature("STORE-X", "feature.pim.multi_variant"))

		# Plan'ı Pro'ya yükselt (yeni mock subscription)
		_setup_subscription(
			"STORE-X",
			"pro",
			capability_flags={"feature.pim.multi_variant": True},
			quota_limits={"quota.max_products": 5000},
		)

		# Cache invalidate
		ent_core.invalidate_store_cache("STORE-X")

		# Yeni durum yansır
		self.assertTrue(ent_core.has_feature("STORE-X", "feature.pim.multi_variant"))


class DowngradeQuotaTests(unittest.TestCase):
	"""FAZ 1.2 chain: Plan downgrade → kota daralır."""

	def setUp(self):
		_reset_state()

	def test_downgrade_reduces_quota_immediately(self):
		"""Pro (5000) → Free (50) downgrade sonrası 100 ürünlü mağaza kotayı aşar."""
		_setup_subscription(
			"STORE-Y",
			"pro",
			capability_flags={},
			quota_limits={"quota.max_products": 5000},
		)

		# Pro plan'da 100 ürün → OK
		self.assertTrue(ent_core.within_quota("STORE-Y", "quota.max_products", 100))

		# Downgrade
		_setup_subscription(
			"STORE-Y",
			"free",
			capability_flags={},
			quota_limits={"quota.max_products": 50},
		)
		ent_core.invalidate_store_cache("STORE-Y")

		# Aynı 100 ürün → artık kota aşımı
		self.assertFalse(ent_core.within_quota("STORE-Y", "quota.max_products", 100))


class PiiMaskingTests(unittest.TestCase):
	"""FAZ 1.3 chain: mask_value + has_pii_access doğru entegre."""

	def setUp(self):
		_reset_state()

	def test_mask_value_for_logs(self):
		"""Audit log'a IBAN yazılırken maskelenmeli (helper test)."""
		from tradehub_core.utils import pii

		# IBAN
		masked = pii.mask_value("TR12 0006 2000 1234 5678 9012 34", "iban")
		self.assertTrue(masked.startswith("TR12"))
		self.assertTrue(masked.endswith("**34"))
		self.assertIn("****", masked)

		# Tax ID
		masked_tax = pii.mask_value("1234567890", "tax_id")
		self.assertEqual(masked_tax, "******7890")

	def test_compliance_officer_full_pii_access(self):
		"""Compliance Officer permlevel 3'e erişebilmeli."""
		from tradehub_core.utils import pii

		_DB[("roles", "compliance@x.com")] = ["Compliance Officer"]
		_DB[
			(
				"exists",
				"Custom DocPerm",
				"{'parent': 'KYC Verification', 'role': ['in', ['Compliance Officer']], 'permlevel': 3, 'read': 1}",
			)
		] = "DocPerm-001"

		self.assertTrue(pii.has_pii_access("compliance@x.com", "KYC Verification", 3))


if __name__ == "__main__":
	unittest.main()
