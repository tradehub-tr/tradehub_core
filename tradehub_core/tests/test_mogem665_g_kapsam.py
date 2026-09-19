"""MOGEM-665 · kapsam genişletme — test türleri: JWT kurcalama/süre dolumu, sır sızıntısı,
hata enjeksiyonu (Redis), migrasyon idempotency, unicode/kodlama, bozuk girdi, kanca/cron
kaydı, yetki matrisi, webhook zaman aşımı, atomiklik (satır geri sarma)."""

from __future__ import annotations

import http.server
import json
import threading
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam

BASLIK = "Kapsam ürünü — kategori, marka ve öne çıkan özelliğiyle betimlenmiş uzun başlık"
ACIKLAMA = (
	"<p>"
	+ ("Toptan satış için uygun ürün; malzeme, ölçü ve kullanım alanı bilgileri ayrıntılı verilir. " * 2)
	+ "</p>"
)


def _urun(sku, **ek):
	p = {"sku": sku, "title": BASLIK, "description": ACIKLAMA, "list_price": 100}
	p.update(ek)
	return p


class TestJwtKurcalama(Mogem665Ortam, FrappeTestCase):
	def _payload(self, token):
		from tradehub_core.api.mobile_api import _b64u_decode

		return json.loads(_b64u_decode(token.split(".")[1]))

	def test_yuku_degistirilmis_jeton_imza_hatasi(self):
		from tradehub_core.api.mobile_api import _b64u
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("jwt1", scopes=("catalog:read",))
		h, p, s = b["token"].split(".")
		yuk = self._payload(b["token"])
		yuk["scopes"] = ["catalog:write", "stock:write", "catalog:read"]  # yetki alanı eklemeye çalış
		sahte = f"{h}.{_b64u(json.dumps(yuk).encode())}.{s}"
		with self.bearer(sahte), self.assertRaises(frappe.AuthenticationError):
			with catalog_context("catalog:write"):
				pass

	def test_suresi_dolmus_jeton(self):
		from tradehub_core.api.mobile_api import _encode_jwt
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("jwt2")
		yuk = self._payload(b["token"])
		yuk["exp"] = int(time.time()) - 5
		with self.bearer(_encode_jwt(yuk)), self.assertRaises(frappe.AuthenticationError):
			with catalog_context("catalog:read"):
				pass

	def test_mobil_jeton_katalogda_gecmez(self):
		"""Aynı sırla imzalanmış ama tipi farklı (mobil erişim) jeton reddedilir."""
		from tradehub_core.api.mobile_api import _encode_jwt
		from tradehub_core.api.v1._catalog_auth import catalog_context

		b = self._api_baglantisi("jwt3")
		yuk = self._payload(b["token"])
		yuk["type"] = "access"
		with self.bearer(_encode_jwt(yuk)), self.assertRaises(frappe.AuthenticationError):
			with catalog_context("catalog:read"):
				pass

	def test_baska_uygulamanin_adi_yazilmis_jeton(self):
		"""sub başka uygulamaya çevrilirse imza bozulur — mağaza değiştirme yok."""
		from tradehub_core.api.mobile_api import _b64u
		from tradehub_core.api.v1._catalog_auth import catalog_context

		a = self._api_baglantisi("jwt4a")
		b = self._api_baglantisi("jwt4b")
		h, p, s = a["token"].split(".")
		yuk = self._payload(a["token"])
		yuk["sub"] = b["app"]
		with (
			self.bearer(f"{h}.{_b64u(json.dumps(yuk).encode())}.{s}"),
			self.assertRaises(frappe.AuthenticationError),
		):
			with catalog_context("catalog:read"):
				pass


class TestSirSizintisi(Mogem665Ortam, FrappeTestCase):
	def test_sir_ne_dbde_acik_ne_logda_ne_okuma_ucunda(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import kullanici

		_seller, user = self._seller("sir")
		with kullanici(user):
			c = ci.create_or_rotate_credentials()
			self.addCleanup(lambda: self._drop("API Application", c["app"]))
			ci.set_webhook("", "webhook-sirri-XYZ")
			durum = ci.get_connection()
			olaylar = ci.list_outbound_events()
		sir = c["client_secret"]
		# DB kolonu düz metin taşımaz (Password alanı __Auth'a gider)
		ham = frappe.db.sql(
			"select client_secret, webhook_secret from `tabAPI Application` where name=%s", c["app"]
		)[0]
		self.assertNotIn(sir, [x or "" for x in ham])
		self.assertNotIn("webhook-sirri-XYZ", [x or "" for x in ham])
		# okuma uçlarının hiçbir alanında sır yok
		for govde in (durum, olaylar):
			self.assertNotIn(sir, json.dumps(govde, default=str))
			self.assertNotIn("webhook-sirri-XYZ", json.dumps(govde, default=str))
		# Error Log'a ve mesaj kuyruğuna sızmamış
		self.assertFalse(frappe.db.exists("Error Log", {"error": ["like", f"%{sir}%"]}))
		self.assertNotIn(sir, json.dumps(getattr(frappe.local, "message_log", []) or [], default=str))


class TestHataEnjeksiyonu(Mogem665Ortam, FrappeTestCase):
	def test_redis_dusunce_hiz_siniri_fail_open_ve_loglanir(self):
		from tradehub_core.api.v1 import _catalog_auth

		b = self._api_baglantisi("redis1")
		once = frappe.db.count("Error Log", {"method": "Catalog rate limiter Redis incr failed"})
		with patch.object(frappe.cache(), "incr", side_effect=ConnectionError("redis yok")):
			with self.bearer(b["token"]), _catalog_auth.catalog_context("catalog:read") as ctx:
				self.assertEqual(ctx.seller, b["seller"])
		self.assertGreater(
			frappe.db.count("Error Log", {"method": "Catalog rate limiter Redis incr failed"}), once
		)

	def test_redis_dusunce_kilit_503_500_degil(self):
		from tradehub_core.api.v1 import catalog

		b = self._api_baglantisi("redis2")
		cache = frappe.cache()
		gercek_set = cache.set

		def yalniz_kilit_dusuk(key, *a, **k):  # yalnız kilit anahtarı için Redis "kesik"
			if "catalog_lock" in str(key):
				raise ConnectionError("redis yok")
			return gercek_set(key, *a, **k)

		with patch.object(cache, "set", side_effect=yalniz_kilit_dusuk):
			with self.bearer(b["token"]), self.assertRaises(catalog.CatalogUnavailableError) as cm:
				catalog.update_stock([{"sku": "X", "stock": 1}])
		self.assertEqual(cm.exception.http_status_code, 503)

	def test_webhook_alicisi_10_sn_cevap_vermezse_failed(self):
		from tradehub_core.integration import outbound

		class Yavas(http.server.BaseHTTPRequestHandler):
			def do_POST(self):
				time.sleep(12)
				self.send_response(204)
				self.end_headers()

			def log_message(self, *a):
				pass

		srv = http.server.HTTPServer(("127.0.0.1", 0), Yavas)
		threading.Thread(target=srv.serve_forever, daemon=True).start()
		self.addCleanup(srv.shutdown)
		b = self._api_baglantisi("timeout")
		frappe.db.set_value(
			"API Application", b["app"], "webhook_url", f"http://127.0.0.1:{srv.server_address[1]}/h"
		)
		name = self._listing(b["seller"], "TO-1")
		with patch("frappe.enqueue"):
			ev = outbound.emit_stock_change(name, "reserve")
		self.addCleanup(lambda: self._drop("Catalog Outbound Event", ev))
		t0 = time.time()
		with patch.object(outbound, "validate_feed_url"):
			sonuc = outbound.deliver(ev)
		gecen = time.time() - t0
		self.assertEqual(sonuc["status"], "failed")
		self.assertTrue(9 <= gecen <= 12, f"zaman aşımı ~10 sn olmalı: {gecen:.1f}")
		self.assertIn("timed out", frappe.db.get_value("Catalog Outbound Event", ev, "last_error").lower())


class TestMigrasyonIdempotency(FrappeTestCase):
	def test_patchler_iki_kez_kosar(self):
		from tradehub_core.patches import v15_9_57_seller_sku_benzersiz as p57
		from tradehub_core.patches import v15_9_58_seed_seller_api_nav as p58

		for _ in range(2):
			p57.execute()
			p58.execute()
		idx = frappe.db.sql("show index from tabListing where Key_name='uniq_listing_seller_sku'")
		self.assertEqual({r[4] for r in idx}, {"seller_profile", "seller_sku"})
		self.assertEqual(
			frappe.db.count("TH Module Registry", {"module_key": "seller.products.toplu.api"}), 1
		)


class TestUnicodeVeBozukGirdi(Mogem665Ortam, FrappeTestCase):
	def _upsert(self, b, products):
		from tradehub_core.api.v1.catalog import upsert_products

		with self.bearer(b["token"]):
			cevap = upsert_products(products)
		for r in cevap["results"]:
			if r.get("listing"):
				self.addCleanup(lambda n=r["listing"]: self._drop("Listing", n))
		self.addCleanup(lambda n=cevap["job"]: self._drop("Bulk Import Job", n))
		return cevap

	def test_turkce_ve_unicode_sku_baslik(self):
		b = self._api_baglantisi("uni")
		cevap = self._upsert(
			b,
			[
				_urun("ÇİFT-ürün-ğüşöç-١٢٣"),
				_urun("  boşluklu  ", title=BASLIK + " İıŞşĞğ"),
				_urun("emoji", title=BASLIK + " 😀"),
				_urun("rtl", description=ACIKLAMA + "<p>منتج بالجملة مناسب للتجار</p>"),
			],
		)
		r = {x["sku"]: x for x in cevap["results"]}
		self.assertEqual(r["ÇİFT-ürün-ğüşöç-١٢٣"]["status"], "created")
		self.assertEqual(
			frappe.db.get_value("Listing", r["ÇİFT-ürün-ğüşöç-١٢٣"]["listing"], "seller_sku"),
			"ÇİFT-ürün-ğüşöç-١٢٣",
		)
		self.assertEqual(r["boşluklu"]["status"], "created", "SKU kırpılır")
		self.assertEqual(r["emoji"]["code"], "SEO_TITLE")
		self.assertEqual(r["rtl"]["status"], "created")
		# kırpılmış SKU'yla güncelleme aynı ürünü bulur (büyük/küçük bağımsız)
		cevap = self._upsert(b, [{"sku": "çift-ürün-ğüşöç-١٢٣", "price": 50}])
		self.assertEqual(cevap["results"][0]["status"], "updated")

	def test_bozuk_girdiler_400_sinifi_500_degil(self):
		from tradehub_core.api.v1.catalog import update_stock, upsert_products

		b = self._api_baglantisi("bozuk")
		with self.bearer(b["token"]):
			for govde in ("{", "null", "7", '{"a":1}', [], ""):
				with self.assertRaises(frappe.ValidationError, msg=repr(govde)):
					upsert_products(govde)
			cevap = upsert_products(
				[
					None,
					7,
					"x",
					[],
					{"sku": None},
					{"sku": {"a": 1}},
					{"sku": "x" * 500, "title": BASLIK, "description": ACIKLAMA, "list_price": 1},
				]
			)
			self.addCleanup(lambda n=cevap["job"]: self._drop("Bulk Import Job", n))
			self.assertEqual(cevap["summary"]["rejected"], 7)
			self.assertEqual(
				[r["code"] for r in cevap["results"]][:6],
				[
					"INVALID_PRODUCT",
					"INVALID_PRODUCT",
					"INVALID_PRODUCT",
					"INVALID_PRODUCT",
					"SKU_REQUIRED",
					"SKU_REQUIRED",
				],
			)
			self.assertIn(
				cevap["results"][6]["code"],
				("VALIDATION", "SYSTEM"),
				"500 karakter SKU sunucu doğrulamasında düşer",
			)
			cevap = update_stock(
				[
					{"sku": "X", "stock": float("inf")},
					{"sku": "Y", "stock": 1e308},
					{"sku": "Z", "price": "1e400"},
				]
			)
			self.assertEqual(cevap["summary"]["rejected"], 3)


class TestKancaVeCronKaydi(FrappeTestCase):
	def test_hooks_kayitlari(self):
		hooks = frappe.get_hooks()
		self.assertIn(
			"tradehub_core.integration.outbound.sweep_due", hooks["scheduler_events"]["cron"]["*/5 * * * *"]
		)
		self.assertIn("tradehub_core.api.v1._catalog_auth.authenticate_catalog_bearer", hooks["auth_hooks"])
		self.assertIn(
			"tradehub_core.integration.outbound.on_listing_trash", hooks["doc_events"]["Listing"]["on_trash"]
		)
		self.assertIn(
			"tradehub_core.patches.v15_9_58_seed_seller_api_nav",
			open(frappe.get_app_path("tradehub_core", "patches.txt")).read(),
		)
		self.assertEqual(
			hooks["permission_query_conditions"]["Catalog Outbound Event"],
			["tradehub_core.permissions.catalog_outbound_event_query_conditions"],
		)

	def test_scheduler_kayitli_ve_acik(self):
		self.assertTrue(
			frappe.db.exists(
				"Scheduled Job Type", {"method": "tradehub_core.integration.outbound.sweep_due"}
			),
			"migrate Scheduled Job Type üretmemiş",
		)


class TestYetkiMatrisi(Mogem665Ortam, FrappeTestCase):
	def test_admin_magazasiz_panel_uclarina_giremez(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import gercek_yetki, kullanici

		# Yerel DB'de Administrator bir mağazanın sahibi (prod restore) — mağazasız bir
		# System Manager kullanıcısı kur: admin rolü tek başına panel uçlarını açmaz.
		admin = self._user("sysmgr")
		frappe.get_doc("User", admin).add_roles("System Manager")
		frappe.db.commit()
		with gercek_yetki(), kullanici(admin), self.assertRaises(frappe.PermissionError):
			ci.get_connection()

	def test_pasif_magaza_sahibi_panelden_baglanti_kuramaz(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import gercek_yetki, kullanici

		seller, user = self._seller("pasif")
		frappe.db.set_value("Admin Seller Profile", seller, "status", "Suspended")
		frappe.db.commit()
		with gercek_yetki(), kullanici(user), self.assertRaises(frappe.PermissionError):
			ci.create_or_rotate_credentials()


class TestAtomiklik(Mogem665Ortam, FrappeTestCase):
	def test_reddedilen_satir_arkasinda_kayit_birakmaz(self):
		"""Görsel indirme başarılı, ürün ekleme kotada düşüyor → savepoint geri sarar; File kalmaz."""
		from tradehub_core.api.v1 import catalog

		b = self._api_baglantisi("atom", plan="pro", kota={"quota.max_products": 1})
		self._listing(b["seller"], "AT-0")

		def sahte_indir(urls, seller_profile, warnings=None):
			import io

			from PIL import Image

			buf = io.BytesIO()
			Image.new("RGB", (1, 1)).save(buf, "PNG")  # gerçek PNG — Frappe EXIF soyarken PIL ile açar
			f = frappe.get_doc(
				{"doctype": "File", "file_name": "atom-x.png", "is_private": 1, "content": buf.getvalue()}
			).insert(ignore_permissions=True)
			return [f.file_url]

		once = frappe.db.count("File", {"file_name": "atom-x.png"})
		with patch.object(catalog.image_url_ingest, "ingest_image_urls", side_effect=sahte_indir):
			with self.bearer(b["token"]):
				cevap = catalog.upsert_products([_urun("AT-1", images=["https://cdn.x/a.jpg"])])
		self.addCleanup(lambda n=cevap["job"]: self._drop("Bulk Import Job", n))
		self.assertEqual(cevap["results"][0]["code"], "QUOTA_EXCEEDED")
		self.assertEqual(
			frappe.db.count("File", {"file_name": "atom-x.png"}),
			once,
			"satır geri sarılmadı; görsel File'ı kaldı",
		)
		self.assertFalse(frappe.db.exists("Listing", {"seller_profile": b["seller"], "seller_sku": "AT-1"}))
