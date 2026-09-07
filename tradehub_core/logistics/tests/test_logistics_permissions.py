# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-103 — Lojistik permission testleri (bench entegrasyon).

Çalıştırma:
	docker exec istoccom-backend-1 bash -c "cd /home/frappe/workspace/frappe-bench && \\
	  bench --site dev.localhost run-tests \\
	  --module tradehub_core.logistics.tests.test_logistics_permissions"

TARİHÇE — neden yeniden yazıldı (Faz A.4):
	Önceki sürüm `sys.modules["frappe"]` üzerine MagicMock yazan bir standalone
	süitti. Bench'te gerçek frappe'yi ezmemek için tüm sınıflar `skipIf` ile
	atlanıyordu (30/30 skip); standalone'da ise
	`sys.modules.setdefault("tradehub_core", ModuleType(...))` gerçek paketi
	`__path__`'siz bir modülle gölgelediği için
	`ModuleNotFoundError: 'tradehub_core' is not a package` veriyordu. Yani süit
	**hiçbir ortamda çalışmıyordu** — TUR-103'ün "pozitif ve negatif permission
	testleri vardır" kabul kriteri fiilen boştu.

	Yeni yaklaşım: gerçek frappe + `FrappeTestCase`, yalnız iki dış bağımlılık
	nokta atışı patch'lenir (`frappe.get_roles`, tenant resolver). Modül
	hijack'ı yok, skip yok.

NEDEN _FakeDoc:
	`Shipment` DocType'ı henüz yok (F bloğu). Permission fonksiyonları
	`_doc_field()` üzerinden hem dict hem obje kabul ettiği için sahte doküman
	ile test edilebiliyor. `Carrier Account` gerçek bir DocType olduğundan onun
	izolasyonu ayrıca uçtan uca (gerçek kayıt + gerçek `get_list`) test edilir.

Senaryolar:
	AC-1  Platform full access (Logistics Manager) tüm sevkiyatları görür
	AC-2  Seller yalnız kendi seller_profile'ına ait sevkiyatları görür
	AC-3  Buyer yalnız kendi siparişine ait sevkiyatı görür (read-only)
	AC-4  Support Agent yalnız read yapabilir
	AC-5  Platform Finance yalnız read yapabilir (yazma ptype'ları False)
	AC-6  Cancel yalnız Logistics Manager
	AC-7  Carrier Account — Carrier Integration Manager tam CRUD
	AC-8  Carrier Account — Logistics Manager yalnız read
	AC-9  Guest erişimi reddedilir
	AC-10 Administrator tam erişim
	E2E   Çapraz satıcı sızıntısı gerçek get_list üzerinde engellenir
"""

from __future__ import annotations

import unittest.mock as mock
from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.logistics.constants import CACHE_PREFIX
from tradehub_core.logistics.permissions import (
	carrier_account_has_permission,
	carrier_account_query_conditions,
	flush_pending_deny_audits,
	mask_carrier_account_fields,
	mask_shipment_cost_fields,
	shipment_event_has_permission,
	shipment_has_permission,
	shipment_leg_has_permission,
	shipment_query_conditions,
)

# ---------------------------------------------------------------------------
# Test yardımcıları
# ---------------------------------------------------------------------------


@contextmanager
def acting_as(roles: list[str], seller_profile: str | None = None):
	"""Rol kümesini ve tenant çözümlemesini senaryoya sabitler.

	Yalnız bu iki dış bağımlılık patch'lenir; permission mantığının kendisi
	gerçek kodla çalışır. Tenant resolver'ın kendi doğruluğu `utils/tenant.py`
	testlerinin işi — burada tekrar edilmez.
	"""
	with (
		mock.patch("frappe.get_roles", return_value=list(roles)),
		mock.patch(
			"tradehub_core.utils.tenant._get_seller_profile_for_user",
			return_value=seller_profile,
		),
	):
		yield


class _FakeDoc:
	"""Minimal Shipment / Carrier Account dokümanı (Shipment DocType'ı yok)."""

	def __init__(self, **kwargs):
		for k, v in kwargs.items():
			setattr(self, k, v)

	def get(self, key, default=None):
		return getattr(self, key, default)


def _shipment(**overrides) -> _FakeDoc:
	base = {
		"name": "SHP-001",
		"seller_profile": "SEL-00001",
		"buyer": "buyer@example.com",
	}
	base.update(overrides)
	return _FakeDoc(**base)


# ---------------------------------------------------------------------------
# AC-1, AC-2, AC-3, AC-5, AC-9, AC-10 — query_conditions
# ---------------------------------------------------------------------------


class TestShipmentQueryConditions(FrappeTestCase):
	"""Liste sorgusuna eklenen WHERE koşulu."""

	def test_ac1_logistics_manager_full_access(self):
		"""AC-1: Logistics Manager tüm sevkiyatları görür (koşul yok)."""
		with acting_as(["Logistics Manager"]):
			self.assertEqual(shipment_query_conditions("logmanager@example.com"), "")

	def test_ac1_system_manager_full_access(self):
		"""AC-1: System Manager tam erişim."""
		with acting_as(["System Manager"]):
			self.assertEqual(shipment_query_conditions("sysmanager@example.com"), "")

	def test_ac2_seller_scoped(self):
		"""AC-2: Seller kendi seller_profile'ına göre filtrelenir."""
		with acting_as(["Seller Staff"], seller_profile="SEL-00001"):
			result = shipment_query_conditions("seller@example.com")
		self.assertIn("seller_profile", result)
		self.assertIn("SEL-00001", result)

	def test_ac3_buyer_scoped(self):
		"""AC-3: Buyer kendi kullanıcısına göre filtrelenir."""
		with acting_as(["Customer"], seller_profile=None):
			result = shipment_query_conditions("buyer@example.com")
		self.assertIn("buyer", result)
		self.assertIn("buyer@example.com", result)

	def test_ac5_platform_finance_sees_all(self):
		"""AC-5: Platform Finance tüm sevkiyatları listeleyebilir (yazamaz)."""
		with acting_as(["Platform Finance"]):
			self.assertEqual(shipment_query_conditions("finance@example.com"), "")

	def test_ac9_guest_blocked(self):
		"""AC-9: Guest hiçbir sevkiyatı görmez."""
		self.assertEqual(shipment_query_conditions("Guest"), "1=0")

	def test_ac10_administrator(self):
		"""AC-10: Administrator tam erişim."""
		self.assertEqual(shipment_query_conditions("Administrator"), "")


# ---------------------------------------------------------------------------
# AC-3, AC-4, AC-5, AC-6, AC-10 — has_permission
# ---------------------------------------------------------------------------


class TestShipmentHasPermission(FrappeTestCase):
	"""Tekil doküman yetki kontrolü."""

	def test_ac3_buyer_read_only(self):
		"""AC-3: Buyer kendi siparişini yalnız okuyabilir."""
		doc = _shipment()
		with acting_as(["Customer"], seller_profile=None):
			self.assertTrue(shipment_has_permission(doc, "read", "buyer@example.com"))
			self.assertFalse(shipment_has_permission(doc, "write", "buyer@example.com"))

	def test_ac4_support_agent_read_only(self):
		"""AC-4: Support Agent yalnız read yapabilir."""
		doc = _shipment()
		with acting_as(["Support Agent"]):
			self.assertTrue(shipment_has_permission(doc, "read", "agent@example.com"))
			self.assertFalse(shipment_has_permission(doc, "write", "agent@example.com"))

	def test_ac5_platform_finance_read_only(self):
		"""AC-5: Platform Finance yalnız read — write/delete reddedilir (J.2 matrisi)."""
		doc = _shipment()
		with acting_as(["Platform Finance"]):
			self.assertTrue(shipment_has_permission(doc, "read", "finance@example.com"))
			self.assertFalse(shipment_has_permission(doc, "write", "finance@example.com"))
			self.assertFalse(shipment_has_permission(doc, "delete", "finance@example.com"))

	def test_ac6_cancel_logistics_manager_only(self):
		"""AC-6: Cancel yalnız Logistics Manager."""
		doc = _shipment()
		with acting_as(["Logistics Manager"]):
			self.assertTrue(shipment_has_permission(doc, "cancel", "logmanager@example.com"))
		with acting_as(["Seller Staff"], seller_profile="SEL-00001"):
			self.assertFalse(shipment_has_permission(doc, "cancel", "seller@example.com"))

	def test_ac10_administrator_full(self):
		"""AC-10: Administrator her ptype'da True döner."""
		doc = _shipment()
		for ptype in ("read", "write", "create", "delete", "cancel"):
			self.assertTrue(shipment_has_permission(doc, ptype, "Administrator"))

	def test_seller_profile_mismatch_denied(self):
		"""NEGATİF: Seller başka satıcının sevkiyatına erişemez."""
		doc = _shipment(seller_profile="SEL-00001")
		with acting_as(["Seller Staff"], seller_profile="SEL-00002"):
			self.assertFalse(shipment_has_permission(doc, "read", "seller2@example.com"))


# ---------------------------------------------------------------------------
# AC-7, AC-8 — Carrier Account
# ---------------------------------------------------------------------------


class TestCarrierAccountPermissions(FrappeTestCase):
	"""Taşıyıcı hesabı yetki matrisi."""

	def test_ac7_carrier_integration_manager_full_crud(self):
		"""AC-7: Carrier Integration Manager kendi tenant'ında tam CRUD."""
		doc = _FakeDoc(name="CC-001", seller_profile="SEL-00001")
		with acting_as(["Carrier Integration Manager"], seller_profile="SEL-00001"):
			for ptype in ("read", "write", "create", "delete"):
				self.assertTrue(
					carrier_account_has_permission(doc, ptype, "carrier@example.com"),
					f"Carrier Integration Manager {ptype} erişimine sahip olmalı",
				)

	def test_ac8_logistics_manager_read_only(self):
		"""AC-8: Logistics Manager taşıyıcı hesabında yalnız read."""
		doc = _FakeDoc(name="CC-001", seller_profile="SEL-00001")
		with acting_as(["Logistics Manager"], seller_profile="SEL-00001"):
			self.assertTrue(carrier_account_has_permission(doc, "read", "logmanager@example.com"))
			self.assertFalse(carrier_account_has_permission(doc, "write", "logmanager@example.com"))
			self.assertFalse(carrier_account_has_permission(doc, "delete", "logmanager@example.com"))

	def test_carrier_account_query_no_role(self):
		"""NEGATİF: Lojistik rolü olmayan kullanıcı hiçbir hesabı göremez."""
		with acting_as(["Customer"]):
			self.assertEqual(carrier_account_query_conditions("norole@example.com"), "1=0")

	def test_carrier_account_tenant_isolation(self):
		"""NEGATİF: Farklı tenant'ın taşıyıcı hesabına erişilemez."""
		doc = _FakeDoc(name="CC-001", seller_profile="SEL-00001")
		with acting_as(["Carrier Integration Manager"], seller_profile="SEL-00002"):
			self.assertFalse(carrier_account_has_permission(doc, "read", "carrier@example.com"))

	def test_platform_global_account_denied_to_tenant_user(self):
		"""NEGATİF: Boş-tenant (platform-global) hesap tenant kullanıcısına kapalı."""
		doc = _FakeDoc(name="CC-GLOBAL", seller_profile=None)
		with acting_as(["Carrier Integration Manager"], seller_profile="SEL-00001"):
			self.assertFalse(carrier_account_has_permission(doc, "read", "carrier@example.com"))

	def test_platform_global_account_allowed_to_platform_user(self):
		"""seller_profile'ı olmayan platform CIM global hesaba erişebilir."""
		doc = _FakeDoc(name="CC-GLOBAL", seller_profile=None)
		with acting_as(["Carrier Integration Manager"], seller_profile=None):
			self.assertTrue(carrier_account_has_permission(doc, "read", "platform-cim@example.com"))


# ---------------------------------------------------------------------------
# Logistics Operator rol matrisi
# ---------------------------------------------------------------------------


class TestOperatorPermissions(FrappeTestCase):
	"""Logistics Operator — tenant içinde yazar, iptal edemez, dışına çıkamaz."""

	def test_operator_reads_own_tenant_shipment(self):
		doc = _shipment(seller_profile="SEL-00001")
		with acting_as(["Logistics Operator"], seller_profile="SEL-00001"):
			self.assertTrue(shipment_has_permission(doc, "read", "operator@example.com"))

	def test_operator_writes_own_tenant_shipment(self):
		doc = _shipment(seller_profile="SEL-00001")
		with acting_as(["Logistics Operator"], seller_profile="SEL-00001"):
			self.assertTrue(shipment_has_permission(doc, "write", "operator@example.com"))

	def test_operator_cannot_cancel_shipment(self):
		"""NEGATİF: Operator iptal edemez — cancel yalnız Logistics Manager."""
		doc = _shipment(seller_profile="SEL-00001")
		with acting_as(["Logistics Operator"], seller_profile="SEL-00001"):
			self.assertFalse(shipment_has_permission(doc, "cancel", "operator@example.com"))

	def test_operator_cross_tenant_denied(self):
		"""NEGATİF: Operator başka tenant'a erişemez."""
		doc = _shipment(seller_profile="SEL-00001")
		with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
			self.assertFalse(shipment_has_permission(doc, "read", "operator@example.com"))


# ---------------------------------------------------------------------------
# Leg/Event — doc=None (doctype-seviyesi) yazma matrisi
# ---------------------------------------------------------------------------


class TestLegEventDoctypeLevelWriteMatrix(FrappeTestCase):
	"""doc=None + yazma-türü ptype fail-open DEĞİL — Shipment deseniyle hizalı.

	ÖLÇÜLEN TUTARSIZLIK (denetim 2026-09-07): `shipment_leg_has_permission` ve
	`shipment_event_has_permission`, tenant'lı kullanıcıda doc=None kontrolde
	ptype'a hiç bakmadan True dönüyordu — Seller Logistics (salt-okuma) rollü
	kullanıcı doctype seviyesinde write/create/delete izni alıyordu. Shipment
	emsali (doc=None + yazma-türü ptype → rol matrisi) aynı durumda kapalıydı.
	Bu dala yalnız seller_profile'lı kullanıcı düşer; matris _TENANT_WRITE_ROLES.
	"""

	FUNCS = (
		("leg", shipment_leg_has_permission),
		("event", shipment_event_has_permission),
	)

	def test_readonly_tenant_role_cannot_write_at_doctype_level(self):
		"""NEGATİF: Seller Logistics doc=None'da yazma-türü ptype alamaz."""
		for label, func in self.FUNCS:
			for ptype in ("write", "create", "delete"):
				with self.subTest(func=label, ptype=ptype):
					with acting_as(["Seller Logistics"], seller_profile="SEL-00001"):
						self.assertFalse(func(None, ptype, "sellerlog@example.com"))

	def test_tenant_write_roles_keep_doctype_level_write(self):
		"""POZİTİF: Logistics Operator/Manager rollü tenant kullanıcısı yazabilir."""
		for label, func in self.FUNCS:
			for role in ("Logistics Operator", "Logistics Manager"):
				with self.subTest(func=label, role=role):
					with acting_as([role], seller_profile="SEL-00001"):
						self.assertTrue(func(None, "write", "operator@example.com"))
						self.assertTrue(func(None, "create", "operator@example.com"))

	def test_read_type_ptypes_stay_open_at_doctype_level(self):
		"""Okuma-türü ptype'lar serbest kalır — liste/form açılışı kırılmamalı."""
		for label, func in self.FUNCS:
			with self.subTest(func=label):
				with acting_as(["Seller Logistics"], seller_profile="SEL-00001"):
					self.assertTrue(func(None, "read", "sellerlog@example.com"))
					self.assertTrue(func(None, None, "sellerlog@example.com"))

	def test_doctype_level_deny_writes_no_audit_row(self):
		"""doc=None reddi ADL'ye satır yazmaz (_log_deny doc=None filtresi)."""
		with mock.patch("tradehub_core.audit.log.log_decision") as log_decision:
			with acting_as(["Seller Logistics"], seller_profile="SEL-00001"):
				shipment_leg_has_permission(None, "write", "sellerlog@example.com")
				shipment_event_has_permission(None, "write", "sellerlog@example.com")
		log_decision.assert_not_called()


# ---------------------------------------------------------------------------
# Alan maskeleme
# ---------------------------------------------------------------------------


class TestMaskShipmentCostFields(FrappeTestCase):
	"""view.logistics_cost capability'si olmayan kullanıcıya maliyet gizlenir."""

	def test_mask_shipment_cost_hides_fields(self):
		"""Capability yoksa maliyet alanları None olur — 0 DEĞİL (DB'yi ezmesin)."""
		doc = _FakeDoc(
			name="SHP-001",
			shipping_cost=150.0,
			insurance_cost=25.0,
			total_cost=175.0,
			carrier_cost=100.0,
			fuel_surcharge=10.0,
			packaging_cost=15.0,
		)
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=False
		):
			mask_shipment_cost_fields(doc, "seller@example.com")
		for field in (
			"shipping_cost",
			"insurance_cost",
			"total_cost",
			"carrier_cost",
			"fuel_surcharge",
			"packaging_cost",
		):
			self.assertIsNone(getattr(doc, field), f"{field} maskelenmeliydi")

	def test_mask_shipment_cost_falsy_user_applies_mask(self):
		"""FAIL-CLOSED: kullanıcı çözülemezse maskeleme UYGULANIR."""
		doc = _FakeDoc(name="SHP-001", shipping_cost=150.0, total_cost=175.0)
		original_user = frappe.session.user
		try:
			frappe.session.user = ""
			mask_shipment_cost_fields(doc, None)
		finally:
			frappe.session.user = original_user
		self.assertIsNone(doc.shipping_cost)
		self.assertIsNone(doc.total_cost)

	def test_mask_shipment_cost_shows_with_capability(self):
		"""POZİTİF: capability varsa maliyet alanları görünür."""
		doc = _FakeDoc(name="SHP-001", shipping_cost=150.0, insurance_cost=25.0, total_cost=175.0)
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=True
		):
			mask_shipment_cost_fields(doc, "finance@example.com")
		self.assertEqual(doc.shipping_cost, 150.0)
		self.assertEqual(doc.insurance_cost, 25.0)
		self.assertEqual(doc.total_cost, 175.0)


class TestMaskCarrierAccountFields(FrappeTestCase):
	"""view.carrier_secret capability'si olmayan kullanıcıya secret gizlenir."""

	def test_mask_carrier_account_hides_api_key(self):
		"""Maske değeri TAMAMEN asterisk olmalı.

		Frappe `BaseDocument._save_passwords` yalnız tümü asterisk olan değeri
		dummy sayıp kaydetmede atlar; bullet (•) içeren bir maske doküman
		kaydedilirse `__Auth`'taki gerçek secret'ın üzerine yazardı.
		"""
		doc = _FakeDoc(
			name="CC-001",
			api_key="secret-key-123",
			api_secret="secret-value",
			webhook_secret="whsec_abc",
			access_token="tok_xyz",
		)
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=False
		):
			mask_carrier_account_fields(doc, "operator@example.com")
		for field in ("api_key", "api_secret", "webhook_secret", "access_token"):
			value = getattr(doc, field)
			self.assertEqual(value, "*" * 8, f"{field} maskelenmeliydi")
			self.assertEqual(set(value), {"*"}, f"{field} maskesi yalnız asterisk içermeli")

	def test_mask_carrier_account_falsy_user_applies_mask(self):
		"""FAIL-CLOSED: kullanıcı çözülemezse maskeleme UYGULANIR."""
		doc = _FakeDoc(name="CC-001", api_key="secret-key-123", api_secret="secret-value")
		original_user = frappe.session.user
		try:
			frappe.session.user = ""
			mask_carrier_account_fields(doc, None)
		finally:
			frappe.session.user = original_user
		self.assertEqual(doc.api_key, "*" * 8)
		self.assertEqual(doc.api_secret, "*" * 8)

	def test_mask_carrier_account_shows_with_capability(self):
		"""POZİTİF: capability varsa secret'lar görünür."""
		doc = _FakeDoc(name="CC-001", api_key="secret-key-123", api_secret="secret-value")
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=True
		):
			mask_carrier_account_fields(doc, "admin@example.com")
		self.assertEqual(doc.api_key, "secret-key-123")
		self.assertEqual(doc.api_secret, "secret-value")


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestAuditLogDeny(FrappeTestCase):
	"""DENY kaydı: neyin yazıldığı kadar neyin YAZILMADIĞI da sözleşmedir.

	`log_decision` senkron bir DB insert'i olduğu için her reddi yazmak istek
	gecikmesi ve ADL şişmesi üretiyordu (Faz A.5). Aşağıdaki testler filtrelerin
	yerinde kaldığını garanti eder.
	"""

	def setUp(self):
		# Dedup guard + bekleyen flush listesi testler arası sızmasın
		frappe.cache.delete_keys(f"{CACHE_PREFIX}deny:")
		frappe.local.tc_pending_deny_audits = []
		# Dedup + flush kaydı zarf bağlamına şartlandı (doğrulama 2026-09-04,
		# Major 2) — bu sınıfın dedup testleri zarf yolunu simüle eder.
		frappe.local.tc_logistics_envelope = True
		self.addCleanup(setattr, frappe.local, "tc_logistics_envelope", False)

	def test_cross_tenant_deny_logs_decision_as_high(self):
		"""POZİTİF: çapraz tenant denemesi HIGH severity ile kaydedilir."""
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch("tradehub_core.audit.log.log_decision") as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")

		log_decision.assert_called()
		_, kwargs = log_decision.call_args
		self.assertEqual(kwargs.get("decision"), "DENY")
		self.assertEqual(kwargs.get("object_doctype"), "Shipment")
		self.assertEqual(kwargs.get("severity"), "HIGH")
		self.assertEqual(kwargs.get("tenant"), "SEL-00001")

	def test_routine_deny_logs_as_normal(self):
		"""Sınır aşımı olmayan reddetme NORMAL severity ile kaydedilir."""
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch("tradehub_core.audit.log.log_decision") as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00001"):
				shipment_has_permission(doc, "cancel", "operator@example.com")

		log_decision.assert_called()
		_, kwargs = log_decision.call_args
		self.assertEqual(kwargs.get("severity"), "NORMAL")

	def test_doctype_level_check_does_not_write_audit_row(self):
		"""NEGATİF: doc=None kontrolü ADL'ye satır YAZMAZ.

		Frappe bu kontrolü her liste/form açılışında çağırır; yazmak
		write amplification demektir.
		"""
		with mock.patch("tradehub_core.audit.log.log_decision") as log_decision:
			with acting_as(["Customer"], seller_profile=None):
				shipment_has_permission(None, "write", "buyer@example.com")
				carrier_account_has_permission(None, "read", "buyer@example.com")

		log_decision.assert_not_called()

	def test_repeated_identical_deny_is_deduplicated(self):
		"""Aynı kullanıcı + eylem + nesne tekrarı TTL içinde tek satır üretir."""
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch("tradehub_core.audit.log.log_decision") as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				for _ in range(5):
					shipment_has_permission(doc, "read", "operator@example.com")

		self.assertEqual(
			log_decision.call_count, 1, "Tekrarlanan aynı reddetme tek kayıt üretmeli"
		)

	def test_different_object_is_not_deduplicated(self):
		"""Farklı nesneye yapılan reddetmeler ayrı ayrı kaydedilir."""
		with mock.patch("tradehub_core.audit.log.log_decision") as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(_shipment(name="SHP-001"), "read", "op@example.com")
				shipment_has_permission(_shipment(name="SHP-002"), "read", "op@example.com")

		self.assertEqual(log_decision.call_count, 2)

	def test_dedup_key_conditioned_on_insert_success(self):
		"""Madde 2a (denetim 2026-09-04): insert BAŞARISIZSA dedup anahtarı yazılmaz.

		log_decision best-effort'tur (hatada None döner); eski kod anahtarı
		insert'ten ÖNCE yazdığı için başarısız yazımın 60 sn'lik tekrar
		denemeleri de susturuluyordu — kayıp satır + kayıp retry.
		"""
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch(
			"tradehub_core.audit.log.log_decision", return_value=None
		) as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")
				shipment_has_permission(doc, "read", "operator@example.com")

		self.assertEqual(
			log_decision.call_count, 2,
			"Başarısız insert dedup anahtarı yazmamalı — ikinci deneme tekrar yazmalı",
		)

	def test_deny_is_registered_for_post_rollback_flush(self):
		"""Madde 2b: başarılı DENY yazımı bekleyen flush listesine de kaydedilir."""
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch("tradehub_core.audit.log.log_decision", return_value="ADL-1"):
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")

		pending = getattr(frappe.local, "tc_pending_deny_audits", [])
		self.assertEqual(len(pending), 1)
		self.assertEqual(pending[0]["payload"]["decision"], "DENY")
		self.assertEqual(pending[0]["payload"]["object_name"], "SHP-001")

	def test_flush_rewrites_pending_rows_and_clears_list(self):
		"""api_utils._fail'in rollback SONRASI çağırdığı flush satırı geri yazar."""
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch("tradehub_core.audit.log.log_decision", return_value="ADL-1"):
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")

		with mock.patch(
			"tradehub_core.audit.log.log_decision", return_value="ADL-2"
		) as log_decision:
			written = flush_pending_deny_audits()

		self.assertEqual(written, 1)
		log_decision.assert_called_once()
		self.assertEqual(log_decision.call_args.kwargs.get("decision"), "DENY")
		self.assertEqual(getattr(frappe.local, "tc_pending_deny_audits", None), [])
		self.assertEqual(
			flush_pending_deny_audits(), 0, "İkinci flush yazacak satır bulmamalı"
		)

	def test_non_envelope_deny_writes_no_dedup_key_and_no_pending(self):
		"""Doğrulama 2026-09-04 Major 2: zarf DIŞI deny dedup anahtarı YAZMAZ.

		Desk /api/resource yolunda deny insert'i persist etmez (GET+exception →
		handle_exception rollback'i, flags.commit yok); eski kod yine de dedup
		anahtarı yazdığı için kayıp satır 60 sn'lik zarflı deny'ları da
		bastırıyordu. Artık zarf dışında ne anahtar ne flush kaydı yazılır —
		insert best-effort kalır, tekrarları da bastırılmaz.
		"""
		frappe.local.tc_logistics_envelope = False
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch(
			"tradehub_core.audit.log.log_decision", return_value="ADL-1"
		) as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")
				shipment_has_permission(doc, "read", "operator@example.com")

		self.assertEqual(
			log_decision.call_count, 2,
			"Zarf dışında dedup anahtarı yazılmamalı — ikinci deneme de insert denemeli",
		)
		self.assertEqual(
			getattr(frappe.local, "tc_pending_deny_audits", None), [],
			"Zarf dışında flush kaydı da tutulmamalı — flush'ı çağıran yol yok",
		)

	def test_non_envelope_deny_does_not_poison_envelope_dedup(self):
		"""Zarf-dışı deny'ın hemen ardından gelen ZARFLI deny ADL'ye yazılır.

		Zehirlenme senaryosunun kendisi: Desk deny anahtarı yazsaydı sonraki
		60 sn'nin zarflı deny'ları bastırılır, pencere her tekrar ile tazelenip
		denetim izi süresiz susardı.
		"""
		doc = _shipment(seller_profile="SEL-00001")

		frappe.local.tc_logistics_envelope = False
		with mock.patch("tradehub_core.audit.log.log_decision", return_value="ADL-1"):
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")

		frappe.local.tc_logistics_envelope = True
		with mock.patch(
			"tradehub_core.audit.log.log_decision", return_value="ADL-2"
		) as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")

		log_decision.assert_called_once()
		self.assertEqual(
			len(getattr(frappe.local, "tc_pending_deny_audits", [])), 1,
			"Zarflı deny flush listesine kaydedilmeli — _fail rollback sonrası geri yazar",
		)

	def test_envelope_deny_still_writes_dedup_key(self):
		"""Zarf İÇİ deny dedup anahtarını yazmaya devam eder (pozitif kontrol)."""
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch(
			"tradehub_core.audit.log.log_decision", return_value="ADL-1"
		) as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")
				shipment_has_permission(doc, "read", "operator@example.com")

		log_decision.assert_called_once()

	def test_flush_failure_reopens_dedup_key(self):
		"""Flush'ta da yazılamayan satır dedup penceresini açar — sonraki deneme loglanır."""
		doc = _shipment(seller_profile="SEL-00001")
		with mock.patch("tradehub_core.audit.log.log_decision", return_value="ADL-1"):
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")

		with mock.patch("tradehub_core.audit.log.log_decision", return_value=None):
			self.assertEqual(flush_pending_deny_audits(), 0)

		# Dedup anahtarı silindi → aynı deny yeniden yazılabilir olmalı
		with mock.patch(
			"tradehub_core.audit.log.log_decision", return_value="ADL-3"
		) as log_decision:
			with acting_as(["Logistics Operator"], seller_profile="SEL-00002"):
				shipment_has_permission(doc, "read", "operator@example.com")
		log_decision.assert_called_once()


# ---------------------------------------------------------------------------
# E2E — gerçek kayıt, gerçek get_list
# ---------------------------------------------------------------------------


class TestCarrierAccountTenantIsolationE2E(FrappeTestCase):
	"""Çapraz satıcı sızıntısı gerçek SQL yolunda engellenir.

	Yukarıdaki testler permission FONKSİYONLARINI doğruluyor. Bu test
	`hooks.py` kaydı → `permission_query_conditions` → gerçek `frappe.get_list`
	zincirinin tamamını doğrular. TUR-103'ün "çapraz satıcı erişimi engellenir"
	kabul kriterinin asıl kanıtı budur.

	`Shipment` için aynısı yapılamıyor — DocType henüz yok (F bloğu).
	"""

	SELLERS = (
		("LOGTEST-A", "logtest-seller-a@example.com"),
		("LOGTEST-B", "logtest-seller-b@example.com"),
	)

	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		self.assertIsNotNone(self.carrier, "Seed edilmiş Logistics Provider bulunamadı")

		for code, email in self.SELLERS:
			self._ensure_user(email)
			self._ensure_seller_profile(code, email)
			self._ensure_carrier_account(code)
			# Tenant resolver pozitif cache tutuyor — testler arası kirlenmesin
			frappe.cache.delete_value(f"tradehub:seller_for_user:{email}")

	def tearDown(self):
		"""Test verisini geride bırakma — dev DB'sini kirletmesin.

		Silme sırası bağımlılığı takip eder: hesap → profil → kullanıcı.
		`frappe.db.commit()` çağırdığımız için FrappeTestCase'in rollback'i bu
		kayıtları toplamaz; temizlik açıkça yapılmalı.
		"""
		for code, email in self.SELLERS:
			frappe.db.delete("Carrier Account", {"seller_profile": code})
			frappe.cache.delete_value(f"tradehub:seller_for_user:{email}")
		frappe.db.commit()

		for code, email in self.SELLERS:
			for doctype, name in (("Admin Seller Profile", code), ("User", email)):
				if not frappe.db.exists(doctype, name):
					continue
				try:
					frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
				except frappe.LinkExistsError:
					# Başka bir kayıt bağlanmışsa bırak — test verisi olduğu
					# adından belli; sessiz kalmamak için logla.
					frappe.log_error(
						f"Test temizliği: {doctype} {name} bağlı kayıt nedeniyle silinemedi",
						"test_logistics_permissions",
					)
		frappe.db.commit()

	# -- kurulum yardımcıları ------------------------------------------------

	def _ensure_user(self, email: str) -> None:
		if frappe.db.exists("User", email):
			return
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@")[0]
		user.send_welcome_email = 0
		user.append("roles", {"role": "Carrier Integration Manager"})
		user.insert(ignore_permissions=True)

	def _ensure_seller_profile(self, code: str, email: str) -> None:
		if frappe.db.exists("Admin Seller Profile", code):
			return
		profile = frappe.new_doc("Admin Seller Profile")
		profile.seller_code = code
		profile.seller_name = f"Test Satıcı {code}"
		profile.user = email
		profile.email = email
		profile.insert(ignore_permissions=True)

	def _ensure_carrier_account(self, code: str) -> None:
		account = frappe.new_doc("Carrier Account")
		account.account_name = f"{code} taşıyıcı hesabı"
		account.carrier = self.carrier
		account.seller_profile = code
		account.environment = "Sandbox"
		account.is_active = 1
		account.insert(ignore_permissions=True)
		frappe.db.commit()

	# -- testler -------------------------------------------------------------

	def test_seller_a_cannot_list_seller_b_carrier_account(self):
		"""NEGATİF: A satıcısının listesinde B'nin hesabı ÇIKMAZ."""
		code_a, email_a = self.SELLERS[0]
		code_b, _ = self.SELLERS[1]

		original_user = frappe.session.user
		try:
			frappe.set_user(email_a)
			rows = frappe.get_list(
				"Carrier Account",
				fields=["name", "seller_profile"],
				limit_page_length=0,
			)
		finally:
			frappe.set_user(original_user)

		profiles = {r["seller_profile"] for r in rows}
		self.assertIn(code_a, profiles, "A kendi hesabını görmeli")
		self.assertNotIn(code_b, profiles, "A, B'nin hesabını GÖRMEMELİ — tenant sızıntısı")

	def test_query_condition_is_actually_applied(self):
		"""Koşulun gerçekten SQL'e girdiğini doğrular (boş dönerse test yanılırdı)."""
		code_a, email_a = self.SELLERS[0]

		original_user = frappe.session.user
		try:
			frappe.set_user(email_a)
			condition = carrier_account_query_conditions(email_a)
		finally:
			frappe.set_user(original_user)

		self.assertIn("seller_profile", condition)
		self.assertIn(code_a, condition)


# ---------------------------------------------------------------------------
# G0 matrisi (C2) — satıcı dar yolu: update_shipment_status
# ---------------------------------------------------------------------------


class TestSellerTransitionNarrowPath(FrappeTestCase):
	"""api/v1/shipment._seller_can_transition — üç koşulun her biri tek başına
	yetmemeli; yalnız rol + tenant + alt-küme ÜÇÜ birden True vermeli."""

	def _can(self, doc, user="seller@example.com", to_status="Picked Up"):
		from tradehub_core.api.v1.shipment import _seller_can_transition

		return _seller_can_transition(doc, user, to_status)

	def test_seller_confirms_pickup_on_own_shipment(self):
		"""Rol + kendi tenant'ı + izinli geçiş → True (FBM confirm-shipment)."""
		doc = _shipment(status="Ready for Pickup")
		with acting_as(["Seller Logistics", "Seller Staff"], seller_profile="SEL-00001"):
			self.assertTrue(self._can(doc))

	def test_without_role_denied(self):
		"""Seller Logistics rolü yoksa tenant eşleşse bile False."""
		doc = _shipment(status="Ready for Pickup")
		with acting_as(["Seller Staff"], seller_profile="SEL-00001"):
			self.assertFalse(self._can(doc))

	def test_cross_tenant_denied(self):
		"""Başka satıcının sevkiyatı — rol olsa da False."""
		doc = _shipment(status="Ready for Pickup", seller_profile="SEL-99999")
		with acting_as(["Seller Logistics"], seller_profile="SEL-00001"):
			self.assertFalse(self._can(doc))

	def test_transition_outside_subset_denied(self):
		"""Alt küme dışı geçiş (iptal) — rol ve tenant tutsa da False."""
		doc = _shipment(status="Ready for Pickup")
		with acting_as(["Seller Logistics"], seller_profile="SEL-00001"):
			self.assertFalse(self._can(doc, to_status="Cancelled"))


# ---------------------------------------------------------------------------
# Carrier Integration Log — satıcı kapısı FAIL-CLOSED (denetim 2026-08-28)
# ---------------------------------------------------------------------------


class TestIntegrationLogSellerGateIsFailClosed(FrappeTestCase):
	"""Tenant resolver `None` dönse bile satıcı platform logunu GÖREMEZ.

	ÖLÇÜLDÜ (2026-08-28): kapı yalnız `_get_user_seller_profile(user)` ile
	kuruluydu ve FAIL-OPEN'dı — `Seller` + `Logistics Operator` rollü,
	`tradehub_tenant=None` bir kullanıcı için `query_conditions` `''`
	(KISITSIZ) dönüyordu ve `has_permission(None, "read")` `True` idi.
	Kodun kendi yorumu "tenant'lı bir Logistics Operator da satıcı tarafıdır"
	diyordu; niyet doğruydu, uygulama resolver'a bağlıydı.

	Düzeltme kapıyı ROL ile de kuruyor (`_SELLER_SIDE_ROLES`). Platform
	rollerinin (satıcı rolü OLMADAN) erişimi KORUNUR — aşağıdaki pozitif
	testler bunu kilitler.
	"""

	USER = "cil-failopen@example.com"

	def _gate(self, roles: list[str], seller_profile: str | None):
		from tradehub_core.logistics.permissions import (
			carrier_integration_log_has_permission,
			carrier_integration_log_query_conditions,
		)

		with acting_as(roles, seller_profile=seller_profile):
			return (
				carrier_integration_log_query_conditions(self.USER),
				carrier_integration_log_has_permission(None, "read", self.USER),
			)

	def test_seller_role_without_tenant_is_blocked(self):
		"""ASIL BULGU: tenant çözülemeyen satıcı rolü artık kapıyı açmıyor."""
		condition, allowed = self._gate(["Seller", "Logistics Operator"], None)
		self.assertEqual(condition, "1=0")
		self.assertFalse(allowed)

	def test_every_seller_side_role_is_blocked_without_tenant(self):
		from tradehub_core.logistics.permissions import _SELLER_SIDE_ROLES

		for role in sorted(_SELLER_SIDE_ROLES):
			with self.subTest(role=role):
				# Platform okuma rolüyle BİRLİKTE bile reddedilmeli
				condition, allowed = self._gate([role, "Logistics Manager"], None)
				self.assertEqual(condition, "1=0")
				self.assertFalse(allowed)

	def test_platform_roles_without_seller_role_keep_access(self):
		"""KIRILMAMASI GEREKEN: platform operasyon zinciri erişimini korur."""
		for role in ("Logistics Manager", "Logistics Operator", "Carrier Integration Manager"):
			with self.subTest(role=role):
				condition, allowed = self._gate([role], None)
				self.assertEqual(condition, "")
				self.assertTrue(allowed)

	def test_tenant_still_closes_the_gate_without_seller_role(self):
		"""Rol kanıtı eklendi diye tenant kanıtı DÜŞMEDİ — ikisi OR'lanıyor."""
		condition, allowed = self._gate(["Logistics Operator"], "SEL-00001")
		self.assertEqual(condition, "1=0")
		self.assertFalse(allowed)

	def test_system_manager_with_seller_role_is_still_exempt(self):
		"""System Manager kapıdan ÖNCE dönüyor — platform yönetimi kilitlenmesin."""
		condition, allowed = self._gate(["System Manager", "Seller"], None)
		self.assertEqual(condition, "")
		self.assertTrue(allowed)


class TestIntegrationLogIsNotDeletableByDocPerm(FrappeTestCase):
	"""Denetim izi DocPerm üzerinden SİLİNEMEZ.

	ÖLÇÜLDÜ (2026-08-28): `carrier_integration_log.json` System Manager
	satırında `"delete": 1` duruyordu; gerçek bir System Manager kullanıcısıyla
	`frappe.client.delete` bir satırı SİLDİ ve arkasında hiçbir `Authorization
	Decision Log` kaydı kalmadı — controller docstring'i ise "append-only"
	diyordu.

	Saklama işi bundan etkilenmez: `frappe.db.delete` ile, DocPerm katmanına hiç
	uğramadan çalışır.
	"""

	DOCTYPE = "Carrier Integration Log"

	def test_no_role_has_delete_permission(self):
		rows = frappe.get_all(
			"DocPerm",
			filters={"parent": self.DOCTYPE},
			fields=["role", "delete", "write", "create"],
		)
		self.assertTrue(rows, "DocPerm satırı yok — DocType migrate edilmemiş olabilir")
		for row in rows:
			with self.subTest(role=row["role"]):
				self.assertEqual(row["delete"], 0, "Denetim izi silinebilir olmamalı")
				self.assertEqual(row["write"], 0, "Append-only: write DocPerm'i olmamalı")
				self.assertEqual(row["create"], 0, "Kayıt yalnız yazıcı yolundan oluşur")

	def test_retention_job_still_bypasses_docperm(self):
		"""Silmenin tek meşru yolu `frappe.db.delete` — DocPerm'e hiç bakmaz."""
		import inspect

		from tradehub_core.logistics.jobs import integration_log_retention as job

		source = inspect.getsource(job)
		self.assertIn("frappe.db.delete", source)
