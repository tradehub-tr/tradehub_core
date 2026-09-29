"""MOGEM-685 F-02 — kupon yarışı, GERÇEK veritabanı + iki bağlantı.

test_cart_price_tampering kilidin ÇAĞRILDIĞINI doğrular; bu dosya işe YARADIĞINI.
İki iş parçacığı ayrı Frappe bağlantılarıyla aynı anda `_reserve_coupon` çağırır.

  1. Tek kullanımlık kupon (max_uses=1): yalnız biri geçer, used_count = 1.
  2. Çok kullanımlık kupon + aynı alıcı: ilk bağlantı ayırır, siparişini yazar ve
     kilidi tutar; ikincisi — gerçek create_order gibi — önce düz bir okuma yapar
     (REPEATABLE READ anlık görüntüsü o anda donar), sonra kupona gelir. Kişi başı
     sayım kilitli okuma değilse ilk siparişi göremez ve kupon ikinci kez geçer.

Kilit kaldırılırsa (for_update / LOCK IN SHARE MODE) iki test de kırmızıya düşer
(karşı kanıt, 28 Eyl 2026).

    bench --site dev.localhost run-tests --module tradehub_core.tests.test_coupon_race
"""

from __future__ import annotations

import secrets
import threading
import time
import unittest

import frappe

from tradehub_core.api import cart

TUTMA_SN = 1.0  # ilk bağlantının kilidi tutma süresi


class TestCouponRace(unittest.TestCase):
	def setUp(self):
		self.site = frappe.local.site
		self.sites_path = frappe.local.sites_path
		self.ek = secrets.token_hex(3).upper()
		self.kuponlar: list[str] = []
		self.siparisler: list[str] = []

	def tearDown(self):
		for ad in self.siparisler:
			frappe.db.sql("DELETE FROM `tabOrder` WHERE name = %s", (ad,))
		for kod in self.kuponlar:
			frappe.db.sql("DELETE FROM `tabCoupon` WHERE name = %s", (kod,))
		frappe.db.commit()

	def _kupon(self, max_uses: int) -> str:
		kod = f"RACE{max_uses}{self.ek}"
		frappe.db.sql(
			"""INSERT INTO `tabCoupon` (name, code, coupon_type, value, max_uses, used_count,
			min_order, is_active, creation, modified, owner, modified_by, docstatus)
			VALUES (%s, %s, 'fixed', 10, %s, 0, 0, 1, NOW(), NOW(), 'Administrator', 'Administrator', 0)""",
			(kod, kod, max_uses),
		)
		frappe.db.commit()
		self.kuponlar.append(kod)
		return kod

	def _paralel(self, kod: str, alici: str, siparis_yaz: bool) -> list[str]:
		"""İki bağlantı; ilki kupon kilidini alır ve TUTMA_SN tutar. Sonuç: ['ok'|mesaj]."""
		sonuc: list[str | None] = [None, None]
		ilk_kilitte = threading.Event()

		def bag(i: int):
			frappe.init(site=self.site, sites_path=self.sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				if i == 1:
					ilk_kilitte.wait(5)
					# create_order kupondan önce adres/ürün okur → anlık görüntü burada donar.
					frappe.db.sql("SELECT COUNT(*) FROM `tabOrder` WHERE buyer = %s", (alici,))
				kod_, _indirim = cart._reserve_coupon(kod, 100, 0, alici)
				if i == 0:
					if siparis_yaz:
						ad = f"RACE-ORD-{self.ek}"
						frappe.db.sql(
							"""INSERT INTO `tabOrder` (name, buyer, coupon_code, status, creation,
							modified, owner, modified_by, docstatus)
							VALUES (%s, %s, %s, 'Ödeme Bekleniyor', NOW(), NOW(), %s, %s, 0)""",
							(ad, alici, kod_, alici, alici),
						)
						self.siparisler.append(ad)
					ilk_kilitte.set()
					time.sleep(TUTMA_SN)
				frappe.db.commit()
				sonuc[i] = "ok"
			except frappe.ValidationError as exc:
				frappe.db.rollback()
				sonuc[i] = str(exc)
			finally:
				ilk_kilitte.set()
				frappe.destroy()

		iplikler = [threading.Thread(target=bag, args=(i,)) for i in (0, 1)]
		for t in iplikler:
			t.start()
		for t in iplikler:
			t.join(20)
		frappe.db.rollback()  # ana bağlantı güncel veriyi görsün
		return sonuc

	def test_tek_kullanimlik_kupon_bir_kez_gecer(self):
		kod = self._kupon(max_uses=1)
		sonuc = self._paralel(kod, "race-a@test.local", siparis_yaz=False)
		self.assertEqual(sonuc[0], "ok", sonuc)
		self.assertIn("maksimum kullanım", sonuc[1] or "", sonuc)
		self.assertEqual(frappe.db.get_value("Coupon", kod, "used_count"), 1)

	def test_ayni_alici_cok_kullanimlik_kuponu_bir_kez_kullanir(self):
		kod = self._kupon(max_uses=100)
		sonuc = self._paralel(kod, "race-b@test.local", siparis_yaz=True)
		self.assertEqual(sonuc[0], "ok", sonuc)
		self.assertIn("daha önce kullandınız", sonuc[1] or "", sonuc)
		self.assertEqual(frappe.db.get_value("Coupon", kod, "used_count"), 1)
