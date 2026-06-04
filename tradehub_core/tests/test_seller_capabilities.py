"""Per-rol capability matrix testleri.

`tradehub_core.utils.seller_capabilities` modülünün has_seller_capability +
require_seller_capability + get_user_capabilities fonksiyonlarını her satıcı
rol profili için doğrular. Pattern: test_sub_users.py ile aynı frappe stub.

Run: cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_seller_capabilities
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
# Minimal frappe stub
# ---------------------------------------------------------------------------

_USERS: dict[str, dict] = {}
_ROLES: dict[str, list[str]] = {}
# Plan feature mock: tenant → {feature_key → bool}. Default boş → has_feature
# default True döner (testlerin çoğu plan-feature ayrımına bakmaz).
_PLAN_FEATURES: dict[str, dict[str, bool]] = {}


def _install_frappe_stub() -> None:
	# Test isolation: mevcut frappe module'ünü mutate et (replace etme),
	# çünkü diğer test modülleri zaten `import frappe` ile referans almış.
	# Replace edersek o referanslar eski stub'a takılı kalır.
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Guest")
	frappe.get_roles = lambda u=None: _ROLES.get(u or frappe.session.user, [])

	def db_get_value(doctype, name=None, fieldname=None, as_dict=False, **kwargs):
		# Admin Seller Profile lookup — owner'lar için tenant resolve etmek için.
		if doctype == "Admin Seller Profile":
			filters = name if isinstance(name, dict) else {}
			target_user = filters.get("user")
			if target_user and _USERS.get(target_user, {}).get("has_admin_seller_profile"):
				return f"SEL-{target_user.split('@')[0].upper()}"
			return None
		# User Profile lookup — K4 KYC check için.
		if doctype == "User Profile":
			filters = name if isinstance(name, dict) else {}
			target_user = filters.get("user")
			profile = _USER_PROFILES.get(target_user)
			if not profile:
				return None
			if as_dict:
				if isinstance(fieldname, list):
					return {f: profile.get(f) for f in fieldname}
				return dict(profile)
			if isinstance(fieldname, list):
				return [profile.get(f) for f in fieldname]
			return profile.get(fieldname)
		if doctype != "User":
			return None
		# name parametresi user email
		user = name if isinstance(name, str) else None
		if not user:
			return None
		user_data = _USERS.get(user, {})

		if as_dict:
			if isinstance(fieldname, list):
				return {f: user_data.get(f) for f in fieldname}
			return dict(user_data)
		if isinstance(fieldname, list):
			return [user_data.get(f) for f in fieldname]
		return user_data.get(fieldname)

	def db_exists(doctype, filters=None):
		# Sadece Admin Seller Profile için seller-relation check'i destekler
		if doctype != "Admin Seller Profile" or not isinstance(filters, dict):
			return False
		target_user = filters.get("user")
		if not target_user:
			return False
		# _USERS içinde "has_admin_seller_profile" flag'i olursa True döner
		return bool(_USERS.get(target_user, {}).get("has_admin_seller_profile"))

	def db_table_exists(_table_name):
		# Saf-Python testler için DB yok; Sprint 6 DB-driven lookup'lar
		# Python sabit listelerine fallback eder.
		return False

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=db_exists,
		table_exists=db_table_exists,
	)

	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *args, **kwargs: None

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class _PE(Exception):
			pass

		frappe.PermissionError = _PE
	if not hasattr(frappe, "throw"):

		def _throw(msg, exc=Exception):
			raise exc(msg) if isinstance(exc, type) else Exception(msg)

		frappe.throw = _throw


def _install_entitlement_stub() -> None:
	"""Test izolasyonu: tradehub_core.entitlement.has_feature stub'ı.

	Default: feature yoksa True döner (testlerin çoğu plan-feature ayrımına
	bakmaz, eski testler eski varsayımla çalışsın). Plan-aware testler
	_PLAN_FEATURES'a explicit set ederek plan kısıtı simüle eder.
	"""
	ent_mod = sys.modules.get("tradehub_core.entitlement")
	if ent_mod is None:
		ent_mod = types.ModuleType("tradehub_core.entitlement")
		sys.modules["tradehub_core.entitlement"] = ent_mod

	def has_feature(tenant, feature_key):
		if not tenant:
			return False
		tenant_map = _PLAN_FEATURES.get(tenant)
		if tenant_map is None:
			return True  # default: tanımsız tenant her feature'ı var sayar
		return tenant_map.get(feature_key, False)

	def check_feature_or_throw(tenant, feature_key, action_description=""):
		if not has_feature(tenant, feature_key):
			raise sys.modules["frappe"].PermissionError(f"feature missing: {feature_key}")

	def check_quota_or_throw(tenant, quota_key, current_count, action_description=""):
		pass  # no-op for tests

	ent_mod.has_feature = has_feature
	ent_mod.check_feature_or_throw = check_feature_or_throw
	ent_mod.check_quota_or_throw = check_quota_or_throw


_install_frappe_stub()
_install_entitlement_stub()


def _reset_state() -> None:
	_USERS.clear()
	_ROLES.clear()
	_PLAN_FEATURES.clear()
	_USER_PROFILES.clear()
	# Test isolation: başka bir test modülü (örn. test_sub_users) frappe stub'ını
	# kendi imzasıyla overwrite etmiş olabilir. Her test setUp'ında BİZİM stub'ı
	# yeniden install et ki db.get_value(doctype, user, fieldname) imzası çalışsın.
	_install_frappe_stub()
	_install_entitlement_stub()


_USER_PROFILES: dict[str, dict] = {}


def _set_user_profile(
	user,
	*,
	kyc_status="Verified",
	kyb_status=None,
	account_type="Business",
):
	"""User Profile mock — K4 KYC check için."""
	_USER_PROFILES[user] = {
		"kyc_status": kyc_status,
		"kyb_status": kyb_status,
		"account_type": account_type,
	}


def _set_user(
	email,
	*,
	is_owner=0,
	role_profile_name="",
	roles=None,
	enabled=1,
	tenant=None,
	has_admin_seller_profile=False,
):
	"""Test user'ı kur.

	C1/H3 preconditions için ek field'lar:
	- enabled: User.enabled (deactive user capability alamaz)
	- tenant: tradehub_tenant link (sub-user için)
	- has_admin_seller_profile: Owner'lar için Admin Seller Profile varlığı

	Default: seller bir user kur (Co-Owner default'ları tenant ile geçer).
	Buyer test'leri için tenant=None + has_admin_seller_profile=False.
	"""
	# Default seller-relation: tenant=SEL-TEST eğer hiç verilmediyse owner değil
	if tenant is None and not is_owner and not has_admin_seller_profile and roles is None:
		tenant = "SEL-TEST"  # default: sub-user var sayalım
	_USERS[email] = {
		"tradehub_is_owner": is_owner,
		"role_profile_name": role_profile_name,
		"enabled": enabled,
		"tradehub_tenant": tenant,
		"has_admin_seller_profile": has_admin_seller_profile,
	}
	# Owner ise Admin Seller Profile var say
	if is_owner and not has_admin_seller_profile:
		_USERS[email]["has_admin_seller_profile"] = True
	_ROLES[email] = roles or []
	sys.modules["frappe"].session.user = email


# Capabilities matrisi referansı — testlerin matrise kilitlenmesi.
# Matris değişirse bu listeler güncellenmeli.
_OPERATIONS_CAPS = {
	"order.ship",
	"listing.write",
	"listing.publish",
	"gallery.write",
	"category.write",
	"inquiry.reply",
	"rfq.quote",
	"crm.lead_capture",
	"view.customer_shipping",
}
_FINANCE_CAPS = {
	"order.confirm_payment",
	"order.refund",
	"balance.withdraw",
	"view.financial_summary",
	"view.balance",
	"view.order_amounts",
}
_MANAGEMENT_CAPS = {
	"listing.delete",
	"seller_profile.write",
	"storefront.write",
	"cert.write",
	"address.write",
	"kyb.submit",
	"view.profit_detail",
}
# Sales tier — Manager + Co-Owner + Sales Rep + Owner Full Access içerir
# (Operations ve Finance Staff bu capability'leri görmez).
_SALES_CAPS = {"view.customer_full"}
_COOWNER_CAPS = {"subuser.manage", "view.bank_info"}
_OWNER_ONLY_CAPS = {
	"bank_info.write",
	"tax_info.write",
	"account.delete",
	"owner.transfer",
	"subscription.change",
	"two_factor.disable",
}


from tradehub_core.utils import seller_capabilities as sc  # noqa: E402


class GuestAndAdminTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_guest_has_no_capabilities(self):
		sys.modules["frappe"].session.user = "Guest"
		self.assertFalse(sc.has_seller_capability("order.ship"))
		self.assertEqual(sc.get_user_capabilities(), [])

	def test_administrator_bypasses_everything(self):
		_set_user("Administrator", roles=["Administrator"])
		sys.modules["frappe"].session.user = "Administrator"
		self.assertTrue(sc.has_seller_capability("order.ship"))
		self.assertTrue(sc.has_seller_capability("bank_info.write"))
		caps = set(sc.get_user_capabilities())
		# Administrator en az SELLER_CAPABILITIES listesini taşımalı; Sprint 6
		# sonrası TH Capability Registry'de ek capability'ler olabilir
		# (örn. owner.transfer, account.delete) — superset olması yeterli.
		self.assertTrue(
			set(sc.SELLER_CAPABILITIES.keys()).issubset(caps),
			f"Eksik capability'ler: {set(sc.SELLER_CAPABILITIES.keys()) - caps}",
		)

	def test_system_manager_bypasses(self):
		_set_user("admin@x.com", roles=["System Manager"])
		self.assertTrue(sc.has_seller_capability("order.ship"))
		self.assertTrue(sc.has_seller_capability("bank_info.write"))

	def test_unknown_capability_denies(self):
		"""Tanımlanmamış capability → fail-secure False."""
		_set_user("u@x.com", role_profile_name="Seller Full Access")
		self.assertFalse(sc.has_seller_capability("unknown.cap"))


class FullAccessProfileTests(unittest.TestCase):
	"""Seller Full Access — Owner profili eşdeğeri (5 role).

	is_owner=1 olduğu için OWNER_ONLY dahil hepsini almalı.
	is_owner=0 olduğu durumda OWNER_ONLY almamalı (Full Access profil
	owner-only'ı tek başına açmaz; tradehub_is_owner şart).
	"""

	def setUp(self):
		_reset_state()

	def test_owner_full_access_gets_everything(self):
		_set_user("owner@x.com", is_owner=1, role_profile_name="Seller Full Access")
		expected = (
			_OPERATIONS_CAPS
			| _FINANCE_CAPS
			| _MANAGEMENT_CAPS
			| _SALES_CAPS
			| _COOWNER_CAPS
			| _OWNER_ONLY_CAPS
		)
		got = set(sc.get_user_capabilities("owner@x.com"))
		self.assertEqual(got, expected)

	def test_non_owner_full_access_gets_all_except_owner_only(self):
		"""Full Access profile sahibi ama is_owner=0 → owner-only HAYIR."""
		_set_user("co@x.com", is_owner=0, role_profile_name="Seller Full Access")
		got = set(sc.get_user_capabilities("co@x.com"))
		expected = _OPERATIONS_CAPS | _FINANCE_CAPS | _MANAGEMENT_CAPS | _SALES_CAPS | _COOWNER_CAPS
		self.assertEqual(got, expected)
		self.assertFalse(sc.has_seller_capability("bank_info.write", "co@x.com"))


class CoOwnerProfileTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_coowner_gets_ops_finance_management_subuser(self):
		_set_user("co@x.com", role_profile_name="Seller Co-Owner")
		got = set(sc.get_user_capabilities("co@x.com"))
		expected = _OPERATIONS_CAPS | _FINANCE_CAPS | _MANAGEMENT_CAPS | _SALES_CAPS | _COOWNER_CAPS
		self.assertEqual(got, expected)

	def test_coowner_denied_owner_only(self):
		_set_user("co@x.com", role_profile_name="Seller Co-Owner")
		for cap in _OWNER_ONLY_CAPS:
			self.assertFalse(sc.has_seller_capability(cap), f"Co-Owner should NOT have {cap}")


class ManagerProfileTests(unittest.TestCase):
	"""Seller Manager — Co-Owner'la aynı role'lere sahip ama subuser yetkisi YOK."""

	def setUp(self):
		_reset_state()

	def test_manager_gets_ops_finance_management(self):
		_set_user("mgr@x.com", role_profile_name="Seller Manager")
		got = set(sc.get_user_capabilities("mgr@x.com"))
		expected = _OPERATIONS_CAPS | _FINANCE_CAPS | _MANAGEMENT_CAPS | _SALES_CAPS
		self.assertEqual(got, expected)

	def test_manager_denied_subuser_management(self):
		_set_user("mgr@x.com", role_profile_name="Seller Manager")
		self.assertFalse(sc.has_seller_capability("subuser.manage"))

	def test_manager_denied_owner_only(self):
		_set_user("mgr@x.com", role_profile_name="Seller Manager")
		for cap in _OWNER_ONLY_CAPS:
			self.assertFalse(sc.has_seller_capability(cap))


class OperationsProfileTests(unittest.TestCase):
	"""Seller Operations — Staff + Viewer; ship/listing.write yapabilir,
	finans işlemleri YAPAMAZ (asıl bug bu role idi)."""

	def setUp(self):
		_reset_state()

	def test_operations_gets_only_ops_caps(self):
		_set_user("ops@x.com", role_profile_name="Seller Operations")
		got = set(sc.get_user_capabilities("ops@x.com"))
		self.assertEqual(got, _OPERATIONS_CAPS)

	def test_operations_can_ship(self):
		_set_user("ops@x.com", role_profile_name="Seller Operations")
		self.assertTrue(sc.has_seller_capability("order.ship"))

	def test_operations_cannot_confirm_payment(self):
		_set_user("ops@x.com", role_profile_name="Seller Operations")
		self.assertFalse(sc.has_seller_capability("order.confirm_payment"))

	def test_operations_cannot_refund(self):
		_set_user("ops@x.com", role_profile_name="Seller Operations")
		self.assertFalse(sc.has_seller_capability("order.refund"))

	def test_operations_cannot_manage_subusers(self):
		_set_user("ops@x.com", role_profile_name="Seller Operations")
		self.assertFalse(sc.has_seller_capability("subuser.manage"))


class FinanceStaffProfileTests(unittest.TestCase):
	"""Seller Finance Staff — Finance + Viewer; payment/refund/withdraw yapabilir,
	ship YAPAMAZ (asıl bug bu role idi)."""

	def setUp(self):
		_reset_state()

	def test_finance_staff_gets_only_finance_caps(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		got = set(sc.get_user_capabilities("fin@x.com"))
		self.assertEqual(got, _FINANCE_CAPS)

	def test_finance_staff_can_confirm_payment(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		self.assertTrue(sc.has_seller_capability("order.confirm_payment"))

	def test_finance_staff_can_refund(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		self.assertTrue(sc.has_seller_capability("order.refund"))

	def test_finance_staff_can_withdraw(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		self.assertTrue(sc.has_seller_capability("balance.withdraw"))

	def test_finance_staff_cannot_ship(self):
		"""CRITICAL: Bu bug'ın doğrudan testidir.

		Reported issue: Finance Staff was able to call seller_ship_order.
		After this fix, has_seller_capability("order.ship") must be False
		AND require_seller_capability("order.ship") must raise PermissionError.
		"""
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		self.assertFalse(sc.has_seller_capability("order.ship"))
		with self.assertRaises(sys.modules["frappe"].PermissionError):
			sc.require_seller_capability("order.ship")

	def test_finance_staff_cannot_edit_listing(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		self.assertFalse(sc.has_seller_capability("listing.write"))

	def test_finance_staff_cannot_edit_profile(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		self.assertFalse(sc.has_seller_capability("seller_profile.write"))

	def test_finance_staff_cannot_submit_kyb(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		self.assertFalse(sc.has_seller_capability("kyb.submit"))

	def test_finance_staff_cannot_manage_subusers(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		self.assertFalse(sc.has_seller_capability("subuser.manage"))

	def test_finance_staff_cannot_owner_only(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		for cap in _OWNER_ONLY_CAPS:
			self.assertFalse(sc.has_seller_capability(cap))


class RequireCapabilityRaisingTests(unittest.TestCase):
	"""require_seller_capability ve decorator integration kontrolü."""

	def setUp(self):
		_reset_state()

	def test_require_raises_for_unauthorized(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")
		with self.assertRaises(sys.modules["frappe"].PermissionError):
			sc.require_seller_capability("order.ship")

	def test_require_passes_for_authorized(self):
		_set_user("ops@x.com", role_profile_name="Seller Operations")
		# raises etmemeli
		sc.require_seller_capability("order.ship")

	def test_decorator_blocks_unauthorized(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff")

		@sc.seller_capability_required("order.ship")
		def _fn():
			return "shipped"

		with self.assertRaises(sys.modules["frappe"].PermissionError):
			_fn()

	def test_decorator_allows_authorized(self):
		_set_user("ops@x.com", role_profile_name="Seller Operations")

		@sc.seller_capability_required("order.ship")
		def _fn():
			return "shipped"

		self.assertEqual(_fn(), "shipped")


class OwnerFlagTests(unittest.TestCase):
	"""tradehub_is_owner=1 user'ı her zaman tam yetki almalı (Full Access dahil)."""

	def setUp(self):
		_reset_state()

	def test_owner_flag_grants_owner_only_caps(self):
		_set_user("owner@x.com", is_owner=1, role_profile_name="Seller Full Access")
		for cap in _OWNER_ONLY_CAPS:
			self.assertTrue(sc.has_seller_capability(cap), f"Owner should have {cap}")

	def test_owner_without_profile_still_full(self):
		"""Defensive: is_owner=1 ama role_profile_name boş — yine de yetki almalı."""
		_set_user("owner@x.com", is_owner=1, role_profile_name="")
		self.assertTrue(sc.has_seller_capability("order.ship"))
		self.assertTrue(sc.has_seller_capability("bank_info.write"))


# ─────────────────────────────────────────────────────────────────────────
# C1 regression: role_profile_name string-match privilege escalation
# ─────────────────────────────────────────────────────────────────────────


class C1_RoleProfileStringMatchTests(unittest.TestCase):
	"""C1 regression — yanlış profil atanmış buyer/orphan user'a
	capability sızıntısı olmamalı.

	Önceden has_seller_capability tek başına role_profile_name'e bakıyordu.
	Şimdi seller relation (tenant VEYA Admin Seller Profile) şart.
	"""

	def setUp(self):
		_reset_state()

	def test_buyer_with_injected_seller_manager_profile_denied(self):
		"""Bir buyer'a yanlışlıkla 'Seller Manager' atandı → capability ALMAMALI."""
		# Buyer: tenant yok + admin seller profile yok + rolleri sadece Buyer
		_USERS["buyer@x.com"] = {
			"tradehub_is_owner": 0,
			"role_profile_name": "Seller Manager",
			"enabled": 1,
			"tradehub_tenant": None,
			"has_admin_seller_profile": False,
		}
		_ROLES["buyer@x.com"] = ["Buyer"]
		sys.modules["frappe"].session.user = "buyer@x.com"

		self.assertFalse(sc.has_seller_capability("order.ship", "buyer@x.com"))
		self.assertFalse(sc.has_seller_capability("order.refund", "buyer@x.com"))
		self.assertFalse(sc.has_seller_capability("seller_profile.write", "buyer@x.com"))
		self.assertEqual(sc.get_user_capabilities("buyer@x.com"), [])

	def test_orphan_user_with_seller_full_access_profile_denied(self):
		"""Owner pasifleştirilmiş ama sub-user'ın role_profile_name'i durur.
		Tenant link bozulmuşsa capability vermemeli.
		"""
		_USERS["orphan@x.com"] = {
			"tradehub_is_owner": 0,
			"role_profile_name": "Seller Full Access",
			"enabled": 1,
			"tradehub_tenant": None,  # tenant gitti
			"has_admin_seller_profile": False,
		}
		_ROLES["orphan@x.com"] = []
		self.assertEqual(sc.get_user_capabilities("orphan@x.com"), [])

	def test_seller_owner_via_admin_seller_profile_works(self):
		"""tenant yok ama Admin Seller Profile.user=self → Owner sayılır."""
		_set_user(
			"owner@x.com",
			is_owner=1,
			role_profile_name="Seller Full Access",
			has_admin_seller_profile=True,
		)
		# is_owner=1 zaten tenant şartını otomatik geçer
		self.assertTrue(sc.has_seller_capability("order.ship"))


# ─────────────────────────────────────────────────────────────────────────
# H3 regression: deactivated user capability sızıntısı
# ─────────────────────────────────────────────────────────────────────────


class H3_DeactivatedUserTests(unittest.TestCase):
	"""H3 regression — User.enabled=0 olan user capability almamalı.

	Senaryo: Sub-user pasifleştirilmiş ama stale session reuse ediliyor.
	"""

	def setUp(self):
		_reset_state()

	def test_deactivated_coowner_no_capabilities(self):
		_set_user(
			"deact@x.com",
			role_profile_name="Seller Co-Owner",
			enabled=0,
			tenant="SEL-TEST",
		)
		self.assertEqual(sc.get_user_capabilities("deact@x.com"), [])
		self.assertFalse(sc.has_seller_capability("order.ship"))
		self.assertFalse(sc.has_seller_capability("subuser.manage"))

	def test_deactivated_owner_no_capabilities(self):
		"""Pasifleştirilen owner bile capability almamalı."""
		_set_user(
			"deact_owner@x.com",
			is_owner=1,
			role_profile_name="Seller Full Access",
			enabled=0,
			has_admin_seller_profile=True,
		)
		self.assertEqual(sc.get_user_capabilities("deact_owner@x.com"), [])
		self.assertFalse(sc.has_seller_capability("bank_info.write"))


# ─────────────────────────────────────────────────────────────────────────
# Whitespace ve edge case regression
# ─────────────────────────────────────────────────────────────────────────


class EdgeCaseRegressionTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_role_profile_with_whitespace_normalized(self):
		"""role_profile_name='  Seller Manager  ' (DB importu kirli olabilir) → strip ile match."""
		_set_user("u@x.com", role_profile_name="  Seller Manager  ")
		self.assertTrue(sc.has_seller_capability("order.ship"))

	def test_unknown_role_profile_no_capabilities(self):
		"""Tanımsız profile (örn. 'Random Profile') → boş capability."""
		_set_user("u@x.com", role_profile_name="Random Custom Profile")
		self.assertEqual(sc.get_user_capabilities("u@x.com"), [])

	def test_marketplace_admin_bypasses(self):
		"""M6: Marketplace Admin de platform-tier bypass'ı almalı."""
		_set_user("mkt@x.com", roles=["Marketplace Admin"])
		self.assertTrue(sc.has_seller_capability("order.ship"))
		self.assertTrue(sc.has_seller_capability("bank_info.write"))
		caps = sc.get_user_capabilities("mkt@x.com")
		# Marketplace Admin tüm matrise erişebilir (ama owner-only farklı handle ediliyor)
		self.assertGreater(len(caps), 15)


# ─────────────────────────────────────────────────────────────────────────
# Plan-aware (pricing entegrasyonu) regression
# ─────────────────────────────────────────────────────────────────────────


class PlanAwareCapabilityTests(unittest.TestCase):
	"""Plan ↔ Capability entegrasyon testleri.

	rfq.quote → feature.functional.rfq gerekir
	crm.lead_capture → feature.crm.module gerekir

	Plan'da feature yoksa role tier'da olsa bile capability reddedilmeli.
	Pricing sayfasında "FREE plan'da RFQ yok" yazısının gerçek karşılığı.
	"""

	def setUp(self):
		_reset_state()

	def test_pro_plan_operations_can_use_rfq(self):
		"""Pro plan + Operations → rfq.quote PASS."""
		_set_user("ops@pro.com", role_profile_name="Seller Operations", tenant="SEL-PRO")
		_PLAN_FEATURES["SEL-PRO"] = {"feature.functional.rfq": True, "feature.crm.module": True}
		self.assertTrue(sc.has_seller_capability("rfq.quote"))
		self.assertTrue(sc.has_seller_capability("crm.lead_capture"))

	def test_free_plan_operations_cannot_use_rfq(self):
		"""Free plan + Operations → rfq.quote BLOK (plan'da feature yok)."""
		_set_user("ops@free.com", role_profile_name="Seller Operations", tenant="SEL-FREE")
		_PLAN_FEATURES["SEL-FREE"] = {"feature.functional.rfq": False, "feature.crm.module": False}
		self.assertFalse(sc.has_seller_capability("rfq.quote"))
		self.assertFalse(sc.has_seller_capability("crm.lead_capture"))
		# Plan-bağımsız capability'ler hala çalışmalı:
		self.assertTrue(sc.has_seller_capability("order.ship"))
		self.assertTrue(sc.has_seller_capability("listing.write"))

	def test_owner_on_free_plan_cannot_use_rfq(self):
		"""Owner bile FREE plan'da rfq.quote yapamaz (pricing tutarlılığı)."""
		_set_user(
			"owner@free.com",
			is_owner=1,
			role_profile_name="Seller Full Access",
			has_admin_seller_profile=True,
		)
		# Owner'ın tenant'ı auto-resolve edilir: "SEL-OWNER"
		_PLAN_FEATURES["SEL-OWNER"] = {"feature.functional.rfq": False, "feature.crm.module": False}
		# Owner bank_info ALABILIR (owner-only plan-bağımsız)
		self.assertTrue(sc.has_seller_capability("bank_info.write"))
		# Ama plan'da rfq yoksa kullanamaz
		self.assertFalse(sc.has_seller_capability("rfq.quote"))
		self.assertFalse(sc.has_seller_capability("crm.lead_capture"))

	def test_get_user_capabilities_filters_by_plan(self):
		"""get_user_capabilities listesinde plan-bağımlı feature olmasın."""
		_set_user("ops@free.com", role_profile_name="Seller Operations", tenant="SEL-FREE")
		_PLAN_FEATURES["SEL-FREE"] = {"feature.functional.rfq": False, "feature.crm.module": False}
		caps = set(sc.get_user_capabilities())
		self.assertNotIn("rfq.quote", caps)
		self.assertNotIn("crm.lead_capture", caps)
		self.assertIn("order.ship", caps)

	def test_no_tenant_means_no_plan_features(self):
		"""Tenant resolve edilemezse (Admin Seller Profile yok) plan-bağımlı
		feature kullanılamaz."""
		# Sub-user için tenant atayıp sonra silelim
		_set_user("ghost@x.com", role_profile_name="Seller Operations", tenant=None)
		# Manually unset
		_USERS["ghost@x.com"]["tradehub_tenant"] = None
		# Plan-bağımsız capability'ler de False çıkar (seller relation yok)
		self.assertFalse(sc.has_seller_capability("rfq.quote"))


# ─────────────────────────────────────────────────────────────────────────
# K4 regression: KYC verification şartı (Finance + bank_info)
# ─────────────────────────────────────────────────────────────────────────


class K4_KYCRequirementTests(unittest.TestCase):
	"""KYC verified olmayan user finance capability alamaz."""

	def setUp(self):
		_reset_state()

	def test_finance_staff_with_kyc_pending_denied(self):
		"""KYC=Pending olan Finance Staff order.confirm_payment yapamamalı."""
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff", tenant="SEL-TEST")
		_set_user_profile("fin@x.com", kyc_status="Pending", account_type="Business")
		self.assertFalse(sc.has_seller_capability("order.confirm_payment"))
		self.assertFalse(sc.has_seller_capability("order.refund"))
		self.assertFalse(sc.has_seller_capability("balance.withdraw"))

	def test_finance_staff_with_kyc_verified_allowed(self):
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff", tenant="SEL-TEST")
		_set_user_profile("fin@x.com", kyc_status="Verified", account_type="Business")
		self.assertTrue(sc.has_seller_capability("order.confirm_payment"))
		self.assertTrue(sc.has_seller_capability("order.refund"))
		self.assertTrue(sc.has_seller_capability("balance.withdraw"))

	def test_owner_with_kyc_pending_denied_bank_info(self):
		"""Owner bile KYC verified değilse bank_info değiştiremez."""
		_set_user(
			"owner@x.com",
			is_owner=1,
			role_profile_name="Seller Full Access",
			has_admin_seller_profile=True,
		)
		_set_user_profile("owner@x.com", kyc_status="Pending", account_type="Business")
		self.assertFalse(sc.has_seller_capability("bank_info.write"))
		# Owner ama diğer owner-only KYC gerektirmiyor
		self.assertTrue(sc.has_seller_capability("account.delete"))

	def test_individual_account_bypasses_kyc(self):
		"""account_type=Individual → KYC bypass (ABAC ile uyumlu)."""
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff", tenant="SEL-TEST")
		_set_user_profile("fin@x.com", kyc_status="Pending", account_type="Individual")
		self.assertTrue(sc.has_seller_capability("order.confirm_payment"))

	def test_no_user_profile_graceful_pass(self):
		"""User Profile yok = legacy user, KYC check bypass."""
		_set_user("legacy@x.com", role_profile_name="Seller Finance Staff", tenant="SEL-TEST")
		# Profile set etmedik → None döner
		self.assertTrue(sc.has_seller_capability("order.confirm_payment"))

	def test_kyb_verified_also_passes(self):
		"""KYB Verified de KYC Verified olarak sayılır."""
		_set_user("fin@x.com", role_profile_name="Seller Finance Staff", tenant="SEL-TEST")
		_set_user_profile("fin@x.com", kyc_status="Pending", kyb_status="Verified", account_type="Business")
		self.assertTrue(sc.has_seller_capability("order.refund"))


# ─────────────────────────────────────────────────────────────────────────
# K6 regression: ReBAC Role Delegation görünürlüğü
# ─────────────────────────────────────────────────────────────────────────


class K6_RoleDelegationTests(unittest.TestCase):
	"""User'a delegasyonla verilen Frappe role'ler capability sistem'ce
	görünmeli — profile match etmese bile."""

	def setUp(self):
		_reset_state()

	def test_operations_with_delegated_finance_role_gets_refund(self):
		"""Operations profile + delegated 'Seller Finance' role → order.refund alır."""
		_set_user(
			"ops@x.com",
			role_profile_name="Seller Operations",
			tenant="SEL-TEST",
			roles=["Seller Staff", "Seller Viewer", "Seller Finance"],  # delegated
		)
		# Operations tier rfq.quote'a sahip (profile + plan check geçer)
		self.assertTrue(sc.has_seller_capability("order.ship"))
		# Profile Finance değil AMA Seller Finance role delegasyonla var
		self.assertTrue(sc.has_seller_capability("order.refund"))
		self.assertTrue(sc.has_seller_capability("order.confirm_payment"))

	def test_finance_staff_with_delegated_staff_role_gets_ship(self):
		"""Finance Staff + delegated 'Seller Staff' role → order.ship alır."""
		_set_user(
			"fin@x.com",
			role_profile_name="Seller Finance Staff",
			tenant="SEL-TEST",
			roles=["Seller Finance", "Seller Viewer", "Seller Staff"],
		)
		self.assertTrue(sc.has_seller_capability("order.refund"))  # normal
		self.assertTrue(sc.has_seller_capability("order.ship"))  # delegated

	def test_operations_with_delegated_admin_gets_management_tier(self):
		"""Operations + delegated 'Seller Admin' → tüm management capability'leri."""
		_set_user(
			"ops@x.com",
			role_profile_name="Seller Operations",
			tenant="SEL-TEST",
			roles=["Seller Staff", "Seller Viewer", "Seller Admin"],
		)
		self.assertTrue(sc.has_seller_capability("listing.delete"))
		self.assertTrue(sc.has_seller_capability("seller_profile.write"))
		self.assertTrue(sc.has_seller_capability("cert.write"))

	def test_co_owner_role_grants_subuser_manage_via_delegation(self):
		"""'Seller Co-Owner' Frappe role'ü delegasyonla varsa subuser.manage alır."""
		_set_user(
			"u@x.com",
			role_profile_name="Seller Manager",  # profile'da subuser.manage yok
			tenant="SEL-TEST",
			roles=["Seller Admin", "Seller Co-Owner"],  # delegated Co-Owner
		)
		self.assertTrue(sc.has_seller_capability("subuser.manage"))

	def test_no_delegation_no_extra_capabilities(self):
		"""Delegation yoksa profile tier'ı dışı capability alınmaz."""
		_set_user(
			"ops@x.com",
			role_profile_name="Seller Operations",
			tenant="SEL-TEST",
			roles=["Seller Staff", "Seller Viewer"],  # delegation yok
		)
		self.assertTrue(sc.has_seller_capability("order.ship"))
		self.assertFalse(sc.has_seller_capability("order.refund"))
		self.assertFalse(sc.has_seller_capability("subuser.manage"))


if __name__ == "__main__":
	unittest.main()
