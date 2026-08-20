"""Ö-3 — KYC Verification kiracı izolasyonu.

`v15_8_3_seller_owner_kyb_kyc_docperm` patch'i "Seller Owner" rolüne HEM KYB
HEM KYC'de permlevel-0 `read=1, write=1, if_owner=0` verdi ve gerekçesinde
"tenant izolasyonu KORUNUR: her iki doctype'ta permission_query_conditions +
has_permission hook'u var" dedi. Bu cümle KYB için doğru, KYC için YANLIŞTI —
`hooks.py` yalnız KYB'yi kaydetmişti. Ölçülen sonuç (canlı DB, 2026-08-19):
mağaza sahibi BAŞKASININ KYC kaydını okuyor ve alanlarını değiştiriyordu.

Bu modül üç şeyi sınar:
  1. Çapraz kiracı okuma ve YAZMA reddedilir (liste sorgusu dahil).
  2. Meşru erişim korunur: kendi kaydı, Marketplace Admin, System Manager,
     ve `has_permission` kancasının Compliance Officer'a verdiği izin.
  3. Kancalar `hooks.py`'de gerçekten kayıtlı (vacuity koruması — kanca
     silinirse 1. gruptaki testler kırmızıya döner).

Gerçek DB kullanılır (`FrappeTestCase`): sınanan şey Frappe'nin izin motoru,
stub'lanamaz.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_kyc_tenant_isolation
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core import permissions


class KYCTenantIsolationTests(FrappeTestCase):
	# -- fixture yardımcıları ------------------------------------------------

	def _drop(self, doctype: str, name: str) -> None:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _user(self, tag: str, roles: tuple[str, ...]) -> str:
		email = f"o3-{tag}-{self.suffix}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("User", doc.name))
		return doc.name

	def _kyc(self, user: str, phone: str) -> frappe.Document:
		doc = frappe.get_doc(
			{
				"doctype": "KYC Verification",
				"user": user,
				"account_type": "Individual",
				"tax_id": "10000000146",  # geçerli TCKN sağlaması
				"phone": phone,
				"address": "Test adres",
				"billing_address": "Test fatura adresi",
				"identity_document": "/private/files/o3-placeholder.pdf",
				"status": "Pending",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("KYC Verification", doc.name))
		return doc

	# -- kurulum -------------------------------------------------------------

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		# Saldırgan: canlıdaki gerçek mağaza sahibi rol kümesi.
		self.attacker = self._user("attacker", ("Marketplace Seller", "Seller", "Seller Owner"))
		# Kurban: başka bir kiracı (alıcı).
		self.victim = self._user("victim", ("Buyer",))
		self.officer = self._user("officer", ("Compliance Officer",))
		self.admin = self._user("admin", ("Marketplace Admin",))
		self.sysmgr = self._user("sysmgr", ("System Manager",))

		self.kyc_victim = self._kyc(self.victim, "+905550000001")
		self.kyc_attacker = self._kyc(self.attacker, "+905550000002")

		# `owner` ekseninin doğru eksen OLMADIĞINI koruyan kurulum: canlıda
		# 24 kaydın 15'inde owner="Administrator", user gerçek kişi. Fixture'ı
		# aynı şekle sokuyoruz ki `if_owner` ile geçen sahte bir yeşil olmasın.
		frappe.db.set_value("KYC Verification", self.kyc_attacker.name, "owner", "Administrator")
		frappe.db.commit()

	# -- 1. çapraz kiracı: REDDEDİLMELİ --------------------------------------

	def test_cross_tenant_read_denied(self):
		"""Seller Owner BAŞKASININ KYC kaydını okuyamaz."""
		frappe.set_user(self.attacker)
		doc = frappe.get_doc("KYC Verification", self.kyc_victim.name)
		self.assertFalse(
			frappe.has_permission("KYC Verification", "read", doc=doc, user=self.attacker),
			"Seller Owner başkasının KYC kaydını okuyabiliyor",
		)
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get("KYC Verification", self.kyc_victim.name)

	def test_cross_tenant_write_denied(self):
		"""Seller Owner BAŞKASININ KYC alanını değiştiremez (asıl bulgu)."""
		frappe.set_user(self.attacker)
		doc = frappe.get_doc("KYC Verification", self.kyc_victim.name)
		self.assertFalse(
			frappe.has_permission("KYC Verification", "write", doc=doc, user=self.attacker),
			"Seller Owner başkasının KYC kaydına yazabiliyor",
		)
		with self.assertRaises(frappe.PermissionError):
			frappe.client.set_value(
				"KYC Verification", self.kyc_victim.name, "phone", "+909999999999"
			)
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("KYC Verification", self.kyc_victim.name, "phone"),
			"+905550000001",
			"reddedilmesine rağmen DB'de değer değişmiş",
		)

	def test_cross_tenant_delete_denied(self):
		frappe.set_user(self.attacker)
		doc = frappe.get_doc("KYC Verification", self.kyc_victim.name)
		self.assertFalse(
			frappe.has_permission("KYC Verification", "delete", doc=doc, user=self.attacker)
		)

	def test_list_excludes_other_tenants(self):
		"""`frappe.get_list` başkasının kaydını döndürmemeli, kendisininkini döndürmeli."""
		frappe.set_user(self.attacker)
		names = [
			r["name"]
			for r in frappe.get_list("KYC Verification", fields=["name"], limit_page_length=0)
		]
		self.assertNotIn(self.kyc_victim.name, names, "liste sorgusunda çapraz kiracı sızıntısı")
		self.assertIn(self.kyc_attacker.name, names, "kendi kaydı listede yok")

	def test_query_conditions_sql_scopes_to_user(self):
		"""Üretilen SQL `user` alanına bağlanmalı — `owner`'a değil."""
		cond = permissions.kyc_verification_query_conditions(self.attacker)
		self.assertIn("`tabKYC Verification`.`user`", cond)
		self.assertIn(frappe.db.escape(self.attacker), cond)

	# -- 2. meşru erişim: KORUNMALI ------------------------------------------

	def test_own_record_read_and_write_allowed(self):
		"""Mağaza sahibi KENDİ kaydını okur ve yazar (v15_8_3'ün meşru amacı).

		Kayıt `owner="Administrator"` — yani bu yeşil `if_owner` üzerinden
		gelmiyor, `user` link'i üzerinden geliyor."""
		frappe.set_user(self.attacker)
		doc = frappe.get_doc("KYC Verification", self.kyc_attacker.name)
		self.assertTrue(frappe.has_permission("KYC Verification", "read", doc=doc, user=self.attacker))
		self.assertTrue(frappe.has_permission("KYC Verification", "write", doc=doc, user=self.attacker))
		self.assertEqual(
			frappe.client.get("KYC Verification", self.kyc_attacker.name).get("name"),
			self.kyc_attacker.name,
		)
		frappe.client.set_value(
			"KYC Verification", self.kyc_attacker.name, "phone", "+905550000042"
		)
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("KYC Verification", self.kyc_attacker.name, "phone"),
			"+905550000042",
			"kendi kaydına yazma kırıldı",
		)

	def test_marketplace_admin_keeps_full_access(self):
		frappe.set_user(self.admin)
		doc = frappe.get_doc("KYC Verification", self.kyc_victim.name)
		self.assertTrue(frappe.has_permission("KYC Verification", "read", doc=doc, user=self.admin))
		self.assertTrue(frappe.has_permission("KYC Verification", "write", doc=doc, user=self.admin))
		names = [
			r["name"]
			for r in frappe.get_list("KYC Verification", fields=["name"], limit_page_length=0)
		]
		self.assertIn(self.kyc_victim.name, names)
		frappe.client.set_value("KYC Verification", self.kyc_victim.name, "phone", "+905551111111")
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("KYC Verification", self.kyc_victim.name, "phone"), "+905551111111"
		)

	def test_system_manager_keeps_full_access(self):
		frappe.set_user(self.sysmgr)
		doc = frappe.get_doc("KYC Verification", self.kyc_victim.name)
		self.assertTrue(frappe.has_permission("KYC Verification", "read", doc=doc, user=self.sysmgr))
		names = [
			r["name"]
			for r in frappe.get_list("KYC Verification", fields=["name"], limit_page_length=0)
		]
		self.assertIn(self.kyc_victim.name, names)

	def test_administrator_keeps_full_access(self):
		frappe.set_user("Administrator")
		self.assertEqual(permissions.kyc_verification_query_conditions("Administrator"), "")
		names = [
			r["name"]
			for r in frappe.get_list("KYC Verification", fields=["name"], limit_page_length=0)
		]
		self.assertIn(self.kyc_victim.name, names)

	def test_compliance_officer_not_blocked_by_this_layer(self):
		"""Compliance Officer bu katmanda ENGELLENMEZ.

		NOT: Compliance Officer'ın KYC'de permlevel-0 Custom DocPerm satırı YOK
		(ölçüldü, 2026-08-19) — bu yüzden `frappe.client.get` bu düzeltmeden
		ÖNCE de sonra da 403 verir. Bu ayrı ve önceden var olan bir eksik
		(rapor: docs/reports/24-kyc-izolasyon.md). Burada sınanan şey, bizim
		eklediğimiz katmanın onu ayrıca kısıtlamadığıdır — düzeltilirse
		Compliance Officer erişimi kendiliğinden çalışmalı."""
		doc = frappe.get_doc("KYC Verification", self.kyc_victim.name)
		self.assertTrue(
			permissions.kyc_verification_has_permission(doc, "read", self.officer),
			"has_permission kancası Compliance Officer'ı reddediyor",
		)
		self.assertEqual(permissions.kyc_verification_query_conditions(self.officer), "")

	def test_compliance_officer_is_read_only_at_this_layer(self):
		"""`_is_platform_full_access` Compliance Officer'a write vermez."""
		doc = frappe.get_doc("KYC Verification", self.kyc_victim.name)
		self.assertFalse(
			permissions.kyc_verification_has_permission(doc, "write", self.officer)
		)

	# -- 3. kancaların kayıtlı olduğu ----------------------------------------

	def test_hooks_registered(self):
		"""Vacuity koruması: kanca kaydı silinirse yukarıdaki testler yalancı
		yeşile dönmeden ÖNCE bu test kırmızıya döner."""
		hooks = frappe.get_hooks()
		self.assertIn(
			"tradehub_core.permissions.kyc_verification_query_conditions",
			hooks.get("permission_query_conditions", {}).get("KYC Verification", []),
		)
		self.assertIn(
			"tradehub_core.permissions.kyc_verification_has_permission",
			hooks.get("has_permission", {}).get("KYC Verification", []),
		)

	def test_docperm_row_is_narrowed(self):
		"""v15_9_24: `Seller Owner` satırında ölü/riskli grant kalmamalı."""
		row = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "KYC Verification", "role": "Seller Owner", "permlevel": 0},
			["read", "write", "create", "delete", "report", "export", "share", "import"],
			as_dict=True,
		)
		if not row:
			self.skipTest("Seller Owner Custom DocPerm satırı yok")
		self.assertEqual(int(row.read), 1)
		self.assertEqual(int(row.write), 1)
		for field in ("create", "delete", "report", "export", "share", "import"):
			self.assertEqual(int(row[field] or 0), 0, f"{field} grant'ı hâlâ açık")
