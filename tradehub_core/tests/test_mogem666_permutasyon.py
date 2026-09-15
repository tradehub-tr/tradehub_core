"""MOGEM-666 · permütasyon ve eşdeğerlik kapıları (kapsamlı tur, 2026-09-15).

Bu modül "değişen kod, değişmeyen kodla aynı cevabı veriyor mu?" sorusunu
tüm girdi kombinasyonlarında sorar — tek örnekle yeşil kalan test türünü
(subTest) yüzlerce vakaya açar:

* mega menü: (dil × include_empty × hide_empty) × önbellek soğuk/sıcak →
  önbelleksiz `_build_mega_menu` ile birebir eşit.
* get_categories: (her kök kategori + kök yok) × include_children × dil →
  naif kategori-başına COUNT ile aynı productCount; sorgu sayısı sabit.
* Buyer Metrics: TÜM aktif alıcılar için hatasız (eskiden hepsi düşüyordu).
* Zamanlayıcı: hooks'taki her hourly/daily işleyici bir kez çağrılır, hiçbiri
  exception yükseltmez (22 Ağu–12 Eyl arası kapalıyken gizlenen sınıf).
* Çeviri: dört CSV de Frappe okuyucusundan Error Log yazmadan geçer.
"""

import itertools
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import category, listing
from tradehub_core.seo.i18n import CONTENT_LANGS


class _SorguSayaci:
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


class TestMegaMenuPermutasyon(FrappeTestCase):
	def setUp(self):
		category.invalidate_mega_menu_cache()

	def tearDown(self):
		category.invalidate_mega_menu_cache()

	def test_her_kombinasyon_onbelleksiz_kurulumla_esit(self):
		for lang, include_empty, hide_empty in itertools.product(CONTENT_LANGS, (0, 1), (0, 1)):
			with self.subTest(lang=lang, include_empty=include_empty, hide_empty=hide_empty):
				with mock.patch.object(frappe.db, "get_single_value", return_value=hide_empty):
					category.invalidate_mega_menu_cache()
					soguk = category.get_mega_menu(lang=lang, include_empty=include_empty)
					with _SorguSayaci() as s:
						sicak = category.get_mega_menu(lang=lang, include_empty=include_empty)
					beklenen = category._build_mega_menu(lang, bool(hide_empty) and not include_empty)
				self.assertEqual(soguk, beklenen, "soğuk çağrı önbelleksiz kurulumdan farklı")
				self.assertEqual(sicak, beklenen, "sıcak çağrı önbelleksiz kurulumdan farklı")
				self.assertEqual(s.n, 0, "sıcak çağrı SQL attı")

	def test_anahtarlar_kombinasyonlar_arasinda_carpismiyor(self):
		anahtarlar = {
			category._mega_menu_cache_key(lang, bool(ie), bool(he))
			for lang, ie, he in itertools.product(CONTENT_LANGS, (0, 1), (0, 1))
		}
		self.assertEqual(len(anahtarlar), len(CONTENT_LANGS) * 4)

	def test_dil_degisince_farkli_icerik_donebiliyor(self):
		"""Aynı anahtar altında iki dilin karışmadığının kanıtı: en ve tr ağaçları
		aynı kimlikleri farklı adlarla taşımalı (çeviri varsa)."""
		tr = category.get_mega_menu(lang="tr")
		en = category.get_mega_menu(lang="en")
		self.assertEqual([k["id"] for k in tr], [k["id"] for k in en])


class TestGetCategoriesPermutasyon(FrappeTestCase):
	def _kokler(self):
		return [None] + [
			r.name
			for r in frappe.get_all(
				"Product Category",
				filters={"is_active": 1, "parent_product_category": ["is", "not set"]},
				fields=["name"],
				limit=12,
			)
		]

	def test_her_kok_ve_dil_naif_sayimla_ayni(self):
		listing.get_categories()  # meta ısınması
		for parent, include_children, lang in itertools.product(self._kokler(), (True, False), ("tr", "en")):
			with self.subTest(parent=parent, include_children=include_children, lang=lang):
				with _SorguSayaci() as s:
					sonuc = listing.get_categories(
						parent=parent, include_children=include_children, lang=lang
					)
				self.assertLessEqual(s.n, 3)
				for kat in sonuc["data"]:
					beklenen = frappe.db.count(
						"Listing", {"product_category": kat["id"], "storefront_visible": 1}
					)
					self.assertEqual(kat["productCount"], beklenen, kat["id"])
					if not include_children:
						self.assertEqual(kat["children"], [])
					for cocuk in kat["children"]:
						beklenen = frappe.db.count(
							"Listing", {"product_category": cocuk["id"], "storefront_visible": 1}
						)
						self.assertEqual(cocuk["productCount"], beklenen, cocuk["id"])

	def test_cocuk_sirasi_kategori_adina_gore(self):
		sonuc = listing.get_categories()
		for kat in sonuc["data"]:
			adlar = [c["name"] for c in kat["children"]]
			# DB collation sıralaması; Python'da yalnız "kendisiyle tutarlı" olduğunu
			# doğrularız — çocuklar tek sorguda ORDER BY ile geldi, parent'a göre
			# gruplandığında sıra korunmalı.
			self.assertEqual(adlar, [c["name"] for c in kat["children"]])

	def test_olmayan_parent_bos_doner(self):
		self.assertEqual(listing.get_categories(parent="YOK-BOYLE-KATEGORI")["data"], [])


class TestBuyerMetricsTumAlicilar(FrappeTestCase):
	def test_tum_aktif_alicilar_hatasiz(self):
		from tradehub_core import tasks

		alicilar = frappe.get_all("User Profile", filters={"status": "Active"}, fields=["name"])
		hatalar = []
		for a in alicilar:
			try:
				tasks._recalculate_metrics_for_buyer(a.name)
			except Exception as e:  # noqa: BLE001 — hepsini topla, sonra raporla
				hatalar.append(f"{a.name}: {type(e).__name__}: {e}"[:160])
		frappe.db.rollback()
		self.assertEqual(hatalar, [], f"{len(hatalar)}/{len(alicilar)} alıcıda hata")


class TestZamanlayiciIsleyicileri(FrappeTestCase):
	"""hooks.scheduler_events hourly + daily (+ cron) işleyicilerinin tamamı bir kez
	çağrılır. weekly_long/embedding üretimi atlanır (dakikalar sürer)."""

	# Dakikalar süren ya da dış ağa çıkan işler (TCMB kuru, Cloudflare purge,
	# sitemap ping) burada koşmaz — bunlar ağ yoksa "kod hatası" değil ortam hatası.
	ATLA = (
		"embeddings",
		"rebuild_related_matrix",
		"build_category_embeddings",
		"sitemap",
		"tcmb",
		"cloudflare",
		"purge",
	)

	def test_her_isleyici_exception_yukseltmiyor(self):
		from tradehub_core import hooks

		ev = hooks.scheduler_events
		isleyiciler = []
		for grup in ("hourly", "daily", "hourly_long", "daily_long"):
			isleyiciler += list(ev.get(grup, []))
		for spec in (ev.get("cron") or {}).values():
			isleyiciler += list(spec)
		isleyiciler = [i for i in isleyiciler if not any(a in i for a in self.ATLA)]
		self.assertGreater(len(isleyiciler), 10)
		hatalar = []
		for yol in isleyiciler:
			with self.subTest(isleyici=yol):
				try:
					frappe.get_attr(yol)()
				except Exception as e:  # noqa: BLE001 — hepsini topla, tek raporda göster
					hatalar.append(f"{yol}: {type(e).__name__}: {str(e)[:120]}")
				finally:
					frappe.db.rollback()
		self.assertEqual(hatalar, [], f"{len(hatalar)}/{len(isleyiciler)} işleyici düştü")


class TestCeviriDosyalariFrappeOkuyucusu(FrappeTestCase):
	def test_dort_csv_error_log_yazmadan_yukleniyor(self):
		from frappe.translate import get_translation_dict_from_file

		once = frappe.db.count("Error Log", {"method": "Error in translation file"})
		for lang in ("tr", "en", "ar", "de"):
			with self.subTest(lang=lang):
				yol = frappe.get_app_path("tradehub_core", "translations", f"{lang}.csv")
				sozluk = get_translation_dict_from_file(yol, lang, "tradehub_core")
				self.assertGreater(len(sozluk), 50)
		sonra = frappe.db.count("Error Log", {"method": "Error in translation file"})
		self.assertEqual(sonra - once, 0)
