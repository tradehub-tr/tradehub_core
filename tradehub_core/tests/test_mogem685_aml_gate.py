"""MOGEM-685 bulgu 1 — satıcı AML / yaptırım kapısı gerçekten kapanıyor.

Eskiden iki kapı da (`seller_capabilities._check_aml_clean`, `permissions._check_aml_sanctions`)
KYB Verification'da OLMAYAN iki sütunu okuyordu; sorgu her çağrıda düşüyor ve "geçti" sayılıyordu
(yerelde 1.775 Error Log). Sütunlar olsa da `docstatus: 1` filtresi hiçbir kaydı bulmazdı — KYB
submittable değil. Kararlar `utils/aml_gate.py` başında.

Her engelleme testinin karşı kanıtı aynı satıcının işaretsizken GEÇMESİ; yoksa "engellendi"
iddiası "hiç yetkisi yoktu"dan ayırt edilemez.

    bench --site dev.localhost run-tests --module tradehub_core.tests.test_mogem685_aml_gate
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core import permissions
from tradehub_core.tests.mogem665_ortak import Mogem665Ortam
from tradehub_core.utils import aml_gate
from tradehub_core.utils.seller_capabilities import has_seller_capability

AML_YETKILERI = ("order.confirm_payment", "order.refund", "balance.withdraw")


class TestAmlKapisi(Mogem665Ortam, FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.seller, self.user = self._seller("aml")
		# Mağaza sahibi bağı — gerçek satıcılarda dolu; yoksa sahip yetkileri hiç açılmaz.
		frappe.db.set_value("User", self.user, {"tradehub_tenant": self.seller, "tradehub_is_owner": 1})
		kyb = frappe.get_doc(
			{
				"doctype": "KYB Verification",
				"user": self.user,
				"company_title": "AML Test",
				"status": "Verified",
			}
		)
		kyb.flags.ignore_mandatory = True
		kyb.insert(ignore_permissions=True)
		frappe.db.set_value("KYB Verification", kyb.name, "owner", self.user)
		frappe.db.commit()
		self.kyb = kyb.name
		self.addCleanup(lambda: self._drop("KYB Verification", self.kyb))
		self.addCleanup(frappe.set_user, "Administrator")

	def _isaretle(self, aml: str = "Not Checked", yaptirim: str = "Not Checked") -> None:
		frappe.db.set_value(
			"KYB Verification", self.kyb, {"aml_check_status": aml, "sanctions_status": yaptirim}
		)
		frappe.db.commit()

	def test_yeni_kayit_kontrol_edilmedi_ile_baslar_ve_gecer(self):
		self.assertEqual(
			frappe.db.get_value("KYB Verification", self.kyb, ["aml_check_status", "sanctions_status"]),
			("Not Checked", "Not Checked"),
		)
		self.assertFalse(aml_gate.aml_engelli_mi(self.user))

	def test_temiz_gecer(self):
		self._isaretle("Clear", "Clear")
		self.assertFalse(aml_gate.aml_engelli_mi(self.user))

	def test_kyb_kaydi_olmayan_satici_gecer(self):
		self.assertFalse(aml_gate.aml_engelli_mi("kyb-kaydi-yok@test.local"))

	def test_aml_eslesmesi_uc_finans_yetkisini_kapatir(self):
		for yetki in AML_YETKILERI:
			self.assertTrue(
				has_seller_capability(yetki, self.user), f"karşı kanıt: işaretsizken {yetki} açık olmalı"
			)
		self._isaretle(aml="Hit Found")
		for yetki in AML_YETKILERI:
			self.assertFalse(has_seller_capability(yetki, self.user), f"AML işaretliyken {yetki} açık")

	def test_yaptirim_eslesmesi_uc_finans_yetkisini_kapatir(self):
		self._isaretle(yaptirim="Match Found")
		for yetki in AML_YETKILERI:
			self.assertFalse(has_seller_capability(yetki, self.user), f"yaptırım işaretliyken {yetki} açık")

	def test_isaret_finans_disi_yetkilere_dokunmaz(self):
		self.assertTrue(has_seller_capability("order.ship", self.user))
		self._isaretle(aml="Hit Found", yaptirim="Match Found")
		self.assertTrue(has_seller_capability("order.ship", self.user))

	def test_hassas_doctype_erisimi_kapanir(self):
		for doctype in permissions.AML_SENSITIVE_DOCTYPES:
			self.assertTrue(permissions._check_aml_sanctions(self.user, doctype), doctype)
		self._isaretle(aml="Hit Found")
		for doctype in permissions.AML_SENSITIVE_DOCTYPES:
			self.assertFalse(permissions._check_aml_sanctions(self.user, doctype), doctype)
		# Hassas olmayan DocType işaretten etkilenmez.
		self.assertTrue(permissions._check_aml_sanctions(self.user, "Listing"))

	def test_sorgu_duserse_islem_durur_ve_kayda_gecer(self):
		# Kullanıcı kararı: kontrol yapılamıyorsa hassas iş güvenli tarafta durur.
		once = frappe.db.count("Error Log", {"method": aml_gate.HATA_BASLIGI})
		gercek = frappe.db.get_value

		def kyb_sorgusu_duser(doctype, *a, **k):
			if doctype == "KYB Verification":
				raise frappe.db.OperationalError(2013, "bağlantı koptu")
			return gercek(doctype, *a, **k)

		with mock.patch.object(frappe.db, "get_value", side_effect=kyb_sorgusu_duser):
			self.assertTrue(aml_gate.aml_engelli_mi(self.user))
		self.assertEqual(frappe.db.count("Error Log", {"method": aml_gate.HATA_BASLIGI}), once + 1)

	def test_satici_isareti_goremez_ve_degistiremez(self):
		self._isaretle(aml="Hit Found", yaptirim="Match Found")
		frappe.set_user(self.user)
		doc = frappe.get_doc("KYB Verification", self.kyb)
		doc.check_permission("read")
		doc.apply_fieldlevel_read_permissions()
		self.assertIsNone(doc.get("aml_check_status"), "satıcı AML alanını görüyor")
		self.assertIsNone(doc.get("sanctions_status"), "satıcı yaptırım alanını görüyor")

		doc = frappe.get_doc("KYB Verification", self.kyb)
		doc.aml_check_status = "Clear"
		doc.sanctions_status = "Clear"
		doc.flags.ignore_mandatory = True
		doc.save()
		frappe.db.commit()
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("KYB Verification", self.kyb, ["aml_check_status", "sanctions_status"]),
			("Hit Found", "Match Found"),
		)

	def test_satici_ignore_permissions_yolunda_da_degistiremez(self):
		# Satıcı akışları (submit_kyb_documents vb.) KYB'yi ignore_permissions ile kaydediyor;
		# permlevel orada atlanır, validate() içindeki kapı durdurmalı.
		self._isaretle(aml="Hit Found")
		frappe.set_user(self.user)
		doc = frappe.get_doc("KYB Verification", self.kyb)
		doc.aml_check_status = "Clear"
		doc.flags.ignore_mandatory = True
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)
		frappe.db.rollback()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("KYB Verification", self.kyb, "aml_check_status"), "Hit Found")

	def test_inceleyici_isaretleyebilir_ve_kaldirabilir(self):
		# Karşı kanıt: kapı yalnız satıcıyı durdurur, admin akışı çalışır.
		doc = frappe.get_doc("KYB Verification", self.kyb)
		doc.aml_check_status = "Hit Found"
		doc.flags.ignore_mandatory = True
		doc.save()
		self.assertTrue(aml_gate.aml_engelli_mi(self.user))
		doc.aml_check_status = "Clear"
		doc.save()
		self.assertFalse(aml_gate.aml_engelli_mi(self.user))

	def test_satici_akisi_isarete_dokunmadan_kaydedebilir(self):
		# Kapı yanlış alarm vermemeli: satıcı kendi belgesini güncellerken işaret değişmiyor.
		self._isaretle(aml="Hit Found")
		frappe.set_user(self.user)
		doc = frappe.get_doc("KYB Verification", self.kyb)
		doc.authorized_person = "Yeni Yetkili"
		doc.flags.ignore_mandatory = True
		doc.save(ignore_permissions=True)
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("KYB Verification", self.kyb, "authorized_person"), "Yeni Yetkili"
		)
