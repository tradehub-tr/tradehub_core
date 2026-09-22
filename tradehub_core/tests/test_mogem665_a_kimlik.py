"""MOGEM-665 · 2. Aşama — satıcının kendi mağazasına güvenli bağlantı kurması.

Kabul kriterleri (görev metni):
- Yetkisi olmayan kişi veya program ürün ekleyemez, değiştiremez ve mağazanın
  stok değişikliklerini göremez.
- Bir mağazanın bağlantı bilgileri başka mağazanın ürünlerini etkilemez.
- Eklenen ürün doğru satıcıya ait görünür; satıcının paketindeki ürün sayısı ve
  özellik sınırları korunur.

Plan K2: mevcut OAuth2 client-credentials jetonu + `API Application` → mağaza bağı;
jeton doğrulanınca istek mağaza sahibinin kullanıcısı olarak koşar (`frappe.set_user`).
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam


class TestJetonVeYetkiAlani(Mogem665Ortam, FrappeTestCase):
	def test_bearer_yoksa_reddedilir(self):
		from tradehub_core.api.v1._catalog_auth import catalog_context

		with self.misafir_istek({}), self.assertRaises(frappe.AuthenticationError):
			with catalog_context("catalog:write"):
				pass

	def test_yanlis_sema_reddedilir(self):
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("sema")
		with (
			self.misafir_istek({"Authorization": "Basic " + b["token"]}),
			self.assertRaises(frappe.AuthenticationError),
		):
			with catalog_context("catalog:write"):
				pass

	def test_bozuk_jeton_reddedilir(self):
		from tradehub_core.api.v1._catalog_auth import catalog_context

		with self.bearer("bu.bir.jeton-degil"), self.assertRaises(frappe.AuthenticationError):
			with catalog_context("catalog:write"):
				pass

	def test_yetki_alani_eksik_jeton_reddedilir(self):
		"""Plan §08·1: yetki alanı eksik jeton da reddedilir."""
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("scope", scopes=("catalog:read",))
		with self.bearer(b["token"]), self.assertRaises(frappe.PermissionError):
			with catalog_context("catalog:write"):
				pass
		with self.bearer(b["token"]):
			with catalog_context("catalog:read") as ctx:
				self.assertEqual(ctx.seller, b["seller"])

	def test_magazaya_bagli_olmayan_uygulama_katalog_yazamaz(self):
		from tradehub_core.api.v1._catalog_auth import catalog_context

		self._seller("bagsiz")
		app, cid, sec = self._api_app(None)
		tok = self._token(cid, sec)
		with self.bearer(tok), self.assertRaises(frappe.PermissionError):
			with catalog_context("catalog:write"):
				pass

	def test_pasif_uygulamanin_gecerli_jetonu_reddedilir(self):
		"""Jeton 24 saat geçerli; uygulama kapatılınca jeton anında ölmeli."""
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("pasif")
		frappe.db.set_value("API Application", b["app"], "is_active", 0)
		frappe.db.commit()
		with self.bearer(b["token"]), self.assertRaises(frappe.AuthenticationError):
			with catalog_context("catalog:write"):
				pass


class TestOturumDevri(Mogem665Ortam, FrappeTestCase):
	def test_istek_magaza_sahibi_olarak_kosar_ve_sonra_geri_doner(self):
		"""Plan §08·3: API ile oluşturulan ürünün sahibi mağaza sahibidir, Guest değil."""
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("devir")
		with self.bearer(b["token"]):
			self.assertEqual(frappe.session.user, "Guest")
			with catalog_context("catalog:write") as ctx:
				self.assertEqual(frappe.session.user, b["user"])
				self.assertEqual(ctx.seller, b["seller"])
				self.assertEqual(ctx.app, b["app"])
			self.assertEqual(frappe.session.user, "Guest", "bağlam çıkışında oturum geri dönmedi")

	def test_hata_olsa_da_oturum_geri_doner(self):
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("devir2")
		with self.bearer(b["token"]):
			with self.assertRaises(RuntimeError):
				with catalog_context("catalog:write"):
					raise RuntimeError("iş mantığı patladı")
			self.assertEqual(frappe.session.user, "Guest")

	def test_iki_magazanin_baglamlari_karismaz(self):
		from tradehub_core.api.v1._catalog_auth import catalog_context

		a = self._api_baglantisi("ma")
		b = self._api_baglantisi("mb")
		with self.bearer(a["token"]), catalog_context("catalog:write") as ctx:
			self.assertEqual((ctx.seller, frappe.session.user), (a["seller"], a["user"]))
		with self.bearer(b["token"]), catalog_context("catalog:write") as ctx:
			self.assertEqual((ctx.seller, frappe.session.user), (b["seller"], b["user"]))

	def test_pasif_magaza_reddedilir(self):
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("pasifmagaza")
		frappe.db.set_value("Admin Seller Profile", b["seller"], "status", "Suspended")
		frappe.db.commit()
		with self.bearer(b["token"]), self.assertRaises(frappe.PermissionError):
			with catalog_context("catalog:write"):
				pass


class TestPaketKapisi(Mogem665Ortam, FrappeTestCase):
	def test_free_paket_api_erisimi_yok(self):
		"""Plan tablosu: free → feature.api.access = false → 403 (plan adı mesajda)."""
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("free", plan="free")
		with self.bearer(b["token"]), self.assertRaises(frappe.PermissionError):
			with catalog_context("catalog:read"):
				pass

	def test_free_paket_panelden_baglanti_kuramaz(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import kullanici

		_seller, user = self._seller("freepanel", plan="free")
		with kullanici(user):
			durum = ci.get_connection()
			self.assertFalse(durum["features"]["api_access"])
			with self.assertRaises(frappe.PermissionError):
				ci.create_or_rotate_credentials()

	def test_pro_paket_kotasi_hiz_sinirini_belirler(self):
		"""quota.api_rate_limit (pro=60) katman tablosunun önüne geçer."""
		from tradehub_core.api.v1 import _catalog_auth

		seller, _user = self._seller("prokota", plan="pro")
		self.assertEqual(_catalog_auth.effective_rate_limit(seller, "enterprise")["max_calls"], 60)
		seller2, _user2 = self._seller("ozelkota", plan="pro", kota={"quota.api_rate_limit": 7})
		self.assertEqual(_catalog_auth.effective_rate_limit(seller2, "enterprise")["max_calls"], 7)


class TestHizSiniri(Mogem665Ortam, FrappeTestCase):
	def test_paket_kotasina_gore_hiz_siniri_uygulanir(self):
		from tradehub_core.api.rate_limit import TooManyRequestsError
		from tradehub_core.api.v1 import _catalog_auth

		b = self._api_baglantisi("hiz", plan="pro", kota={"quota.api_rate_limit": 5})
		_catalog_auth.reset_rate_limit(b["app"])
		limit = 5
		with self.bearer(b["token"]):
			for _ in range(limit):
				with _catalog_auth.catalog_context("catalog:read"):
					pass
			with self.assertRaises(TooManyRequestsError):
				with _catalog_auth.catalog_context("catalog:read"):
					pass
		_catalog_auth.reset_rate_limit(b["app"])


class TestPanelBaglantiYonetimi(Mogem665Ortam, FrappeTestCase):
	"""Satıcı bağlantı bilgilerini panelden yönetir: oluştur/yenile/webhook/kapat."""

	def test_magaza_sahibi_bilgi_olusturur_ve_sir_yalniz_bir_kez_gorunur(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import kullanici

		seller, user = self._seller("panel1")
		with kullanici(user):
			sonuc = ci.create_or_rotate_credentials()
			self.assertTrue(sonuc["client_id"])
			self.assertTrue(sonuc["client_secret"], "sır oluşturmada bir kez dönmeli")
			durum = ci.get_connection()
			self.assertEqual(durum["client_id"], sonuc["client_id"])
			self.assertTrue(durum["has_secret"])
			self.assertNotIn("client_secret", durum, "sır tekrar okunamaz")
			self.assertEqual(set(durum["scopes"]), {"catalog:write", "stock:write", "catalog:read"})
		self.addCleanup(lambda: self._drop("API Application", sonuc["app"]))
		# Jeton gerçekten çalışıyor
		tok = self._token(sonuc["client_id"], sonuc["client_secret"])
		from tradehub_core.api.v1._catalog_auth import catalog_context

		with self.bearer(tok), catalog_context("catalog:write") as ctx:
			self.assertEqual(ctx.seller, seller)

	def test_yenileme_eski_sirri_gecersiz_kilar(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.api.v1.public_api import token
		from tradehub_core.tests.mogem620_ortak import kullanici

		_seller, user = self._seller("panel2")
		with kullanici(user):
			ilk = ci.create_or_rotate_credentials()
			ikinci = ci.create_or_rotate_credentials()
		self.addCleanup(lambda: self._drop("API Application", ilk["app"]))
		self.assertEqual(ilk["client_id"], ikinci["client_id"], "yenileme client_id'yi değiştirmez")
		self.assertNotEqual(ilk["client_secret"], ikinci["client_secret"])
		with self.misafir_istek({}), self.assertRaises(frappe.AuthenticationError):
			token("client_credentials", ilk["client_id"], ilk["client_secret"])
		self._token(ikinci["client_id"], ikinci["client_secret"])  # yenisi çalışır

	def test_baska_magazanin_sahibi_bilgileri_goremez_degistiremez(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import kullanici

		_s1, u1 = self._seller("panel3a")
		_s2, u2 = self._seller("panel3b")
		with kullanici(u1):
			a = ci.create_or_rotate_credentials()
		self.addCleanup(lambda: self._drop("API Application", a["app"]))
		with kullanici(u2):
			self.assertIsNone(ci.get_connection()["client_id"], "başka mağazanın bağlantısı göründü")
			b = ci.create_or_rotate_credentials()
		self.addCleanup(lambda: self._drop("API Application", b["app"]))
		self.assertNotEqual(a["client_id"], b["client_id"])

	def test_misafir_ve_yetkisiz_kullanici_baglanti_kuramaz(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import gercek_yetki, kullanici

		with (
			gercek_yetki(),
			kullanici("Guest"),
			self.assertRaises((frappe.PermissionError, frappe.AuthenticationError)),
		):
			ci.create_or_rotate_credentials()
		yalniz_kullanici = self._user("magazasiz")
		with gercek_yetki(), kullanici(yalniz_kullanici), self.assertRaises(frappe.PermissionError):
			ci.create_or_rotate_credentials()

	def test_webhook_adresi_dogrulanir_ve_kaydedilir(self):
		import socket
		from unittest.mock import patch

		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import kullanici

		gercek = socket.getaddrinfo

		def dns(host, port, *a, **k):
			# Konteynerde dış DNS yok: yalnız örnek ERP alan adını genel bir IP'ye çöz,
			# IP hazır adresler (127.0.0.1) gerçek çözümleyiciden geçsin ki SSRF reddi sınansın.
			if host == "erp.example.com":
				return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))]
			return gercek(host, port, *a, **k)

		_seller, user = self._seller("panel4")
		with kullanici(user), patch("tradehub_core.bulk_import.feed_security.socket.getaddrinfo", dns):
			a = ci.create_or_rotate_credentials()
			self.addCleanup(lambda: self._drop("API Application", a["app"]))
			with self.assertRaises(frappe.ValidationError):
				ci.set_webhook("http://127.0.0.1:9/ic-ag", "s")  # SSRF: yerel adres
			with self.assertRaises(frappe.ValidationError):
				ci.set_webhook("ftp://example.com/x", "s")
			sonuc = ci.set_webhook("https://erp.example.com/istoc/stok", "cok-gizli")
			self.assertTrue(sonuc["ok"])
			durum = ci.get_connection()
			self.assertEqual(durum["webhook_url"], "https://erp.example.com/istoc/stok")
			self.assertTrue(durum["has_webhook_secret"])
			self.assertNotIn("webhook_secret", durum)

	def test_kapatma_jetonu_anında_gecersiz_kilar(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.api.v1._catalog_auth import catalog_context
		from tradehub_core.tests.mogem620_ortak import kullanici

		_seller, user = self._seller("panel5")
		with kullanici(user):
			a = ci.create_or_rotate_credentials()
			self.addCleanup(lambda: self._drop("API Application", a["app"]))
		tok = self._token(a["client_id"], a["client_secret"])
		with kullanici(user):
			ci.revoke_credentials()
		with self.bearer(tok), self.assertRaises(frappe.AuthenticationError):
			with catalog_context("catalog:write"):
				pass


class TestAuthKancasi(Mogem665Ortam, FrappeTestCase):
	"""Gerçek HTTP'de validate_auth 401 kesmesin: kanca yalnız catalog.* yolunda oturum kurar."""

	def _yol_ile(self, headers: dict, path: str):
		from contextlib import contextmanager

		@contextmanager
		def _cm():
			with self.misafir_istek(headers):
				frappe.local.request.path = path
				yield

		return _cm()

	def test_catalog_yolunda_gecerli_jeton_oturum_kurar(self):
		from tradehub_core.api.v1._catalog_auth import authenticate_catalog_bearer

		b = self._api_baglantisi("kanca")
		with self._yol_ile(
			{"Authorization": f"Bearer {b['token']}"}, "/api/method/tradehub_core.api.v1.catalog.update_stock"
		):
			authenticate_catalog_bearer()
			self.assertEqual(frappe.session.user, b["user"])

	def test_baska_yolda_jeton_oturum_kurmaz(self):
		"""Jeton başka uçlara (örn. frappe.client.get_list) mağaza sahibi yetkisi vermez."""
		from tradehub_core.api.v1._catalog_auth import authenticate_catalog_bearer

		b = self._api_baglantisi("kanca2")
		for yol in (
			"/api/method/frappe.client.get_list",
			"/api/resource/Listing",
			"/api/method/tradehub_core.api.v1.catalogx",
		):
			with self._yol_ile({"Authorization": f"Bearer {b['token']}"}, yol):
				authenticate_catalog_bearer()
				self.assertEqual(frappe.session.user, "Guest", yol)

	def test_bozuk_veya_pasif_jeton_oturum_kurmaz_ve_mesaj_birakmaz(self):
		from tradehub_core.api.v1._catalog_auth import authenticate_catalog_bearer

		b = self._api_baglantisi("kanca3")
		frappe.db.set_value("API Application", b["app"], "is_active", 0)
		frappe.db.commit()
		yol = "/api/method/tradehub_core.api.v1.catalog.changes"
		for tok in ("bozuk.jeton", b["token"]):
			with self._yol_ile({"Authorization": f"Bearer {tok}"}, yol):
				n = len(getattr(frappe.local, "message_log", None) or [])
				authenticate_catalog_bearer()
				self.assertEqual(frappe.session.user, "Guest")
				self.assertEqual(
					len(getattr(frappe.local, "message_log", None) or []), n, "mesaj kuyruğu kirlendi"
				)

	def test_kanca_istek_govdesini_korur(self):
		"""frappe.set_user form_dict'i sıfırlar; kanca gövdeyi (`items`) geri koymalı."""
		from tradehub_core.api.v1._catalog_auth import authenticate_catalog_bearer

		b = self._api_baglantisi("kanca4")
		with self._yol_ile(
			{"Authorization": f"Bearer {b['token']}"}, "/api/method/tradehub_core.api.v1.catalog.update_stock"
		):
			frappe.local.form_dict = frappe._dict(items=[{"sku": "X", "stock": 1}], cmd="x")
			authenticate_catalog_bearer()
			self.assertEqual(frappe.session.user, b["user"])
			self.assertEqual(
				frappe.local.form_dict.get("items"), [{"sku": "X", "stock": 1}], "gövde kayboldu"
			)

	def test_kanca_hooks_te_kayitli(self):
		self.assertIn(
			"tradehub_core.api.v1._catalog_auth.authenticate_catalog_bearer", frappe.get_hooks("auth_hooks")
		)
