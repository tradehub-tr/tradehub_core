"""
meta_builder pure-function testleri.

Frappe runtime'a bağımlı değil; standalone unittest ile koşar:

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_meta_builder
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.meta_builder import (  # noqa: E402
	build_for_static_page,
	build_home_json_ld,
	compose_seo_payload,
)

DEFAULTS = {
	"title_pattern": "{title} | İstoç B2B",
	"description": "İstoç global B2B pazaryeri.",
	"og_image": "/files/site-default-og.png",
	"site_name": "İstoç",
	"twitter_handle": "@istoctr",
	"robots": "index,follow",
}

SITE_URL = "https://istoc.com"


def _listing(**overrides):
	base = {
		"name": "LST-TEST",
		"title": "iPhone 15 Pro 128GB",
		"slug": "iphone-15-pro-128gb",
	}
	base.update(overrides)
	return base


def _payload(record, **kwargs):
	return compose_seo_payload(
		record=record,
		url_prefix=kwargs.pop("url_prefix", "/urun"),
		defaults=kwargs.pop("defaults", DEFAULTS),
		site_url=kwargs.pop("site_url", SITE_URL),
		**kwargs,
	)


class TestTitleAndDescription(unittest.TestCase):
	def test_uses_record_meta_title_when_set(self):
		seo = _payload(_listing(meta_title="Özel başlık"))
		self.assertEqual(seo["title"], "Özel başlık")

	def test_falls_back_to_title_pattern_when_meta_title_empty(self):
		seo = _payload(_listing())
		self.assertEqual(seo["title"], "iPhone 15 Pro 128GB | İstoç B2B")

	def test_uses_record_meta_description_when_set(self):
		seo = _payload(_listing(meta_description="Özel açıklama metni."))
		self.assertEqual(seo["description"], "Özel açıklama metni.")

	def test_falls_back_to_record_description(self):
		seo = _payload(_listing(description="Ürün açıklaması"))
		self.assertEqual(seo["description"], "Ürün açıklaması")

	def test_falls_back_to_site_default_description(self):
		seo = _payload(_listing())
		self.assertEqual(seo["description"], "İstoç global B2B pazaryeri.")


class TestCanonical(unittest.TestCase):
	def test_canonical_uses_slug_with_prefix(self):
		seo = _payload(_listing())
		self.assertEqual(seo["canonical"], "https://istoc.com/urun/iphone-15-pro-128gb")

	def test_canonical_override_wins(self):
		seo = _payload(_listing(canonical_url_override="https://istoc.com/ozel-url"))
		self.assertEqual(seo["canonical"], "https://istoc.com/ozel-url")

	def test_canonical_empty_when_no_slug(self):
		seo = _payload({"name": "X", "title": "Y"})
		self.assertEqual(seo["canonical"], "")

	def test_alternate_slug_field(self):
		record = {"name": "CAT", "category_name": "Elektronik", "url_slug": "elektronik"}
		seo = _payload(record, url_prefix="/kategori", slug_field="url_slug")
		self.assertEqual(seo["canonical"], "https://istoc.com/kategori/elektronik")

	def test_override_relative_path_absolutized(self):
		seo = _payload(_listing(canonical_url_override="/ozel-url"))
		self.assertEqual(seo["canonical"], "https://istoc.com/ozel-url")

	def test_override_www_host_rebased_to_apex(self):
		seo = _payload(_listing(canonical_url_override="https://www.istoc.com/urun/iphone-15-pro-128gb"))
		self.assertEqual(seo["canonical"], "https://istoc.com/urun/iphone-15-pro-128gb")

	def test_override_backend_host_rebased_to_apex(self):
		seo = _payload(_listing(canonical_url_override="https://istoc.cronbi.com/urun/x?varyant=kirmizi"))
		self.assertEqual(seo["canonical"], "https://istoc.com/urun/x?varyant=kirmizi")

	def test_override_og_url_matches_normalized_canonical(self):
		seo = _payload(_listing(canonical_url_override="http://www.istoc.com/ozel-url"))
		self.assertEqual(seo["og_url"], "https://istoc.com/ozel-url")


class TestRobots(unittest.TestCase):
	def test_default_directive(self):
		seo = _payload(_listing())
		self.assertEqual(seo["robots"], "index,follow")

	def test_noindex_flag_overrides_default(self):
		seo = _payload(_listing(noindex=1))
		self.assertEqual(seo["robots"], "noindex,follow")

	def test_explicit_override_wins_over_noindex(self):
		seo = _payload(_listing(noindex=1, robots_directive_override="noindex,nofollow"))
		self.assertEqual(seo["robots"], "noindex,nofollow")


class TestOgFields(unittest.TestCase):
	def test_og_title_falls_back_to_meta_title(self):
		seo = _payload(_listing(meta_title="Meta Başlık"))
		self.assertEqual(seo["og_title"], "Meta Başlık")

	def test_og_title_override_wins(self):
		seo = _payload(_listing(meta_title="Meta", og_title_override="OG Özel"))
		self.assertEqual(seo["og_title"], "OG Özel")

	def test_og_description_override_wins(self):
		seo = _payload(
			_listing(
				meta_description="Meta açıklama",
				og_description_override="OG özel açıklama",
			)
		)
		self.assertEqual(seo["og_description"], "OG özel açıklama")

	def test_og_image_record_wins(self):
		seo = _payload(_listing(og_image="/files/listing-og.png"))
		self.assertEqual(seo["og_image"], "https://istoc.com/files/listing-og.png")

	def test_og_image_resolver_fallback(self):
		seo = _payload(_listing(), og_image_resolver=lambda r: "/files/auto-resized.jpg")
		self.assertEqual(seo["og_image"], "https://istoc.com/files/auto-resized.jpg")

	def test_og_image_site_default_fallback(self):
		seo = _payload(_listing())
		self.assertEqual(seo["og_image"], "https://istoc.com/files/site-default-og.png")

	def test_og_image_absolute_url_unchanged(self):
		seo = _payload(_listing(og_image="https://cdn.istoc.com/x.png"))
		self.assertEqual(seo["og_image"], "https://cdn.istoc.com/x.png")


class TestOgTypeAndSlugField(unittest.TestCase):
	def test_default_og_type_website(self):
		seo = _payload(_listing())
		self.assertEqual(seo["og_type"], "website")

	def test_og_type_override(self):
		seo = _payload(_listing(), og_type="product")
		self.assertEqual(seo["og_type"], "product")

	def test_og_url_equals_canonical(self):
		seo = _payload(_listing())
		self.assertEqual(seo["og_url"], seo["canonical"])


class TestJsonLdAndSiteFields(unittest.TestCase):
	def test_json_ld_empty_in_phase_1(self):
		seo = _payload(_listing())
		self.assertEqual(seo["json_ld"], [])

	def test_site_name_from_defaults(self):
		seo = _payload(_listing())
		self.assertEqual(seo["site_name"], "İstoç")

	def test_twitter_handle_from_defaults(self):
		seo = _payload(_listing())
		self.assertEqual(seo["twitter_handle"], "@istoctr")

	def test_home_json_ld_uses_backend_defaults(self):
		schemas = build_home_json_ld(defaults=DEFAULTS, site_url=SITE_URL)
		self.assertEqual([schema["@type"] for schema in schemas], ["Organization", "WebSite"])
		self.assertEqual(schemas[0]["name"], "İstoç")
		self.assertEqual(schemas[1]["url"], SITE_URL)


class TestStaticPageHreflang(unittest.TestCase):
	"""Statik sayfada slug zaten tam path; `//` üretilmemeli."""

	def _home(self, lang="tr"):
		return build_for_static_page(
			record={"page_path": "/", "meta_title": "iStoc", "meta_description": "test"},
			page_meta={"path": "/", "title": "iStoc"},
			defaults=DEFAULTS,
			site_url=SITE_URL,
			lang=lang,
		)

	def test_home_hreflang_has_no_double_slash(self):
		hrefs = [link["href"] for link in self._home()["hreflang_links"]]
		self.assertNotIn(f"{SITE_URL}//", hrefs)
		# tr + x-default; `/en/` girdisi 2026-09-21'de kaldırıldı (canlıda 404 dönüyordu).
		self.assertEqual(hrefs, [f"{SITE_URL}/", f"{SITE_URL}/"])

	def test_inner_static_page_hreflang(self):
		seo = build_for_static_page(
			record={"page_path": "/urunler", "meta_title": "Ürünler", "meta_description": "test"},
			page_meta={"path": "/urunler", "title": "Ürünler"},
			defaults=DEFAULTS,
			site_url=SITE_URL,
		)
		hrefs = [link["href"] for link in seo["hreflang_links"]]
		self.assertEqual(hrefs, [f"{SITE_URL}/urunler", f"{SITE_URL}/urunler"])

	def test_canonical_dile_gore_degismez(self):
		"""Canonical artık dilden bağımsız — adres tek (K7, `?hl=` ile dil taşınır).

		2026-09-21'e kadar `lang="en"` canonical'i `/en/` yapıyordu; o adres hiç
		sunulmuyordu, yani canonical KIRIK bir adrese işaret ediyordu. Bu, kırık
		alternate'ten daha ağır bir kusurdu: canonical Google'a "asıl sürüm
		burası" der.
		"""
		for lang in ("tr", "en", "ar", "ru"):
			with self.subTest(lang=lang):
				self.assertEqual(self._home(lang=lang)["canonical"], f"{SITE_URL}/")


if __name__ == "__main__":
	unittest.main()
