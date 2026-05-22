"""
slugify_tr unit testleri.

Frappe runtime'a bağımlı değil; standalone unittest ile koşar:

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_slugify
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.slugify import slugify_tr  # noqa: E402


class TestSlugifyTr(unittest.TestCase):
	def test_basic_lowercase(self):
		self.assertEqual(slugify_tr("iPhone 15 Pro"), "iphone-15-pro")

	def test_turkish_chars(self):
		self.assertEqual(slugify_tr("Çiçek Böreği"), "cicek-boregi")
		self.assertEqual(slugify_tr("İstanbul Ürünleri"), "istanbul-urunleri")
		self.assertEqual(slugify_tr("Şeker Ağacı"), "seker-agaci")

	def test_strips_punctuation(self):
		self.assertEqual(slugify_tr("Apple iPad! (2024)"), "apple-ipad-2024")

	def test_collapses_whitespace(self):
		self.assertEqual(slugify_tr("  Multiple    Spaces  "), "multiple-spaces")

	def test_strips_special_chars(self):
		self.assertEqual(slugify_tr("100% Cotton & Wool"), "100-cotton-wool")

	def test_empty_input(self):
		self.assertEqual(slugify_tr(""), "")
		self.assertEqual(slugify_tr("   "), "")

	def test_only_unicode(self):
		self.assertEqual(slugify_tr("✓✓✓"), "")

	def test_preserves_numbers(self):
		self.assertEqual(slugify_tr("Samsung S24 Ultra 512GB"), "samsung-s24-ultra-512gb")


if __name__ == "__main__":
	unittest.main()
