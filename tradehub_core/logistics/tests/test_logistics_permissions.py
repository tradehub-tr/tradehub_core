# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-103 — Lojistik permission testleri.

Frappe runtime olmadan calisabilecek test'ler (mock/stub pattern).
Bu suit standalone unit suitidir; bench'te (gercek frappe import'luyken) skip
edilir — bench-uyumlu entegrasyon testleri Gorev 18 kapsaminda yazilacak.
AC-1..AC-8 karsiligi 10 test senaryosu.

Test senaryolari:
  AC-1: Platform full access (Logistics Manager) tum sevkiyatlari gorur
  AC-2: Seller sadece kendi seller_profile'ina ait sevkiyatlari gorur
  AC-3: Buyer sadece kendi siparisine ait sevkiyati gorur (read-only)
  AC-4: Support Agent sadece read yapabilir
  AC-5: Platform Finance yalniz read yapabilir (write dahil yazma False)
  AC-6: Cancel sadece Logistics Manager yapabilir
  AC-7: Carrier Account — Carrier Integration Manager tam CRUD
  AC-8: Carrier Account — Logistics Manager sadece read
  AC-9: Guest erisim reddedilir
  AC-10: Administrator tam erisim
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Frappe mock'u — permissions.py import edilebilsin
# ---------------------------------------------------------------------------
# Gerçek frappe zaten import edilmişse (bench run-tests) mock kurulumu YAPILMAZ:
# sys.modules["frappe"] üzerine MagicMock yazmak redis cache pickle aşamasında
# PicklingError ile tüm bench koşusunu düşürür. Bu durumda süit skip edilir.
# isinstance kontrolü, standalone koşucuların önceden kurduğu frappe MOCK'unu
# gerçek frappe ile karıştırmamak için gerekli.
_REAL_FRAPPE: bool = "frappe" in sys.modules and not isinstance(sys.modules["frappe"], MagicMock)

_SKIP_REASON: str = (
	"standalone-only unit suite; bench'te mock frappe gerçek frappe'yi ezemez"
)


def _setup_frappe_mock() -> MagicMock:
	"""Minimal frappe mock olusturur."""
	frappe_mock = MagicMock()
	frappe_mock.session = MagicMock()
	frappe_mock.session.user = "test@example.com"
	frappe_mock._ = lambda x: x  # i18n pass-through
	frappe_mock.db = MagicMock()
	frappe_mock.db.escape = lambda x: f"'{x}'"
	frappe_mock.db.get_value = MagicMock(return_value=None)
	frappe_mock.log_error = MagicMock()
	frappe_mock.get_roles = MagicMock(return_value=[])
	frappe_mock.throw = MagicMock(side_effect=Exception)
	frappe_mock.cache = MagicMock(return_value=MagicMock())

	# frappe modulu olarak register et
	sys.modules["frappe"] = frappe_mock
	sys.modules["frappe.model"] = MagicMock()
	sys.modules["frappe.model.document"] = MagicMock()
	sys.modules["frappe.utils"] = MagicMock()

	return frappe_mock


if _REAL_FRAPPE:
	# Bench modu: sys.modules'a HİÇBİR mock yazılmaz (frappe ve tradehub_core.*
	# dahil). Aşağıdaki isimler yalnız modülün import edilebilmesi için
	# placeholder — tüm test sınıfları skipIf ile atlanır.
	_frappe = MagicMock()
	audit_log_mock = MagicMock()
	tenant_mock = MagicMock()
	resolver_mock = MagicMock()
else:
	_frappe = _setup_frappe_mock()

	# tradehub_core mock'lari
	sys.modules.setdefault("tradehub_core", types.ModuleType("tradehub_core"))
	sys.modules.setdefault("tradehub_core.utils", types.ModuleType("tradehub_core.utils"))
	sys.modules.setdefault("tradehub_core.utils.tenant", types.ModuleType("tradehub_core.utils.tenant"))
	sys.modules.setdefault("tradehub_core.audit", types.ModuleType("tradehub_core.audit"))

	# audit.log mock
	audit_log_mock = MagicMock()
	audit_log_mock.log_decision = MagicMock(return_value=None)
	audit_log_mock.DECISION_DENY = "DENY"
	audit_log_mock.LAYER_L2 = "L2"
	sys.modules["tradehub_core.audit.log"] = audit_log_mock

	# tenant mock
	tenant_mock = sys.modules["tradehub_core.utils.tenant"]
	tenant_mock._get_seller_profile_for_user = MagicMock(return_value=None)

	# permission_resolver mock — patch("tradehub_core.utils.permission_resolver.has_capability")
	# hedefi standalone modda da (Frappe/bench olmadan) çözülebilsin
	sys.modules.setdefault(
		"tradehub_core.utils.permission_resolver",
		types.ModuleType("tradehub_core.utils.permission_resolver"),
	)
	resolver_mock = sys.modules["tradehub_core.utils.permission_resolver"]
	if not hasattr(resolver_mock, "has_capability"):
		resolver_mock.has_capability = MagicMock(return_value=False)
	# mock.patch'in getattr zinciri (tradehub_core → utils → permission_resolver)
	# import edilmemiş alt modüllerde kopuk kalmasın diye parent attribute'ları bağla
	sys.modules["tradehub_core.utils"].permission_resolver = resolver_mock
	sys.modules["tradehub_core"].utils = sys.modules["tradehub_core.utils"]

# Simdi import edebiliriz
from tradehub_core.logistics.permissions import (  # noqa: E402
	carrier_account_has_permission,
	carrier_account_query_conditions,
	mask_carrier_account_fields,
	mask_shipment_cost_fields,
	shipment_has_permission,
	shipment_query_conditions,
)


class _FakeDoc:
	"""Minimal Shipment/Carrier Account doc mock'u."""

	def __init__(self, **kwargs):
		for k, v in kwargs.items():
			setattr(self, k, v)

	def get(self, key, default=None):
		return getattr(self, key, default)


@unittest.skipIf(_REAL_FRAPPE, _SKIP_REASON)
class TestShipmentQueryConditions(unittest.TestCase):
	"""AC-1, AC-2, AC-3: query_conditions testleri."""

	def setUp(self):
		_frappe.session.user = "test@example.com"
		_frappe.get_roles.return_value = []
		tenant_mock._get_seller_profile_for_user.return_value = None

	def test_ac1_logistics_manager_full_access(self):
		"""AC-1: Logistics Manager tum sevkiyatlari gorur."""
		_frappe.get_roles.return_value = ["Logistics Manager"]
		result = shipment_query_conditions("logmanager@example.com")
		self.assertEqual(result, "")

	def test_ac1_system_manager_full_access(self):
		"""AC-1: System Manager tam erisim."""
		_frappe.get_roles.return_value = ["System Manager"]
		result = shipment_query_conditions("admin@example.com")
		self.assertEqual(result, "")

	def test_ac2_seller_scoped(self):
		"""AC-2: Seller kendi seller_profile'ina gore filtrelenir."""
		_frappe.get_roles.return_value = ["Seller Staff"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00001"
		result = shipment_query_conditions("seller@example.com")
		self.assertIn("seller_profile", result)
		self.assertIn("SEL-00001", result)

	def test_ac3_buyer_scoped(self):
		"""AC-3: Buyer kendi user'ina gore filtrelenir."""
		_frappe.get_roles.return_value = ["Customer"]
		tenant_mock._get_seller_profile_for_user.return_value = None
		result = shipment_query_conditions("buyer@example.com")
		self.assertIn("buyer", result)
		self.assertIn("buyer@example.com", result)

	def test_ac5_platform_finance_sees_all(self):
		"""AC-5: Platform Finance tum sevkiyatlari listeleyebilir."""
		_frappe.get_roles.return_value = ["Platform Finance"]
		result = shipment_query_conditions("finance@example.com")
		self.assertEqual(result, "")

	def test_ac9_guest_blocked(self):
		"""AC-9: Guest erisim reddedilir."""
		result = shipment_query_conditions("Guest")
		self.assertEqual(result, "1=0")

	def test_ac10_administrator(self):
		"""AC-10: Administrator tam erisim."""
		result = shipment_query_conditions("Administrator")
		self.assertEqual(result, "")


@unittest.skipIf(_REAL_FRAPPE, _SKIP_REASON)
class TestShipmentHasPermission(unittest.TestCase):
	"""AC-3, AC-4, AC-5, AC-6: has_permission testleri."""

	def setUp(self):
		_frappe.session.user = "test@example.com"
		_frappe.get_roles.return_value = []
		tenant_mock._get_seller_profile_for_user.return_value = None

	def test_ac3_buyer_read_only(self):
		"""AC-3: Buyer kendi siparisini sadece okuyabilir."""
		_frappe.get_roles.return_value = ["Customer"]
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		# read → True
		self.assertTrue(shipment_has_permission(doc, "read", "buyer@example.com"))
		# write → False
		self.assertFalse(shipment_has_permission(doc, "write", "buyer@example.com"))

	def test_ac4_support_agent_read_only(self):
		"""AC-4: Support Agent sadece read yapabilir."""
		_frappe.get_roles.return_value = ["Support Agent"]
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		self.assertTrue(shipment_has_permission(doc, "read", "agent@example.com"))
		self.assertFalse(shipment_has_permission(doc, "write", "agent@example.com"))

	def test_ac5_platform_finance_read_only(self):
		"""AC-5: Platform Finance yalniz read; write/delete dahil yazma ptype'lari False."""
		_frappe.get_roles.return_value = ["Platform Finance"]
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		self.assertTrue(shipment_has_permission(doc, "read", "finance@example.com"))
		# J.2 yetki matrisi: Finance yalniz READ — write artik False
		self.assertFalse(shipment_has_permission(doc, "write", "finance@example.com"))
		self.assertFalse(shipment_has_permission(doc, "delete", "finance@example.com"))

	def test_ac6_cancel_logistics_manager_only(self):
		"""AC-6: Cancel sadece Logistics Manager yapabilir."""
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")

		# Logistics Manager → cancel izni
		_frappe.get_roles.return_value = ["Logistics Manager"]
		self.assertTrue(shipment_has_permission(doc, "cancel", "logmanager@example.com"))

		# Seller → cancel izni yok
		_frappe.get_roles.return_value = ["Seller Staff"]
		self.assertFalse(shipment_has_permission(doc, "cancel", "seller@example.com"))

	def test_ac10_administrator_full(self):
		"""AC-10: Administrator her ptype'da True doner."""
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		for ptype in ("read", "write", "create", "delete", "cancel"):
			self.assertTrue(shipment_has_permission(doc, ptype, "Administrator"))

	def test_seller_profile_mismatch_denied(self):
		"""Seller baska seller'in sevkiyatina erisilemez."""
		_frappe.get_roles.return_value = ["Seller Staff"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00002"
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		self.assertFalse(shipment_has_permission(doc, "read", "seller2@example.com"))


@unittest.skipIf(_REAL_FRAPPE, _SKIP_REASON)
class TestCarrierAccountPermissions(unittest.TestCase):
	"""AC-7, AC-8: Carrier Account permission testleri."""

	def setUp(self):
		_frappe.session.user = "test@example.com"
		_frappe.get_roles.return_value = []
		tenant_mock._get_seller_profile_for_user.return_value = None

	def test_ac7_carrier_integration_manager_full_crud(self):
		"""AC-7: Carrier Integration Manager tam CRUD."""
		_frappe.get_roles.return_value = ["Carrier Integration Manager"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00001"
		doc = _FakeDoc(name="CC-001", seller_profile="SEL-00001")

		for ptype in ("read", "write", "create", "delete"):
			self.assertTrue(
				carrier_account_has_permission(doc, ptype, "carrier@example.com"),
				f"Carrier Integration Manager should have {ptype} access",
			)

	def test_ac8_logistics_manager_read_only(self):
		"""AC-8: Logistics Manager sadece read."""
		_frappe.get_roles.return_value = ["Logistics Manager"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00001"
		doc = _FakeDoc(name="CC-001", seller_profile="SEL-00001")

		self.assertTrue(carrier_account_has_permission(doc, "read", "logmanager@example.com"))
		self.assertFalse(carrier_account_has_permission(doc, "write", "logmanager@example.com"))
		self.assertFalse(carrier_account_has_permission(doc, "delete", "logmanager@example.com"))

	def test_carrier_account_query_no_role(self):
		"""Rolleri olmayan kullanici Carrier Account'lari goremez."""
		_frappe.get_roles.return_value = ["Customer"]
		result = carrier_account_query_conditions("norole@example.com")
		self.assertEqual(result, "1=0")

	def test_carrier_account_tenant_isolation(self):
		"""Farkli tenant'in Carrier Account'ina erisilemez."""
		_frappe.get_roles.return_value = ["Carrier Integration Manager"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00002"
		doc = _FakeDoc(name="CC-001", seller_profile="SEL-00001")
		self.assertFalse(
			carrier_account_has_permission(doc, "read", "carrier@example.com")
		)

	def test_platform_global_account_denied_to_tenant_user(self):
		"""Bos-tenant (platform-global) hesap tenant kullanicisina kapali."""
		_frappe.get_roles.return_value = ["Carrier Integration Manager"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00001"
		doc = _FakeDoc(name="CC-GLOBAL", seller_profile=None)
		self.assertFalse(
			carrier_account_has_permission(doc, "read", "carrier@example.com")
		)

	def test_platform_global_account_allowed_to_platform_user(self):
		"""seller_profile'i olmayan platform CIM global hesaba erisebilir."""
		_frappe.get_roles.return_value = ["Carrier Integration Manager"]
		tenant_mock._get_seller_profile_for_user.return_value = None
		doc = _FakeDoc(name="CC-GLOBAL", seller_profile=None)
		self.assertTrue(
			carrier_account_has_permission(doc, "read", "platform-cim@example.com")
		)


@unittest.skipIf(_REAL_FRAPPE, _SKIP_REASON)
class TestOperatorPermissions(unittest.TestCase):
	"""Logistics Operator rol testleri — MAJOR-1."""

	def setUp(self):
		_frappe.session.user = "operator@example.com"
		_frappe.get_roles.return_value = []
		tenant_mock._get_seller_profile_for_user.return_value = None
		audit_log_mock.log_decision.reset_mock()

	def test_operator_reads_own_tenant_shipment(self):
		"""Operator kendi tenant'ına ait Shipment'ı okuyabilir."""
		_frappe.get_roles.return_value = ["Logistics Operator"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00001"
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		self.assertTrue(shipment_has_permission(doc, "read", "operator@example.com"))

	def test_operator_writes_own_tenant_shipment(self):
		"""Operator kendi tenant'ına write yapabilir."""
		_frappe.get_roles.return_value = ["Logistics Operator"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00001"
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		self.assertTrue(shipment_has_permission(doc, "write", "operator@example.com"))

	def test_operator_cannot_cancel_shipment(self):
		"""AC-2: Operator cancel yapamaz — sadece Logistics Manager cancel edebilir."""
		_frappe.get_roles.return_value = ["Logistics Operator"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00001"
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		self.assertFalse(shipment_has_permission(doc, "cancel", "operator@example.com"))

	def test_operator_cross_tenant_denied(self):
		"""AC-4: Operator başka tenant'a erişemez."""
		_frappe.get_roles.return_value = ["Logistics Operator"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00002"
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")
		self.assertFalse(shipment_has_permission(doc, "read", "operator@example.com"))


@unittest.skipIf(_REAL_FRAPPE, _SKIP_REASON)
class TestMaskShipmentCostFields(unittest.TestCase):
	"""mask_shipment_cost_fields testleri — MAJOR-2."""

	def setUp(self):
		_frappe.session.user = "test@example.com"

	def test_mask_shipment_cost_hides_fields(self):
		"""Capability yoksa maliyet alanlari None olur (0 DEGIL — DB'yi ezmesin)."""
		doc = _FakeDoc(
			name="SHP-001", shipping_cost=150.0, insurance_cost=25.0,
			total_cost=175.0, carrier_cost=100.0, fuel_surcharge=10.0,
			packaging_cost=15.0,
		)
		with patch(
			"tradehub_core.utils.permission_resolver.has_capability",
			return_value=False,
		):
			mask_shipment_cost_fields(doc, "seller@example.com")
		self.assertIsNone(doc.shipping_cost)
		self.assertIsNone(doc.insurance_cost)
		self.assertIsNone(doc.total_cost)
		self.assertIsNone(doc.carrier_cost)
		self.assertIsNone(doc.fuel_surcharge)
		self.assertIsNone(doc.packaging_cost)

	def test_mask_shipment_cost_falsy_user_applies_mask(self):
		"""User falsy ise maskeleme UYGULANIR (fail-closed)."""
		_frappe.session.user = ""
		doc = _FakeDoc(name="SHP-001", shipping_cost=150.0, total_cost=175.0)
		mask_shipment_cost_fields(doc, None)
		self.assertIsNone(doc.shipping_cost)
		self.assertIsNone(doc.total_cost)

	def test_mask_shipment_cost_shows_with_capability(self):
		"""Capability varsa maliyet alanları gösterilir."""
		doc = _FakeDoc(
			name="SHP-001", shipping_cost=150.0, insurance_cost=25.0,
			total_cost=175.0,
		)
		with patch(
			"tradehub_core.utils.permission_resolver.has_capability",
			return_value=True,
		):
			mask_shipment_cost_fields(doc, "finance@example.com")
		self.assertEqual(doc.shipping_cost, 150.0)
		self.assertEqual(doc.insurance_cost, 25.0)
		self.assertEqual(doc.total_cost, 175.0)


@unittest.skipIf(_REAL_FRAPPE, _SKIP_REASON)
class TestMaskCarrierAccountFields(unittest.TestCase):
	"""mask_carrier_account_fields testleri — MAJOR-2."""

	def setUp(self):
		_frappe.session.user = "test@example.com"

	def test_mask_carrier_account_hides_api_key(self):
		"""Capability yoksa api_key tum-asterisk degerle maskelenir.

		Mask degeri "*" * 8 olmali: Frappe _save_passwords yalniz tum-asterisk
		degerleri dummy sayar; bullet'li mask kayitta gercek secret'i ezerdi.
		"""
		doc = _FakeDoc(
			name="CC-001", api_key="secret-key-123",
			api_secret="secret-value", webhook_secret="whsec_abc",
			access_token="tok_xyz",
		)
		with patch(
			"tradehub_core.utils.permission_resolver.has_capability",
			return_value=False,
		):
			mask_carrier_account_fields(doc, "operator@example.com")
		self.assertEqual(doc.api_key, "*" * 8)
		self.assertEqual(doc.api_secret, "*" * 8)
		self.assertEqual(doc.webhook_secret, "*" * 8)
		self.assertEqual(doc.access_token, "*" * 8)

	def test_mask_carrier_account_falsy_user_applies_mask(self):
		"""User falsy ise maskeleme UYGULANIR (fail-closed)."""
		_frappe.session.user = ""
		doc = _FakeDoc(name="CC-001", api_key="secret-key-123", api_secret="secret-value")
		mask_carrier_account_fields(doc, None)
		self.assertEqual(doc.api_key, "*" * 8)
		self.assertEqual(doc.api_secret, "*" * 8)

	def test_mask_carrier_account_shows_with_capability(self):
		"""Capability varsa api_key gösterilir."""
		doc = _FakeDoc(
			name="CC-001", api_key="secret-key-123",
			api_secret="secret-value",
		)
		with patch(
			"tradehub_core.utils.permission_resolver.has_capability",
			return_value=True,
		):
			mask_carrier_account_fields(doc, "admin@example.com")
		self.assertEqual(doc.api_key, "secret-key-123")
		self.assertEqual(doc.api_secret, "secret-value")


@unittest.skipIf(_REAL_FRAPPE, _SKIP_REASON)
class TestAuditLogDeny(unittest.TestCase):
	"""MINOR-1: Audit log DENY assert — en az 1 DENY senaryosunda mock assert."""

	def setUp(self):
		_frappe.session.user = "test@example.com"
		_frappe.get_roles.return_value = []
		tenant_mock._get_seller_profile_for_user.return_value = None
		audit_log_mock.log_decision.reset_mock()

	def test_cross_tenant_deny_logs_decision(self):
		"""Cross-tenant DENY durumunda audit.log_decision çağrılır."""
		_frappe.get_roles.return_value = ["Logistics Operator"]
		tenant_mock._get_seller_profile_for_user.return_value = "SEL-00002"
		doc = _FakeDoc(name="SHP-001", seller_profile="SEL-00001", buyer="buyer@example.com")

		shipment_has_permission(doc, "read", "operator@example.com")

		audit_log_mock.log_decision.assert_called()
		# _log_deny keyword argümanlarla çağırır — decision="DENY" olmalı
		_, kwargs = audit_log_mock.log_decision.call_args
		self.assertEqual(kwargs.get("decision"), "DENY")


if __name__ == "__main__":
	unittest.main()
