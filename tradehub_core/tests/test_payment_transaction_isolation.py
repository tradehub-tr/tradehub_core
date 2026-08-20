"""T1 — `Payment Transaction` çapraz-kiracı IDOR.

Sızma testi (docs/reports/28-faz13-pentest.md §2 T1) gerçek HTTP üzerinden
kanıtladı: hiçbir ödeme kaydına sahip OLMAYAN yeni bir `Marketplace Seller`,
`/api/resource/Payment Transaction` ile BAŞKA satıcının 3 kaydını okudu —
alıcı kimliği, tutar, satıcı IBAN'ı ve dekont yolu düz JSON'da döndü.

Kök neden: `hooks.py`'de bu doctype için NE `permission_query_conditions` NE
`has_permission` kaydı vardı; DocPerm ise `Marketplace Seller` rolüne
`read=1, if_owner=0` veriyordu. KYB/KYC (Ö-3) ve File (Ö-2) ile aynı desen.

Bu modül üç şeyi sınar:
  1. Çapraz kiracı okuma reddedilir (tek belge + liste sorgusu).
  2. Meşru erişim korunur: satıcı kendi mağazasının işlemi, alıcı kendi
     ödemesi, alıcının organizasyon üyesi, Marketplace Admin hepsi.
  3. Kancalar `hooks.py`'de gerçekten kayıtlı (vacuity koruması — kanca
     silinirse 1. gruptaki testler yalancı yeşile dönmeden ÖNCE bu kırılır).

Gerçek DB kullanılır (`FrappeTestCase`): sınanan şey Frappe'nin izin motoru.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_payment_transaction_isolation
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core import permissions


class PaymentTransactionIsolationTests(FrappeTestCase):
	# -- fixture yardımcıları ------------------------------------------------

	def _drop(self, doctype: str, name: str) -> None:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _user(self, tag: str, roles: tuple[str, ...]) -> str:
		email = f"t1-{tag}-{self.suffix}@test.local"
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

	def _store(self, tag: str, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"T1{tag}{self.suffix}",
				"seller_name": f"T1 {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Admin Seller Profile", doc.name))
		return doc.name

	def _payment(self, store: str, buyer: str) -> str:
		# `order` Link alanı reqd=1 ama izin mantığı ona HİÇ bakmaz; gerçek bir
		# Order üretmek `Order.validate`ın KYB kapısını (Verified Seller rolü)
		# tetikler ve bu testin konusuyla ilgisiz bir kurulum zinciri doğurur.
		# `ignore_links` + `ignore_mandatory` ile sentetik bir referans yeterli.
		doc = frappe.get_doc(
			{
				"doctype": "Payment Transaction",
				"transaction_type": "Ödeme",
				"order": f"T1-ORD-{self.suffix}",
				"buyer": buyer,
				"seller": store,
				"seller_name": store,
				"amount": 21428.4,
				"currency": "TRY",
				"seller_bank_name": "Test Bank",
				"seller_iban": "TR710004600640888000110422",
				"receipt_url": "/private/files/t1-placeholder.jpg",
				"status": "Gönderildi",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		# Canlı veriyle aynı şekil: kayıt alıcının istek bağlamında üretilir
		# (`api/payment.create_payment_transaction`), yani `owner == buyer`.
		# `Buyer` DocPerm satırı `if_owner=1` olduğu için bu alan, alıcının
		# KENDİ ödemesini okuyabilmesinin ÖN KOŞULU — has_permission kancası
		# rol izninden daha fazlasını veremez (Frappe ikisini VE'ler).
		frappe.db.set_value("Payment Transaction", doc.name, "owner", buyer)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Payment Transaction", doc.name))
		return doc.name

	# -- kurulum -------------------------------------------------------------

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		# Kurban satıcı — ödeme kaydının sahibi mağaza.
		self.victim_seller = self._user("vseller", ("Marketplace Seller", "Seller"))
		self.victim_store = self._store("V", self.victim_seller)
		self.buyer = self._user("buyer", ("Buyer",))
		self.payment = self._payment(self.victim_store, self.buyer)

		# Saldırgan — sızma testindeki persona: hiçbir ödemesi olmayan,
		# mağazası bile olmayan yeni bir `Marketplace Seller`.
		self.attacker = self._user("attacker", ("Marketplace Seller",))
		# İkinci saldırgan — mağazası VAR ama başka mağaza.
		self.other_seller = self._user("oseller", ("Marketplace Seller", "Seller"))
		self.other_store = self._store("O", self.other_seller)

		self.admin = self._user("admin", ("Marketplace Admin",))

	# -- 1. çapraz kiracı: REDDEDİLMELİ --------------------------------------

	def test_storeless_seller_cannot_read(self):
		"""Sızma testinin birebir personası: mağazası olmayan Marketplace Seller."""
		doc = frappe.get_doc("Payment Transaction", self.payment)
		self.assertFalse(
			frappe.has_permission("Payment Transaction", "read", doc=doc, user=self.attacker),
			"mağazasız satıcı başkasının ödeme kaydını okuyabiliyor",
		)
		frappe.set_user(self.attacker)
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get("Payment Transaction", self.payment)

	def test_other_store_seller_cannot_read(self):
		doc = frappe.get_doc("Payment Transaction", self.payment)
		self.assertFalse(
			frappe.has_permission("Payment Transaction", "read", doc=doc, user=self.other_seller),
			"başka mağazanın satıcısı ödeme kaydını okuyabiliyor",
		)

	def test_list_excludes_other_tenants(self):
		frappe.set_user(self.attacker)
		names = [
			r["name"]
			for r in frappe.get_list("Payment Transaction", fields=["name"], limit_page_length=0)
		]
		self.assertNotIn(self.payment, names, "liste sorgusunda çapraz kiracı sızıntısı")

		frappe.set_user(self.other_seller)
		names = [
			r["name"]
			for r in frappe.get_list("Payment Transaction", fields=["name"], limit_page_length=0)
		]
		self.assertNotIn(self.payment, names, "liste sorgusunda çapraz kiracı sızıntısı")

	def test_guest_gets_no_rows(self):
		self.assertEqual(permissions.payment_transaction_query_conditions("Guest"), "1=0")

	def test_query_conditions_bind_to_seller_and_buyer(self):
		cond = permissions.payment_transaction_query_conditions(self.victim_seller)
		self.assertIn("`tabPayment Transaction`.`seller`", cond)
		self.assertIn(frappe.db.escape(self.victim_store), cond)
		self.assertIn("`tabPayment Transaction`.`buyer`", cond)

	# -- 2. meşru erişim: KORUNMALI ------------------------------------------

	def test_owner_seller_sees_own_payment(self):
		doc = frappe.get_doc("Payment Transaction", self.payment)
		self.assertTrue(
			frappe.has_permission("Payment Transaction", "read", doc=doc, user=self.victim_seller)
		)
		frappe.set_user(self.victim_seller)
		names = [
			r["name"]
			for r in frappe.get_list("Payment Transaction", fields=["name"], limit_page_length=0)
		]
		self.assertIn(self.payment, names, "satıcı KENDİ ödeme kaydını göremiyor")
		# Rapor 92 (B-03 kapanışı): `seller_iban` permlevel-1'e taşındı — yetki
		# denetimli okuma yolu (frappe.client.get / REST) alanı satır-okuru
		# rollere (Buyer, Marketplace Seller) ARTIK vermez; eski pin bu satırın
		# IBAN döndürdüğünü doğruluyordu. Satıcının kendi IBAN'ının kaynağı
		# `Admin Seller Profile.iban`dır; alıcının havale ekranları ise
		# `api/payment.py`nin whitelisted uçlarından okur (ignore_permissions —
		# rapor 92 §2'de canlı ölçüldü, kırılmadı).
		self.assertIsNone(
			frappe.client.get("Payment Transaction", self.payment).get("seller_iban"),
			"seller_iban permlevel-1 koruması düştü — satır-okuru rol IBAN'ı yine okuyor (B-03 regresyonu)",
		)

	def test_buyer_sees_own_payment(self):
		doc = frappe.get_doc("Payment Transaction", self.payment)
		self.assertTrue(
			frappe.has_permission("Payment Transaction", "read", doc=doc, user=self.buyer)
		)
		frappe.set_user(self.buyer)
		names = [
			r["name"]
			for r in frappe.get_list("Payment Transaction", fields=["name"], limit_page_length=0)
		]
		self.assertIn(self.payment, names, "alıcı KENDİ ödemesini göremiyor")

	def test_buyer_docperm_is_if_owner_scoped(self):
		"""Alıcı tarafındaki asıl daraltma `Buyer` DocPerm satırının `if_owner=1`i.

		Bu, bu düzeltmeden ÖNCE de sonra da böyle (ölçüldü). Kayıt başka biri
		tarafından üretilmişse (ör. `backfill_payment_transactions` patch'i
		Administrator olarak koşar) alıcı kendi ödemesini okuyamaz. Bu ayrı ve
		önceden var olan bir konu; burada yalnız kayıt altına alınıyor ki
		yukarıdaki yeşil, kancanın değil `owner` alanının eseri sanılmasın.
		"""
		row = frappe.db.get_value(
			"DocPerm",
			{"parent": "Payment Transaction", "role": "Buyer", "permlevel": 0},
			["read", "if_owner"],
			as_dict=True,
		)
		self.assertEqual(int(row.read), 1)
		self.assertEqual(int(row.if_owner), 1)

	def test_marketplace_admin_sees_everything(self):
		doc = frappe.get_doc("Payment Transaction", self.payment)
		self.assertTrue(
			frappe.has_permission("Payment Transaction", "read", doc=doc, user=self.admin)
		)
		self.assertEqual(permissions.payment_transaction_query_conditions(self.admin), "")
		frappe.set_user(self.admin)
		names = [
			r["name"]
			for r in frappe.get_list("Payment Transaction", fields=["name"], limit_page_length=0)
		]
		self.assertIn(self.payment, names)
		# Rapor 92 (B-03): pozitif kontrol — permlevel-1 taşıması "kimse görmez"
		# değil "yalnız yönetici görür" demek; Marketplace Admin IBAN'ı OKUMALI.
		self.assertEqual(
			frappe.client.get("Payment Transaction", self.payment).get("seller_iban"),
			"TR710004600640888000110422",
			"Marketplace Admin permlevel-1'de IBAN okuyamıyor — yönetici görünürlüğü düştü",
		)

	def test_administrator_unrestricted(self):
		self.assertEqual(permissions.payment_transaction_query_conditions("Administrator"), "")
		self.assertTrue(
			permissions.payment_transaction_has_permission(
				frappe.get_doc("Payment Transaction", self.payment), "read", "Administrator"
			)
		)

	def test_doctype_level_check_not_broken(self):
		"""doc=None (liste ekranı açılışı) engellenmez — Order emsali."""
		self.assertTrue(
			permissions.payment_transaction_has_permission(None, "read", self.victim_seller)
		)

	# -- 3. kancaların kayıtlı olduğu ----------------------------------------

	def test_hooks_registered(self):
		"""Vacuity koruması: kanca kaydı silinirse bu test kırmızıya döner."""
		hooks = frappe.get_hooks()
		self.assertIn(
			"tradehub_core.permissions.payment_transaction_query_conditions",
			hooks.get("permission_query_conditions", {}).get("Payment Transaction", []),
		)
		self.assertIn(
			"tradehub_core.permissions.payment_transaction_has_permission",
			hooks.get("has_permission", {}).get("Payment Transaction", []),
		)
