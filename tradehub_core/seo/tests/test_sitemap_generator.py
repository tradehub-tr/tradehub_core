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

	def test_seller_uses_seller_code_slug(self):
		"""BE-MAP bug fix: mağaza URL'leri seller_code taşır, 'slug' değil."""
		self.assertEqual(DOCTYPE_CONFIG["Admin Seller Profile"]["slug_field"], "seller_code")


class TestSitemapFileName(unittest.TestCase):
	def test_single_part_has_no_suffix(self):
		from tradehub_core.seo.sitemap_generator import sitemap_file_name

		self.assertEqual(sitemap_file_name("products", 1, 1), "sitemap-products.xml")

	def test_multi_part_is_numbered(self):
		from tradehub_core.seo.sitemap_generator import sitemap_file_name

		self.assertEqual(sitemap_file_name("products", 3, 21), "sitemap-products-3.xml")


class TestParseSitemapName(unittest.TestCase):
	"""BE-MAP guard: yalnız bilinen adlar + pozitif parça; keyfi ad 404."""

	def test_plain_name(self):
		from tradehub_core.seo.sitemap_generator import parse_sitemap_name

		self.assertEqual(parse_sitemap_name("products"), ("Listing", 1))
		self.assertEqual(parse_sitemap_name("static-pages"), ("Static Page SEO", 1))

	def test_numbered_part(self):
		from tradehub_core.seo.sitemap_generator import parse_sitemap_name

		self.assertEqual(parse_sitemap_name("products-3"), ("Listing", 3))
		self.assertEqual(parse_sitemap_name("static-pages-2"), ("Static Page SEO", 2))

	def test_unknown_or_malicious_rejected(self):
		from tradehub_core.seo.sitemap_generator import parse_sitemap_name

		for bad in ("unknown", "products-0", "products--2", "../etc/passwd", "products-x", ""):
			self.assertEqual(parse_sitemap_name(bad)[0], None, bad)


class TestBuildIndexParts(unittest.TestCase):
	def test_multi_part_index_lists_numbered_files(self):
		"""build_index parça sayısına göre numaralı loc'lar üretir."""
		from unittest.mock import patch

		from tradehub_core.seo import sitemap_generator

		with patch.object(sitemap_generator, "_site_url", return_value="https://istoc.com"):
			xml = sitemap_generator.build_index({"products": 3, "brands": 1})
		self.assertIn("https://istoc.com/sitemap-products-1.xml", xml)
		self.assertIn("https://istoc.com/sitemap-products-3.xml", xml)
		self.assertIn("https://istoc.com/sitemap-brands.xml", xml)
		self.assertNotIn("sitemap-brands-1.xml", xml)


class TestChunkStreaming(unittest.TestCase):
	"""BE-MAP bug fix: chunks[0] kaybı — tüm parçalar üretilmeli."""

	def test_all_chunks_emitted_and_no_empty_tail(self):
		from unittest.mock import patch

		from tradehub_core.seo import sitemap_generator as sg

		rows = [{"name": f"L{i}", "slug": f"urun-{i}", "modified": "2026-07-23"} for i in range(120)]
		with (
			patch.object(sg, "MAX_URLS_PER_SITEMAP", 50),
			patch.object(sg, "_iter_records_for", return_value=iter(rows)),
			patch.object(sg, "_site_url", return_value="https://istoc.com"),
		):
			chunks = list(sg.build_chunks_for_type("Listing"))
		self.assertEqual(len(chunks), 3)  # 50 + 50 + 20
		self.assertIn("urun-0", chunks[0])
		self.assertIn("urun-119", chunks[2])

	def test_exact_multiple_has_no_extra_empty_chunk(self):
		from unittest.mock import patch

		from tradehub_core.seo import sitemap_generator as sg

		rows = [{"name": f"L{i}", "slug": f"u-{i}", "modified": "2026-07-23"} for i in range(100)]
		with (
			patch.object(sg, "MAX_URLS_PER_SITEMAP", 50),
			patch.object(sg, "_iter_records_for", return_value=iter(rows)),
			patch.object(sg, "_site_url", return_value="https://istoc.com"),
		):
			chunks = list(sg.build_chunks_for_type("Listing"))
		self.assertEqual(len(chunks), 2)

	def test_empty_dataset_yields_single_valid_urlset(self):
		from unittest.mock import patch

		from tradehub_core.seo import sitemap_generator as sg

		with (
			patch.object(sg, "_iter_records_for", return_value=iter([])),
			patch.object(sg, "_site_url", return_value="https://istoc.com"),
		):
			chunks = list(sg.build_chunks_for_type("Listing"))
		self.assertEqual(len(chunks), 1)
		self.assertIn("<urlset", chunks[0])

	def test_uretilen_entry_sayisi_ham_satirdan_fazlaysa_parca_sinirini_asmaz(self):
		"""Düzeltme turu 1 (görev denetimi — Important, Task 5): watch girdileri
		eklenince bir satır BİRDEN FAZLA `<url>` üretebiliyor (ürün + watch).
		Flush kararı artık ÜRETİLEN entry sayısına bağlı — `_entries_for_rows`
		burada mock'lanıp her satırın 2 entry ürettiği simüle ediliyor, DB'ye
		dokunmadan (gerçek watch girdisi üretimi `test_media_video_seo.py`'de
		ayrıca doğrulanıyor)."""
		from unittest.mock import patch

		from tradehub_core.seo import sitemap_generator as sg

		rows = [{"name": f"L{i}"} for i in range(5)]

		def sahte_entries_for_rows(raw_rows, cfg, site):
			entries = []
			for row in raw_rows:
				entries.append({"loc": f"{site}/urun/{row['name']}"})
				entries.append({"loc": f"{site}/medya/v/{row['name']}"})
			return entries

		with (
			patch.object(sg, "MAX_URLS_PER_SITEMAP", 3),
			patch.object(sg, "_iter_records_for", return_value=iter(rows)),
			patch.object(sg, "_site_url", return_value="https://istoc.com"),
			patch.object(sg, "_entries_for_rows", side_effect=sahte_entries_for_rows),
		):
			chunks = list(sg.build_chunks_for_type("Listing"))

		toplam_url = 0
		for xml in chunks:
			sayisi = xml.count("<url>")
			self.assertLessEqual(sayisi, 3, "hiçbir parça MAX_URLS_PER_SITEMAP'i aşmamalı")
			toplam_url += sayisi
		self.assertEqual(toplam_url, 10, "5 satır x 2 entry = 10 toplam, kayıp/fazlalık olmamalı")


if __name__ == "__main__":
	unittest.main()
