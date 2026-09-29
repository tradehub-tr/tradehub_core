"""MOGEM-685 F-04 — misafire satıcının kişisel/iletişim verisi gitmez (regresyon).

11 Eylül raporu "misafire satıcı adresi gidiyor" diyordu; 21 Eylül'de ölçüldü, kusur
çözülmüştü (`get_seller` misafirde adres sorgusunu hiç yapmıyor, email/phone/user'ı
düşürüyor) ama bunu koruyan test yoktu. 29 Eylül işaretli (kanarya) taramasında 20 misafir
kanalından biri sızdırıyordu: `get_sellers` listedeki HER satıcının `user`ını (giriş
e-postası) döndürüyordu — `get_seller`'daki kural liste ucunda unutulmuştu.

Karşı kanıt her testin içinde: aynı çağrı giriş yapmış kullanıcıyla veriyi GÖRMELİ; yoksa
"misafirde yok" iddiası "veri hiç yok"tan ayırt edilemez (21 Eylül'de tam bu tuzağa
düşülmüştü — ilk denenen satıcının adres kaydı yoktu).

    bench --site dev.localhost run-tests --module tradehub_core.tests.test_mogem685_f04_misafir_satici
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.seller import get_seller, get_sellers
from tradehub_core.tests.mogem665_ortak import Mogem665Ortam

KANARYA_ADRES = "F04KANARYA SOKAK No 7"
KANARYA_TEL = "+905550004040"
KANARYA_ADRES_TEL = "5550004141"


class TestMisafireSaticiVerisi(Mogem665Ortam, FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.seller, self.user = self._seller("f04")
		self.kod = frappe.db.get_value("Admin Seller Profile", self.seller, "seller_code")
		self.ad = frappe.db.get_value("Admin Seller Profile", self.seller, "seller_name")
		frappe.db.set_value("Admin Seller Profile", self.seller, "phone", KANARYA_TEL)
		adres = frappe.get_doc(
			{
				"doctype": "Addresses",
				"kind": "Seller",
				"seller": self.seller,
				"is_default": 1,
				"title": "F04KANARYA",
				"contact_name": "F04KANARYA KISI",
				"phone_prefix": "+90",
				"phone": KANARYA_ADRES_TEL,
				"country": "Turkey",
				"state": "Istanbul",
				"city": "Istanbul",
				"street": KANARYA_ADRES,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Addresses", adres.name))
		self.addCleanup(frappe.set_user, "Administrator")

	def _gizli_degerler(self) -> tuple[str, ...]:
		return (KANARYA_ADRES, KANARYA_TEL, KANARYA_ADRES_TEL, self.user)

	def _sizan(self, yanit) -> list[str]:
		metin = json.dumps(yanit, default=str, ensure_ascii=False)
		return [d for d in self._gizli_degerler() if d in metin]

	def _liste_kaydi(self) -> dict:
		kayitlar = get_sellers(search=self.ad, page_size=50)["sellers"]
		bizimki = [s for s in kayitlar if s.get("seller_code") == self.kod]
		self.assertEqual(len(bizimki), 1, "satıcı listede bulunamadı — test kurulumu bozuk")
		return bizimki[0]

	def test_get_seller_misafire_adres_ve_iletisim_vermez(self):
		frappe.set_user("Guest")
		yanit = get_seller(slug=self.kod)
		self.assertIsNone(yanit.get("address"))
		for alan in ("email", "phone", "user"):
			self.assertNotIn(alan, yanit, f"misafir yanıtında {alan} var")
		self.assertEqual(self._sizan(yanit), [])
		# Herkese açık konum bilgisi korunur (vitrin "şehir, ülke" gösteriyor).
		self.assertIn("city", yanit)
		self.assertIn("country", yanit)

	def test_get_seller_giris_yapmisa_adresi_gosterir_karsi_kanit(self):
		frappe.set_user(self.user)
		yanit = get_seller(slug=self.kod)
		self.assertEqual((yanit.get("address") or {}).get("street"), KANARYA_ADRES)
		self.assertEqual(yanit.get("phone"), KANARYA_TEL)
		self.assertEqual(yanit.get("user"), self.user)

	def test_get_sellers_misafire_giris_eposta_ve_iletisim_vermez(self):
		frappe.set_user("Guest")
		kayit = self._liste_kaydi()
		for alan in ("user", "email", "phone", "website"):
			self.assertNotIn(alan, kayit, f"misafir listesinde {alan} var")
		self.assertEqual(self._sizan(kayit), [])
		# `verified` giriş e-postasından hesaplanıyor — alan düşerken rozet bozulmamalı.
		self.assertIn("verified", kayit)

	def test_get_sellers_giris_yapmisa_ayni_kaydi_verir_karsi_kanit(self):
		frappe.set_user(self.user)
		kayit = self._liste_kaydi()
		self.assertEqual(kayit.get("user"), self.user)
		self.assertEqual(kayit.get("phone"), KANARYA_TEL)

	def test_verified_rozeti_misafir_ve_giris_yapmista_ayni(self):
		frappe.set_user("Guest")
		misafir = self._liste_kaydi()["verified"]
		frappe.set_user(self.user)
		self.assertEqual(self._liste_kaydi()["verified"], misafir)
