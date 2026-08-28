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

	def test_unsupported_language_uses_turkish_metadata(self):
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
			page_resolver.get_static_page_meta("/", "unsupported")
		build.assert_called_once_with(
			record={
				"page_path": "/",
				"page_title": "Anasayfa",
				"meta_title": "Anasayfa",
				"meta_description": "",
				"noindex": 1,
			},
			page_meta=entry,
			lang="tr",
		)


class TestWhitelistRegistration(unittest.TestCase):
	def test_static_meta_endpoint_is_registered_for_guests(self):
		registered = []

		def whitelist(**kwargs):
			def decorate(fn):
				registered.append((fn, kwargs))
				return fn

			return decorate

		original_functions = {
			name: getattr(page_resolver, name)
			for name in (
				"render_listing",
				"render_category",
				"render_brand",
				"render_seller",
				"render_media_watch",
				"render_static_page",
				"get_static_page_meta",
			)
		}
		try:
			with patch.dict(sys.modules, {"frappe": SimpleNamespace(whitelist=whitelist)}):
				page_resolver._register_whitelists()
			self.assertIn(
				(original_functions["get_static_page_meta"], {"allow_guest": True}),
				registered,
			)
			self.assertIn(
				(original_functions["render_media_watch"], {"allow_guest": True}),
				registered,
			)
		finally:
			for name, fn in original_functions.items():
				setattr(page_resolver, name, fn)


class TestAbsoluteMediaUrl(unittest.TestCase):
	def test_relative_path_prefixed_with_site(self):
		self.assertEqual(
			page_resolver._absolute_media_url("/files/a.jpg", "https://istoc.com"),
			"https://istoc.com/files/a.jpg",
		)

	def test_absolute_url_unchanged(self):
		self.assertEqual(
			page_resolver._absolute_media_url("https://cdn.example.com/a.jpg", "https://istoc.com"),
			"https://cdn.example.com/a.jpg",
		)

	def test_empty_returns_empty(self):
		self.assertEqual(page_resolver._absolute_media_url("", "https://istoc.com"), "")


class TestWatchVideoSeo(unittest.TestCase):
	"""`_watch_video_seo` pure — Frappe gerektirmez (`build_video_object` da pure)."""

	def _data(self, **overrides):
		base = {
			"title": "Video Başlık",
			"caption": "Altyazı",
			"description": "Açıklama",
			"posterUrl": "/files/poster.jpg",
			"sources": [{"src": "/files/video.mp4", "type": "video/mp4"}],
			"durationSec": 42,
			"uploadDate": "2026-08-01",
			"transcript": "merhaba",
			"canonical": "https://istoc.com/medya/v/ornek",
			"robots": "index,follow",
			"indexable": True,
		}
		base.update(overrides)
		return base

	def test_indexable_seo_has_canonical_and_video_object(self):
		seo = page_resolver._watch_video_seo(self._data(), "ornek", "https://istoc.com")
		self.assertEqual(seo["canonical"], "https://istoc.com/medya/v/ornek")
		self.assertEqual(seo["robots"], "index,follow")
		self.assertEqual(len(seo["json_ld"]), 1)
		video = seo["json_ld"][0]
		self.assertEqual(video["@type"], "VideoObject")
		self.assertEqual(video["@context"], "https://schema.org")
		self.assertEqual(
			video["potentialAction"]["target"]["urlTemplate"],
			"https://istoc.com/medya/v/ornek?t={seek_to_second_number}",
		)
		self.assertEqual(video["potentialAction"]["startOffset-input"], "required name=seek_to_second_number")

	def test_og_video_and_og_image_absolute(self):
		seo = page_resolver._watch_video_seo(self._data(), "ornek", "https://istoc.com")
		self.assertEqual(seo["og_image"], "https://istoc.com/files/poster.jpg")
		self.assertEqual(seo["og_video"], "https://istoc.com/files/video.mp4")

	def test_postersiz_video_json_ld_atlanir(self):
		data = self._data(posterUrl="", robots="noindex,follow,nosnippet", indexable=False)
		seo = page_resolver._watch_video_seo(data, "ornek", "https://istoc.com")
		self.assertEqual(seo["json_ld"], [])
		self.assertIn("noindex", seo["robots"])
		self.assertEqual(seo["canonical"], "https://istoc.com/medya/v/ornek", "canonical noindex'te de kalır")

	def test_og_video_type_ilk_source_tipinden_gelir(self):
		seo = page_resolver._watch_video_seo(self._data(), "ornek", "https://istoc.com")
		self.assertEqual(seo["og_video_type"], "video/mp4")

	def test_og_video_type_kaynak_yoksa_bos(self):
		data = self._data(sources=[])
		seo = page_resolver._watch_video_seo(data, "ornek", "https://istoc.com")
		self.assertEqual(seo["og_video"], "")
		self.assertEqual(seo["og_video_type"], "")

	def test_og_video_secure_url_https_sitede_eklenir(self):
		seo = page_resolver._watch_video_seo(self._data(), "ornek", "https://istoc.com")
		self.assertEqual(seo["og_video_secure_url"], "https://istoc.com/files/video.mp4")

	def test_og_video_secure_url_http_sitede_eklenmez(self):
		seo = page_resolver._watch_video_seo(self._data(), "ornek", "http://istoc.local")
		self.assertEqual(seo["og_video_secure_url"], "")

	def test_og_video_secure_url_width_height_yok(self):
		"""Ruling: width/height ATLANIR — videoda alan yok."""
		seo = page_resolver._watch_video_seo(self._data(), "ornek", "https://istoc.com")
		self.assertNotIn("og_video_width", seo)
		self.assertNotIn("og_video_height", seo)


class TestIsSafeRedirectTarget(unittest.TestCase):
	"""Görev denetimi düzeltme turu 1 — 301 hedefinde ikinci savunma katmanı."""

	def test_files_prefix_kabul_edilir(self):
		self.assertTrue(page_resolver._is_safe_redirect_target("/files/video.mp4"))

	def test_medya_v_prefix_kabul_edilir(self):
		self.assertTrue(page_resolver._is_safe_redirect_target("/medya/v/yeni-slug"))

	def test_harici_host_reddedilir(self):
		self.assertFalse(page_resolver._is_safe_redirect_target("https://evil.example"))

	def test_protokolsuz_harici_host_reddedilir(self):
		self.assertFalse(page_resolver._is_safe_redirect_target("//evil.example"))

	def test_alakasiz_path_reddedilir(self):
		self.assertFalse(page_resolver._is_safe_redirect_target("/urun/baska-bir-yer"))

	def test_bos_deger_reddedilir(self):
		self.assertFalse(page_resolver._is_safe_redirect_target(""))


if __name__ == "__main__":
	unittest.main()
