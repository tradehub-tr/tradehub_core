"""seo_admin endpoint pure-helper testleri.

cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_seo_admin
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.api.seo_admin import (  # noqa: E402
	SEO_FIELDS_BY_DOCTYPE,
	_slug_field_for,
	_suggest_unique_slug,
)


class TestSuggestUniqueSlug(unittest.TestCase):
	def test_returns_base_if_free(self):
		result = _suggest_unique_slug("yeni-slug", lambda s: False)
		self.assertEqual(result, "yeni-slug")

	def test_appends_2_when_base_taken(self):
		result = _suggest_unique_slug("iphone-15-pro", lambda s: s == "iphone-15-pro")
		self.assertEqual(result, "iphone-15-pro-2")

	def test_increments_until_unique(self):
		taken = {"iphone-15-pro", "iphone-15-pro-2", "iphone-15-pro-3"}
		result = _suggest_unique_slug("iphone-15-pro", lambda s: s in taken)
		self.assertEqual(result, "iphone-15-pro-4")

	def test_max_iterations_bounded(self):
		result = _suggest_unique_slug("x", lambda s: True, max_tries=5)
		self.assertIsNone(result)


class TestSlugFieldFor(unittest.TestCase):
	def test_category_returns_url_slug(self):
		self.assertEqual(_slug_field_for("Product Category"), "url_slug")

	def test_listing_returns_slug(self):
		self.assertEqual(_slug_field_for("Listing"), "slug")

	def test_brand_returns_slug(self):
		self.assertEqual(_slug_field_for("Brand"), "slug")

	def test_seller_returns_slug(self):
		self.assertEqual(_slug_field_for("Admin Seller Profile"), "slug")


class TestSeoFieldsConfig(unittest.TestCase):
	def test_listing_config_has_slug(self):
		self.assertIn("slug", SEO_FIELDS_BY_DOCTYPE["Listing"])

	def test_category_uses_url_slug(self):
		self.assertIn("url_slug", SEO_FIELDS_BY_DOCTYPE["Product Category"])

	def test_all_doctypes_have_meta_fields(self):
		for fields in SEO_FIELDS_BY_DOCTYPE.values():
			self.assertIn("meta_title", fields)
			self.assertIn("meta_description", fields)
			self.assertIn("noindex", fields)
			self.assertIn("og_image", fields)

	def test_category_has_sitemap_fields(self):
		fields = SEO_FIELDS_BY_DOCTYPE["Product Category"]
		self.assertIn("sitemap_priority", fields)
		self.assertIn("sitemap_changefreq", fields)

	def test_brand_seo_fields_complete(self):
		"""Brand SEO_FIELDS_BY_DOCTYPE entry'si TR + EN tüm field'ları kapsar."""
		brand_fields = set(SEO_FIELDS_BY_DOCTYPE["Brand"])
		expected_tr = {
			"slug",
			"meta_title",
			"meta_description",
			"noindex",
			"og_image",
			"og_title_override",
			"og_description_override",
			"canonical_url_override",
			"robots_directive_override",
		}
		expected_en = {
			"slug_en",
			"meta_title_en",
			"meta_description_en",
			"og_title_override_en",
			"og_description_override_en",
		}
		self.assertTrue(expected_tr.issubset(brand_fields))
		self.assertTrue(expected_en.issubset(brand_fields))


if __name__ == "__main__":
	unittest.main()
