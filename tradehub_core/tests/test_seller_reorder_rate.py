"""
Satıcı tekrar sipariş oranı (reorder rate) testleri.

    docker exec istocc-dev-backend-1 bench --site tradehub.localhost \
        run-tests --module tradehub_core.tests.test_seller_reorder_rate
"""

import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tasks import _seller_reorder_rate


def _ensure_user(email: str) -> str:
	# Order.buyer bir User Link alanı — sipariş kaydından önce User var olmalı
	# (bkz. listing_review testlerindeki aynı desen: _ensure_user).
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Reorder",
				"last_name": "Buyer",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	return email


class TestSellerReorderRate(FrappeTestCase):
	def setUp(self):
		# autoname = "field:seller_code" — bu alan ignore_mandatory ile atlanamaz,
		# isimlendirme için zorunlu (bkz. listing_review testlerindeki aynı desen).
		self.seller = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": "Reorder Test Satıcı",
				"seller_code": frappe.generate_hash(length=10),
				"company_name": "Reorder Test A.Ş.",
			}
		).insert(ignore_permissions=True, ignore_mandatory=True).name

	def _order(self, buyer, status="Tamamlandı", days_ago=10, refund_status=None):
		_ensure_user(buyer)
		doc = frappe.get_doc(
			{
				"doctype": "Order",
				"buyer": buyer,
				"seller": self.seller,
				"status": status,
				"order_date": datetime.datetime.now() - datetime.timedelta(days=days_ago),
				"refund_status": refund_status,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)
		return doc.name

	def test_alici_sayisi_esikten_azsa_none_doner(self):
		for i in range(4):
			self._order(f"buyer{i}@test.local")
		self.assertIsNone(_seller_reorder_rate(self.seller))

	def test_tekrar_eden_alici_orani_hesaplanir(self):
		# 5 benzersiz alıcı, 2'si iki kez sipariş vermiş → %40
		for i in range(5):
			self._order(f"rb{i}@test.local")
		self._order("rb0@test.local")
		self._order("rb1@test.local")
		self.assertEqual(_seller_reorder_rate(self.seller), 40.0)

	def test_satilmamis_statuler_sayilmaz(self):
		for i in range(5):
			self._order(f"st{i}@test.local")
		# Bu ikinci sipariş "Ödeme Bekleniyor" — tekrar sayılmamalı
		self._order("st0@test.local", status="Ödeme Bekleniyor")
		self.assertEqual(_seller_reorder_rate(self.seller), 0.0)

	def test_iadesi_onaylanan_siparis_haric(self):
		for i in range(5):
			self._order(f"rf{i}@test.local")
		self._order("rf0@test.local", refund_status="Approved")
		self.assertEqual(_seller_reorder_rate(self.seller), 0.0)

	def test_12_aydan_eski_siparis_haric(self):
		for i in range(5):
			self._order(f"old{i}@test.local")
		self._order("old0@test.local", days_ago=400)
		self.assertEqual(_seller_reorder_rate(self.seller), 0.0)
