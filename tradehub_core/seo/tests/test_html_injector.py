"""
seo_html_injector pure-function testleri.

Jinja2 gerekir ama Frappe runtime'a bağımlı değil:

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_html_injector
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.seo_html_injector import (  # noqa: E402
	PLACEHOLDER,
	inject_meta_into_html,
	render_seo_head,
)

SAMPLE_HTML = (
	"<!doctype html>\n"
	"<html><head>\n"
	'<meta charset="utf-8">\n'
	f"{PLACEHOLDER}\n"
	"</head><body><h1>test</h1></body></html>"
)


def _seo(**overrides):
	base = {
		"title": "Test Başlık",
		"description": "Test açıklama",
		"canonical": "https://istoc.com/test",
		"robots": "index,follow",
		"og_type": "website",
		"og_title": "Test Başlık",
		"og_description": "Test açıklama",
		"og_image": "https://istoc.com/og.png",
		"og_url": "https://istoc.com/test",
		"site_name": "İstoç",
		"twitter_handle": "@istoctr",
		"json_ld": [],
	}
	base.update(overrides)
	return base


class TestRenderSeoHead(unittest.TestCase):
	def test_includes_title_tag(self):
		out = render_seo_head(_seo())
		self.assertIn("<title>Test Başlık</title>", out)

	def test_includes_description_meta(self):
		out = render_seo_head(_seo())
		self.assertIn('name="description" content="Test açıklama"', out)

	def test_includes_canonical_when_set(self):
		out = render_seo_head(_seo())
		self.assertIn('rel="canonical" href="https://istoc.com/test"', out)

	def test_omits_canonical_when_empty(self):
		out = render_seo_head(_seo(canonical=""))
		self.assertNotIn('rel="canonical"', out)

	def test_includes_og_image_meta(self):
		out = render_seo_head(_seo())
		self.assertIn('property="og:image" content="https://istoc.com/og.png"', out)

	def test_omits_og_image_when_empty(self):
		out = render_seo_head(_seo(og_image=""))
		self.assertNotIn('property="og:image"', out)
		self.assertNotIn('name="twitter:image"', out)

	def test_twitter_card_summary_large_image(self):
		out = render_seo_head(_seo())
		self.assertIn('name="twitter:card" content="summary_large_image"', out)

	def test_robots_directive_rendered(self):
		out = render_seo_head(_seo(robots="noindex,nofollow"))
		self.assertIn('name="robots" content="noindex,nofollow"', out)

	def test_json_ld_block_when_provided(self):
		ld = [{"@type": "Product", "name": "Test Ürün"}]
		out = render_seo_head(_seo(json_ld=ld))
		self.assertIn("application/ld+json", out)
		self.assertIn('"@type"', out)
		self.assertIn("Test", out)

	def test_no_json_ld_block_when_empty(self):
		out = render_seo_head(_seo())
		self.assertNotIn("application/ld+json", out)

	def test_html_autoescape_for_description(self):
		# XSS güvenliği: description'da < > karakterleri escape edilmeli
		out = render_seo_head(_seo(description="<script>alert(1)</script>"))
		self.assertNotIn("<script>", out)
		self.assertIn("&lt;script&gt;", out)


class TestInjectMetaIntoHtml(unittest.TestCase):
	def test_replaces_placeholder(self):
		out = inject_meta_into_html(SAMPLE_HTML, _seo())
		self.assertNotIn(PLACEHOLDER, out)
		self.assertIn("<title>Test Başlık</title>", out)

	def test_passthrough_when_no_placeholder(self):
		raw = "<html><head></head><body></body></html>"
		out = inject_meta_into_html(raw, _seo())
		self.assertEqual(out, raw)

	def test_idempotent_second_call_is_noop(self):
		once = inject_meta_into_html(SAMPLE_HTML, _seo())
		twice = inject_meta_into_html(once, _seo())
		self.assertEqual(once, twice)

	def test_favicon_links_always_rendered(self):
		"""Storefront dist mount edilmese de bot HTML'i favicon taşımalı."""
		out = inject_meta_into_html(SAMPLE_HTML, _seo())
		self.assertIn('rel="icon" href="/favicon.ico"', out)
		self.assertIn('sizes="96x96" href="/images/istoc-favicon-96.png"', out)
		self.assertIn('rel="apple-touch-icon"', out)

	def test_hardcoded_favicon_links_deduplicated(self):
		"""Vite build'den gelen ikon linkleri sökülür; şablon tek otorite."""
		raw = SAMPLE_HTML.replace(
			'<meta charset="utf-8">',
			'<meta charset="utf-8">\n'
			'<link rel="icon" type="image/png" sizes="32x32" href="/images/istoc-favicon-32.png" />\n'
			'<link rel="apple-touch-icon" sizes="180x180" href="/icons/apple-touch-icon.png" />',
		)
		out = inject_meta_into_html(raw, _seo())
		self.assertEqual(out.count('rel="apple-touch-icon"'), 1)
		self.assertEqual(out.count('href="/images/istoc-favicon-32.png"'), 1)

	def test_replaces_only_first_occurrence(self):
		double = f"<head>\n{PLACEHOLDER}\n{PLACEHOLDER}\n</head>"
		out = inject_meta_into_html(double, _seo())
		# İkinci placeholder hala kalmalı (replace count=1)
		self.assertIn(PLACEHOLDER, out)


if __name__ == "__main__":
	unittest.main()
