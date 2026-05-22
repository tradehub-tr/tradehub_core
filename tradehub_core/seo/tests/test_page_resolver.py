"""
page_resolver pure-helper testleri.

Whitelist endpoint'leri (render_listing vb.) Frappe runtime gerektirir;
bu test paketinde sadece pure helper'lar test edilir.

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_page_resolver
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.page_resolver import (  # noqa: E402
	SLUG_FIELD_MAP,
	TEMPLATE_MAP,
	_build_404_seo,
	_minimal_fallback_html,
)
from tradehub_core.seo.seo_html_injector import PLACEHOLDER  # noqa: E402


class TestMinimalFallbackHtml(unittest.TestCase):
	def test_includes_placeholder(self):
		html = _minimal_fallback_html()
		self.assertIn(PLACEHOLDER, html)

	def test_includes_doctype_declaration(self):
		html = _minimal_fallback_html()
		self.assertTrue(html.startswith("<!doctype html>"))

	def test_includes_viewport_meta(self):
		html = _minimal_fallback_html()
		self.assertIn("viewport", html)

	def test_is_valid_html_structure(self):
		html = _minimal_fallback_html()
		self.assertIn("<html", html)
		self.assertIn("</html>", html)
		self.assertIn("<head>", html)
		self.assertIn("</head>", html)
		self.assertIn("<body>", html)
		self.assertIn("</body>", html)


class TestBuild404Seo(unittest.TestCase):
	def test_404_robots_is_noindex(self):
		seo = _build_404_seo("https://istoc.com")
		self.assertEqual(seo["robots"], "noindex,nofollow")

	def test_404_title_includes_site_name(self):
		seo = _build_404_seo("https://istoc.com", site_name="MySite")
		self.assertIn("MySite", seo["title"])

	def test_404_canonical_empty(self):
		seo = _build_404_seo("https://istoc.com")
		self.assertEqual(seo["canonical"], "")

	def test_404_has_all_required_keys(self):
		seo = _build_404_seo("https://istoc.com")
		required = {
			"title", "description", "canonical", "robots",
			"og_type", "og_title", "og_description", "og_image", "og_url",
			"site_name", "twitter_handle", "json_ld",
		}
		self.assertTrue(required.issubset(set(seo.keys())))


class TestMaps(unittest.TestCase):
	def test_template_map_has_all_doctypes(self):
		expected = {"Listing", "Product Category", "Brand", "Admin Seller Profile"}
		self.assertEqual(set(TEMPLATE_MAP.keys()), expected)

	def test_slug_field_map_has_all_doctypes(self):
		expected = {"Listing", "Product Category", "Brand", "Admin Seller Profile"}
		self.assertEqual(set(SLUG_FIELD_MAP.keys()), expected)

	def test_product_category_uses_url_slug(self):
		self.assertEqual(SLUG_FIELD_MAP["Product Category"], "url_slug")

	def test_other_doctypes_use_slug(self):
		for dt in ("Listing", "Brand", "Admin Seller Profile"):
			self.assertEqual(SLUG_FIELD_MAP[dt], "slug")

	def test_template_paths_are_relative(self):
		for path in TEMPLATE_MAP.values():
			self.assertFalse(path.startswith("/"))
			self.assertTrue(path.endswith(".html"))


if __name__ == "__main__":
	unittest.main()
