"""redirect_cache pure-function testleri.

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_redirect_cache
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.redirect_cache import (  # noqa: E402
	InMemoryCacheBackend,
	RedirectCache,
)


REDIRECTS_SAMPLE = [
	{"source_path": "/a", "target_path": "/b", "match_type": "exact", "status_code": "301"},
	{"source_path": "/c", "target_path": "/d", "match_type": "exact", "status_code": "302"},
]


class TestRedirectCache(unittest.TestCase):
	def setUp(self):
		self.cache = RedirectCache(backend=InMemoryCacheBackend())

	def test_get_returns_none_when_empty(self):
		self.assertIsNone(self.cache.get_all_redirects())

	def test_set_then_get_roundtrip(self):
		self.cache.set_all_redirects(REDIRECTS_SAMPLE)
		result = self.cache.get_all_redirects()
		self.assertEqual(len(result), 2)
		self.assertEqual(result[0]["source_path"], "/a")

	def test_invalidate_clears_cache(self):
		self.cache.set_all_redirects(REDIRECTS_SAMPLE)
		self.cache.invalidate()
		self.assertIsNone(self.cache.get_all_redirects())

	def test_empty_list_is_cached(self):
		self.cache.set_all_redirects([])
		result = self.cache.get_all_redirects()
		self.assertEqual(result, [])


if __name__ == "__main__":
	unittest.main()
