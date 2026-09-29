"""MOGEM-685 Bulgu 1 / Adım C — Ürün API'sinin iki ölçülmüş kusuru (gerçek HTTP, 28 Eyl 2026).

C1 · Gövde kimlikten ÖNCE doğrulanıyordu: jetonsuz ziyaretçi bozuk gövdeyle 401 yerine
     417 + doğrulama mesajı alıyordu.
C2 · Kılavuzun "paket ya da mağaza durumu → 403" sözü HTTP'de tutmuyordu: kimlik kancası
     (`authenticate_catalog_bearer`) zincirin HER hatasını yutuyor, Frappe validate_auth
     mesajsız 401 dönüyordu. `test_mogem665_a_kimlik` ucu süreç içinde çağırdığı için 403
     görüyor ve bunu yakalamıyordu — buradaki testler KANCAYI sınar.

    bench --site dev.localhost run-tests --module tradehub_core.tests.test_mogem685_katalog
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam

YOL = "/api/method/tradehub_core.api.v1.catalog.changes"


class TestKancaYetkiHatasi(Mogem665Ortam, FrappeTestCase):
	"""C2 — geçerli jeton + yetki yok → kanca 403'ü (PermissionError) MESAJIYLA yükseltir."""

	def _kanca(self, token: str) -> None:
		from tradehub_core.api.v1._catalog_auth import authenticate_catalog_bearer

		with self.bearer(token):
			frappe.local.request.path = YOL
			authenticate_catalog_bearer()

	def _yetki_hatasi(self, token: str) -> str:
		frappe.clear_messages()
		with self.assertRaises(frappe.PermissionError) as ctx:
			self._kanca(token)
		self.assertEqual(frappe.session.user, "Administrator", "oturum geri dönmedi")
		return str(ctx.exception)

	def test_magazasiz_uygulama_403_ve_sebep(self):
		self._seller("m685bagsiz")
		_app, cid, sec = self._api_app(None)
		mesaj = self._yetki_hatasi(self._token(cid, sec))
		self.assertIn("mağaza", mesaj.lower())

	def test_pasif_magaza_403_ve_sebep(self):
		b = self._api_baglantisi("m685pasif")
		frappe.db.set_value("Admin Seller Profile", b["seller"], "status", "Suspended")
		frappe.db.commit()
		self.assertIn("Suspended", self._yetki_hatasi(b["token"]))

	def test_api_erisimi_olmayan_paket_403(self):
		b = self._api_baglantisi("m685free", plan="free")
		self._yetki_hatasi(b["token"])

	def test_kimlik_hatasi_hala_sessizce_yutulur(self):
		# Kapsam: yalnız YETKİ hatası yükselir; bozuk/kapalı jeton eskisi gibi 401'e düşer.
		b = self._api_baglantisi("m685kimlik")
		frappe.db.set_value("API Application", b["app"], "is_active", 0)
		frappe.db.commit()
		for tok in ("bozuk.jeton.x", b["token"]):
			with self.subTest(tok=tok[:12]):
				self._kanca(tok)  # fırlatmaz

	def test_gecerli_jeton_oturum_kurar(self):
		b = self._api_baglantisi("m685gecer")
		from tradehub_core.api.v1._catalog_auth import authenticate_catalog_bearer

		with self.bearer(b["token"]):
			frappe.local.request.path = YOL
			authenticate_catalog_bearer()
			self.assertEqual(frappe.session.user, b["user"])


class TestGovdeKimliktenSonra(Mogem665Ortam, FrappeTestCase):
	"""C1 — jetonsuz istekte bozuk gövde doğrulama mesajı değil kimlik hatası alır."""

	def test_jetonsuz_bozuk_govde_kimlik_hatasi_alir(self):
		from tradehub_core.api.v1 import catalog

		for ad, cagri in (
			("upsert_products", lambda: catalog.upsert_products(products="bozuk")),
			("upsert_products bos", lambda: catalog.upsert_products(products="[]")),
			("update_stock", lambda: catalog.update_stock(items="bozuk")),
		):
			with self.subTest(ad), self.misafir_istek({}), self.assertRaises(frappe.AuthenticationError):
				cagri()

	def test_gecerli_jetonla_bozuk_govde_yine_dogrulama_hatasi(self):
		# Pozitif kontrol: kimlik geçince gövde doğrulaması hâlâ çalışıyor (417).
		from tradehub_core.api.v1 import catalog

		b = self._api_baglantisi("m685govde")
		with self.bearer(b["token"]), self.assertRaises(frappe.ValidationError):
			catalog.update_stock(items="bozuk")
