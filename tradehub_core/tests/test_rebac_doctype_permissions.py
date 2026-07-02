"""FAZ 3.6 — ReBAC/Audit DocType izolasyon testleri.

permissions.py içindeki yeni query_conditions / has_permission çiftleri:
  - order_approval / approval_rule (organization-bazlı)
  - cost_center (buyer tenant-bazlı)
  - owner_transfer_request / role_delegation (seller tenant-bazlı)
  - authorization_decision_log / role_change_log (platform + tenant)
  - authorization_anomaly_alert (platform + tenant)
  - authorization_anomaly_rule / permission_override_log / pii_field_policy (platform-only)

Saf-Python unittest:

    cd apps/tradehub_core && python3 -m unittest \
        tradehub_core.tests.test_rebac_doctype_permissions
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

_DB: dict = {}
_ROLES: dict[str, list[str]] = {}
_ORG_PARENT: dict[str, str | None] = {}


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	def db_get_value(doctype, filters=None, fieldname=None, **kw):
		# Organization hiyerarşisi sorgusu
		if doctype == "CRM Organization" and fieldname == "tradehub_parent_org":
			return _ORG_PARENT.get(filters)
		# User → tradehub_parent_organization veya tenant alanları
		if doctype == "User" and isinstance(filters, str):
			return _DB.get(("User", filters, fieldname))
		# Admin Seller Profile lookup'ları
		if doctype == "Admin Seller Profile" and isinstance(filters, dict):
			# (filter_dict, fieldname) anahtarına göre döner
			return _DB.get(("ASP_lookup", str(filters), fieldname))
		return _DB.get((doctype, str(filters), fieldname))

	def db_exists(*a, **kw):
		return False

	def get_all(doctype, filters=None, pluck=None, **kw):
		return _DB.get(("get_all", doctype, str(filters), pluck), [])

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=db_exists,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		# _buyer_tenant_for_user has_column guard'ı kullanıyor; stub'ın bu alanları
		# "var" sayması lazım yoksa buyer tenant çözülemez → cost_center 1=0 (drift).
		has_column=lambda dt, col, *a, **kw: col in ("tradehub_buyer_tenant", "tradehub_tenant"),
	)
	frappe.session = SimpleNamespace(user="Guest")
	frappe.local = SimpleNamespace()
	frappe.get_all = get_all
	frappe.get_roles = lambda u: _ROLES.get(u, [])

	_cache_store: dict = {}

	class _CacheStub:
		def get_value(self, key):
			return _cache_store.get(key)

		def set_value(self, key, value, expires_in_sec=None):
			_cache_store[key] = value

		def delete_value(self, key):
			_cache_store.pop(key, None)

	frappe.cache = lambda: _CacheStub()

	class _MetaStub:
		def __init__(self, doctype):
			self.doctype = doctype

		def has_field(self, fieldname):
			return False

	frappe.get_meta = lambda doctype: _MetaStub(doctype)

	class PermissionError(Exception):
		pass

	frappe.PermissionError = PermissionError
	frappe.throw = lambda msg, exc=Exception: (_ for _ in ()).throw(exc(msg))
	frappe._ = lambda s: s
	frappe.log_error = lambda *a, **kw: None

	if not hasattr(frappe, "utils"):
		frappe.utils = types.ModuleType("frappe.utils")
		frappe.utils.cint = int
		frappe.utils.flt = float
		sys.modules["frappe.utils"] = frappe.utils


_install_frappe_stub()


def _reset_state():
	_DB.clear()
	_ROLES.clear()
	_ORG_PARENT.clear()


from tradehub_core import permissions  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_user_org(user: str, org: str | None) -> None:
	_DB[("User", user, "tradehub_parent_organization")] = org


def _set_user_tenant(user: str, tenant: str | None) -> None:
	_DB[("User", user, "tradehub_tenant")] = tenant
	# _get_seller_profile_name için ASP lookup'ları
	_DB[("ASP_lookup", f"{{'user': '{user}'}}", "name")] = tenant
	_DB[("ASP_lookup", f"{{'owner': '{user}'}}", "name")] = None
	_DB[("ASP_lookup", f"{{'email': '{user}'}}", "name")] = None


def _set_user_buyer_tenant(user: str, tenant: str | None) -> None:
	_DB[("User", user, "tradehub_buyer_tenant")] = tenant


def _link_org_parent(child: str, parent: str | None) -> None:
	_ORG_PARENT[child] = parent


def _set_roles(user: str, roles: list[str]) -> None:
	_ROLES[user] = roles


# ---------------------------------------------------------------------------
# Order Approval
# ---------------------------------------------------------------------------


class OrderApprovalScopeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_admin_full_access(self):
		_set_roles("admin@x.com", ["System Manager"])
		self.assertEqual(permissions.order_approval_query_conditions("admin@x.com"), "")

	def test_compliance_officer_full_access(self):
		_set_roles("dpo@x.com", ["Compliance Officer"])
		self.assertEqual(permissions.order_approval_query_conditions("dpo@x.com"), "")

	def test_buyer_user_sees_own_org_and_ancestors(self):
		_set_roles("can@acme.com", ["Buyer Approver L1"])
		_set_user_org("can@acme.com", "acme-istanbul")
		_link_org_parent("acme-istanbul", "acme-root")
		_link_org_parent("acme-root", None)

		clause = permissions.order_approval_query_conditions("can@acme.com")
		self.assertIn("`organization` IN", clause)
		self.assertIn("'acme-istanbul'", clause)
		self.assertIn("'acme-root'", clause)
		self.assertIn("`requisitioner` = 'can@acme.com'", clause)

	def test_user_without_org_only_sees_own_requisitions(self):
		_set_roles("loner@x.com", ["Buyer"])
		_set_user_org("loner@x.com", None)
		clause = permissions.order_approval_query_conditions("loner@x.com")
		self.assertIn("`requisitioner` = 'loner@x.com'", clause)
		self.assertNotIn("organization IN", clause)

	def test_guest_blocked(self):
		self.assertEqual(permissions.order_approval_query_conditions("Guest"), "1=0")
		self.assertEqual(permissions.order_approval_query_conditions(""), "1=0")

	def test_has_permission_requisitioner_allowed(self):
		_set_roles("can@acme.com", ["Buyer Approver L1"])
		_set_user_org("can@acme.com", "acme-istanbul")
		doc = SimpleNamespace(organization="other-org", requisitioner="can@acme.com")
		self.assertTrue(permissions.order_approval_has_permission(doc, "read", "can@acme.com"))

	def test_has_permission_ancestor_org_allowed(self):
		_set_roles("can@acme.com", ["Buyer Approver L1"])
		_set_user_org("can@acme.com", "acme-pazarlama")
		_link_org_parent("acme-pazarlama", "acme-istanbul")
		_link_org_parent("acme-istanbul", "acme-root")
		doc = SimpleNamespace(organization="acme-root", requisitioner="other@x.com")
		self.assertTrue(permissions.order_approval_has_permission(doc, "read", "can@acme.com"))

	def test_has_permission_cross_org_denied(self):
		_set_roles("can@acme.com", ["Buyer Approver L1"])
		_set_user_org("can@acme.com", "acme-istanbul")
		doc = SimpleNamespace(organization="globex-root", requisitioner="other@x.com")
		self.assertFalse(permissions.order_approval_has_permission(doc, "read", "can@acme.com"))


# ---------------------------------------------------------------------------
# Approval Rule
# ---------------------------------------------------------------------------


class ApprovalRuleScopeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_admin_full_access(self):
		_set_roles("admin@x.com", ["System Manager"])
		self.assertEqual(permissions.approval_rule_query_conditions("admin@x.com"), "")

	def test_buyer_admin_scoped_to_org(self):
		_set_roles("buyeradmin@acme.com", ["Buyer Admin"])
		_set_user_org("buyeradmin@acme.com", "acme-root")
		clause = permissions.approval_rule_query_conditions("buyeradmin@acme.com")
		self.assertEqual(clause, "`tabApproval Rule`.`organization` IN ('acme-root')")

	def test_user_without_org_blocked(self):
		_set_roles("loner@x.com", ["Buyer Approver L1"])
		_set_user_org("loner@x.com", None)
		self.assertEqual(permissions.approval_rule_query_conditions("loner@x.com"), "1=0")

	def test_has_permission_org_match(self):
		_set_roles("u@acme.com", ["Buyer Approver L2"])
		_set_user_org("u@acme.com", "acme-root")
		doc = SimpleNamespace(organization="acme-root")
		self.assertTrue(permissions.approval_rule_has_permission(doc, "read", "u@acme.com"))

	def test_has_permission_other_org_denied(self):
		_set_roles("u@acme.com", ["Buyer Approver L2"])
		_set_user_org("u@acme.com", "acme-root")
		doc = SimpleNamespace(organization="globex-root")
		self.assertFalse(permissions.approval_rule_has_permission(doc, "read", "u@acme.com"))


# ---------------------------------------------------------------------------
# Cost Center
# ---------------------------------------------------------------------------


class CostCenterScopeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_buyer_user_sees_own_tenant(self):
		_set_roles("u@acme.com", ["Buyer"])
		_set_user_buyer_tenant("u@acme.com", "BUYER-TENANT-A")
		clause = permissions.cost_center_query_conditions("u@acme.com")
		self.assertEqual(clause, "`tabCost Center`.`tenant` = 'BUYER-TENANT-A'")

	def test_user_without_tenant_blocked(self):
		_set_roles("seller@x.com", ["Seller"])
		self.assertEqual(permissions.cost_center_query_conditions("seller@x.com"), "1=0")

	def test_has_permission_tenant_match(self):
		_set_roles("u@acme.com", ["Buyer"])
		_set_user_buyer_tenant("u@acme.com", "BUYER-TENANT-A")
		doc = SimpleNamespace(tenant="BUYER-TENANT-A")
		self.assertTrue(permissions.cost_center_has_permission(doc, "read", "u@acme.com"))

	def test_has_permission_cross_tenant_denied(self):
		_set_roles("u@acme.com", ["Buyer"])
		_set_user_buyer_tenant("u@acme.com", "BUYER-TENANT-A")
		doc = SimpleNamespace(tenant="BUYER-TENANT-B")
		self.assertFalse(permissions.cost_center_has_permission(doc, "read", "u@acme.com"))


# ---------------------------------------------------------------------------
# Owner Transfer Request
# ---------------------------------------------------------------------------


class OwnerTransferRequestScopeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_admin_full_access(self):
		_set_roles("admin@x.com", ["System Manager"])
		self.assertEqual(permissions.owner_transfer_request_query_conditions("admin@x.com"), "")

	def test_owner_sees_own_tenant(self):
		_set_roles("mehmet@anatolian.com", ["Seller Owner"])
		_set_user_tenant("mehmet@anatolian.com", "STORE-A")
		clause = permissions.owner_transfer_request_query_conditions("mehmet@anatolian.com")
		self.assertIn("`current_owner` = 'mehmet@anatolian.com'", clause)
		self.assertIn("`proposed_owner` = 'mehmet@anatolian.com'", clause)
		self.assertIn("`tenant` = 'STORE-A'", clause)

	def test_proposed_owner_can_see_doc(self):
		_set_roles("co@anatolian.com", ["Seller Co-Owner"])
		doc = SimpleNamespace(
			current_owner="mehmet@anatolian.com",
			proposed_owner="co@anatolian.com",
			tenant="STORE-A",
		)
		self.assertTrue(permissions.owner_transfer_request_has_permission(doc, "read", "co@anatolian.com"))

	def test_unrelated_user_denied(self):
		_set_roles("other@x.com", ["Buyer"])
		doc = SimpleNamespace(current_owner="a@x.com", proposed_owner="b@x.com", tenant="STORE-A")
		self.assertFalse(permissions.owner_transfer_request_has_permission(doc, "read", "other@x.com"))


# ---------------------------------------------------------------------------
# Role Delegation
# ---------------------------------------------------------------------------


class RoleDelegationScopeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_delegate_can_see(self):
		_set_roles("delegate@x.com", ["Seller Staff"])
		doc = SimpleNamespace(delegator="boss@x.com", delegate="delegate@x.com", tenant="STORE-A")
		self.assertTrue(permissions.role_delegation_has_permission(doc, "read", "delegate@x.com"))

	def test_unrelated_user_denied(self):
		_set_roles("other@x.com", ["Buyer"])
		doc = SimpleNamespace(delegator="a@x.com", delegate="b@x.com", tenant="STORE-A")
		self.assertFalse(permissions.role_delegation_has_permission(doc, "read", "other@x.com"))

	def test_query_includes_self_and_tenant(self):
		_set_roles("u@anatolian.com", ["Seller Staff"])
		_set_user_tenant("u@anatolian.com", "STORE-A")
		clause = permissions.role_delegation_query_conditions("u@anatolian.com")
		self.assertIn("`delegator` = 'u@anatolian.com'", clause)
		self.assertIn("`delegate` = 'u@anatolian.com'", clause)
		self.assertIn("`tenant` = 'STORE-A'", clause)


# ---------------------------------------------------------------------------
# Authorization Decision Log
# ---------------------------------------------------------------------------


class AuthorizationDecisionLogScopeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_compliance_officer_full_access(self):
		_set_roles("dpo@x.com", ["Compliance Officer"])
		self.assertEqual(permissions.authorization_decision_log_query_conditions("dpo@x.com"), "")

	def test_seller_sees_own_tenant_logs(self):
		_set_roles("seller@anatolian.com", ["Seller Owner"])
		_set_user_tenant("seller@anatolian.com", "STORE-A")
		clause = permissions.authorization_decision_log_query_conditions("seller@anatolian.com")
		self.assertIn("`tenant` = 'STORE-A'", clause)
		self.assertIn("`actor` = 'seller@anatolian.com'", clause)

	def test_user_without_tenant_only_own_actor(self):
		_set_roles("buyer@x.com", ["Buyer"])
		clause = permissions.authorization_decision_log_query_conditions("buyer@x.com")
		# Yeni format her zaman parantezli (O5 sonrası clause OR join)
		self.assertEqual(clause, "(`tabAuthorization Decision Log`.`actor` = 'buyer@x.com')")

	def test_buyer_with_org_sees_org_audit_logs(self):
		"""O5: Buyer'ın organization'ındaki audit logları (buyer_org) görür."""
		_set_roles("fin@acme.com", ["Buyer Finance"])
		_set_user_org("fin@acme.com", "acme-root")
		clause = permissions.authorization_decision_log_query_conditions("fin@acme.com")
		self.assertIn("`buyer_org` IN ('acme-root')", clause)
		self.assertIn("`actor` = 'fin@acme.com'", clause)

	def test_has_permission_buyer_org_match(self):
		"""O5: ADL.buyer_org user'ın organization'ı ile eşleşirse görür."""
		_set_roles("fin@acme.com", ["Buyer Finance"])
		_set_user_org("fin@acme.com", "acme-root")
		doc = SimpleNamespace(
			actor="other@acme.com",
			tenant=None,
			buyer_org="acme-root",
		)
		self.assertTrue(permissions.authorization_decision_log_has_permission(doc, "read", "fin@acme.com"))


# ---------------------------------------------------------------------------
# Platform-only doctypes
# ---------------------------------------------------------------------------


class PlatformOnlyDoctypeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_anomaly_rule_seller_denied(self):
		_set_roles("seller@x.com", ["Seller Owner"])
		self.assertEqual(
			permissions.authorization_anomaly_rule_query_conditions("seller@x.com"),
			"1=0",
		)
		self.assertFalse(
			permissions.authorization_anomaly_rule_has_permission(SimpleNamespace(), "read", "seller@x.com")
		)

	def test_anomaly_rule_compliance_officer_allowed(self):
		_set_roles("dpo@x.com", ["Compliance Officer"])
		self.assertEqual(permissions.authorization_anomaly_rule_query_conditions("dpo@x.com"), "")
		self.assertTrue(
			permissions.authorization_anomaly_rule_has_permission(SimpleNamespace(), "read", "dpo@x.com")
		)

	def test_permission_override_log_buyer_denied(self):
		_set_roles("buyer@x.com", ["Buyer Approver L1"])
		self.assertEqual(permissions.permission_override_log_query_conditions("buyer@x.com"), "1=0")

	def test_pii_field_policy_seller_denied(self):
		_set_roles("seller@x.com", ["Seller Owner"])
		self.assertFalse(
			permissions.pii_field_policy_has_permission(SimpleNamespace(), "read", "seller@x.com")
		)

	def test_anomaly_alert_seller_sees_own_tenant(self):
		_set_roles("seller@anatolian.com", ["Seller Owner"])
		_set_user_tenant("seller@anatolian.com", "STORE-A")
		clause = permissions.authorization_anomaly_alert_query_conditions("seller@anatolian.com")
		# D10 sonrası clause artık parantezli (OR-list potansiyeli için)
		self.assertEqual(clause, "(`tabAuthorization Anomaly Alert`.`tenant` = 'STORE-A')")

	def test_anomaly_alert_buyer_sees_own_org(self):
		"""D10: Buyer organization'ındaki anomaly alert'leri görür."""
		_set_roles("fin@acme.com", ["Buyer Finance"])
		_set_user_org("fin@acme.com", "acme-root")
		clause = permissions.authorization_anomaly_alert_query_conditions("fin@acme.com")
		self.assertIn("`buyer_org` IN ('acme-root')", clause)


# ---------------------------------------------------------------------------
# FAZ 5.1 — Platform Admin / Platform Finance / yeni roller
# ---------------------------------------------------------------------------


class NewRolesBypassTests(unittest.TestCase):
	"""9 yeni rolden Platform Admin + Platform Finance için platform-bypass."""

	def setUp(self):
		_reset_state()

	def test_platform_admin_full_bypass_on_audit(self):
		_set_roles("padmin@x.com", ["Platform Admin"])
		# Platform Admin _PLATFORM_FULL_ACCESS_ROLES içinde — her şeyi görür
		self.assertEqual(permissions.authorization_decision_log_query_conditions("padmin@x.com"), "")
		self.assertEqual(permissions.permission_override_log_query_conditions("padmin@x.com"), "")
		self.assertEqual(permissions.pii_field_policy_query_conditions("padmin@x.com"), "")
		self.assertTrue(
			permissions.authorization_anomaly_rule_has_permission(SimpleNamespace(), "write", "padmin@x.com")
		)

	def test_platform_finance_audit_read_but_no_admin_doctypes(self):
		_set_roles("pfin@x.com", ["Platform Finance"])
		# Audit log + Anomaly Alert read OK
		self.assertEqual(permissions.authorization_decision_log_query_conditions("pfin@x.com"), "")
		self.assertEqual(permissions.authorization_anomaly_alert_query_conditions("pfin@x.com"), "")
		# Ama Anomaly Rule / Permission Override / PII Policy yönetim doctype'ları
		# Platform Finance'a kapalı — sadece audit-read
		self.assertEqual(
			permissions.authorization_anomaly_rule_query_conditions("pfin@x.com"),
			"1=0",
		)
		self.assertEqual(permissions.permission_override_log_query_conditions("pfin@x.com"), "1=0")
		self.assertEqual(permissions.pii_field_policy_query_conditions("pfin@x.com"), "1=0")
		self.assertFalse(permissions.pii_field_policy_has_permission(SimpleNamespace(), "read", "pfin@x.com"))

	def test_buyer_finance_scoped_to_org(self):
		_set_roles("bfin@acme.com", ["Buyer Finance"])
		_set_user_org("bfin@acme.com", "acme-root")
		clause = permissions.approval_rule_query_conditions("bfin@acme.com")
		self.assertEqual(clause, "`tabApproval Rule`.`organization` IN ('acme-root')")

	def test_seller_viewer_no_platform_access(self):
		_set_roles("v@anatolian.com", ["Seller Viewer"])
		# Anomaly Rule platform-only — Seller Viewer kapalı
		self.assertFalse(
			permissions.authorization_anomaly_rule_has_permission(
				SimpleNamespace(), "read", "v@anatolian.com"
			)
		)
		# PII Policy de kapalı
		self.assertFalse(
			permissions.pii_field_policy_has_permission(SimpleNamespace(), "read", "v@anatolian.com")
		)

	def test_support_agent_no_audit_admin_access(self):
		_set_roles("agent@x.com", ["Support Agent"])
		# Support Agent platform-full değil; audit-read da değil
		self.assertEqual(
			permissions.authorization_decision_log_query_conditions("agent@x.com"),
			"(`tabAuthorization Decision Log`.`actor` = 'agent@x.com')",
		)
		self.assertEqual(
			permissions.authorization_anomaly_rule_query_conditions("agent@x.com"),
			"1=0",
		)


# ---------------------------------------------------------------------------
# K2 — Order buyer-side scope (yeni davranış)
# ---------------------------------------------------------------------------


class OrderBuyerScopeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_buyer_sees_own_orders(self):
		"""Buyer Order.buyer = self koşuluyla kendi order'larını görür."""
		_set_roles("ayse@acme.com", ["Buyer Procurement"])
		clause = permissions.order_query_conditions("ayse@acme.com")
		self.assertIn("`tabOrder`.`buyer` = 'ayse@acme.com'", clause)

	def test_buyer_with_org_sees_org_members_orders(self):
		"""Buyer Approver kendi org'undaki diğer buyer'ların order'larını görür."""
		_set_roles("can@acme.com", ["Buyer Approver L1"])
		_set_user_org("can@acme.com", "acme-root")
		clause = permissions.order_query_conditions("can@acme.com")
		self.assertIn("tradehub_parent_organization", clause)
		self.assertIn("'acme-root'", clause)

	def test_seller_still_sees_own_orders(self):
		"""Yeni K2 fix mevcut seller davranışını kırmadı."""
		_set_roles("seller@anatolian.com", ["Seller Owner"])
		_set_user_tenant("seller@anatolian.com", "STORE-A")
		clause = permissions.order_query_conditions("seller@anatolian.com")
		self.assertIn("`tabOrder`.`seller` = 'STORE-A'", clause)

	def test_platform_admin_full_bypass(self):
		"""Platform Admin tüm order'ları görür (K3 ile birlikte)."""
		_set_roles("padmin@x.com", ["Platform Admin"])
		self.assertEqual(permissions.order_query_conditions("padmin@x.com"), "")

	def test_has_permission_buyer_owns_order(self):
		_set_roles("ayse@acme.com", ["Buyer Procurement"])
		doc = SimpleNamespace(buyer="ayse@acme.com", seller="STORE-X")
		self.assertTrue(permissions.order_has_permission(doc, "read", "ayse@acme.com"))

	def test_has_permission_buyer_same_org_member(self):
		_set_roles("can@acme.com", ["Buyer Approver L1"])
		_set_user_org("can@acme.com", "acme-root")
		# Başka org user'ı acme-root'ta sipariş açtı
		_set_user_org("ayse@acme.com", "acme-root")
		doc = SimpleNamespace(buyer="ayse@acme.com", seller="STORE-X")
		self.assertTrue(permissions.order_has_permission(doc, "read", "can@acme.com"))


# ---------------------------------------------------------------------------
# K3 — Platform full-access bypass eski legacy handler'larda
# ---------------------------------------------------------------------------


class LegacyHandlerPlatformBypassTests(unittest.TestCase):
	"""Platform Admin / Marketplace Admin / Compliance Officer eski
	query_conditions'ları (Listing, Admin Seller Profile vb.) bypass etmeli."""

	def setUp(self):
		_reset_state()

	def test_platform_admin_listing_bypass(self):
		_set_roles("padmin@x.com", ["Platform Admin"])
		self.assertEqual(permissions.listing_query_conditions("padmin@x.com"), "")
		self.assertTrue(
			permissions.listing_has_permission(SimpleNamespace(seller_profile="X"), "read", "padmin@x.com")
		)

	def test_marketplace_admin_admin_seller_profile_bypass(self):
		_set_roles("madmin@x.com", ["Marketplace Admin"])
		self.assertEqual(permissions.admin_seller_profile_query_conditions("madmin@x.com"), "")

	def test_compliance_officer_listing_bypass(self):
		"""Compliance Officer da platform-full set'inde → tüm listing'leri görür."""
		_set_roles("dpo@x.com", ["Compliance Officer"])
		self.assertEqual(permissions.listing_query_conditions("dpo@x.com"), "")


if __name__ == "__main__":
	unittest.main()
