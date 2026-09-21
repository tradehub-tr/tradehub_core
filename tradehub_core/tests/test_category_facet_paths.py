"""Kategori filtre ağacı — facet kategorilerine ata zinciri (path) eklenmesi.

Storefront listeleme sayfasındaki "Kategoriler" filtresi düz listeden ağaca
dönüşüyor. Mega menü 3 seviyede kesildiği, DB ağacı ise daha derine indiği
için (Ev & Bahçe > Mutfak > Saklama > Kavanoz > Baharatlık) ağaç, facet'in
kendisinin döndürdüğü ata zincirinden kurulur. Bu test o çözücüyü sabitler.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.listing import _category_ancestor_paths

_TUZ = "cfp"


def _mk(external_id, name, parent=None, slug=None, is_active=1):
	doc = frappe.get_doc(
		{
			"doctype": "Product Category",
			"external_id": external_id,
			"category_name": name,
			"parent_product_category": parent,
			"url_slug": slug,
			"is_active": is_active,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


class TestCategoryAncestorPaths(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.root = _mk(f"{_TUZ}-root", f"{_TUZ} Kök", slug=f"{_TUZ}-kok")
		cls.mid = _mk(f"{_TUZ}-mid", f"{_TUZ} Orta", parent=cls.root, slug=f"{_TUZ}-orta")
		cls.leaf = _mk(f"{_TUZ}-leaf", f"{_TUZ} Yaprak", parent=cls.mid, slug=f"{_TUZ}-yaprak")
		cls.other_root = _mk(f"{_TUZ}-other", f"{_TUZ} Diğer", slug=f"{_TUZ}-diger")

	def test_leaf_gets_root_to_parent_chain_in_order(self):
		result = _category_ancestor_paths([self.leaf])
		self.assertEqual(
			result[self.leaf]["path"],
			[
				{"id": self.root, "name": f"{_TUZ} Kök", "slug": f"{_TUZ}-kok"},
				{"id": self.mid, "name": f"{_TUZ} Orta", "slug": f"{_TUZ}-orta"},
			],
		)

	def test_root_has_empty_path_and_own_name_slug(self):
		result = _category_ancestor_paths([self.root])
		self.assertEqual(result[self.root]["path"], [])
		self.assertEqual(result[self.root]["name"], f"{_TUZ} Kök")
		self.assertEqual(result[self.root]["slug"], f"{_TUZ}-kok")

	def test_mixed_input_resolves_every_requested_category(self):
		result = _category_ancestor_paths([self.leaf, self.other_root, self.mid])
		self.assertEqual(set(result.keys()), {self.leaf, self.other_root, self.mid})
		self.assertEqual([p["id"] for p in result[self.mid]["path"]], [self.root])
		self.assertEqual(result[self.other_root]["path"], [])

	def test_unknown_id_falls_back_to_id_as_name(self):
		result = _category_ancestor_paths(["cfp-does-not-exist"])
		self.assertEqual(
			result["cfp-does-not-exist"],
			{"name": "cfp-does-not-exist", "slug": "", "path": []},
		)

	def test_empty_input_returns_empty_map(self):
		self.assertEqual(_category_ancestor_paths([]), {})


class TestCategoryAncestorPathsDil(FrappeTestCase):
	"""Facet kategori adları ARAYÜZ DİLİNE çözülmeli.

	NEDEN VAR: 21 Eylül 2026'da alpha'da ölçüldü — Rusça arayüzde mega menü
	Rusça iken filtre kenar çubuğu TÜRKÇE kalıyordu. Sebep veri eksikliği
	değildi: `_category_ancestor_paths` dili hiç ALMIYOR, adı ham
	`category_name`den okuyordu. Yani bekleyen yaprak çevirileri tamamlansa
	bile filtre Türkçe kalacaktı.

	Bu test iki şeyi birden sabitler: (a) istenen dil varsa o yazılır,
	(b) o dil boşsa kaydın kendi varsayılanına düşülür — ad ASLA boş kalmaz.
	Ata zinciri de (path) aynı çözümden geçmeli; yalnız düğümün adını
	çevirmek, ağacın üst satırlarını Türkçe bırakırdı.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.kok = (
			frappe.get_doc(
				{
					"doctype": "Product Category",
					"external_id": "cfpd-kok",
					"category_name": "cfpd Mobilya",
					"category_name_ru": "cfpd Мебель",
					"category_name_en": "cfpd Furniture",
					"url_slug": "cfpd-mobilya",
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		# Çevirisi OLMAYAN çocuk — fallback davranışını ölçmek için.
		cls.cocuk = (
			frappe.get_doc(
				{
					"doctype": "Product Category",
					"external_id": "cfpd-cocuk",
					"category_name": "cfpd Banyo Taburesi",
					"parent_product_category": cls.kok,
					"url_slug": "cfpd-banyo-taburesi",
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_istenen_dil_varsa_o_yazilir(self):
		r = _category_ancestor_paths([self.kok], lang="ru")
		self.assertEqual(r[self.kok]["name"], "cfpd Мебель")
		r_en = _category_ancestor_paths([self.kok], lang="en")
		self.assertEqual(r_en[self.kok]["name"], "cfpd Furniture")

	def test_dil_verilmezse_turkce_kalir(self):
		# Varsayılan `tr` — eski davranış korunuyor, mevcut çağıranlar kırılmaz.
		r = _category_ancestor_paths([self.kok])
		self.assertEqual(r[self.kok]["name"], "cfpd Mobilya")

	def test_ceviri_yoksa_ad_bos_kalmaz(self):
		# Çocuk kaydın Rusçası yok; ad Türkçeye düşmeli, boş DÖNMEMELİ.
		r = _category_ancestor_paths([self.cocuk], lang="ru")
		self.assertEqual(r[self.cocuk]["name"], "cfpd Banyo Taburesi")

	def test_ata_zinciri_de_cevrilir(self):
		# Yalnız düğümün adını çevirmek, ağacın ÜST satırlarını Türkçe bırakırdı.
		r = _category_ancestor_paths([self.cocuk], lang="ru")
		self.assertEqual([a["name"] for a in r[self.cocuk]["path"]], ["cfpd Мебель"])


class TestFacetDilBaglantisi(FrappeTestCase):
	"""`get_filter_facets` dili çözücüye GERÇEKTEN geçiriyor mu — kaynak denetimi.

	NEDEN KAYNAK DENETİMİ: yukarıdaki testler çözücüyü (`_category_ancestor_paths`)
	doğrudan çağırıyor ve onu sabitliyor. Ama biri `get_filter_facets` içindeki
	`lang=lang` bağlantısını koparırsa o testlerin hepsi YEŞİL kalır ve filtre
	sessizce Türkçeye döner — ölçüldü (21 Eyl): bağlantı koparıldığında 9 testin
	9'u da geçmeye devam etti.

	Davranış testiyle yakalamak listing + kategori + sayım verisi kurmayı
	gerektiriyor; bağlantı tek satır olduğu için kaynakta aranması hem ucuz hem
	kesin. Frontend tarafında aynı gerekçeyle yazılmış bir eşi var
	(`icerikDiliGonderimi.test.ts`).
	"""

	def test_facet_dili_cozucuye_gecirir(self):
		import inspect

		from tradehub_core.api import listing

		kaynak = inspect.getsource(listing.get_filter_facets)
		self.assertIn(
			"_category_ancestor_paths(",
			kaynak,
			"get_filter_facets kategori çözücüsünü çağırmıyor — facet ağacı nereden geliyor?",
		)
		self.assertIn(
			"lang=lang",
			kaynak,
			"get_filter_facets dili çözücüye geçirmiyor: filtre kenar çubuğu "
			"arayüz dili ne olursa olsun Türkçe kalır.",
		)

	def test_facet_imzasinda_lang_var(self):
		import inspect

		from tradehub_core.api import listing

		imza = inspect.signature(listing.get_filter_facets)
		self.assertIn(
			"lang",
			imza.parameters,
			"get_filter_facets `lang` almıyor — ön yüz gönderse bile yok sayılır.",
		)

	def test_onbellek_anahtari_dili_iceriyor(self):
		"""Önbellek anahtarı dili taşımazsa ilk isteğin dili herkese servis edilir.

		NEDEN AYRI TEST: `lang` çözümünü eklemek TEK BAŞINA yetmiyor. Facet
		yanıtı `_cache_key(...)` ile önbelleğe yazılıyor ve o anahtar 21 Eylül
		2026'ya kadar dili içermiyordu. O hâliyle düzeltme rastgele çalışır
		görünürdü: aynı sayfa bazen Rusça bazen Türkçe — hangi dil önce
		istendiyse o.
		"""
		import inspect

		from tradehub_core.api import listing

		kaynak = inspect.getsource(listing.get_filter_facets)
		anahtar = kaynak.split("cached = frappe.cache.get_value")[0]
		self.assertIn(
			"lang=normalize_lang(lang)",
			anahtar,
			"Facet önbellek anahtarı dili içermiyor: ilk isteğin dili tüm "
			"dillere servis edilir ve düzeltme rastgele çalışır görünür.",
		)
