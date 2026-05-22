"""TF-IDF semantic resolver testleri."""

import unittest

try:
	from sklearn.feature_extraction.text import TfidfVectorizer  # noqa

	HAS_SKLEARN = True
except ImportError:
	HAS_SKLEARN = False

try:
	import frappe  # noqa

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False


@unittest.skipUnless(HAS_SKLEARN and HAS_FRAPPE, "sklearn + frappe required")
class TestSemantic(unittest.TestCase):
	def test_resolve_known_synonym(self):
		from tradehub_core.bulk_import.ingestion import semantic

		field, score = semantic.resolve_header_semantic("Stok Kodu")
		self.assertEqual(field, "sku")
		self.assertGreater(score, 0.5)

	def test_resolve_price_synonym(self):
		from tradehub_core.bulk_import.ingestion import semantic

		field, score = semantic.resolve_header_semantic("Birim Fiyat (TL)")
		self.assertEqual(field, "base_price")

	def test_resolve_below_threshold(self):
		from tradehub_core.bulk_import.ingestion import semantic

		field, _score = semantic.resolve_header_semantic("xyzqwerty randomtext")
		self.assertIsNone(field)


if __name__ == "__main__":
	unittest.main()
