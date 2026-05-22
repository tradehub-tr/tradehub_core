"""sitemap_generator pure-function testleri.

cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_sitemap_generator
"""

import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.sitemap_generator import (  # noqa: E402
	DOCTYPE_CONFIG,
	MAX_URLS_PER_SITEMAP,
	build_index_xml,
	build_urlset_xml,
	chunk_urls_for_pagination,
	urlentry,
)

SAMPLE_URLS = [
	{
		"loc": "https://istoc.com/urun/iphone-15-pro",
		"lastmod": "2026-05-20",
		"changefreq": "weekly",
		"priority": "0.9",
	},
	{
		"loc": "https://istoc.com/urun/samsung-s24",
		"lastmod": "2026-05-21",
		"changefreq": "weekly",
		"priority": "0.9",
	},
]

SAMPLE_SITEMAPS = [
	{"loc": "https://istoc.com/sitemap-products.xml", "lastmod": "2026-05-21"},
	{"loc": "https://istoc.com/sitemap-categories.xml", "lastmod": "2026-05-21"},
]


class TestBuildUrlsetXml(unittest.TestCase):
	def test_returns_valid_xml(self):
		xml = build_urlset_xml(SAMPLE_URLS)
		root = ET.fromstring(xml)
		self.assertTrue(root.tag.endswith("urlset"))

	def test_includes_all_urls(self):
		xml = build_urlset_xml(SAMPLE_URLS)
		self.assertIn("/urun/iphone-15-pro", xml)
		self.assertIn("/urun/samsung-s24", xml)

	def test_includes_priority_and_changefreq(self):
		xml = build_urlset_xml(SAMPLE_URLS)
		self.assertIn("<priority>0.9</priority>", xml)
		self.assertIn("<changefreq>weekly</changefreq>", xml)

	def test_xml_declaration_present(self):
		xml = build_urlset_xml(SAMPLE_URLS)
		self.assertTrue(xml.startswith("<?xml"))

	def test_empty_urlset_valid(self):
		xml = build_urlset_xml([])
		root = ET.fromstring(xml)
		self.assertTrue(root.tag.endswith("urlset"))
		self.assertEqual(len(list(root)), 0)

	def test_namespace_present(self):
		xml = build_urlset_xml(SAMPLE_URLS)
		self.assertIn('xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"', xml)


class TestBuildIndexXml(unittest.TestCase):
	def test_returns_valid_sitemapindex(self):
		xml = build_index_xml(SAMPLE_SITEMAPS)
		root = ET.fromstring(xml)
		self.assertTrue(root.tag.endswith("sitemapindex"))

	def test_includes_all_sub_sitemaps(self):
		xml = build_index_xml(SAMPLE_SITEMAPS)
		self.assertIn("sitemap-products.xml", xml)
		self.assertIn("sitemap-categories.xml", xml)

	def test_includes_lastmod(self):
		xml = build_index_xml(SAMPLE_SITEMAPS)
		self.assertIn("<lastmod>2026-05-21</lastmod>", xml)


class TestUrlEntry(unittest.TestCase):
	def test_basic_entry(self):
		entry = urlentry(
			loc="https://istoc.com/urun/x",
			lastmod="2026-05-20",
			priority="0.9",
			changefreq="weekly",
		)
		self.assertEqual(entry["loc"], "https://istoc.com/urun/x")
		self.assertEqual(entry["priority"], "0.9")

	def test_defaults(self):
		entry = urlentry(loc="https://istoc.com/x", lastmod="2026-05-20")
		self.assertEqual(entry["priority"], "0.5")
		self.assertEqual(entry["changefreq"], "monthly")


class TestPagination(unittest.TestCase):
	def test_no_split_when_under_limit(self):
		urls = [{"loc": f"https://x.com/{i}", "lastmod": "2026-05-21"} for i in range(100)]
		chunks = chunk_urls_for_pagination(urls)
		self.assertEqual(len(chunks), 1)
		self.assertEqual(len(chunks[0]), 100)

	def test_splits_at_50k(self):
		urls = [
			{"loc": f"https://x.com/{i}", "lastmod": "2026-05-21"} for i in range(MAX_URLS_PER_SITEMAP + 5)
		]
		chunks = chunk_urls_for_pagination(urls)
		self.assertEqual(len(chunks), 2)
		self.assertEqual(len(chunks[0]), MAX_URLS_PER_SITEMAP)
		self.assertEqual(len(chunks[1]), 5)

	def test_three_chunks_when_100k(self):
		urls = [
			{"loc": f"https://x.com/{i}", "lastmod": "2026-05-21"}
			for i in range(MAX_URLS_PER_SITEMAP * 2 + 1)
		]
		chunks = chunk_urls_for_pagination(urls)
		self.assertEqual(len(chunks), 3)


class TestDoctypeConfig(unittest.TestCase):
	def test_listing_config(self):
		cfg = DOCTYPE_CONFIG["Listing"]
		self.assertEqual(cfg["url_prefix"], "/urun")
		self.assertEqual(cfg["priority"], "0.9")
		self.assertEqual(cfg["changefreq"], "weekly")
		self.assertEqual(cfg["slug_field"], "slug")

	def test_product_category_uses_url_slug(self):
		cfg = DOCTYPE_CONFIG["Product Category"]
		self.assertEqual(cfg["slug_field"], "url_slug")

	def test_all_four_doctypes_present(self):
		expected = {"Listing", "Product Category", "Brand", "Admin Seller Profile", "Static Page SEO"}
		self.assertEqual(set(DOCTYPE_CONFIG.keys()), expected)


if __name__ == "__main__":
	unittest.main()
