"""MOGEM-665 · 1. Aşama — aktarım başlamadan kapatılan kusurlar (plan §05).

Kabul kriterleri (görev metni, kelimesi kelimesine):
- Aynı mağazada aynı stok koduyla iki ayrı ürün oluşmaz; farklı mağazalar aynı
  kodu kullanabilir.
- Metre, ton, kutu, çift ve saat gibi birimler gönderildiği biçimde doğru
  kaydedilir; metre olarak gönderilen ürün adet olarak görünmez.
- Renk/beden seçilmiş bir ürün sepete eklenirken o seçeneğin gerçek stoğu
  dikkate alınır.
- API aktarımı sırf dosya yüklemesi devam ediyor diye her durumda engellenmez.
  Yoğunluk ve dosya boyutu uyarıları gerçek sınırı doğru açıklar.

Önce yazıldı (kırmızı), sonra kod (yeşil): her test bugünkü kodda düşen bir
davranışı sabitler.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam


class TestSellerSkuBenzersiz(Mogem665Ortam, FrappeTestCase):
	def test_ayni_magazada_ayni_stok_kodu_ikinci_kez_acilamaz(self):
		seller, _ = self._seller("sku1")
		self._listing(seller, sku="ABC-100")
		with self.assertRaises(
			(frappe.ValidationError, frappe.DuplicateEntryError, frappe.UniqueValidationError)
		):
			self._listing(seller, sku="ABC-100")
		frappe.db.rollback()
		self.assertEqual(frappe.db.count("Listing", {"seller_profile": seller, "seller_sku": "ABC-100"}), 1)

	def test_bosluk_ve_buyuk_kucuk_farki_ayni_kod_sayilir(self):
		"""'abc-100 ' ile 'ABC-100' aynı stok kodudur — satıcı programları tutarsız yazar."""
		seller, _ = self._seller("sku2")
		self._listing(seller, sku="ABC-100")
		with self.assertRaises(
			(frappe.ValidationError, frappe.DuplicateEntryError, frappe.UniqueValidationError)
		):
			self._listing(seller, sku=" abc-100 ")
		frappe.db.rollback()

	def test_farkli_magazalar_ayni_kodu_kullanabilir(self):
		s1, _ = self._seller("sku3a")
		s2, _ = self._seller("sku3b")
		a = self._listing(s1, sku="ORTAK-1")
		b = self._listing(s2, sku="ORTAK-1")
		self.assertNotEqual(a, b)

	def test_stok_kodu_olmayan_urunler_birbirini_engellemez(self):
		seller, _ = self._seller("sku4")
		self._listing(seller, sku=None)
		self._listing(seller, sku="")
		self._listing(seller, sku=None)
		self.assertEqual(frappe.db.count("Listing", {"seller_profile": seller}), 3)

	def test_veritabani_seviyesinde_bilesik_benzersiz_indeks_var(self):
		"""Plan §08·11: 'veritabanı seviyesinde engellenir' — Python doğrulaması atlansa da."""
		rows = frappe.db.sql(
			"""SELECT INDEX_NAME, NON_UNIQUE, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) cols
			   FROM information_schema.STATISTICS
			   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tabListing'
			   GROUP BY INDEX_NAME, NON_UNIQUE""",
			as_dict=True,
		)
		benzersiz = [r for r in rows if not r.NON_UNIQUE and r.cols == "seller_profile,seller_sku"]
		self.assertTrue(benzersiz, "(seller_profile, seller_sku) benzersiz indeksi yok")


class TestBirimCevirisi(FrappeTestCase):
	"""DB'deki birimler Türkçe (localize_uom_tr): Adet, Metre, Ton, Kutu, Çift, Saat…"""

	def test_turkce_birimler_gonderildigi_gibi_cozulur(self):
		from tradehub_core.bulk_import import persister

		beklenen = {
			"metre": "Metre",
			"Metre": "Metre",
			"m": "Metre",
			"ton": "Ton",
			"kutu": "Kutu",
			"koli": "Kutu",
			"paket": "Kutu",
			"çift": "Çift",
			"saat": "Saat",
			"adet": "Adet",
			"Adet": "Adet",
			"pcs": "Adet",
			"kg": "Kg",
			"gram": "Gram",
			"litre": "Litre",
			"cm": "Santimetre",
			"mm": "Milimetre",
			"m2": "Metrekare",
			"m3": "Metreküp",
			"gün": "Gün",
		}
		for ham, dogru in beklenen.items():
			with self.subTest(birim=ham):
				self.assertEqual(persister._resolve_link("UOM", ham), dogru)

	def test_ham_deger_db_adiyla_birebir_eslesiyorsa_alias_tablosu_atlanir(self):
		from tradehub_core.bulk_import import persister

		# "Ton" hem DB adı hem alias tablosu girdisi; ikisi de aynı yere çıkmalı.
		self.assertEqual(persister._resolve_link("UOM", "Ton"), "Ton")

	def test_metre_olarak_gonderilen_urun_adet_olarak_kaydedilmez(self):
		from tradehub_core.bulk_import import persister

		coerced = persister._coerce_row({"stock_uom": "metre"})
		self.assertEqual(coerced.get("stock_uom"), "Metre")


class TestSepetVaryantStogu(Mogem665Ortam, FrappeTestCase):
	def _varyantli(self):
		seller, _ = self._seller("var")
		name = self._listing(
			seller,
			sku="VAR-1",
			stock_qty=100,
			has_variants=1,
			variant_items=[
				{
					"attribute_type": "Beden",
					"attribute_value": "S",
					"variant_sku": "VAR-1-S",
					"variant_stock": 2,
					"variant_price": 90,
					"is_default": 1,
				},
				{
					"attribute_type": "Beden",
					"attribute_value": "M",
					"variant_sku": "VAR-1-M",
					"variant_stock": 0,
					"variant_price": 90,
				},
			],
		)
		doc = frappe.get_doc("Listing", name)
		return doc, {r.attribute_value: r.name for r in doc.variant_items}

	def test_varyant_satiri_ile_stok_kontrolu_o_varyantin_stogunu_kullanir(self):
		from tradehub_core.api import cart

		doc, satirlar = self._varyantli()
		# S bedeninden 2 var: 2 geçer, 3 düşer (ürün seviyesinde 100 olsa da).
		cart._check_stock(doc, doc.name, satirlar["S"], 2)
		with self.assertRaises(frappe.ValidationError):
			cart._check_stock(doc, doc.name, satirlar["S"], 3)

	def test_stogu_sifir_varyant_urun_stogu_yuz_olsa_da_eklenemez(self):
		from tradehub_core.api import cart

		doc, satirlar = self._varyantli()
		with self.assertRaises(frappe.ValidationError):
			cart._check_stock(doc, doc.name, satirlar["M"], 1)

	def test_etiketle_gelen_varyant_da_ayni_sonucu_verir(self):
		"""Storefront varyantı 'Beden: S' etiketiyle gönderir — iki yol tutarlı olmalı."""
		from tradehub_core.api import cart

		doc, _ = self._varyantli()
		cart._check_stock(doc, doc.name, None, 2, variant_label="Beden: S")
		with self.assertRaises(frappe.ValidationError):
			cart._check_stock(doc, doc.name, None, 3, variant_label="Beden: S")


class TestVaryantStoguTekDusum(Mogem665Ortam, FrappeTestCase):
	"""Rezerve + düşüm aynı varyantı iki kez eritiyordu (keşifte bulunan B15)."""

	def test_rezerve_ve_dusum_varyant_stogunu_bir_kez_azaltir(self):
		from unittest import mock

		from tradehub_core.utils import stock

		seller, _ = self._seller("dusum")
		name = self._listing(
			seller,
			sku="DUS-1",
			stock_qty=10,
			has_variants=1,
			variant_items=[
				{
					"attribute_type": "Beden",
					"attribute_value": "S",
					"variant_sku": "DUS-1-S",
					"variant_stock": 5,
					"variant_price": 90,
					"is_default": 1,
				},
			],
		)
		kalemler = [frappe._dict(listing=name, quantity=2, variation="Beden: S", listing_title="x")]
		gercek_get_all = frappe.get_all

		def sahte_get_all(doctype, *a, **k):
			# Yalnız sipariş kalemleri sahte; varyant satırı araması gerçek DB'ye gider.
			return kalemler if doctype == "Order Item" else gercek_get_all(doctype, *a, **k)

		with mock.patch.object(frappe, "get_all", side_effect=sahte_get_all):
			stock.reserve_stock_for_order("M665-SAHTE-SIPARIS")
			stock.deduct_stock_for_order("M665-SAHTE-SIPARIS")
		frappe.db.commit()
		row = frappe.db.get_value(
			"Listing Variant Item", {"parent": name, "variant_sku": "DUS-1-S"}, "variant_stock"
		)
		self.assertEqual(float(row), 3.0, "varyant stoğu 5 → 3 olmalı (bir kez düşüm), iki kez düşseydi 1")
		self.assertEqual(float(frappe.db.get_value("Listing", name, "stock_qty")), 8.0)


class TestCokluVaryantKapisi(FrappeTestCase):
	def test_variant_items_alani_okunuyor(self):
		from tradehub_core.entitlement.checks import _is_variant_listing

		doc = frappe._dict(variant_items=[{"attribute_value": "S"}, {"attribute_value": "M"}], has_variants=1)
		self.assertTrue(_is_variant_listing(doc))
		self.assertFalse(_is_variant_listing(frappe._dict(variant_items=[], has_variants=0)))


class TestIsKilidiVeMesajlar(Mogem665Ortam, FrappeTestCase):
	def _is(self, seller: str, source: str, status: str = "Running") -> str:
		job = frappe.get_doc(
			{
				"doctype": "Bulk Import Job",
				"seller_profile": seller,
				"source": source,
				"data_file": "/private/files/m665-sahte.json"
				if source == "api"
				else "/private/files/m665-sahte.xlsx",
				"file_format": "json" if source == "api" else "xlsx",
				"update_mode": "upsert",
				"status": status,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Bulk Import Job", job.name))
		return job.name

	def test_devam_eden_api_aktarimi_dosya_yuklemesini_engellemez(self):
		from tradehub_core.bulk_import import api

		seller, _ = self._seller("kilit1")
		self._is(seller, "api")
		api._assert_no_active_file_import(seller)  # fırlatmamalı

	def test_devam_eden_dosya_yuklemesi_ikinci_dosya_yuklemesini_engeller(self):
		from tradehub_core.bulk_import import api

		seller, _ = self._seller("kilit2")
		self._is(seller, "file")
		with self.assertRaises(frappe.ValidationError):
			api._assert_no_active_file_import(seller)

	def test_bulk_import_job_source_alani_var_ve_varsayilan_file(self):
		seller, _ = self._seller("kilit3")
		job = frappe.get_doc(
			{
				"doctype": "Bulk Import Job",
				"seller_profile": seller,
				"data_file": "/private/files/m665-sahte.xlsx",
				"file_format": "xlsx",
				"status": "Queued",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._drop("Bulk Import Job", job.name))
		self.assertEqual(job.source, "file")

	def test_gorsel_arsivi_siniri_mesaji_gercek_siniri_soyler(self):
		import inspect

		from tradehub_core.bulk_import import api

		kaynak = inspect.getsource(api.start_product_import)
		self.assertNotIn("200 MB", kaynak)
		# Mesaj sabitten üretilir: sabit değişince mesaj da değişir, bir daha ayrışamaz.
		self.assertIn("MAX_IMAGES_ZIP_BYTES // (1024 * 1024)", kaynak)
		self.assertEqual(api.MAX_IMAGES_ZIP_BYTES // (1024 * 1024), 50)
