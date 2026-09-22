"""i18n pure-function testleri.

cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_i18n
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.i18n import (  # noqa: E402
	CONTENT_LANGS,
	DEFAULT_LANG,
	SUPPORTED_LANGS,
	build_hreflang_links,
	get_field_with_fallback,
	localize_url,
	normalize_lang,
	resolve_content_field,
	slug_field_for,
)

SITE = "https://istoc.com"


class TestGetFieldWithFallback(unittest.TestCase):
	def test_tr_returns_base_field(self):
		record = {"meta_title": "TR Title", "meta_title_en": "EN Title"}
		self.assertEqual(get_field_with_fallback(record, "meta_title", "tr"), "TR Title")

	def test_en_returns_en_field(self):
		record = {"meta_title": "TR Title", "meta_title_en": "EN Title"}
		self.assertEqual(get_field_with_fallback(record, "meta_title", "en"), "EN Title")

	def test_en_falls_back_when_en_empty(self):
		record = {"meta_title": "TR Title", "meta_title_en": ""}
		self.assertEqual(get_field_with_fallback(record, "meta_title", "en"), "TR Title")

	def test_en_falls_back_when_en_missing(self):
		record = {"meta_title": "TR Title"}
		self.assertEqual(get_field_with_fallback(record, "meta_title", "en"), "TR Title")

	def test_empty_record(self):
		self.assertEqual(get_field_with_fallback({}, "meta_title", "tr"), "")

	def test_none_value_treated_empty(self):
		record = {"meta_title": "TR", "meta_title_en": None}
		self.assertEqual(get_field_with_fallback(record, "meta_title", "en"), "TR")


class TestLocalizeUrl(unittest.TestCase):
	"""Dil URL'e YANSIMAZ (2026-09-21, K7) — `?hl=` ile taşınır.

	Bu sınıf 2026-09-21'e kadar tersini kilitliyordu: `localize_url("/urun/x",
	"en") == "/en/urun/x"`. O şema hiç sunulmuyordu (canlıda 404) ve beş site
	haritası 25.997 kırık alternate bildiriyordu. Testler o gün yeni sözleşmeye
	çevrildi; bir gün yol öneki GERÇEKTEN kurulursa buradan başlanır.
	"""

	def test_tr_no_prefix(self):
		self.assertEqual(localize_url("/urun/x", "tr"), "/urun/x")

	def test_en_no_prefix(self):
		self.assertEqual(localize_url("/urun/x", "en"), "/urun/x")

	def test_ar_no_prefix(self):
		self.assertEqual(localize_url("/urun/x", "ar"), "/urun/x")

	def test_ru_no_prefix(self):
		self.assertEqual(localize_url("/urun/x", "ru"), "/urun/x")

	def test_root_unchanged_every_lang(self):
		for lang in ("tr", "en", "ar", "ru", "de"):
			with self.subTest(lang=lang):
				self.assertEqual(localize_url("/", lang), "/")

	def test_unknown_lang_no_change(self):
		self.assertEqual(localize_url("/urun/x", "de"), "/urun/x")

	def test_no_leading_slash(self):
		self.assertEqual(localize_url("urun/x", "en"), "/urun/x")

	def test_empty_path_is_root(self):
		self.assertEqual(localize_url("", "en"), "/")

	def test_legacy_en_prefix_is_not_reproduced(self):
		"""Kırık şemanın geri sızmadığının kanıtı: hiçbir çıktı `/en` ile başlamaz."""
		for lang in ("tr", "en", "ar", "ru"):
			for path in ("/", "/urun/x", "/kategori/y", "/urunler"):
				with self.subTest(lang=lang, path=path):
					self.assertFalse(localize_url(path, lang).startswith("/en"))


class TestBuildHreflangLinks(unittest.TestCase):
	def test_returns_two_entries(self):
		# tr + x-default. 2026-09-21'e kadar üçüncü bir `en` girdisi vardı ve
		# gösterdiği adres 404 dönüyordu (ölçüldü, canlı).
		links = build_hreflang_links("/urun/iphone", SITE)
		self.assertEqual(len(links), 2)

	def test_tr_link(self):
		links = build_hreflang_links("/urun/iphone", SITE)
		tr = next(l for l in links if l["hreflang"] == "tr")
		self.assertEqual(tr["href"], "https://istoc.com/urun/iphone")

	def test_no_broken_en_alternate(self):
		"""KARŞI KANIT: `en` alternate'i üretilmemeli; üretilirse 404 bildiririz."""
		links = build_hreflang_links("/urun/iphone", SITE)
		self.assertNotIn("en", [l["hreflang"] for l in links])
		self.assertFalse(any("/en/" in l["href"] for l in links))

	def test_every_alternate_is_self_referencing(self):
		"""Tek adres var; bildirilen her alternate ona işaret etmeli."""
		links = build_hreflang_links("/urun/iphone", SITE)
		for link in links:
			with self.subTest(hreflang=link["hreflang"]):
				self.assertEqual(link["href"], "https://istoc.com/urun/iphone")

	def test_x_default_points_to_tr(self):
		links = build_hreflang_links("/urun/iphone", SITE)
		xdef = next(l for l in links if l["hreflang"] == "x-default")
		self.assertEqual(xdef["href"], "https://istoc.com/urun/iphone")

	def test_trailing_slash_site_url(self):
		links = build_hreflang_links("/urun/x", "https://istoc.com/")
		# rstrip("/") yapılır, çift slash olmaz
		self.assertEqual(links[0]["href"], "https://istoc.com/urun/x")


class TestSlugFieldFor(unittest.TestCase):
	def test_listing_tr(self):
		self.assertEqual(slug_field_for("Listing", "tr"), "slug")

	def test_listing_en(self):
		self.assertEqual(slug_field_for("Listing", "en"), "slug_en")

	def test_product_category_tr(self):
		self.assertEqual(slug_field_for("Product Category", "tr"), "url_slug")

	def test_product_category_en(self):
		self.assertEqual(slug_field_for("Product Category", "en"), "url_slug_en")

	def test_brand_en(self):
		self.assertEqual(slug_field_for("Brand", "en"), "slug_en")

	def test_seller_profile_en(self):
		self.assertEqual(slug_field_for("Admin Seller Profile", "en"), "slug_en")


class TestNormalizeLang(unittest.TestCase):
	def test_valid_content_lang(self):
		for lang in ("tr", "en", "ar", "ru"):
			self.assertEqual(normalize_lang(lang), lang)

	def test_unknown_falls_back_to_default(self):
		self.assertEqual(normalize_lang("de"), "tr")

	def test_none_falls_back(self):
		self.assertEqual(normalize_lang(None), "tr")

	def test_empty_falls_back(self):
		self.assertEqual(normalize_lang(""), "tr")


class TestResolveContentField(unittest.TestCase):
	def test_returns_requested_lang(self):
		record = {"title_tr": "Başlık", "title_ar": "عنوان", "content_default_lang": "tr"}
		self.assertEqual(resolve_content_field(record, "title", "ar", "tr"), "عنوان")

	def test_falls_back_to_default_when_empty(self):
		record = {"title_tr": "Başlık", "title_ar": "", "content_default_lang": "tr"}
		self.assertEqual(resolve_content_field(record, "title", "ar", "tr"), "Başlık")

	def test_falls_back_to_default_when_missing(self):
		record = {"title_tr": "Başlık", "content_default_lang": "tr"}
		self.assertEqual(resolve_content_field(record, "title", "ru", "tr"), "Başlık")

	def test_non_tr_default(self):
		# Kaynak dili EN olan kayıt: AR boşsa EN'e düşer (TR'ye değil)
		record = {"title_en": "Title", "title_tr": "", "content_default_lang": "en"}
		self.assertEqual(resolve_content_field(record, "title", "ar", "en"), "Title")

	def test_legacy_base_column_fallback(self):
		# Sufix kolonları henüz doldurulmamış eski kayıt → base kolona düşer
		record = {"title": "Eski TR"}
		self.assertEqual(resolve_content_field(record, "title", "en", "tr"), "Eski TR")

	def test_unknown_lang_normalized(self):
		record = {"title_tr": "Başlık", "content_default_lang": "tr"}
		self.assertEqual(resolve_content_field(record, "title", "de", "tr"), "Başlık")

	def test_empty_record(self):
		self.assertEqual(resolve_content_field({}, "title", "en", "tr"), "")


class TestConstants(unittest.TestCase):
	def test_default_is_tr(self):
		self.assertEqual(DEFAULT_LANG, "tr")

	def test_supported_is_tr_only(self):
		# URL/hreflang dili yalnız tr. İçerik dili ayrı (CONTENT_LANGS, dört dil).
		# Buraya bir dil eklemek, o dilin adresinin GERÇEKTEN sunulduğu
		# doğrulanmadan yapılmamalı — kırık alternate Google'da hata olur.
		self.assertEqual(SUPPORTED_LANGS, ("tr",))

	def test_content_langs_four(self):
		self.assertEqual(set(CONTENT_LANGS), {"tr", "en", "ar", "ru"})


if __name__ == "__main__":
	unittest.main()
