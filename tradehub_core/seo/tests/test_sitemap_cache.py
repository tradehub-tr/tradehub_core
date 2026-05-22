"""sitemap_cache pure-function testleri.

Frappe runtime'a bağımlı değil; standalone unittest:

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_sitemap_cache
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.sitemap_cache import (  # noqa: E402
	CACHE_KEY_PREFIX,
	DIRTY_KEY_PREFIX,
	InMemoryCacheBackend,
	SitemapCache,
	cache_key_for,
	dirty_key_for,
)


class TestCacheKeys(unittest.TestCase):
	def test_cache_key_for_index(self):
		self.assertEqual(cache_key_for("index"), f"{CACHE_KEY_PREFIX}index")

	def test_cache_key_for_listing(self):
		self.assertEqual(cache_key_for("Listing"), f"{CACHE_KEY_PREFIX}Listing")

	def test_dirty_key_for_listing(self):
		self.assertEqual(dirty_key_for("Listing"), f"{DIRTY_KEY_PREFIX}Listing")

	def test_dirty_key_for_product_category(self):
		self.assertEqual(dirty_key_for("Product Category"), f"{DIRTY_KEY_PREFIX}Product Category")


class TestCacheBackend(unittest.TestCase):
	def setUp(self):
		self.backend = InMemoryCacheBackend()

	def test_get_returns_none_when_missing(self):
		self.assertIsNone(self.backend.get("any-key"))

	def test_set_then_get(self):
		self.backend.set("k", "value", ttl=60)
		self.assertEqual(self.backend.get("k"), "value")

	def test_delete(self):
		self.backend.set("k", "v", ttl=60)
		self.backend.delete("k")
		self.assertIsNone(self.backend.get("k"))

	def test_overwrite(self):
		self.backend.set("k", "v1", ttl=60)
		self.backend.set("k", "v2", ttl=60)
		self.assertEqual(self.backend.get("k"), "v2")


class TestDirtyFlagLogic(unittest.TestCase):
	def setUp(self):
		self.backend = InMemoryCacheBackend()
		self.cache = SitemapCache(backend=self.backend)

	def test_no_dirty_flag_initially(self):
		self.assertFalse(self.cache.is_dirty("Listing"))

	def test_mark_dirty(self):
		self.cache.mark_dirty("Listing")
		self.assertTrue(self.cache.is_dirty("Listing"))

	def test_clear_dirty(self):
		self.cache.mark_dirty("Listing")
		self.cache.clear_dirty("Listing")
		self.assertFalse(self.cache.is_dirty("Listing"))

	def test_dirty_isolated_per_doctype(self):
		self.cache.mark_dirty("Listing")
		self.assertFalse(self.cache.is_dirty("Brand"))


class TestSitemapCacheGetSet(unittest.TestCase):
	def setUp(self):
		self.backend = InMemoryCacheBackend()
		self.cache = SitemapCache(backend=self.backend)

	def test_get_xml_missing_returns_none(self):
		self.assertIsNone(self.cache.get_xml("Listing"))

	def test_set_then_get_xml(self):
		self.cache.set_xml("Listing", "<urlset></urlset>")
		self.assertEqual(self.cache.get_xml("Listing"), "<urlset></urlset>")

	def test_index_separate_from_doctype(self):
		self.cache.set_xml("index", "<sitemapindex></sitemapindex>")
		self.cache.set_xml("Listing", "<urlset></urlset>")
		self.assertEqual(self.cache.get_xml("index"), "<sitemapindex></sitemapindex>")
		self.assertEqual(self.cache.get_xml("Listing"), "<urlset></urlset>")


if __name__ == "__main__":
	unittest.main()
