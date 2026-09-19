"""MOGEM-665 · 3. Aşama — ürün aktarımı (`catalog.upsert_products`).

Kabul kriterleri (görev metni, kelimesi kelimesine):
- Tek istekte en fazla 100 ürün; fazlası tek ve net bir hata.
- Her ürün için ayrı sonuç: oluşturuldu / güncellendi / reddedildi + sebep.
- Kısmi başarı: hatalı satır diğerlerini düşürmez.
- Negatif fiyat/stok reddedilir; satış fiyatı liste fiyatını geçemez.
- Güncellemede boş bırakılan alan mevcut değeri korur; stok 0 kabul edilir.
- Para birimi verilmezse TRY.
- En fazla 10 görsel (jpg/png/webp, ≤5 MB); fazlası uyarıyla atlanır.
- Varyantlar yalnız oluştururken yazılır; güncellemede açık "değiştirilmedi" uyarısı.
- Eş zamanlılık: mağaza başına aynı anda tek upsert (409).
- Dosya içe aktarma kilidi API'yi engellemez.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam


def _sonuc(cevap: dict, sku: str) -> dict:
	for r in cevap["results"]:
		if r.get("sku") == sku:
			return r
	raise AssertionError(f"{sku} için sonuç yok: {cevap['results']}")


class _UrunOrtam(Mogem665Ortam):
	def _upsert(self, b: dict, products):
		from tradehub_core.api.v1.catalog import upsert_products

		with self.bearer(b["token"]):
			cevap = upsert_products(products)
		for r in cevap["results"]:
			if r.get("listing"):
				self.addCleanup(lambda n=r["listing"]: self._drop("Listing", n))
		self.addCleanup(lambda n=cevap["job"]: self._drop("Bulk Import Job", n))
		return cevap

	def _urun(self, sku: str, **ek) -> dict:
		# SEO kuralı (utils.seo_content): başlık 50–250, açıklama ≥150 görünür karakter.
		p = {
			"sku": sku,
			"title": f"API ürün {sku} — kategori, marka ve öne çıkan özelliğiyle betimlenmiş uzun başlık",
			"list_price": 100,
			"description": "<p>"
			+ (
				"Bu ürün toptan satış için uygundur; malzeme, ölçü ve kullanım alanı bilgileri burada ayrıntılı verilir. "
				* 2
			)
			+ "</p>",
		}
		p.update(ek)
		return p


class TestTopluSinir(_UrunOrtam, FrappeTestCase):
	def test_bos_liste_reddedilir(self):
		from tradehub_core.api.v1.catalog import upsert_products

		b = self._api_baglantisi("bos")
		with self.bearer(b["token"]), self.assertRaises(frappe.ValidationError):
			upsert_products([])

	def test_101_urun_tek_hata(self):
		from tradehub_core.api.v1.catalog import MAX_PRODUCTS_PER_CALL, upsert_products

		b = self._api_baglantisi("yuz")
		fazla = [self._urun(f"F-{i}") for i in range(MAX_PRODUCTS_PER_CALL + 1)]
		with self.bearer(b["token"]), self.assertRaises(frappe.ValidationError) as cm:
			upsert_products(fazla)
		self.assertIn(str(MAX_PRODUCTS_PER_CALL), str(cm.exception))
		self.assertFalse(frappe.db.exists("Listing", {"seller_profile": b["seller"], "seller_sku": "F-0"}))

	def test_json_metni_de_kabul_edilir(self):
		import json

		b = self._api_baglantisi("jsonstr")
		cevap = self._upsert(b, json.dumps([self._urun("J-1")]))
		self.assertEqual(_sonuc(cevap, "J-1")["status"], "created")

	def test_liste_degil_ise_reddedilir(self):
		from tradehub_core.api.v1.catalog import upsert_products

		b = self._api_baglantisi("dict")
		with self.bearer(b["token"]), self.assertRaises(frappe.ValidationError):
			upsert_products({"sku": "X"})

	def test_yetki_alani_stock_write_yeterli_degil(self):
		from tradehub_core.api.v1.catalog import upsert_products

		b = self._api_baglantisi("scope", scopes=("stock:write",))
		with self.bearer(b["token"]), self.assertRaises(frappe.PermissionError):
			upsert_products([self._urun("S-1")])


class TestOlusturma(_UrunOrtam, FrappeTestCase):
	def test_asgari_urun_olusur_pending_try_sahip_dogru(self):
		b = self._api_baglantisi("olustur")
		cevap = self._upsert(b, [self._urun("OL-1", stock=5)])
		r = _sonuc(cevap, "OL-1")
		self.assertEqual(r["status"], "created", r)
		doc = frappe.get_doc("Listing", r["listing"])
		self.assertEqual(doc.seller_profile, b["seller"])
		self.assertEqual(doc.status, "Pending", "API ürünü onay bekler; kendiliğinden yayına çıkmaz")
		self.assertEqual(doc.currency, "TRY")
		self.assertEqual(float(doc.base_price), 100.0)
		self.assertEqual(float(doc.selling_price), 100.0, "satış fiyatı verilmedi → liste fiyatı")
		self.assertEqual(float(doc.stock_qty), 5.0)
		self.assertEqual(doc.owner, b["user"], "ürün Guest değil mağaza sahibi adına açılır")
		self.assertEqual(doc.created_by_bulk_job, cevap["job"])
		self.assertEqual(cevap["summary"], {"total": 1, "created": 1, "updated": 0, "rejected": 0})

	def test_birim_korunur(self):
		b = self._api_baglantisi("birim")
		cevap = self._upsert(
			b,
			[
				self._urun("B-metre", unit="metre"),
				self._urun("B-ton", unit="Ton"),
				self._urun("B-kutu", unit="kutu"),
				self._urun("B-cift", unit="çift"),
				self._urun("B-saat", unit="saat"),
				self._urun("B-yok", unit="parsek"),
			],
		)
		beklenen = {"B-metre": "Metre", "B-ton": "Ton", "B-kutu": "Kutu", "B-cift": "Çift", "B-saat": "Saat"}
		for sku, uom in beklenen.items():
			r = _sonuc(cevap, sku)
			self.assertEqual(frappe.db.get_value("Listing", r["listing"], "stock_uom"), uom, sku)
		r = _sonuc(cevap, "B-yok")
		self.assertEqual(r["status"], "created")
		self.assertIn("UNIT_UNKNOWN", [w["code"] for w in r["warnings"]])
		self.assertEqual(frappe.db.get_value("Listing", r["listing"], "stock_uom"), "Adet")

	def test_stok_sifir_kabul_edilir(self):
		b = self._api_baglantisi("sifir")
		cevap = self._upsert(b, [self._urun("SF-1", stock=0)])
		r = _sonuc(cevap, "SF-1")
		self.assertEqual(r["status"], "created")
		self.assertEqual(float(frappe.db.get_value("Listing", r["listing"], "stock_qty")), 0.0)

	def test_oznitelikler_yazilir_bilinmeyen_uyari(self):
		self.assertTrue(frappe.db.exists("Product Attribute", "color"), "seed: color özniteliği yok")
		b = self._api_baglantisi("attr")
		cevap = self._upsert(b, [self._urun("AT-1", attributes={"color": "Kırmızı", "yok_boyle": "x"})])
		r = _sonuc(cevap, "AT-1")
		self.assertEqual(r["status"], "created")
		rows = frappe.get_all(
			"Listing Attribute Value",
			filters={"parent": r["listing"]},
			fields=["attribute", "attribute_value"],
		)
		self.assertEqual([(x.attribute, x.attribute_value) for x in rows], [("color", "Kırmızı")])
		self.assertIn("ATTRIBUTE_UNKNOWN", [w["code"] for w in r["warnings"]])

	def test_bilinmeyen_alan_uyari_verir_ama_urun_olusur(self):
		b = self._api_baglantisi("alan")
		cevap = self._upsert(b, [self._urun("AL-1", renk="mavi")])
		r = _sonuc(cevap, "AL-1")
		self.assertEqual(r["status"], "created")
		self.assertIn("UNKNOWN_FIELD", [w["code"] for w in r["warnings"]])


class TestGuncelleme(_UrunOrtam, FrappeTestCase):
	def test_bos_alanlar_korunur_fiyat_guncellenir_durum_degismez(self):
		b = self._api_baglantisi("gunc")
		mevcut = self._listing(
			b["seller"], "GU-1", description="<p>uzun açıklama</p>", base_price=200, selling_price=150
		)
		self.assertEqual(frappe.db.get_value("Listing", mevcut, "status"), "Active")
		cevap = self._upsert(b, [{"sku": "GU-1", "price": 120}])
		r = _sonuc(cevap, "GU-1")
		self.assertEqual(r["status"], "updated", r)
		self.assertEqual(r["listing"], mevcut)
		doc = frappe.get_doc("Listing", mevcut)
		self.assertEqual(float(doc.selling_price), 120.0)
		self.assertEqual(float(doc.base_price), 200.0, "gönderilmeyen liste fiyatı korunur")
		self.assertEqual(doc.description, "<p>uzun açıklama</p>", "gönderilmeyen açıklama korunur")
		self.assertEqual(doc.status, "Active", "güncelleme yeniden onaya düşürmez")
		self.assertEqual(cevap["summary"]["updated"], 1)

	def test_bos_string_alan_da_korunur(self):
		b = self._api_baglantisi("bosstr")
		mevcut = self._listing(b["seller"], "GU-2", title="Eski başlık")
		self._upsert(b, [{"sku": "GU-2", "title": "", "description": None}])
		self.assertEqual(frappe.db.get_value("Listing", mevcut, "title"), "Eski başlık")

	def test_guncellemede_stok_sifir_yazilir(self):
		b = self._api_baglantisi("guncsifir")
		mevcut = self._listing(b["seller"], "GU-3", stock_qty=10)
		self._upsert(b, [{"sku": "GU-3", "stock": 0}])
		self.assertEqual(float(frappe.db.get_value("Listing", mevcut, "stock_qty")), 0.0)

	def test_sku_bosluk_ve_buyuk_kucuk_ayni_urunu_bulur(self):
		b = self._api_baglantisi("skunorm")
		mevcut = self._listing(b["seller"], "abc-100")
		cevap = self._upsert(b, [{"sku": "  abc-100 ", "price": 90}])
		r = _sonuc(cevap, "abc-100")
		self.assertEqual((r["status"], r["listing"]), ("updated", mevcut))

	def test_baska_magazanin_sku_su_etkilenmez(self):
		a = self._api_baglantisi("izoa")
		b = self._api_baglantisi("izob")
		digerinin = self._listing(b["seller"], "ORTAK-1", title="B'nin ürünü", selling_price=50)
		cevap = self._upsert(a, [self._urun("ORTAK-1", price=10)])
		r = _sonuc(cevap, "ORTAK-1")
		self.assertEqual(r["status"], "created", "A için yeni ürün açılmalı")
		self.assertNotEqual(r["listing"], digerinin)
		self.assertEqual(float(frappe.db.get_value("Listing", digerinin, "selling_price")), 50.0)
		self.assertEqual(frappe.db.get_value("Listing", digerinin, "title"), "B'nin ürünü")


class TestRedKurallari(_UrunOrtam, FrappeTestCase):
	def test_sku_yoksa_red(self):
		b = self._api_baglantisi("red1")
		cevap = self._upsert(b, [{"title": "x", "list_price": 1}])
		r = cevap["results"][0]
		self.assertEqual((r["status"], r["code"]), ("rejected", "SKU_REQUIRED"))

	def test_yeni_urunde_baslik_ve_fiyat_zorunlu(self):
		b = self._api_baglantisi("red2")
		cevap = self._upsert(b, [{"sku": "R-2", "list_price": 5}, {"sku": "R-3", "title": "t"}])
		self.assertEqual(_sonuc(cevap, "R-2")["code"], "TITLE_REQUIRED")
		self.assertEqual(_sonuc(cevap, "R-3")["code"], "PRICE_REQUIRED")

	def test_negatif_fiyat_ve_stok(self):
		b = self._api_baglantisi("red3")
		cevap = self._upsert(
			b,
			[
				self._urun("R-4", list_price=-1),
				self._urun("R-5", price=-5),
				self._urun("R-6", stock=-1),
				self._urun("R-7", list_price="abc"),
			],
		)
		self.assertEqual(_sonuc(cevap, "R-4")["code"], "PRICE_NEGATIVE")
		self.assertEqual(_sonuc(cevap, "R-5")["code"], "PRICE_NEGATIVE")
		self.assertEqual(_sonuc(cevap, "R-6")["code"], "STOCK_NEGATIVE")
		self.assertEqual(_sonuc(cevap, "R-7")["code"], "INVALID_NUMBER")
		self.assertEqual(cevap["summary"]["rejected"], 4)

	def test_satis_fiyati_liste_fiyatini_gecemez(self):
		b = self._api_baglantisi("red4")
		mevcut = self._listing(b["seller"], "R-9", base_price=100, selling_price=80)
		cevap = self._upsert(
			b,
			[
				self._urun("R-8", list_price=100, price=101),
				{"sku": "R-9", "price": 150},  # mevcut liste 100
				{"sku": "R-9", "list_price": 50},  # mevcut satış 80 — aynı sku 2. kez → batch dup
			],
		)
		self.assertEqual(_sonuc(cevap, "R-8")["code"], "PRICE_RULE")
		sonuclar = [r for r in cevap["results"] if r["sku"] == "R-9"]
		self.assertEqual(sonuclar[0]["code"], "PRICE_RULE")
		self.assertEqual(sonuclar[1]["code"], "DUPLICATE_IN_BATCH")
		self.assertEqual(float(frappe.db.get_value("Listing", mevcut, "selling_price")), 80.0)

	def test_guncellemede_liste_fiyati_mevcut_satisin_altina_inemez(self):
		b = self._api_baglantisi("red5")
		self._listing(b["seller"], "R-10", base_price=100, selling_price=80)
		cevap = self._upsert(b, [{"sku": "R-10", "list_price": 50}])
		self.assertEqual(_sonuc(cevap, "R-10")["code"], "PRICE_RULE")

	def test_seo_kurali_baslik_ve_aciklama(self):
		"""Üretimde Listing.validate'in uyguladığı kural API'de açık kodla döner."""
		b = self._api_baglantisi("seo")
		mevcut = self._listing(b["seller"], "SEO-4")
		cevap = self._upsert(
			b,
			[
				self._urun("SEO-1", title="Kısa başlık"),
				self._urun("SEO-2", description="kısa"),
				{**self._urun("SEO-3"), "description": None},  # yeni üründe açıklama zorunlu
				{"sku": "SEO-4", "price": 50},  # mevcut üründe açıklama gönderilmedi → serbest
				{"sku": "SEO-4", "title": "kısa"},  # aynı istekte 2. kez → batch dup, SEO'ya gelmez
			],
		)
		self.assertEqual(_sonuc(cevap, "SEO-1")["code"], "SEO_TITLE")
		self.assertEqual(_sonuc(cevap, "SEO-2")["code"], "SEO_DESCRIPTION")
		self.assertEqual(_sonuc(cevap, "SEO-3")["code"], "SEO_DESCRIPTION")
		self.assertEqual(cevap["results"][3]["status"], "updated")
		self.assertEqual(float(frappe.db.get_value("Listing", mevcut, "selling_price")), 50.0)
		cevap = self._upsert(b, [{"sku": "SEO-4", "title": "😀 emoji başlık " + "x" * 50}])
		self.assertEqual(_sonuc(cevap, "SEO-4")["code"], "SEO_TITLE")

	def test_kismi_basari_hatali_satir_digerini_dusurmez(self):
		b = self._api_baglantisi("kismi")
		cevap = self._upsert(b, [self._urun("K-1"), self._urun("K-2", list_price=-1), self._urun("K-3")])
		self.assertEqual(_sonuc(cevap, "K-1")["status"], "created")
		self.assertEqual(_sonuc(cevap, "K-2")["status"], "rejected")
		self.assertEqual(_sonuc(cevap, "K-3")["status"], "created")
		self.assertEqual(cevap["summary"], {"total": 3, "created": 2, "updated": 0, "rejected": 1})
		job = frappe.get_doc("Bulk Import Job", cevap["job"])
		self.assertEqual((job.source, job.file_format, job.status), ("api", "json", "Partial"))
		self.assertEqual((job.inserted_count, job.updated_count, job.error_count), (2, 0, 1))
		hatalar = [e for e in job.error_details if e.severity == "error"]
		self.assertEqual(len(hatalar), 1)
		self.assertEqual((hatalar[0].sku, hatalar[0].row_number), ("K-2", 2))
		self.assertTrue(job.data_file, "istek gövdesi denetim için dosya olarak saklanır")
		dosya = frappe.db.get_value(
			"File",
			{"file_url": job.data_file},
			["attached_to_doctype", "attached_to_name", "attached_to_field", "is_private"],
			as_dict=True,
		)
		self.assertEqual(
			dict(dosya),
			{
				"attached_to_doctype": "Bulk Import Job",
				"attached_to_name": job.name,
				"attached_to_field": "data_file",
				"is_private": 1,
			},
		)
		# İçerik-hash'li adlandırma: aynı gövde → aynı file_url; başka koşulardan kalan
		# dosyalar sayımı şişirebilir. Bu koşuda açılan her File bu job'a bağlı olmalı.
		bu_kosu = frappe.get_all(
			"File",
			# Dosya job'dan ÖNCE açılır — job.creation'dan biraz geriye bak.
			filters={"file_url": job.data_file, "creation": [">=", add_to_date(job.creation, seconds=-10)]},
			fields=["attached_to_name"],
		)
		self.assertEqual([f.attached_to_name for f in bu_kosu], [job.name], "ikinci/bağsız File açıldı")
		self.assertFalse(
			frappe.db.exists(
				"Error Log", {"method": "Error Attaching File", "creation": [">", job.creation]}
			),
			"Frappe dosya bağlama hatası üretti",
		)

	def test_kota_asiminda_red(self):
		b = self._api_baglantisi("kota", plan="pro", kota={"quota.max_products": 1})
		self._listing(b["seller"], "Q-0")
		cevap = self._upsert(b, [self._urun("Q-1")])
		r = _sonuc(cevap, "Q-1")
		self.assertEqual((r["status"], r["code"]), ("rejected", "QUOTA_EXCEEDED"), r)
		self.assertFalse(frappe.db.exists("Listing", {"seller_profile": b["seller"], "seller_sku": "Q-1"}))

	def test_hepsi_hataliysa_is_failed(self):
		b = self._api_baglantisi("hepsi")
		cevap = self._upsert(b, [self._urun("H-1", list_price=-1), {"title": "x"}])
		self.assertEqual(frappe.db.get_value("Bulk Import Job", cevap["job"], "status"), "Failed")


class TestGorseller(_UrunOrtam, FrappeTestCase):
	def test_on_gorsel_siniri_ve_basarisiz_gorsel_uyari(self):
		from tradehub_core.api.v1 import catalog

		b = self._api_baglantisi("gorsel")
		urls = [f"https://cdn.example.com/{i}.jpg" for i in range(12)]

		def sahte_indir(urls_, seller_profile, warnings=None):
			if warnings is not None:
				warnings.append("Görsel indirilemedi (https://cdn.example.com/1.jpg): 404")
			return [f"/private/files/g{i}.jpg" for i, u in enumerate(urls_) if not u.endswith("/1.jpg")]

		with patch.object(catalog.image_url_ingest, "ingest_image_urls", side_effect=sahte_indir) as m:
			cevap = self._upsert(b, [self._urun("G-1", images=urls)])
		r = _sonuc(cevap, "G-1")
		self.assertEqual(r["status"], "created")
		self.assertEqual(len(m.call_args[0][0]), catalog.MAX_IMAGES_PER_PRODUCT)
		kodlar = [w["code"] for w in r["warnings"]]
		self.assertIn("IMAGE_LIMIT", kodlar)
		self.assertIn("IMAGE_FAILED", kodlar)
		doc = frappe.get_doc("Listing", r["listing"])
		self.assertEqual(doc.primary_image, "/private/files/g0.jpg")
		self.assertEqual(len(doc.listing_images), 8)

	def test_gorsel_listesi_degilse_red(self):
		b = self._api_baglantisi("gorsel2")
		cevap = self._upsert(b, [self._urun("G-2", images="https://x/y.jpg")])
		self.assertEqual(_sonuc(cevap, "G-2")["code"], "IMAGES_INVALID")

	def test_gorsel_boyut_ve_tur_kurali_ingest_ile_ayni(self):
		"""5 MB / jpg-png-webp kuralı image_url_ingest'te; API onu çağırır (sabit paylaşımı)."""
		from tradehub_core.api.v1 import catalog
		from tradehub_core.bulk_import import image_url_ingest

		self.assertIs(catalog.image_url_ingest, image_url_ingest)
		self.assertEqual(image_url_ingest.MAX_IMAGE_BYTES, 5 * 1024 * 1024)
		self.assertEqual(set(image_url_ingest.ALLOWED_EXT), {"jpg", "jpeg", "png", "webp"})


class TestVaryantlar(_UrunOrtam, FrappeTestCase):
	def _varyantli(self, sku: str) -> dict:
		return self._urun(
			sku,
			variants=[
				{"sku": f"{sku}-K-M", "price": 90, "stock": 3, "axes": {"Renk": "Kırmızı", "Beden": "M"}},
				{"sku": f"{sku}-M-L", "price": 95, "stock": 0, "axes": {"Renk": "Mavi", "Beden": "L"}},
			],
		)

	def test_olustururken_varyantlar_yazilir(self):
		b = self._api_baglantisi("var")
		cevap = self._upsert(b, [self._varyantli("V-1")])
		r = _sonuc(cevap, "V-1")
		self.assertEqual(r["status"], "created", r)
		doc = frappe.get_doc("Listing", r["listing"])
		self.assertEqual(doc.has_variants, 1)
		self.assertEqual(len(doc.variant_items), 2)
		ilk = doc.variant_items[0]
		self.assertEqual(
			(ilk.variant_sku, float(ilk.variant_price), float(ilk.variant_stock)), ("V-1-K-M", 90.0, 3.0)
		)
		self.assertEqual((ilk.attribute_type, ilk.attribute_value), ("Renk", "Kırmızı"))
		self.assertEqual((ilk.attribute_type_2, ilk.attribute_value_2), ("Beden", "M"))
		self.assertEqual(ilk.is_default, 1)
		self.assertIn("Renk", doc.variant_axes_config)

	def test_guncellemede_varyantlar_degismez_ve_uyari_verilir(self):
		b = self._api_baglantisi("var2")
		cevap = self._upsert(b, [self._varyantli("V-2")])
		name = _sonuc(cevap, "V-2")["listing"]
		guncel = self._varyantli("V-2")
		guncel["variants"][0]["stock"] = 999
		guncel["price"] = 80
		cevap2 = self._upsert(b, [guncel])
		r = _sonuc(cevap2, "V-2")
		self.assertEqual(r["status"], "updated")
		self.assertIn("VARIANTS_NOT_UPDATED", [w["code"] for w in r["warnings"]])
		doc = frappe.get_doc("Listing", name)
		self.assertEqual(
			float(doc.variant_items[0].variant_stock), 3.0, "varyant stoğu güncellemede değişmez"
		)
		self.assertEqual(float(doc.selling_price), 80.0, "ana alanlar yine de güncellenir")

	def test_gecersiz_varyant_red(self):
		b = self._api_baglantisi("var3")
		cevap = self._upsert(
			b,
			[
				self._urun("V-3", variants=[{"sku": "V-3-a"}]),  # eksen yok
				self._urun("V-4", variants=[{"axes": {"Renk": "K"}, "price": -1}]),
				self._urun("V-5", variants="yok"),
			],
		)
		self.assertEqual(_sonuc(cevap, "V-3")["code"], "VARIANT_INVALID")
		self.assertEqual(_sonuc(cevap, "V-4")["code"], "PRICE_NEGATIVE")
		self.assertEqual(_sonuc(cevap, "V-5")["code"], "VARIANT_INVALID")

	def test_coklu_varyant_paket_ozelligi_yoksa_red(self):
		"""pro/enterprise'da var; kapatılmış override ile FEATURE_DENIED."""
		from tradehub_core.tests.mogem665_ortak import VARSAYILAN_PLAN

		b = self._api_baglantisi("varfeat", plan=VARSAYILAN_PLAN)
		sub = frappe.db.get_value("Store Subscription", {"store": b["seller"]}, "name")
		frappe.db.set_value(
			"Store Subscription", sub, "custom_capability_overrides", '{"feature.pim.multi_variant": false}'
		)
		frappe.db.commit()
		for k in ("subscription", "capabilities", "quotas"):
			frappe.cache().delete_value(f"tradehub:entitlement:{k}:{b['seller']}")
		cevap = self._upsert(b, [self._varyantli("V-6")])
		r = _sonuc(cevap, "V-6")
		self.assertEqual((r["status"], r["code"]), ("rejected", "FEATURE_DENIED"), r)


class TestKilitVeDosyaKilidi(_UrunOrtam, FrappeTestCase):
	def test_ayni_magazada_ikinci_upsert_409(self):
		from tradehub_core.api.v1 import catalog

		b = self._api_baglantisi("kilit")
		with catalog.store_lock(b["seller"], "upsert"):
			with self.assertRaises(catalog.CatalogBusyError) as cm:
				self._upsert(b, [self._urun("L-1")])
			self.assertEqual(cm.exception.http_status_code, 409)
		cevap = self._upsert(b, [self._urun("L-1")])  # kilit bırakılınca çalışır
		self.assertEqual(_sonuc(cevap, "L-1")["status"], "created")

	def test_kilit_baska_magazayi_etkilemez(self):
		from tradehub_core.api.v1 import catalog

		a = self._api_baglantisi("kilita")
		b = self._api_baglantisi("kilitb")
		with catalog.store_lock(a["seller"], "upsert"):
			cevap = self._upsert(b, [self._urun("L-2")])
		self.assertEqual(_sonuc(cevap, "L-2")["status"], "created")

	def test_hata_olsa_da_kilit_birakilir(self):
		from tradehub_core.api.v1 import catalog

		b = self._api_baglantisi("kilithata")
		with patch.object(catalog, "_open_job", side_effect=RuntimeError("patladı")):
			with self.bearer(b["token"]), self.assertRaises(RuntimeError):
				catalog.upsert_products([self._urun("L-3")])
		cevap = self._upsert(b, [self._urun("L-3")])
		self.assertEqual(_sonuc(cevap, "L-3")["status"], "created")

	def test_dosya_ice_aktarma_kilidi_apiyi_engellemez(self):
		b = self._api_baglantisi("dosyakilit")
		job = frappe.get_doc(
			{
				"doctype": "Bulk Import Job",
				"seller_profile": b["seller"],
				"source": "file",
				"data_file": "/private/files/m665-x.xlsx",
				"file_format": "xlsx",
				"status": "Running",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Bulk Import Job", job.name))
		cevap = self._upsert(b, [self._urun("DK-1")])
		self.assertEqual(_sonuc(cevap, "DK-1")["status"], "created")
