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
	DEFAULT_LANG,
	SUPPORTED_LANGS,
	build_hreflang_links,
	get_field_with_fallback,
	localize_url,
	parse_lang_from_path,
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


class TestConstants(unittest.TestCase):
	def test_default_is_tr(self):
		self.assertEqual(DEFAULT_LANG, "tr")

	def test_supported_includes_tr_en(self):
		self.assertIn("tr", SUPPORTED_LANGS)
		self.assertIn("en", SUPPORTED_LANGS)


if __name__ == "__main__":
	unittest.main()
