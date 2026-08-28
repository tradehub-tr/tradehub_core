# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Carrier Account — platform seviyesi hesap ve kapsam benzersizliği (Faz B.5).

Çalıştırma:
	docker exec istoccom-backend-1 bash -c "cd /home/frappe/workspace/frappe-bench && \\
	  bench --site dev.localhost run-tests \\
	  --module tradehub_core.logistics.tests.test_carrier_account"

İki kapsam var:
	* **Satıcı hesabı** — `seller_profile` dolu; satıcının kendi kargo sözleşmesi
	* **Platform hesabı** — `seller_profile` boş; İstoç'un sözleşmesi, satıcılar
	  bunu backend üzerinden kullanır ama credential'ı GÖREMEZ

Her iki kapsamda da "taşıyıcı başına tek aktif hesap" kuralı geçerli; kapsamlar
birbirini engellemez.
"""

from __future__ import annotations

import unittest.mock as mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.logistics.constants import CREDENTIAL_SECRET_FIELDS


class _CarrierAccountBase(FrappeTestCase):
	SELLER_CODE = "CATEST-SELLER"
	SELLER_EMAIL = "catest-seller@example.com"

	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		self.assertIsNotNone(self.carrier, "Seed edilmiş Logistics Provider yok")
		self._ensure_seller()

	def tearDown(self):
		frappe.db.delete("Carrier Account", {"carrier": self.carrier})
		frappe.db.commit()

	def _ensure_seller(self) -> None:
		if frappe.db.exists("Admin Seller Profile", self.SELLER_CODE):
			return
		if not frappe.db.exists("User", self.SELLER_EMAIL):
			user = frappe.new_doc("User")
			user.email = self.SELLER_EMAIL
			user.first_name = "CA Test"
			user.send_welcome_email = 0
			user.insert(ignore_permissions=True)
		profile = frappe.new_doc("Admin Seller Profile")
		profile.seller_code = self.SELLER_CODE
		profile.seller_name = "Carrier Account Test Satıcı"
		profile.user = self.SELLER_EMAIL
		profile.email = self.SELLER_EMAIL
		profile.insert(ignore_permissions=True)
		frappe.db.commit()

	def _new_account(self, seller_profile: str | None, name: str = "Hesap") -> frappe.Document:
		doc = frappe.new_doc("Carrier Account")
		doc.account_name = name
		doc.carrier = self.carrier
		doc.seller_profile = seller_profile
		doc.environment = "Sandbox"
		doc.is_active = 1
		return doc


class TestPlatformAccountCreation(_CarrierAccountBase):
	"""Platform seviyesi hesap artık modellenebiliyor."""

	def test_platform_account_can_be_created_without_seller(self):
		"""POZİTİF: seller_profile boş bırakılabilir.

		Daha önce alan `reqd=1` idi; permissions.py'deki 'platform-global' dalı
		bu yüzden ULAŞILAMAZ ölü koddu.
		"""
		doc = self._new_account(None, "İstoç Platform Hesabı")
		doc.insert(ignore_permissions=True)
		self.assertIsNone(doc.seller_profile)

	def test_empty_string_is_normalized_to_none(self):
		"""Boş string ile None aynı kapsamı ifade etmeli.

		İki farklı 'boş' değer platform hesabı sorgularını sessizce ıskalatırdı.
		"""
		doc = self._new_account("", "Boş String Hesabı")
		doc.insert(ignore_permissions=True)
		self.assertIsNone(doc.seller_profile)

	def test_tenant_user_gets_own_profile_autoset(self):
		"""1. KATMAN: tenant kullanıcısı boş bıraksa da alan kendi profiline set edilir.

		`utils/tenant.enforce_seller_isolation_on_insert` before_insert hook'u
		devrede olduğu sürece tenant kullanıcısı platform hesabı OLUŞTURAMAZ —
		alan sessizce kendi mağazasına bağlanır.
		"""
		doc = self._new_account(None, "Tenant Denemesi")
		original_user = frappe.session.user
		try:
			frappe.session.user = self.SELLER_EMAIL
			doc.insert(ignore_permissions=True)
		finally:
			frappe.session.user = original_user

		self.assertEqual(
			doc.seller_profile,
			self.SELLER_CODE,
			"Tenant kullanıcısının hesabı kendi profiline bağlanmalıydı",
		)

	def test_guard_blocks_when_tenant_hook_is_bypassed(self):
		"""2. KATMAN: hook atlanırsa controller guard'ı devreye girer.

		`doc.insert()` doğrudan çağrıldığında veya hook kaydı düştüğünde
		1. katman yoktur. Guard olmasaydı tenant kullanıcısı kendi mağazası
		dışına yazma yolu açardı.
		"""
		doc = self._new_account(None, "Kaçak Platform Hesabı")
		original_user = frappe.session.user
		try:
			frappe.session.user = self.SELLER_EMAIL
			with (
				# 1. katmanı devre dışı bırak — guard tek başına kalsın
				mock.patch(
					"tradehub_core.utils.tenant.enforce_seller_isolation_on_insert",
					return_value=None,
				),
				mock.patch(
					"tradehub_core.logistics.permissions._get_user_seller_profile",
					return_value=self.SELLER_CODE,
				),
				mock.patch("frappe.get_roles", return_value=["Carrier Integration Manager"]),
			):
				with self.assertRaises(frappe.PermissionError):
					doc.insert(ignore_permissions=True)
		finally:
			frappe.session.user = original_user


class TestScopedUniqueness(_CarrierAccountBase):
	"""Taşıyıcı başına tek aktif hesap — her kapsam kendi içinde."""

	def test_second_platform_account_rejected(self):
		"""NEGATİF: aynı taşıyıcı için ikinci aktif PLATFORM hesabı açılamaz."""
		self._new_account(None, "Platform 1").insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self._new_account(None, "Platform 2").insert(ignore_permissions=True)

	def test_second_seller_account_rejected(self):
		"""NEGATİF: aynı satıcı + taşıyıcı için ikinci aktif hesap açılamaz."""
		self._new_account(self.SELLER_CODE, "Satıcı 1").insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self._new_account(self.SELLER_CODE, "Satıcı 2").insert(ignore_permissions=True)

	def test_platform_and_seller_accounts_coexist(self):
		"""POZİTİF: platform hesabı ile satıcı hesabı aynı taşıyıcıda birlikte yaşar.

		Ana senaryo budur: İstoç'un sözleşmesi varken satıcı kendi sözleşmesini
		de tanımlayabilmeli.
		"""
		self._new_account(None, "Platform").insert(ignore_permissions=True)
		seller_doc = self._new_account(self.SELLER_CODE, "Satıcı")
		seller_doc.insert(ignore_permissions=True)
		self.assertEqual(seller_doc.seller_profile, self.SELLER_CODE)

	def test_inactive_account_does_not_block(self):
		"""Pasif hesap benzersizlik kuralını tetiklemez."""
		first = self._new_account(None, "Pasif Platform")
		first.is_active = 0
		first.insert(ignore_permissions=True)
		self._new_account(None, "Aktif Platform").insert(ignore_permissions=True)


class TestPlatformAccountVisibility(_CarrierAccountBase):
	"""Platform hesabının credential'ı tenant kullanıcısına kapalı."""

	def test_tenant_user_cannot_read_platform_account(self):
		"""NEGATİF: satıcı, platform hesabının satırını göremez.

		Satıcı platform anlaşmasını KULLANIR ama API anahtarını görmemeli.
		"""
		from tradehub_core.logistics.permissions import carrier_account_has_permission

		doc = self._new_account(None, "Platform")
		doc.insert(ignore_permissions=True)

		with mock.patch("frappe.get_roles", return_value=["Carrier Integration Manager"]), mock.patch(
			"tradehub_core.utils.tenant._get_seller_profile_for_user",
			return_value=self.SELLER_CODE,
		):
			self.assertFalse(
				carrier_account_has_permission(doc, "read", self.SELLER_EMAIL)
			)

	def test_platform_user_can_read_platform_account(self):
		"""POZİTİF: tenant'ı olmayan platform kullanıcısı erişebilir."""
		from tradehub_core.logistics.permissions import carrier_account_has_permission

		doc = self._new_account(None, "Platform")
		doc.insert(ignore_permissions=True)

		with mock.patch("frappe.get_roles", return_value=["Carrier Integration Manager"]), mock.patch(
			"tradehub_core.utils.tenant._get_seller_profile_for_user", return_value=None
		):
			self.assertTrue(
				carrier_account_has_permission(doc, "read", "platform-cim@example.com")
			)


class TestCredentialSecretFieldsContract(FrappeTestCase):
	"""`CREDENTIAL_SECRET_FIELDS` ile DocType şeması SÜRÜKLENMEMELİ.

	Küme üç yeri birden besliyor: değer-tabanlı redaksiyonun girdisi
	(`integration/secrets.py`), transport (`adapters/http_client.py`) ve API
	yanıtından çıkarılan alanlar (`api/v1/logistics_admin.py::SECRET_FIELDS`).
	Eskiden iki yerde AYRI İÇERİKLE yazılıydı (yedi ad / dört ad) ve yorum
	"aynı küme" diyordu.

	DocType'a yeni bir `Password` alanı eklendiğinde bu test kırılır — aksi
	hâlde redaksiyon o alana SESSİZCE kör kalırdı.
	"""

	def test_constant_matches_the_password_fields_of_the_doctype(self):
		meta = frappe.get_meta("Carrier Account")
		password_fields = {field.fieldname for field in meta.fields if field.fieldtype == "Password"}

		self.assertEqual(password_fields, set(CREDENTIAL_SECRET_FIELDS))

	def test_api_layer_reuses_the_same_constant(self):
		"""`SECRET_FIELDS` artık bir kopya değil, takma ad."""
		from tradehub_core.api.v1.logistics_admin import SECRET_FIELDS

		self.assertIs(SECRET_FIELDS, CREDENTIAL_SECRET_FIELDS)
