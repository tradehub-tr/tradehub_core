"""static_pages_registry pure-helper testleri.

cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_static_pages_registry
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.static_pages_registry import STATIC_PAGES, find_entry, indexable_paths  # noqa: E402


class TestStaticPagesRegistry(unittest.TestCase):
	def test_has_minimum_entries(self):
		self.assertGreaterEqual(len(STATIC_PAGES), 30)

	def test_all_paths_unique(self):
		paths = [e["path"] for e in STATIC_PAGES]
		self.assertEqual(len(paths), len(set(paths)))

	def test_all_paths_start_with_slash(self):
		for e in STATIC_PAGES:
			self.assertTrue(e["path"].startswith("/"), f"{e['path']} should start with /")

	def test_all_entries_have_required_keys(self):
		required = {"path", "title", "html_path", "indexable_default"}
		for e in STATIC_PAGES:
			self.assertTrue(
				required.issubset(set(e.keys())), f"{e['path']} missing keys: {required - set(e.keys())}"
			)

	def test_homepage_is_indexable(self):
		entry = find_entry("/")
		self.assertIsNotNone(entry)
		self.assertTrue(entry["indexable_default"])

	def test_legal_pages_are_noindex(self):
		"""Kullanıcı kararı 2026-07-23: 4 yasal sayfa Google'a kapalı,
		sitede erişilebilir (frontend staticMeta NOINDEX_FILES ile senkron)."""
		for path in ("/kvkk", "/iade-kosullari", "/fikri-mulkiyet", "/yasal-uyari"):
			entry = find_entry(path)
			self.assertIsNotNone(entry, path)
			self.assertFalse(entry["indexable_default"], path)

	def test_cart_is_hidden(self):
		entry = find_entry("/sepet")
		self.assertIsNotNone(entry)
		self.assertFalse(entry["indexable_default"])

	def test_find_missing_returns_none(self):
		self.assertIsNone(find_entry("/asdf-nonexistent"))

	def test_indexable_paths_helper(self):
		paths = indexable_paths()
		self.assertIn("/", paths)
		self.assertIn("/gizlilik", paths)
		self.assertNotIn("/sepet", paths)
		self.assertNotIn("/kvkk", paths)


if __name__ == "__main__":
	unittest.main()
