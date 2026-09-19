"""MOGEM-665 · maymun testi — rastgele gövdelerle değişmezler.

Yeşil birim testlerine inanmamak için: tohumlu rastgele ürün/stok gövdeleri üretilir
(bozuk tipler, negatifler, dev sayılar, Unicode, boş/None, iç içe çöp), her çağrıdan
sonra şu değişmezler ölçülür:

- Çağrı ya sözleşme hatası fırlatır (ValidationError/PermissionError) ya da cevap döner;
  başka istisna YOK.
- Her sonuç satırının `status`'u tanımlı kümede; `rejected` ise `code` var.
- `summary` sayaçları sonuç satırlarıyla tutarlı.
- Veritabanında hiçbir ürünün fiyatı/stoğu negatif değil, satış > liste değil.
- Mağaza kilidi çağrı sonunda serbest.
- Başka mağazanın ürünü hiç değişmedi.
"""

from __future__ import annotations

import random

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam

COP = [
	None,
	"",
	" ",
	"abc",
	"1e3",
	"12,5",
	"-0",
	"١٢",
	"😀",
	[],
	{},
	[1],
	{"a": 1},
	True,
	False,
	0,
	-1,
	1e12,
	3.7,
	"  x-1 ",
]


def _rastgele_sku(rnd: random.Random) -> object:
	return rnd.choice(
		[
			f"MK-{rnd.randint(1, 6)}",
			f" mk-{rnd.randint(1, 6)} ",
			"",
			None,
			42,
			"çift-ürün-ğ",
			"x" * 150,
			[],
			{"s": 1},
		]
	)


def _rastgele_urun(rnd: random.Random) -> object:
	if rnd.random() < 0.06:
		return rnd.choice(COP)
	p: dict = {"sku": _rastgele_sku(rnd)}
	for alan in (
		"title",
		"list_price",
		"price",
		"stock",
		"unit",
		"currency",
		"description",
		"images",
		"variants",
		"attributes",
		"renk",
	):
		if rnd.random() < 0.55:
			if alan in ("list_price", "price", "stock"):
				p[alan] = rnd.choice([rnd.randint(-5, 500), rnd.random() * 1000, *COP])
			elif alan == "images":
				p[alan] = rnd.choice([[f"https://cdn.x/{i}.jpg" for i in range(rnd.randint(0, 14))], *COP])
			elif alan == "variants":
				p[alan] = rnd.choice(
					[
						[
							{
								"sku": f"V-{i}",
								"price": rnd.randint(-2, 50),
								"stock": rnd.randint(-1, 9),
								"axes": rnd.choice([{"Renk": "K"}, {}, "x", {"": ""}]),
							}
							for i in range(rnd.randint(0, 3))
						],
						*COP,
					]
				)
			elif alan == "attributes":
				p[alan] = rnd.choice([{"color": "K"}, {"yok": "x"}, *COP])
			else:
				uzun = "Toptan ürün başlığı: kategori, marka ve öne çıkan özelliğiyle betimlenmiş " + str(
					rnd.randint(1, 9)
				)
				p[alan] = rnd.choice(
					[
						f"başlık {rnd.randint(1, 9)}",
						uzun,
						"<p>" + uzun * 3 + "</p>",
						"metre",
						"parsek",
						"TRY",
						"USD",
						*COP,
					]
				)
	return p


class TestMaymun(Mogem665Ortam, FrappeTestCase):
	DURUMLAR_URUN = {"created", "updated", "rejected"}
	DURUMLAR_STOK = {"updated", "unchanged", "rejected"}

	def _db_degismezleri(self, seller: str) -> None:
		rows = frappe.get_all(
			"Listing",
			filters={"seller_profile": seller},
			fields=["name", "base_price", "selling_price", "stock_qty", "available_qty", "reserved_qty"],
		)
		for r in rows:
			self.assertGreaterEqual(float(r.base_price or 0), 0, r)
			self.assertGreaterEqual(float(r.selling_price or 0), 0, r)
			self.assertGreaterEqual(float(r.stock_qty or 0), 0, r)
			self.assertGreaterEqual(float(r.available_qty or 0), 0, r)
			if r.base_price and r.selling_price:
				self.assertLessEqual(float(r.selling_price), float(r.base_price), r)
		for v in frappe.get_all(
			"Listing Variant Item",
			filters={"parent": ["in", [r.name for r in rows] or ["__yok__"]]},
			fields=["variant_stock", "variant_price"],
		):
			self.assertGreaterEqual(float(v.variant_stock or 0), 0)
			self.assertGreaterEqual(float(v.variant_price or 0), 0)

	def _kilit_serbest(self, seller: str, op: str) -> None:
		cache = frappe.cache()
		self.assertIsNone(
			cache.get(cache.make_key(f"catalog_lock:{seller}:{op}")), f"{op} kilidi bırakılmadı"
		)

	def test_upsert_ve_update_stock_rastgele_govdeler(self):
		import os
		from unittest.mock import patch

		from tradehub_core.api.v1 import catalog

		# Tohum taraması: M665_SEED=<n> ile farklı rastgele uzaylar (soak kampanyası).
		rnd = random.Random(int(os.environ.get("M665_SEED") or 665))
		a = self._api_baglantisi("maymun")
		b = self._api_baglantisi("maymunb")
		diger = self._listing(b["seller"], "MK-1", base_price=100, selling_price=50, stock_qty=7)
		diger_once = frappe.db.get_value(
			"Listing", diger, ["modified", "selling_price", "stock_qty"], as_dict=True
		)

		def sahte_indir(urls, seller_profile, warnings=None):
			return [f"/private/files/mk{i}.jpg" for i, _ in enumerate(urls[:3])]

		bilinen_istisnalar = (frappe.ValidationError, frappe.PermissionError)
		cagri = 0
		with patch.object(catalog.image_url_ingest, "ingest_image_urls", side_effect=sahte_indir):
			for _tur in range(int(os.environ.get("M665_TURLAR") or 40)):
				n = rnd.choice([0, 1, 2, 5, 12])
				govde = rnd.choice([[_rastgele_urun(rnd) for _ in range(n)], "{", None, {"x": 1}, [], 7])
				try:
					with self.bearer(a["token"]):
						cevap = catalog.upsert_products(govde)
					cagri += 1
					self.assertEqual(len(cevap["results"]), len(govde))
					self.assertEqual(cevap["summary"]["total"], len(govde))
					sayac = {"created": 0, "updated": 0, "rejected": 0}
					for r in cevap["results"]:
						self.assertIn(r["status"], self.DURUMLAR_URUN, r)
						sayac[r["status"]] += 1
						if r["status"] == "rejected":
							self.assertTrue(r.get("code"), r)
						else:
							self.assertTrue(r.get("listing"), r)
							self.addCleanup(lambda n=r["listing"]: self._drop("Listing", n))
					self.assertEqual({k: cevap["summary"][k] for k in sayac}, sayac)
					self.addCleanup(lambda n=cevap["job"]: self._drop("Bulk Import Job", n))
				except bilinen_istisnalar:
					pass
				self._kilit_serbest(a["seller"], "upsert")
				self._db_degismezleri(a["seller"])

				# stok/fiyat güncellemesi
				kalemler = [
					{
						"sku": _rastgele_sku(rnd),
						**{
							k: rnd.choice([rnd.randint(-3, 300), *COP])
							for k in rnd.sample(["stock", "price", "list_price"], rnd.randint(0, 3))
						},
					}
					for _ in range(rnd.choice([0, 1, 3, 8]))
				]
				govde2 = rnd.choice([kalemler, kalemler, "x", None, {}])
				try:
					with self.bearer(a["token"]):
						cevap = catalog.update_stock(govde2)
					self.assertEqual(len(cevap["results"]), len(govde2))
					for r in cevap["results"]:
						self.assertIn(r["status"], self.DURUMLAR_STOK, r)
						if r["status"] == "rejected":
							self.assertTrue(r.get("code"), r)
					self.assertEqual(
						sum(cevap["summary"][k] for k in ("updated", "unchanged", "rejected")), len(govde2)
					)
				except bilinen_istisnalar:
					pass
				self._kilit_serbest(a["seller"], "stock")
				self._db_degismezleri(a["seller"])

		# Sağlık eşiği: 60 turluk tohum taramasında (15 Eyl) 8 tohum 2–5 geçerli çağrı üretti;
		# eşik "hiç üretmedi"yi yakalasın, üreteç istatistiğini değil.
		self.assertGreaterEqual(cagri, 2, "maymun hiç geçerli çağrı üretemedi — üreteç bozuk")
		diger_sonra = frappe.db.get_value(
			"Listing", diger, ["modified", "selling_price", "stock_qty"], as_dict=True
		)
		self.assertEqual(diger_once, diger_sonra, "başka mağazanın ürünü değişti")
		self.assertEqual(
			frappe.db.count("Catalog Outbound Event", {"seller_profile": a["seller"]}),
			0,
			"API yazması olay üretmemeli",
		)
