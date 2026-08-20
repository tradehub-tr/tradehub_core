"""T2/T3 — KYC/KYB kendini-doğrulama (yetki yükseltme).

Sızma testi (docs/reports/28-faz13-pentest.md §2 T2/T3) ölçtü: `Seller` /
`Marketplace Seller` rolündeki bir kullanıcı KENDİ KYC/KYB kaydında
`status = "Verified"` yazabiliyordu. Sonuç veri sızıntısı DEĞİL, iş kuralının
tamamen atlanmasıydı:

  * KYC `Verified` → `on_update._sync_kyc_status` → `User Profile.can_buy = 1`
  * KYB `Verified` → `on_update._sync_verified_seller_role` → kullanıcı kendine
    **`Verified Seller`** rolünü verdi, `can_sell = 1` — yani satış kapısını
    hiçbir belge incelenmeden kendi kendine açtı.

Kök neden: `status` permlevel-1'deydi ve aynı permlevel'de satıcı rollerinin
`write=1` satırı vardı. Frappe'nin permlevel kapısı `if_owner`a HİÇ bakmaz
(`Document.get_permlevel_access`), yalnız rol + permlevel + write üçlüsüne bakar.

İki katmanlı düzeltme sınanıyor:
  1. permlevel: `status` → permlevel 4, satıcı rollerinde `write=0`
     (patch `v15_9_26_kyc_kyb_status_permlevel`). Bu katman sessizce ESKİ
     değeri geri yazar (frappe/model/document.py:412, `validate` ÖNCESİ koşar).
  2. controller: `permissions.guard_verification_status_change` — `validate()`
     içinde çalışır, `flags.ignore_permissions` ile ATLANAMAZ. Bu depoda
     KYC/KYB'yi `ignore_permissions=True` ile kaydeden 5 fonksiyon / 12 çağrı
     noktası var (ölçüldü), o yüzden asıl kapı budur.

Ayrıca meşru akışın kırılmadığı sınanır: başvuru sahibi belge/adres alanlarını
yazabilmeli, durumunu OKUYABİLMELİ, `Draft→Pending` ve `Rejected→Pending`
geçişlerini yapabilmeli; inceleme rolleri her geçişi yapabilmeli.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_verification_status_guard
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core import permissions


class VerificationStatusGuardTests(FrappeTestCase):
	# -- fixture yardımcıları ------------------------------------------------

	def _drop(self, doctype: str, name: str) -> None:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _user(self, tag: str, roles: tuple[str, ...]) -> str:
		email = f"t23-{tag}-{self.suffix}@test.local"
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

	def _profile(self, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "User Profile",
				"user": user,
				"account_type": "Business",
				"can_buy": 0,
				"can_sell": 0,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("User Profile", doc.name))
		return doc.name

	def _kyc(self, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "KYC Verification",
				"user": user,
				"account_type": "Individual",
				"tax_id": "10000000146",  # geçerli TCKN sağlaması
				"phone": "+905550000001",
				"address": "Test adres",
				"billing_address": "Test fatura adresi",
				"identity_document": "/private/files/t23-placeholder.pdf",
				"status": "Pending",
			}
		).insert(ignore_permissions=True)
		# Meşru akışla aynı şekil: `api/v1/kyc.submit_kyc` kaydı başvuru
		# sahibinin bağlamında açar (`owner == user`). `Seller`/`Marketplace
		# Seller` DocPerm satırları `if_owner=1` olduğu için bu, sahibin kendi
		# kaydını düzenleyebilmesinin ÖN KOŞULU.
		frappe.db.set_value("KYC Verification", doc.name, "owner", user)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("KYC Verification", doc.name))
		return doc.name

	def _kyb(self, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "KYB Verification",
				"user": user,
				"company_title": f"T23 {self.suffix} Ltd",
				"tax_id_type": "VKN",
				"tax_id": "1234567890",
				"identity_document": "/private/files/t23-a.pdf",
				"imza_sirkuleri": "/private/files/t23-b.pdf",
				"ticaret_sicil_gazetesi": "/private/files/t23-c.pdf",
				"vergi_levhasi": "/private/files/t23-d.pdf",
				"bank_account_document": "/private/files/t23-e.pdf",
				"status": "Pending",
			}
		).insert(ignore_permissions=True)
		# `api/v1/kyb` kayıtları `doc.owner = user` ile açar — bkz. _kyc notu.
		frappe.db.set_value("KYB Verification", doc.name, "owner", user)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("KYB Verification", doc.name))
		return doc.name

	def _set_status(self, doctype: str, name: str, status: str) -> None:
		frappe.set_user("Administrator")
		frappe.db.set_value(doctype, name, "status", status, update_modified=False)
		frappe.db.commit()

	def _try_status(self, doctype: str, name: str, new_status: str, user: str) -> str:
		"""`ignore_permissions=True` ile status yazmayı dene → ALLOWED/BLOCKED.

		`ignore_permissions` BİLEREK: permlevel katmanını atlar, geriye yalnız
		controller kapısı kalır. Test tam olarak o kapıyı sınıyor.
		"""
		frappe.set_user(user)
		try:
			doc = frappe.get_doc(doctype, name)
			doc.status = new_status
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			frappe.db.commit()
			return "ALLOWED"
		except frappe.PermissionError:
			frappe.db.rollback()
			frappe.clear_last_message()
			return "BLOCKED"
		finally:
			frappe.set_user("Administrator")

	# -- kurulum -------------------------------------------------------------

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		self.seller = self._user("seller", ("Seller", "Marketplace Seller"))
		self._profile(self.seller)
		self.kyc = self._kyc(self.seller)
		self.kyb = self._kyb(self.seller)
		self.admin = self._user("admin", ("Marketplace Admin",))
		self.officer = self._user("officer", ("Compliance Officer",))

	# -- 1. yetki yükseltme: REDDEDİLMELİ ------------------------------------

	def test_seller_cannot_self_verify_kyc(self):
		self.assertEqual(self._try_status("KYC Verification", self.kyc, "Verified", self.seller), "BLOCKED")
		self.assertEqual(frappe.db.get_value("KYC Verification", self.kyc, "status"), "Pending")
		self.assertEqual(
			frappe.db.get_value("User Profile", {"user": self.seller}, "can_buy"),
			0,
			"can_buy kendi kendine açıldı",
		)

	def test_seller_cannot_self_verify_kyb(self):
		self.assertEqual(self._try_status("KYB Verification", self.kyb, "Verified", self.seller), "BLOCKED")
		self.assertEqual(frappe.db.get_value("KYB Verification", self.kyb, "status"), "Pending")
		self.assertFalse(
			frappe.db.exists("Has Role", {"parent": self.seller, "role": "Verified Seller"}),
			"kullanıcı kendine Verified Seller rolünü verdi",
		)
		self.assertEqual(frappe.db.get_value("User Profile", {"user": self.seller}, "can_sell"), 0)

	def test_seller_cannot_move_to_other_review_states(self):
		for status in ("Under Review", "Rejected", "Suspended"):
			self._set_status("KYB Verification", self.kyb, "Pending")
			self.assertEqual(
				self._try_status("KYB Verification", self.kyb, status, self.seller),
				"BLOCKED",
				f"satıcı status={status} yazabildi",
			)

	def test_seller_cannot_create_prevrified_record(self):
		"""Yeni kayıt açarken `status="Verified"` ile başlamak da engellenmeli."""
		frappe.set_user(self.seller)
		other = frappe.new_doc("KYB Verification")
		other.user = self.seller
		other.company_title = f"T23 pre {self.suffix}"
		other.status = "Verified"
		other.flags.ignore_permissions = True
		other.flags.ignore_mandatory = True
		# Kapı KIRILIRSA kayıt gerçekten oluşur; temizliği şimdiden bağla ki
		# kırmızı bir koşum DB'de "Verified" bir KYB kaydı bırakmasın.
		self.addCleanup(
			lambda: [
				self._drop("KYB Verification", n)
				for n in frappe.get_all(
					"KYB Verification",
					filters={"company_title": f"T23 pre {self.suffix}"},
					pluck="name",
				)
			]
		)
		with self.assertRaises(frappe.PermissionError):
			other.insert(ignore_permissions=True)
		frappe.db.rollback()
		frappe.clear_last_message()
		frappe.set_user("Administrator")

	def test_permlevel_layer_denies_write_to_seller_roles(self):
		"""İkinci katman: permlevel-4'te satıcı rollerinde write YOK."""
		frappe.set_user(self.seller)
		doc = frappe.get_doc("KYC Verification", self.kyc)
		status_permlevel = doc.meta.get_field("status").permlevel
		self.assertEqual(status_permlevel, 4, "status permlevel-4'te değil")
		self.assertNotIn(
			status_permlevel,
			doc.get_permlevel_access("write"),
			"satıcı rolü permlevel-4'e yazabiliyor",
		)
		frappe.set_user("Administrator")

	# -- 2. meşru akış: KORUNMALI --------------------------------------------

	def test_applicant_self_service_transitions_allowed(self):
		self._set_status("KYB Verification", self.kyb, "Draft")
		self.assertEqual(self._try_status("KYB Verification", self.kyb, "Pending", self.seller), "ALLOWED")
		self._set_status("KYB Verification", self.kyb, "Rejected")
		self.assertEqual(self._try_status("KYB Verification", self.kyb, "Pending", self.seller), "ALLOWED")
		self._set_status("KYC Verification", self.kyc, "Rejected")
		self.assertEqual(self._try_status("KYC Verification", self.kyc, "Pending", self.seller), "ALLOWED")

	def test_applicant_can_still_edit_own_documents(self):
		"""Başvuru sahibi belge/adres alanlarını yazabilmeye devam etmeli."""
		frappe.set_user(self.seller)
		frappe.client.set_value(
			"KYB Verification", self.kyb, "faaliyet_belgesi", "/private/files/t23-f.pdf"
		)
		frappe.client.set_value("KYC Verification", self.kyc, "address", "Yeni adres")
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("KYB Verification", self.kyb, "faaliyet_belgesi"),
			"/private/files/t23-f.pdf",
		)
		self.assertEqual(frappe.db.get_value("KYC Verification", self.kyc, "address"), "Yeni adres")

	def test_applicant_can_read_own_status(self):
		"""permlevel-4 read=1 — satıcı kendi durumunu görmeye devam eder."""
		frappe.set_user(self.seller)
		self.assertEqual(frappe.client.get("KYC Verification", self.kyc).get("status"), "Pending")
		self.assertEqual(frappe.client.get("KYB Verification", self.kyb).get("status"), "Pending")
		frappe.set_user("Administrator")

	def test_marketplace_admin_can_decide(self):
		self.assertEqual(self._try_status("KYB Verification", self.kyb, "Verified", self.admin), "ALLOWED")
		self.assertEqual(frappe.db.get_value("KYB Verification", self.kyb, "status"), "Verified")
		self.assertTrue(
			frappe.db.exists("Has Role", {"parent": self.seller, "role": "Verified Seller"}),
			"admin onayı Verified Seller rolünü tetiklemedi",
		)
		# temizlik: rolü geri al
		for hr in frappe.get_all(
			"Has Role", filters={"parent": self.seller, "role": "Verified Seller"}, pluck="name"
		):
			frappe.db.delete("Has Role", hr)
		frappe.db.commit()

	def test_marketplace_admin_has_permlevel_write(self):
		frappe.set_user(self.admin)
		for doctype, name in (("KYC Verification", self.kyc), ("KYB Verification", self.kyb)):
			doc = frappe.get_doc(doctype, name)
			self.assertIn(4, doc.get_permlevel_access("write"), f"{doctype}: admin permlevel-4 yazamıyor")
		frappe.set_user("Administrator")

	def test_compliance_officer_is_a_reviewer_at_this_layer(self):
		"""Compliance Officer bu kapıda ENGELLENMEZ.

		NOT: CO'nun KYC/KYB'de permlevel-0 Custom DocPerm satırı YOK (T4 —
		docs/reports/28-faz13-pentest.md §3, ayrı ve önceden var olan bulgu),
		bu yüzden belgeyi generic REST ile hiç açamıyor. Burada sınanan şey
		bizim eklediğimiz kapının onu ayrıca kısıtlamadığıdır.
		"""
		self.assertTrue(permissions.is_verification_reviewer(self.officer))
		frappe.set_user(self.officer)
		doc = frappe.get_doc("KYC Verification", self.kyc)
		self.assertIn(4, doc.get_permlevel_access("write"))
		frappe.set_user("Administrator")

	def test_seller_is_not_a_reviewer(self):
		self.assertFalse(permissions.is_verification_reviewer(self.seller))

	# -- 3. vacuity koruması --------------------------------------------------

	def test_guard_is_wired_into_both_controllers(self):
		"""Kapı `validate()` zincirinden çıkarılırsa bu test kırmızıya döner."""
		import inspect

		from tradehub_core.tradehub_core.doctype.kyb_verification.kyb_verification import (
			KYBVerification,
		)
		from tradehub_core.tradehub_core.doctype.kyc_verification.kyc_verification import (
			KYCVerification,
		)

		for cls in (KYCVerification, KYBVerification):
			self.assertIn(
				"_guard_status_change",
				inspect.getsource(cls.validate),
				f"{cls.__name__}.validate status kapısını çağırmıyor",
			)
			self.assertIn(
				"guard_verification_status_change",
				inspect.getsource(cls._guard_status_change),
			)

	def test_permlevel4_docperm_matrix(self):
		"""Patch v15_9_26'nın yazdığı satırlar yerinde mi."""
		for doctype in ("KYC Verification", "KYB Verification"):
			rows = {
				r["role"]: r
				for r in frappe.get_all(
					"Custom DocPerm",
					filters={"parent": doctype, "permlevel": 4},
					fields=["role", "read", "write"],
				)
			}
			self.assertTrue(rows, f"{doctype}: permlevel-4 satırı yok")
			for role in ("System Manager", "Marketplace Admin", "Compliance Officer"):
				self.assertEqual(int(rows[role]["write"]), 1, f"{doctype}/{role} write yok")
			for role in ("Seller", "Marketplace Seller", "Seller Owner"):
				self.assertEqual(int(rows[role]["read"]), 1, f"{doctype}/{role} read yok")
				self.assertEqual(int(rows[role]["write"]), 0, f"{doctype}/{role} write açık")
