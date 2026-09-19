"""MOGEM-665 · 6. Aşama — panel: API içe aktarmaları ayrı süzülür, toplu onay, kaynak rozeti."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam


class TestPanelGecmisVeOnay(Mogem665Ortam, FrappeTestCase):
	def _api_urun(self, b, sku):
		from tradehub_core.api.v1.catalog import upsert_products

		with self.bearer(b["token"]):
			cevap = upsert_products(
				[
					{
						"sku": sku,
						"title": f"API ürün {sku} — kategori, marka ve öne çıkan özelliğiyle betimlenmiş uzun başlık",
						"list_price": 10,
						"description": "<p>"
						+ (
							"Bu ürün toptan satış için uygundur; malzeme, ölçü ve kullanım alanı bilgileri burada ayrıntılı verilir. "
							* 2
						)
						+ "</p>",
					}
				]
			)
		self.addCleanup(lambda n=cevap["job"]: self._drop("Bulk Import Job", n))
		for r in cevap["results"]:
			if r.get("listing"):
				self.addCleanup(lambda n=r["listing"]: self._drop("Listing", n))
		return cevap

	def test_gecmis_kaynak_suzgeci(self):
		from tradehub_core.bulk_import.api import get_my_history
		from tradehub_core.tests.mogem620_ortak import kullanici

		b = self._api_baglantisi("gecmis")
		api_job = self._api_urun(b, "GC-1")["job"]
		dosya_job = frappe.get_doc(
			{
				"doctype": "Bulk Import Job",
				"seller_profile": b["seller"],
				"source": "file",
				"data_file": "/private/files/m665-gc.xlsx",
				"file_format": "xlsx",
				"status": "Completed",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Bulk Import Job", dosya_job.name))
		with kullanici(b["user"]):
			hepsi = {j["name"]: j["source"] for j in get_my_history(limit=50)}
			self.assertEqual(hepsi.get(api_job), "api")
			self.assertEqual(hepsi.get(dosya_job.name), "file")
			yalniz_api = [j["name"] for j in get_my_history(limit=50, source="api")]
			self.assertIn(api_job, yalniz_api)
			self.assertNotIn(dosya_job.name, yalniz_api)
			yalniz_dosya = [j["name"] for j in get_my_history(limit=50, source="file")]
			self.assertNotIn(api_job, yalniz_dosya)
			with self.assertRaises(frappe.ValidationError):
				get_my_history(limit=50, source="ftp")

	def test_api_urunleri_toplu_onaylanir(self):
		from tradehub_core.bulk_import.api import bulk_approve_listings_from_job

		b = self._api_baglantisi("onay")
		cevap = self._api_urun(b, "ON-1")
		name = cevap["results"][0]["listing"]
		self.assertEqual(frappe.db.get_value("Listing", name, "status"), "Pending")
		frappe.set_user("Administrator")
		sonuc = bulk_approve_listings_from_job(cevap["job"])
		self.assertEqual(sonuc, {"approved": 1, "total": 1})
		self.assertEqual(frappe.db.get_value("Listing", name, "status"), "Active")

	def test_satici_listesi_import_source_ve_api_suzgeci(self):
		from tradehub_core.api.listing import get_seller_listings
		from tradehub_core.tests.mogem620_ortak import kullanici

		b = self._api_baglantisi("liste")
		api_name = self._api_urun(b, "LS-1")["results"][0]["listing"]
		elle = self._listing(b["seller"], "LS-2")
		with kullanici(b["user"]):
			hepsi = {
				r["name"]: r.get("import_source") for r in get_seller_listings(page_size=100)["listings"]
			}
			self.assertEqual(hepsi.get(api_name), "api")
			self.assertIsNone(hepsi.get(elle))
			api_only = [r["name"] for r in get_seller_listings(page_size=100, source="api")["listings"]]
			self.assertEqual(api_only, [api_name])
			manual = [r["name"] for r in get_seller_listings(page_size=100, source="manual")["listings"]]
			self.assertIn(elle, manual)
			self.assertNotIn(api_name, manual)

	def test_dosya_yukleme_api_kaydindan_etkilenmez(self):
		"""API job'ı Running kalsa bile dosya içe aktarma kilidi devreye girmez."""
		from tradehub_core.bulk_import.api import _assert_no_active_file_import

		b = self._api_baglantisi("dosya")
		job = frappe.get_doc(
			{
				"doctype": "Bulk Import Job",
				"seller_profile": b["seller"],
				"source": "api",
				"data_file": "/private/files/m665-api.json",
				"file_format": "json",
				"status": "Running",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Bulk Import Job", job.name))
		_assert_no_active_file_import(b["seller"])  # fırlatmamalı

	def test_navigasyon_kaydi_ve_spec(self):
		from tradehub_core.setup.module_navigation_spec import get_all_modules

		spec = next((m for m in get_all_modules() if m["key"] == "seller.products.toplu.api"), None)
		self.assertIsNotNone(spec)
		self.assertEqual(
			(spec["route"], spec["panel"], spec["section"]), ("/seller-api", "seller", "products")
		)
		self.assertTrue(
			frappe.db.exists("TH Module Registry", "seller.products.toplu.api"), "seed patch koşmadı"
		)
		self.assertEqual(
			frappe.db.get_value("TH Module Registry", "seller.products.toplu.api", "route"), "/seller-api"
		)
