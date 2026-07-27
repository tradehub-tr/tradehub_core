"""
page_resolver pure-helper testleri.

Whitelist endpoint'leri (render_listing vb.) Frappe runtime gerektirir;
bu test paketinde sadece pure helper'lar test edilir.

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_page_resolver
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo import page_resolver  # noqa: E402
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
			"title",
			"description",
			"canonical",
			"robots",
			"og_type",
			"og_title",
			"og_description",
			"og_image",
			"og_url",
			"site_name",
			"twitter_handle",
			"json_ld",
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

	def test_listing_and_brand_use_slug(self):
		for dt in ("Listing", "Brand"):
			self.assertEqual(SLUG_FIELD_MAP[dt], "slug")

	def test_admin_seller_profile_uses_seller_code(self):
		self.assertEqual(SLUG_FIELD_MAP["Admin Seller Profile"], "seller_code")

	def test_template_paths_are_relative(self):
		for path in TEMPLATE_MAP.values():
			self.assertFalse(path.startswith("/"))
			self.assertTrue(path.endswith(".html"))


class TestLoadStaticPageSeo(unittest.TestCase):
	def test_unknown_path_returns_none(self):
		with patch.object(page_resolver, "_resolve_static_page", return_value=None):
			self.assertIsNone(page_resolver._load_static_page_seo("/unknown"))

	def test_database_override_is_built_with_shared_meta_builder(self):
		entry = {"path": "/", "title": "Anasayfa", "html_path": "index.html"}
		override = {"page_path": "/", "meta_title": "Güncel"}
		frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda doctype, name: True),
			get_doc=lambda doctype, name: SimpleNamespace(as_dict=lambda: override),
		)
		payload = {"title": "Güncel"}
		with (
			patch.object(page_resolver, "_resolve_static_page", return_value=entry),
			patch.dict(sys.modules, {"frappe": frappe}),
			patch.object(page_resolver.meta_builder, "build_for_static_page", return_value=payload) as build,
		):
			self.assertEqual(page_resolver._load_static_page_seo("/", "tr"), payload)
		build.assert_called_once_with(record=override, page_meta=entry, lang="tr")

	def test_missing_override_uses_safe_registry_default(self):
		entry = {"path": "/", "title": "Anasayfa", "html_path": "index.html"}
		frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda doctype, name: False),
		)
		with (
			patch.object(page_resolver, "_resolve_static_page", return_value=entry),
			patch.dict(sys.modules, {"frappe": frappe}),
			patch.object(
				page_resolver.meta_builder,
				"build_for_static_page",
				return_value={"title": "Anasayfa"},
			) as build,
		):
			page_resolver._load_static_page_seo("/", "tr")
		record = build.call_args.kwargs["record"]
		self.assertEqual(record["page_path"], "/")
		self.assertEqual(record["meta_title"], "Anasayfa")
		self.assertEqual(record["noindex"], 1)


if __name__ == "__main__":
	unittest.main()
