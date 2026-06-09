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
	parse_lang_from_path,
	resolve_content_field,
	slug_field_for,
)

SITE = "https://istoc.com"


class TestParseLangFromPath(unittest.TestCase):
	def test_no_prefix_returns_default(self):
		self.assertEqual(parse_lang_from_path("/urun/x"), ("tr", "/urun/x"))

	def test_en_prefix(self):
		self.assertEqual(parse_lang_from_path("/en/urun/x"), ("en", "/urun/x"))

	def test_tr_explicit_prefix(self):
		# /tr/ prefix'i de normalize edilir
		self.assertEqual(parse_lang_from_path("/tr/urun/x"), ("tr", "/urun/x"))

	def test_en_alone(self):
		self.assertEqual(parse_lang_from_path("/en"), ("en", "/"))

	def test_root(self):
		self.assertEqual(parse_lang_from_path("/"), ("tr", "/"))

	def test_empty(self):
		self.assertEqual(parse_lang_from_path(""), ("tr", "/"))

	def test_unknown_prefix(self):
		# /de/ desteklenmiyor → tr olarak kabul
		self.assertEqual(parse_lang_from_path("/de/urun/x"), ("tr", "/de/urun/x"))

	def test_no_leading_slash(self):
		self.assertEqual(parse_lang_from_path("en/urun"), ("en", "/urun"))


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
	def test_tr_no_prefix(self):
		self.assertEqual(localize_url("/urun/x", "tr"), "/urun/x")

	def test_en_adds_prefix(self):
		self.assertEqual(localize_url("/urun/x", "en"), "/en/urun/x")

	def test_root_tr(self):
		self.assertEqual(localize_url("/", "tr"), "/")

	def test_root_en(self):
		self.assertEqual(localize_url("/", "en"), "/en/")

	def test_unknown_lang_no_change(self):
		self.assertEqual(localize_url("/urun/x", "de"), "/urun/x")

	def test_already_prefixed(self):
		self.assertEqual(localize_url("/en/urun/x", "en"), "/en/urun/x")

	def test_no_leading_slash(self):
		self.assertEqual(localize_url("urun/x", "en"), "/en/urun/x")


class TestBuildHreflangLinks(unittest.TestCase):
	def test_returns_three_entries(self):
		links = build_hreflang_links("/urun/iphone", SITE)
		self.assertEqual(len(links), 3)

	def test_tr_link(self):
		links = build_hreflang_links("/urun/iphone", SITE)
		tr = next(l for l in links if l["hreflang"] == "tr")
		self.assertEqual(tr["href"], "https://istoc.com/urun/iphone")

	def test_en_link(self):
		links = build_hreflang_links("/urun/iphone", SITE)
		en = next(l for l in links if l["hreflang"] == "en")
		self.assertEqual(en["href"], "https://istoc.com/en/urun/iphone")

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

	def test_supported_includes_tr_en(self):
		self.assertIn("tr", SUPPORTED_LANGS)
		self.assertIn("en", SUPPORTED_LANGS)

	def test_content_langs_four(self):
		self.assertEqual(set(CONTENT_LANGS), {"tr", "en", "ar", "ru"})


if __name__ == "__main__":
	unittest.main()
