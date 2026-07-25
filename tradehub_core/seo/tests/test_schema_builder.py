"""schema_builder pure-function testleri.

cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_schema_builder
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.schema_builder import (  # noqa: E402
	_get_listing_extra_context,
	build_breadcrumb_schema,
	build_faq_schema,
	build_item_list_schema,
	build_organization_schema,
	build_product_schema,
	build_website_schema,
)


class TestProductSchema(unittest.TestCase):
	def _listing(self, **overrides):
		base = {
			"name": "LST-001",
			"title": "iPhone 15 Pro",
			"slug": "iphone-15-pro",
			"description": "Apple iPhone 15 Pro",
			"primary_image": "https://istoc.com/files/x.jpg",
			"base_price": 45000.0,
		}
		base.update(overrides)
		return base

	def test_basic_product(self):
		schema = build_product_schema(
			listing=self._listing(),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertEqual(schema["@context"], "https://schema.org")
		self.assertEqual(schema["@type"], "Product")
		self.assertEqual(schema["name"], "iPhone 15 Pro")
		self.assertEqual(schema["sku"], "LST-001")

	def test_product_image_array(self):
		schema = build_product_schema(
			listing=self._listing(),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertIsInstance(schema["image"], list)
		self.assertEqual(schema["image"][0], "https://istoc.com/files/x.jpg")

	def test_product_offers(self):
		schema = build_product_schema(
			listing=self._listing(),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		offers = schema["offers"]
		self.assertEqual(offers["@type"], "Offer")
		self.assertEqual(offers["price"], "45000.0")
		self.assertEqual(offers["priceCurrency"], "TRY")
		self.assertTrue(offers["url"].endswith("/urun/iphone-15-pro"))
		self.assertIn("InStock", offers["availability"])

	def test_product_with_brand(self):
		schema = build_product_schema(
			listing=self._listing(),
			site_url="https://istoc.com",
			brand={"name": "Apple", "slug": "apple"},
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertEqual(schema["brand"]["@type"], "Brand")
		self.assertEqual(schema["brand"]["name"], "Apple")
		self.assertTrue(schema["brand"]["url"].endswith("/marka/apple"))

	def test_product_with_aggregate_rating(self):
		schema = build_product_schema(
			listing=self._listing(),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating={"value": 4.5, "count": 12},
			reviews=None,
		)
		ar = schema["aggregateRating"]
		self.assertEqual(ar["@type"], "AggregateRating")
		self.assertEqual(ar["ratingValue"], "4.5")
		self.assertEqual(ar["reviewCount"], "12")

	def test_product_with_reviews(self):
		reviews = [
			{
				"@type": "Review",
				"author": {"@type": "Person", "name": "Ahmet"},
				"reviewRating": {"@type": "Rating", "ratingValue": "5"},
				"reviewBody": "Harika ürün",
			}
		]
		schema = build_product_schema(
			listing=self._listing(),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=reviews,
		)
		self.assertEqual(len(schema["review"]), 1)
		self.assertEqual(schema["review"][0]["reviewBody"], "Harika ürün")

	def test_product_missing_image_empty_array(self):
		schema = build_product_schema(
			listing=self._listing(primary_image=None),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertEqual(schema["image"], [])

	def test_product_no_brand_field_absent(self):
		schema = build_product_schema(
			listing=self._listing(),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertNotIn("brand", schema)

	def test_product_currency_default_try(self):
		schema = build_product_schema(
			listing=self._listing(),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertEqual(schema["offers"]["priceCurrency"], "TRY")

	def test_product_uses_absolute_image_effective_price_currency_and_stock(self):
		schema = build_product_schema(
			listing=self._listing(
				primary_image="/files/x.jpg",
				selling_price=100.0,
				discount_percentage=20,
				currency="USD",
				status="Out of Stock",
			),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertEqual(schema["@id"], "https://istoc.com/urun/iphone-15-pro#product")
		self.assertEqual(schema["image"], ["https://istoc.com/files/x.jpg"])
		self.assertEqual(schema["offers"]["@id"], "https://istoc.com/urun/iphone-15-pro#offer")
		self.assertEqual(schema["offers"]["price"], "80.0")
		self.assertEqual(schema["offers"]["priceCurrency"], "USD")
		self.assertEqual(schema["offers"]["availability"], "https://schema.org/OutOfStock")

	def test_tracked_zero_available_quantity_is_out_of_stock(self):
		schema = build_product_schema(
			listing=self._listing(track_inventory=1, available_qty=0),
			site_url="https://istoc.com",
			brand=None,
			category_name=None,
			aggregate_rating=None,
			reviews=None,
		)
		self.assertEqual(schema["offers"]["availability"], "https://schema.org/OutOfStock")


class TestBreadcrumbSchema(unittest.TestCase):
	def test_three_items_positions(self):
		schema = build_breadcrumb_schema(
			items=[
				{"name": "Anasayfa", "url": "https://istoc.com/"},
				{"name": "Elektronik", "url": "https://istoc.com/kategori/elektronik"},
				{"name": "iPhone", "url": "https://istoc.com/urun/iphone"},
			]
		)
		self.assertEqual(schema["@type"], "BreadcrumbList")
		items = schema["itemListElement"]
		self.assertEqual(len(items), 3)
		self.assertEqual(items[0]["position"], 1)
		self.assertEqual(items[2]["position"], 3)

	def test_listitem_type(self):
		schema = build_breadcrumb_schema(
			items=[
				{"name": "Anasayfa", "url": "https://istoc.com/"},
			]
		)
		self.assertEqual(schema["itemListElement"][0]["@type"], "ListItem")

	def test_name_and_item_fields(self):
		schema = build_breadcrumb_schema(
			items=[
				{"name": "Test", "url": "https://x.com"},
			]
		)
		item = schema["itemListElement"][0]
		self.assertEqual(item["name"], "Test")
		self.assertEqual(item["item"], "https://x.com")

	def test_single_item_edge_case(self):
		schema = build_breadcrumb_schema(
			items=[
				{"name": "Anasayfa", "url": "https://istoc.com/"},
			]
		)
		self.assertEqual(len(schema["itemListElement"]), 1)

	def test_schema_id_is_exposed_when_provided(self):
		schema = build_breadcrumb_schema(
			items=[{"name": "Anasayfa", "url": "https://istoc.com/"}],
			schema_id="https://istoc.com/#breadcrumb",
		)
		self.assertEqual(schema["@id"], "https://istoc.com/#breadcrumb")


class TestOrganizationSchema(unittest.TestCase):
	def test_basic(self):
		schema = build_organization_schema(
			site_name="İstoç",
			site_url="https://istoc.com",
			logo_url="https://istoc.com/logo.png",
			same_as=None,
		)
		self.assertEqual(schema["@type"], "Organization")
		self.assertEqual(schema["name"], "İstoç")
		self.assertEqual(schema["url"], "https://istoc.com")
		self.assertEqual(schema["logo"], "https://istoc.com/logo.png")
		self.assertEqual(schema["@id"], "https://istoc.com/#organization")

	def test_same_as_array(self):
		schema = build_organization_schema(
			site_name="İstoç",
			site_url="https://istoc.com",
			logo_url=None,
			same_as=["https://twitter.com/x", "https://facebook.com/y"],
		)
		self.assertEqual(len(schema["sameAs"]), 2)

	def test_logo_none_omitted(self):
		schema = build_organization_schema(
			site_name="X",
			site_url="https://x.com",
			logo_url=None,
			same_as=None,
		)
		self.assertNotIn("logo", schema)

	def test_relative_logo_is_absolute(self):
		schema = build_organization_schema(
			site_name="X",
			site_url="https://istoc.com/marka/x",
			logo_url="/files/x.png",
			same_as=None,
		)
		self.assertEqual(schema["logo"], "https://istoc.com/files/x.png")
		self.assertEqual(schema["@id"], "https://istoc.com/marka/x#organization")


class TestWebSiteSchema(unittest.TestCase):
	def test_search_action_target(self):
		schema = build_website_schema(
			site_url="https://istoc.com",
			search_url_template="https://istoc.com/?q={search_term_string}",
		)
		self.assertEqual(schema["@type"], "WebSite")
		self.assertEqual(schema["@id"], "https://istoc.com/#website")
		self.assertEqual(
			schema["potentialAction"]["target"],
			"https://istoc.com/?q={search_term_string}",
		)

	def test_query_input_format(self):
		schema = build_website_schema(
			site_url="https://istoc.com",
			search_url_template="https://istoc.com/?q={search_term_string}",
		)
		self.assertEqual(
			schema["potentialAction"]["query-input"],
			"required name=search_term_string",
		)


class TestFaqSchema(unittest.TestCase):
	def test_basic_qa(self):
		schema = build_faq_schema(
			questions=[
				{"question": "Stok var mı?", "answer": "Evet 50 adet."},
			]
		)
		self.assertEqual(schema["@type"], "FAQPage")
		me = schema["mainEntity"]
		self.assertEqual(me[0]["@type"], "Question")
		self.assertEqual(me[0]["name"], "Stok var mı?")
		self.assertEqual(me[0]["acceptedAnswer"]["@type"], "Answer")
		self.assertEqual(me[0]["acceptedAnswer"]["text"], "Evet 50 adet.")

	def test_empty_returns_none(self):
		self.assertIsNone(build_faq_schema(questions=[]))

	def test_html_escape_in_question(self):
		schema = build_faq_schema(
			questions=[
				{"question": "<script>alert(1)</script>", "answer": "ok"},
			]
		)
		self.assertNotIn("<script>", schema["mainEntity"][0]["name"])
		self.assertIn("&lt;script&gt;", schema["mainEntity"][0]["name"])


class TestItemListSchema(unittest.TestCase):
	def test_current_page_items_have_absolute_urls_and_positions(self):
		schema = build_item_list_schema(
			items=[
				{"name": "Ürün A", "href": "/urun/urun-a", "imageSrc": "/files/a.jpg"},
				{"name": "Ürün B", "slug": "urun-b"},
			],
			canonical_url="https://istoc.com/urunler",
			site_url="https://istoc.com",
		)
		self.assertEqual(schema["@type"], "ItemList")
		self.assertEqual(schema["@id"], "https://istoc.com/urunler#itemlist")
		self.assertEqual(len(schema["itemListElement"]), 2)
		first = schema["itemListElement"][0]
		self.assertEqual(first["position"], 1)
		self.assertEqual(first["item"]["@id"], "https://istoc.com/urun/urun-a#product")
		self.assertEqual(first["item"]["image"], "https://istoc.com/files/a.jpg")


from tradehub_core.seo.schema_builder import (  # noqa: E402
	_pure_compose_for_brand,
	_pure_compose_for_category,
	_pure_compose_for_listing,
	_pure_compose_for_seller,
)

SITE_URL = "https://istoc.com"

DEFAULTS = {
	"site_name": "İstoç",
	"logo": "https://istoc.com/files/logo.png",
	"twitter": "https://twitter.com/istoctr",
}


class TestPureComposeForListing(unittest.TestCase):
	def _ctx(self, **overrides):
		base = {
			"listing": {
				"name": "LST-001",
				"title": "iPhone 15 Pro",
				"slug": "iphone-15-pro",
				"description": "desc",
				"primary_image": "https://istoc.com/files/p.jpg",
				"base_price": 45000.0,
			},
			"brand": {"name": "Apple", "slug": "apple"},
			"category_name": "Elektronik",
			"category_url": "https://istoc.com/kategori/elektronik",
			"aggregate_rating": {"value": 4.5, "count": 12},
			"reviews": [],
			"questions": [],
		}
		base.update(overrides)
		return base

	def test_three_schemas_when_no_faq(self):
		schemas = _pure_compose_for_listing(
			ctx=self._ctx(),
			defaults=DEFAULTS,
			site_url=SITE_URL,
		)
		types = [s["@type"] for s in schemas]
		self.assertEqual(types, ["Product", "BreadcrumbList", "Organization"])

	def test_includes_faq_when_questions_present(self):
		ctx = self._ctx(questions=[{"question": "Stok?", "answer": "Var"}])
		schemas = _pure_compose_for_listing(ctx=ctx, defaults=DEFAULTS, site_url=SITE_URL)
		types = [s["@type"] for s in schemas]
		self.assertIn("FAQPage", types)

	def test_breadcrumb_order(self):
		schemas = _pure_compose_for_listing(ctx=self._ctx(), defaults=DEFAULTS, site_url=SITE_URL)
		bc = next(s for s in schemas if s["@type"] == "BreadcrumbList")
		items = bc["itemListElement"]
		self.assertEqual(items[0]["name"], "Anasayfa")
		self.assertEqual(items[1]["name"], "Elektronik")
		self.assertEqual(items[2]["name"], "iPhone 15 Pro")
		self.assertEqual(bc["@id"], "https://istoc.com/urun/iphone-15-pro#breadcrumb")

	def test_listing_context_uses_platform_taxonomy_slug(self):
		class FakeDb:
			@staticmethod
			def get_value(doctype, name, fields, as_dict=False):
				if doctype == "Listing":
					return {
						"brand": None,
						"product_category": "PC-001",
						"product_category_name": "Elektronik",
						"average_rating": 0,
						"review_count": 0,
					}
				if doctype == "Product Category":
					return {"category_name": "Elektronik", "url_slug": "elektronik"}
				return None

		fake_frappe = SimpleNamespace(
			db=FakeDb(),
			get_all=lambda *args, **kwargs: [],
			log_error=lambda *args, **kwargs: None,
		)
		fake_site_url = SimpleNamespace(storefront_url=lambda: SITE_URL)
		with (
			patch.dict(sys.modules, {"frappe": fake_frappe}),
			patch.dict(sys.modules, {"tradehub_core.seo.site_url": fake_site_url}),
		):
			ctx = _get_listing_extra_context("LST-001")

		self.assertEqual(ctx["category_name"], "Elektronik")
		self.assertEqual(ctx["category_url"], "https://istoc.com/kategori/elektronik")


class TestPureComposeForCategory(unittest.TestCase):
	def test_two_schemas(self):
		schemas = _pure_compose_for_category(
			category={"category_name": "Elektronik", "url_slug": "elektronik"},
			defaults=DEFAULTS,
			site_url=SITE_URL,
		)
		types = [s["@type"] for s in schemas]
		self.assertEqual(types, ["BreadcrumbList", "Organization"])


class TestPureComposeForBrand(unittest.TestCase):
	def test_two_schemas(self):
		schemas = _pure_compose_for_brand(
			brand={"brand_name": "Apple", "slug": "apple", "logo": "https://istoc.com/files/apple.png"},
			defaults=DEFAULTS,
			site_url=SITE_URL,
		)
		types = [s["@type"] for s in schemas]
		self.assertEqual(types, ["Organization", "BreadcrumbList"])

	def test_brand_as_organization_uses_brand_name(self):
		schemas = _pure_compose_for_brand(
			brand={"brand_name": "Apple", "slug": "apple", "logo": None},
			defaults=DEFAULTS,
			site_url=SITE_URL,
		)
		org = schemas[0]
		self.assertEqual(org["name"], "Apple")


class TestPureComposeForSeller(unittest.TestCase):
	def test_two_schemas(self):
		schemas = _pure_compose_for_seller(
			seller={"seller_name": "ABC Firma", "slug": "abc-firma"},
			defaults=DEFAULTS,
			site_url=SITE_URL,
		)
		types = [s["@type"] for s in schemas]
		self.assertEqual(types, ["Organization", "BreadcrumbList"])

	def test_seller_breadcrumb_points_to_existing_producer_directory(self):
		schemas = _pure_compose_for_seller(
			seller={"seller_name": "ABC Firma", "slug": "abc-firma"},
			defaults=DEFAULTS,
			site_url=SITE_URL,
		)
		breadcrumb = schemas[1]
		self.assertEqual(breadcrumb["itemListElement"][1]["item"], "https://istoc.com/ureticiler")


if __name__ == "__main__":
	unittest.main()
