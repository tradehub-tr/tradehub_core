"""MOGEM-666 · performans regresyon kapıları (MOGEM-638 raporunun kabul kriterleri).

Her test rapordaki bir ölçüme bağlı; sayılar oradan geliyor:
- §4.2  get_categories 74 sorgu  → ≤ 10 (burada: ≤ 5, meta yüklemesi hariç)
- §4.4  get_mega_menu p50 159 ms → önbellekten (ikinci çağrıda sorgu yok)
- §4.6  Buyer Metrics 15K hata/ay → var olmayan doctype'a başvuru sıfır
- §4.6  tr.csv 59K hata/ay        → test_translations_csv.py (site'sız koşar)
"""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import category, listing


class _SorguSayaci:
	"""frappe.db.sql sarmalayıcısı — kaç SQL gitti?"""

	def __init__(self):
		self.n = 0

	def __enter__(self):
		self._orig = frappe.db.sql

		def sarmal(*a, **k):
			self.n += 1
			return self._orig(*a, **k)

		frappe.db.sql = sarmal
		return self

	def __exit__(self, *_exc):
		frappe.db.sql = self._orig


class TestGetCategoriesSorguSayisi(FrappeTestCase):
	def test_kok_ve_cocuklar_sabit_sorgu_sayisiyla_geliyor(self):
		"""Eski hâli kategori başına COUNT + çocuk sorgusu atıyordu (N+1)."""
		listing.get_categories()  # meta ısınması — DocType meta yüklemesi sayılmasın
		with _SorguSayaci() as s:
			sonuc = listing.get_categories()
		self.assertLessEqual(s.n, 5, f"get_categories {s.n} sorgu attı; N+1 geri gelmiş olabilir")
		self.assertIn("data", sonuc)

	def test_product_count_naif_sayimla_ayni(self):
		"""GROUP BY sayımı, kategori başına COUNT ile birebir aynı sonucu vermeli."""
		sonuc = listing.get_categories()
		for kok in sonuc["data"][:5]:
			beklenen = frappe.db.count("Listing", {"product_category": kok["id"], "storefront_visible": 1})
			self.assertEqual(kok["productCount"], beklenen, kok["id"])
			for cocuk in kok["children"][:5]:
				beklenen = frappe.db.count(
					"Listing", {"product_category": cocuk["id"], "storefront_visible": 1}
				)
				self.assertEqual(cocuk["productCount"], beklenen, cocuk["id"])

	def test_cocuksuz_cagri_iki_sorgu(self):
		listing.get_categories(include_children=False)  # meta ısınması
		with _SorguSayaci() as s:
			listing.get_categories(include_children=False)
		self.assertLessEqual(s.n, 2)


class TestMegaMenuOnbellegi(FrappeTestCase):
	def setUp(self):
		category.invalidate_mega_menu_cache()

	def tearDown(self):
		category.invalidate_mega_menu_cache()

	def test_ikinci_cagri_veritabanina_gitmiyor(self):
		ilk = category.get_mega_menu()
		with _SorguSayaci() as s:
			ikinci = category.get_mega_menu()
		self.assertEqual(s.n, 0, "sıcak çağrı SQL attı — önbellek isabet etmiyor")
		self.assertEqual(ilk, ikinci)

	def test_ayni_surecte_tekrar_tekrar_isabet_ediyor(self):
		"""`get_value(expires=True)` olmadan ilk ıska local cache'e None yazıyor ve
		aynı süreçte bir daha Redis'e bakılmıyordu (ölçüldü: sıcak çağrı 142 ms)."""
		category.get_mega_menu()
		for _ in range(3):
			with _SorguSayaci() as s:
				category.get_mega_menu()
			self.assertEqual(s.n, 0)

	def test_dil_ve_ayar_ayri_anahtar(self):
		self.assertNotEqual(
			category._mega_menu_cache_key("tr", False, False),
			category._mega_menu_cache_key("en", False, False),
		)
		self.assertNotEqual(
			category._mega_menu_cache_key("tr", False, False),
			category._mega_menu_cache_key("tr", False, True),
		)

	def test_kategori_yazimi_onbellegi_dusuruyor(self):
		category.get_mega_menu()
		self.assertTrue(frappe.cache.get_keys("mega_menu:*"))
		listing.invalidate_category_cache()
		self.assertFalse(frappe.cache.get_keys("mega_menu:*"), "kategori yazımı mega menüyü düşürmedi")

	def test_listing_yazimi_hide_empty_kapaliyken_dusurmuyor(self):
		"""Ayar kapalıyken Listing kaydı mega menüyü etkilemez; boşuna yeniden kurulmasın."""
		category.get_mega_menu()
		with mock.patch.object(frappe.db, "get_single_value", return_value=0):
			listing.invalidate_listing_cache(doc=frappe._dict(name="x", status="Active"))
		self.assertTrue(frappe.cache.get_keys("mega_menu:*"))

	def test_listing_yazimi_hide_empty_acikken_dusuruyor(self):
		category.get_mega_menu()
		with mock.patch.object(frappe.db, "get_single_value", return_value=1):
			listing.invalidate_listing_cache(doc=frappe._dict(name="x", status="Active"))
		self.assertFalse(frappe.cache.get_keys("mega_menu:*"))

	def test_include_empty_ayardan_bagimsiz(self):
		"""include_empty=1 ayarı override eder; sonuç her zaman tüm aktif kategorileri içerir."""
		with mock.patch.object(frappe.db, "get_single_value", return_value=1):
			hepsi = category.get_mega_menu(include_empty=1)
		self.assertIsInstance(hepsi, list)


class TestBuyerMetricsSemasi(FrappeTestCase):
	def test_var_olmayan_doctype_yok(self):
		"""'Marketplace Order' ve 'Dispute' hiçbir app'te yok; 15K/ay hatanın kaynağıydı."""
		import inspect

		from tradehub_core import tasks

		kaynak = inspect.getsource(tasks._recalculate_metrics_for_buyer)
		# Yorumda geçmesi serbest; DB çağrısında geçmesi hata.
		self.assertNotRegex(kaynak, r'(get_all|get_list|count|exists)\(\s*"(Marketplace Order|Dispute)"')
		self.assertTrue(frappe.db.exists("DocType", "Order"))
		self.assertTrue(frappe.db.exists("DocType", "Order Dispute"))

	def test_gercek_aliciyla_patlamiyor(self):
		from tradehub_core import tasks

		alici = frappe.get_all("User Profile", filters={"status": "Active"}, fields=["name"], limit=1)
		if not alici:
			self.skipTest("aktif User Profile yok")
		tasks._recalculate_metrics_for_buyer(alici[0].name)  # exception yükselmemeli
		deger = frappe.db.get_value("User Profile", alici[0].name, "total_orders")
		self.assertIsNotNone(deger)

	def test_iptal_durumu_order_secenegiyle_ayni(self):
		from tradehub_core import tasks

		secenekler = frappe.get_meta("Order").get_field("status").options.split("\n")
		self.assertIn(tasks.ORDER_STATUS_CANCELLED, secenekler)


class TestZamanlayiciIlkSaatKusurlari(FrappeTestCase):
	"""Zamanlayıcı 22 Ağustos'tan beri kapalıydı; açılınca ilk saatte 191 işten 3'ü
	düştü. Üçü de Buyer Metrics ile aynı sınıf: kod hiç çalışmadığı için görülmemiş
	şema uyumsuzlukları. Rapor kabul kriteri: Failed oranı < %1."""

	def test_sla_eposta_govdesi_int_bilet_adiyla_calisiyor(self):
		"""HD Ticket adı bigint → `quote(int)` TypeError('quote_from_bytes…') veriyordu."""
		from tradehub_core.utils.sla_checker import _email_body_html

		html = _email_body_html("başlık", "gövde", 1)
		self.assertIn("/helpdesk/tickets/1", html)

	def test_reorder_rate_none_ise_null_yazilmiyor(self):
		"""`reorder_rate` Percent kolonu NOT NULL; None → IntegrityError 1048 idi."""
		from tradehub_core import tasks

		yazilan: list[dict] = []

		def sahte_set_value(doctype, name, values, *a, **k):
			yazilan.append(values)

		with (
			mock.patch.object(tasks, "_seller_reorder_rate", return_value=None),
			mock.patch.object(tasks, "_seller_response_metrics", return_value=(0, 0)),
			mock.patch.object(
				frappe, "get_all", return_value=[frappe._dict(name="X", rating=0, review_count=0)]
			),
			mock.patch.object(frappe.db, "count", return_value=0),
			mock.patch.object(frappe.db, "set_value", side_effect=sahte_set_value),
			mock.patch.object(frappe.db, "commit"),
		):
			tasks.recompute_seller_performance_metrics()
		self.assertEqual(len(yazilan), 1)
		self.assertIsNotNone(yazilan[0]["reorder_rate"])
		self.assertEqual(yazilan[0]["reorder_rate"], 0)

	def test_sertifika_kontrolu_listing_semasiyla_calisiyor(self):
		"""`Listing Certification`'da `verification_status` yok; sorgu ona basınca
		Unknown column ile düşüyordu. Şema-duyarlı sorgu hatasız dönmeli."""
		from tradehub_core.utils import cert_expiry_check

		self.assertFalse(frappe.db.has_column("Listing Certification", "verification_status"))
		with mock.patch.object(cert_expiry_check, "_notify_expiry"), mock.patch.object(frappe.db, "commit"):
			stats = cert_expiry_check.check_certificate_expiry()
		self.assertIn("listing_expired", stats)
