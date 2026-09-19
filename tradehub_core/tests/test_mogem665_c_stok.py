"""MOGEM-665 · 4. Aşama — stok / fiyat güncelleme (`catalog.update_stock`).

Kabul kriterleri (görev metni):
- Tek istekte en fazla 500 kalem; değerler mutlak (delta değil), aynı istek iki
  kez gönderilince sonuç değişmez (idempotent).
- Güncelleme ürünü yeniden onaya düşürmez; ürün durumu kendiliğinden değişmez.
- Stok 0 kabul; negatif red; satış fiyatı liste fiyatını geçemez.
- Eş zamanlılık: mağaza başına tek stok işlemi; upsert kilidinden bağımsız.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam


def _sonuc(cevap: dict, sku: str) -> dict:
	for r in cevap["results"]:
		if r.get("sku") == sku:
			return r
	raise AssertionError(f"{sku} için sonuç yok: {cevap['results']}")


class _StokOrtam(Mogem665Ortam):
	def _stok(self, b: dict, items):
		from tradehub_core.api.v1.catalog import update_stock

		with self.bearer(b["token"]):
			return update_stock(items)


class TestSinirVeYetki(_StokOrtam, FrappeTestCase):
	def test_501_kalem_tek_hata(self):
		from tradehub_core.api.v1.catalog import MAX_STOCK_ITEMS_PER_CALL

		b = self._api_baglantisi("s501")
		with self.assertRaises(frappe.ValidationError) as cm:
			self._stok(b, [{"sku": f"X-{i}", "stock": 1} for i in range(MAX_STOCK_ITEMS_PER_CALL + 1)])
		self.assertIn("500", str(cm.exception))

	def test_bos_liste_red(self):
		b = self._api_baglantisi("sbos")
		with self.assertRaises(frappe.ValidationError):
			self._stok(b, [])

	def test_catalog_read_yetkisi_yetmez(self):
		b = self._api_baglantisi("sscope", scopes=("catalog:read",))
		with self.assertRaises(frappe.PermissionError):
			self._stok(b, [{"sku": "X", "stock": 1}])


class TestStokGuncelleme(_StokOrtam, FrappeTestCase):
	def test_mutlak_stok_yazilir_durum_degismez(self):
		b = self._api_baglantisi("mutlak")
		name = self._listing(b["seller"], "ST-1", stock_qty=10)
		frappe.db.set_value("Listing", name, "reserved_qty", 2)
		cevap = self._stok(b, [{"sku": "ST-1", "stock": 3}])
		r = _sonuc(cevap, "ST-1")
		self.assertEqual(r["status"], "updated", r)
		self.assertEqual((r["stock_qty"], r["available_qty"]), (3.0, 1.0))
		doc = frappe.db.get_value(
			"Listing",
			name,
			["stock_qty", "available_qty", "reserved_qty", "status", "modified_by"],
			as_dict=True,
		)
		self.assertEqual(
			(float(doc.stock_qty), float(doc.available_qty), float(doc.reserved_qty)), (3.0, 1.0, 2.0)
		)
		self.assertEqual(doc.status, "Active", "stok güncellemesi durumu değiştirmez")
		self.assertEqual(doc.modified_by, b["user"], "denetim izi: mağaza sahibi")
		self.assertEqual(cevap["summary"], {"total": 1, "updated": 1, "unchanged": 0, "rejected": 0})

	def test_idempotent_ikinci_cagri_unchanged(self):
		b = self._api_baglantisi("idem")
		self._listing(b["seller"], "ST-2", stock_qty=10)
		self._stok(b, [{"sku": "ST-2", "stock": 7, "price": 80}])
		cevap = self._stok(b, [{"sku": "ST-2", "stock": 7, "price": 80}])
		r = _sonuc(cevap, "ST-2")
		self.assertEqual(r["status"], "unchanged")
		self.assertEqual((r["stock_qty"], r["price"]), (7.0, 80.0))

	def test_stok_sifir_kabul_negatif_red(self):
		b = self._api_baglantisi("sifir")
		name = self._listing(b["seller"], "ST-3", stock_qty=10)
		cevap = self._stok(b, [{"sku": "ST-3", "stock": 0}])
		self.assertEqual(_sonuc(cevap, "ST-3")["status"], "updated")
		self.assertEqual(float(frappe.db.get_value("Listing", name, "stock_qty")), 0.0)
		cevap = self._stok(b, [{"sku": "ST-3", "stock": -1}])
		self.assertEqual(_sonuc(cevap, "ST-3")["code"], "STOCK_NEGATIVE")
		self.assertEqual(float(frappe.db.get_value("Listing", name, "stock_qty")), 0.0)

	def test_pending_ve_rejected_urun_onaya_dusmez_durum_ayni_kalir(self):
		b = self._api_baglantisi("pend")
		pending = self._listing(b["seller"], "ST-4", status="Pending")
		rejected = self._listing(b["seller"], "ST-5", status="Rejected", rejection_reason="kötü foto")
		cevap = self._stok(b, [{"sku": "ST-4", "stock": 1}, {"sku": "ST-5", "stock": 2}])
		self.assertEqual(_sonuc(cevap, "ST-4")["status"], "updated")
		self.assertEqual(_sonuc(cevap, "ST-5")["status"], "updated")
		self.assertEqual(frappe.db.get_value("Listing", pending, "status"), "Pending")
		self.assertEqual(
			frappe.db.get_value("Listing", rejected, ["status", "rejection_reason"], as_dict=True),
			{"status": "Rejected", "rejection_reason": "kötü foto"},
		)

	def test_out_of_stock_durumu_kendiliginden_degismez(self):
		b = self._api_baglantisi("oos")
		name = self._listing(b["seller"], "ST-6", status="Out of Stock", stock_qty=0)
		self._stok(b, [{"sku": "ST-6", "stock": 50}])
		self.assertEqual(
			frappe.db.get_value("Listing", name, "status"), "Out of Stock", "durum satıcının kararı"
		)


class TestFiyatGuncelleme(_StokOrtam, FrappeTestCase):
	def test_fiyat_ve_liste_fiyati(self):
		b = self._api_baglantisi("fiyat")
		name = self._listing(b["seller"], "FY-1", base_price=100, selling_price=90)
		cevap = self._stok(b, [{"sku": "FY-1", "price": 70}])
		self.assertEqual(_sonuc(cevap, "FY-1")["status"], "updated")
		doc = frappe.db.get_value(
			"Listing", name, ["selling_price", "selling_price_base", "base_price"], as_dict=True
		)
		self.assertEqual(
			(float(doc.selling_price), float(doc.selling_price_base), float(doc.base_price)),
			(70.0, 70.0, 100.0),
		)
		cevap = self._stok(b, [{"sku": "FY-1", "list_price": 120, "price": 110}])
		self.assertEqual(_sonuc(cevap, "FY-1")["status"], "updated")
		doc = frappe.db.get_value("Listing", name, ["selling_price", "base_price"], as_dict=True)
		self.assertEqual((float(doc.selling_price), float(doc.base_price)), (110.0, 120.0))

	def test_fiyat_kurali_mevcut_degerle_karsilastirilir(self):
		b = self._api_baglantisi("kural")
		name = self._listing(b["seller"], "FY-2", base_price=100, selling_price=90)
		cevap = self._stok(b, [{"sku": "FY-2", "price": 101}])
		self.assertEqual(_sonuc(cevap, "FY-2")["code"], "PRICE_RULE")
		cevap = self._stok(b, [{"sku": "FY-2", "list_price": 80}])  # mevcut satış 90 > 80
		self.assertEqual(_sonuc(cevap, "FY-2")["code"], "PRICE_RULE")
		cevap = self._stok(b, [{"sku": "FY-2", "list_price": 80, "price": 80}])  # birlikte tutarlı
		self.assertEqual(_sonuc(cevap, "FY-2")["status"], "updated")
		self.assertEqual(float(frappe.db.get_value("Listing", name, "selling_price")), 80.0)

	def test_negatif_fiyat_ve_sayi_olmayan(self):
		b = self._api_baglantisi("neg")
		self._listing(b["seller"], "FY-3")
		cevap = self._stok(b, [{"sku": "FY-3", "price": -1}])
		self.assertEqual(_sonuc(cevap, "FY-3")["code"], "PRICE_NEGATIVE")
		cevap = self._stok(b, [{"sku": "FY-3", "stock": "bol"}])
		self.assertEqual(_sonuc(cevap, "FY-3")["code"], "INVALID_NUMBER")


class TestRedVeIzolasyon(_StokOrtam, FrappeTestCase):
	def test_bulunamayan_sku_ve_bos_kalem(self):
		b = self._api_baglantisi("nf")
		self._listing(b["seller"], "NF-1")
		cevap = self._stok(b, [{"sku": "YOK", "stock": 1}, {"sku": "NF-1"}, {"stock": 1}, "metin"])
		self.assertEqual(_sonuc(cevap, "YOK")["code"], "NOT_FOUND")
		self.assertEqual(_sonuc(cevap, "NF-1")["code"], "NOTHING_TO_UPDATE")
		self.assertEqual(cevap["results"][2]["code"], "SKU_REQUIRED")
		self.assertEqual(cevap["results"][3]["code"], "INVALID_ITEM")
		self.assertEqual(cevap["summary"]["rejected"], 4)

	def test_baska_magazanin_sku_su_not_found(self):
		a = self._api_baglantisi("iza")
		b = self._api_baglantisi("izb")
		digerinin = self._listing(b["seller"], "IZ-1", stock_qty=10)
		cevap = self._stok(a, [{"sku": "IZ-1", "stock": 0}])
		self.assertEqual(_sonuc(cevap, "IZ-1")["code"], "NOT_FOUND")
		self.assertEqual(float(frappe.db.get_value("Listing", digerinin, "stock_qty")), 10.0)

	def test_yinelenen_sku_ve_bosluklu_sku(self):
		b = self._api_baglantisi("dup")
		name = self._listing(b["seller"], "DP-1", stock_qty=10)
		cevap = self._stok(b, [{"sku": " dp-1 ", "stock": 4}, {"sku": "DP-1", "stock": 9}])
		self.assertEqual(cevap["results"][0]["status"], "updated")
		self.assertEqual(cevap["results"][1]["code"], "DUPLICATE_IN_BATCH")
		self.assertEqual(float(frappe.db.get_value("Listing", name, "stock_qty")), 4.0)

	def test_kismi_basari(self):
		b = self._api_baglantisi("kismi")
		self._listing(b["seller"], "KS-1", stock_qty=1)
		self._listing(b["seller"], "KS-2", stock_qty=1)
		cevap = self._stok(
			b, [{"sku": "KS-1", "stock": 5}, {"sku": "YOK", "stock": 5}, {"sku": "KS-2", "stock": 5}]
		)
		self.assertEqual(cevap["summary"], {"total": 3, "updated": 2, "unchanged": 0, "rejected": 1})


class TestVaryantStok(_StokOrtam, FrappeTestCase):
	def test_varyant_sku_ile_stok_ve_fiyat(self):
		b = self._api_baglantisi("vstok")
		name = self._listing(
			b["seller"],
			"VP-1",
			has_variants=1,
			variant_items=[
				{
					"attribute_type": "Renk",
					"attribute_value": "Kırmızı",
					"variant_sku": "VP-1-K",
					"variant_stock": 5,
					"variant_price": 50,
					"is_default": 1,
				},
				{
					"attribute_type": "Renk",
					"attribute_value": "Mavi",
					"variant_sku": "VP-1-M",
					"variant_stock": 5,
					"variant_price": 50,
				},
			],
		)
		cevap = self._stok(
			b, [{"sku": "VP-1-K", "stock": 2, "price": 45}, {"sku": "VP-1-M", "list_price": 1}]
		)
		r = _sonuc(cevap, "VP-1-K")
		self.assertEqual((r["status"], r["variant"], r["listing"]), ("updated", True, name))
		self.assertEqual(_sonuc(cevap, "VP-1-M")["code"], "VARIANT_FIELD_UNSUPPORTED")
		row = frappe.db.get_value(
			"Listing Variant Item",
			{"parent": name, "variant_sku": "VP-1-K"},
			["variant_stock", "variant_price"],
			as_dict=True,
		)
		self.assertEqual((float(row.variant_stock), float(row.variant_price)), (2.0, 45.0))
		mavi = frappe.db.get_value(
			"Listing Variant Item", {"parent": name, "variant_sku": "VP-1-M"}, "variant_stock"
		)
		self.assertEqual(float(mavi), 5.0)


class TestVaryantRezerv(_StokOrtam, FrappeTestCase):
	def test_acik_siparis_rezervi_mutlak_stokta_silinmez(self):
		"""Kod incelemesi bulgusu: varyantta ayrı reserved_qty yok; ERP'nin fiziksel sayımı
		açık rezervi ezmemeli (yoksa aynı adet ikinci alıcıya satılır)."""
		b = self._api_baglantisi("vrezerv")
		name = self._listing(
			b["seller"],
			"VR-1",
			has_variants=1,
			variant_items=[
				{
					"attribute_type": "Renk",
					"attribute_value": "Kırmızı",
					"variant_sku": "VR-1-K",
					"variant_stock": 5,
					"is_default": 1,
				},
				{
					"attribute_type": "Renk",
					"attribute_value": "Mavi",
					"variant_sku": "VR-1-M",
					"variant_stock": 5,
				},
			],
		)
		alici = self._user("alici")
		# Açık (sevk edilmemiş) sipariş: Kırmızı'dan 2 adet; rezerv variant_stock'tan düşülmüş varsayılır.
		order = frappe.get_doc(
			{
				"doctype": "Order",
				"buyer": alici,
				"status": "Onaylanıyor",
				"stock_deducted": 0,
				"items": [
					{"listing": name, "variation": "Renk: Kırmızı", "quantity": 2, "listing_title": "VR"}
				],
			}
		)
		order.flags.ignore_validate = True
		order.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Order", order.name))
		frappe.db.set_value(
			"Listing Variant Item", {"parent": name, "variant_sku": "VR-1-K"}, "variant_stock", 3
		)

		cevap = self._stok(b, [{"sku": "VR-1-K", "stock": 10}, {"sku": "VR-1-M", "stock": 10}])
		k = _sonuc(cevap, "VR-1-K")
		self.assertEqual(
			(k["status"], k["stock_qty"], k["reserved_qty"], k["available_qty"]),
			("updated", 10.0, 2.0, 8.0),
			k,
		)
		self.assertEqual(
			float(
				frappe.db.get_value(
					"Listing Variant Item", {"parent": name, "variant_sku": "VR-1-K"}, "variant_stock"
				)
			),
			8.0,
		)
		m = _sonuc(cevap, "VR-1-M")
		self.assertEqual((m["reserved_qty"], m["available_qty"]), (0.0, 10.0), "rezervsiz varyant etkilenmez")
		# idempotent: aynı fiziksel sayım ikinci kez → unchanged
		cevap = self._stok(b, [{"sku": "VR-1-K", "stock": 10}])
		self.assertEqual(_sonuc(cevap, "VR-1-K")["status"], "unchanged")
		# sevk edilmiş sipariş artık rezerv sayılmaz
		frappe.db.set_value("Order", order.name, "stock_deducted", 1)
		cevap = self._stok(b, [{"sku": "VR-1-K", "stock": 10}])
		self.assertEqual(_sonuc(cevap, "VR-1-K")["available_qty"], 10.0)


class TestKilitVeOnbellek(_StokOrtam, FrappeTestCase):
	def test_stok_kilidi_409_ve_upsert_kilidinden_bagimsiz(self):
		from tradehub_core.api.v1 import catalog

		b = self._api_baglantisi("skilit")
		self._listing(b["seller"], "KL-1")
		with catalog.store_lock(b["seller"], "stock"), self.assertRaises(catalog.CatalogBusyError):
			self._stok(b, [{"sku": "KL-1", "stock": 1}])
		with catalog.store_lock(b["seller"], "upsert"):
			cevap = self._stok(b, [{"sku": "KL-1", "stock": 1}])
		self.assertEqual(_sonuc(cevap, "KL-1")["status"], "updated")

	def test_gorunur_urun_degisince_vitrin_onbellegi_dusurulur(self):
		from tradehub_core.api.v1 import catalog

		b = self._api_baglantisi("cache")
		self._listing(b["seller"], "CC-1", status="Active", stock_qty=1)
		self._listing(b["seller"], "CC-2", status="Pending", stock_qty=1)
		with patch.object(catalog, "invalidate_listing_cache") as m:
			self._stok(b, [{"sku": "CC-2", "stock": 3}])
			self.assertEqual(m.call_count, 0, "vitrinde görünmeyen ürün önbelleği düşürmez")
			self._stok(b, [{"sku": "CC-1", "stock": 3}])
			self.assertEqual(m.call_count, 1)
			self._stok(b, [{"sku": "CC-1", "stock": 3}])
			self.assertEqual(m.call_count, 1, "değişmeyen değer önbelleği düşürmez")
