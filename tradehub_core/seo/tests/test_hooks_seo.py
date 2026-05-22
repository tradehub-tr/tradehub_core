"""
hooks_seo pure-function unit testleri.

Frappe runtime'a bağımlı değil; standalone unittest ile koşar:

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_hooks_seo
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.hooks_seo import _build_slug, _check_seo_lengths  # noqa: E402


class TestBuildSlug(unittest.TestCase):
	def test_basic_from_title(self):
		slug = _build_slug("iPhone 15 Pro", "LST-2026-000001", slug_exists=lambda s: False)
		self.assertEqual(slug, "iphone-15-pro")

	def test_turkish_title(self):
		slug = _build_slug("Çiçek Böreği", "LST-AAA", slug_exists=lambda s: False)
		self.assertEqual(slug, "cicek-boregi")

	def test_falls_back_to_name_when_title_empty(self):
		slug = _build_slug("", "LST-2026-000042", slug_exists=lambda s: False)
		self.assertEqual(slug, "lst-2026-000042")

	def test_empty_when_both_empty(self):
		slug = _build_slug("", "", slug_exists=lambda s: False)
		self.assertEqual(slug, "")

	def test_duplicate_gets_name_suffix(self):
		slug = _build_slug("iPhone 15", "LST-ZZZZZZ", slug_exists=lambda s: True)
		self.assertEqual(slug, "iphone-15-ZZZZZZ")

	def test_duplicate_with_short_name_uses_fallback_suffix(self):
		slug = _build_slug("Test", "", slug_exists=lambda s: True)
		self.assertEqual(slug, "test-x")

	def test_only_unicode_returns_empty(self):
		slug = _build_slug("✓✓✓", "ABC123", slug_exists=lambda s: False)
		# title slug'lanamaz, fallback name var
		self.assertEqual(slug, "abc123")


class TestCheckSeoLengths(unittest.TestCase):
	def test_no_warnings_when_within_limits(self):
		warnings = _check_seo_lengths("Kısa başlık", "Kısa açıklama")
		self.assertEqual(warnings, [])

	def test_warns_meta_title_over_70(self):
		warnings = _check_seo_lengths("A" * 71, "")
		self.assertEqual(len(warnings), 1)
		self.assertIn("meta_title", warnings[0])
		self.assertIn("71", warnings[0])

	def test_warns_meta_description_over_160(self):
		warnings = _check_seo_lengths("OK", "B" * 161)
		self.assertEqual(len(warnings), 1)
		self.assertIn("meta_description", warnings[0])

	def test_warns_both_when_both_over(self):
		warnings = _check_seo_lengths("A" * 100, "B" * 200)
		self.assertEqual(len(warnings), 2)

	def test_handles_none_inputs(self):
		warnings = _check_seo_lengths(None, None)
		self.assertEqual(warnings, [])

	def test_strips_whitespace_before_check(self):
		# Tam sınır + boşluk; strip sonrası limit'i aşmıyor
		warnings = _check_seo_lengths("A" * 70 + "   ", "")
		self.assertEqual(warnings, [])


if __name__ == "__main__":
	unittest.main()
