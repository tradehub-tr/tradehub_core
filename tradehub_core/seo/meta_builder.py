"""
SEO meta payload üretici.

Pure `compose_seo_payload(...)` Frappe runtime'a bağımlı değildir; tüm
girdiler parametre olarak verilir (test edilebilir).

Frappe wrapper'lar (`build_for_listing/category/brand/seller`) Website Settings
ve site URL'sini Frappe'den okuyup pure fonksiyonu çağırır.
"""

from collections.abc import Callable
from urllib.parse import urljoin

from tradehub_core.seo.i18n import (
	DEFAULT_LANG,
	build_hreflang_links,
	get_field_with_fallback,
	localize_url,
)

# Pure helpers ---------------------------------------------------------------


def _absolute(url_or_path: str, site_url: str) -> str:
	"""Relative path'i mutlak URL'e çevir; URL ise olduğu gibi döndür."""
	if not url_or_path:
		return ""
	if url_or_path.startswith(("http://", "https://")):
		return url_or_path
	return urljoin(site_url.rstrip("/") + "/", url_or_path.lstrip("/"))


def _pick_title_source(record: dict) -> str:
	"""Doctype'tan bağımsız: title benzeri field'lardan ilk doluyu döner."""
	for key in ("title", "category_name", "brand_name", "seller_name", "name1", "name"):
		val = record.get(key)
		if val:
			return val
	return ""


def _pick_description_source(record: dict) -> str:
	"""Free-text description benzeri field'lardan ilk doluyu döner."""
	for key in ("description", "short_description", "summary", "about"):
		val = record.get(key)
		if val:
			return val
	return ""


def _resolve_robots(record: dict, default: str) -> str:
	"""Robots directive: override > noindex flag > default."""
	override = record.get("robots_directive_override")
	if override:
		return override
	if record.get("noindex"):
		return "noindex,follow"
	return default


def _resolve_canonical(record: dict, url_prefix: str, slug_field: str, site_url: str) -> str:
	"""Canonical URL: override > <site>/<prefix>/<slug>."""
	override = record.get("canonical_url_override")
	if override:
		return override
	slug = record.get(slug_field) or record.get("slug") or ""
	if not slug:
		return ""
	return _absolute(f"{url_prefix}/{slug}", site_url)


# Main pure entry point ------------------------------------------------------


def compose_seo_payload(
	*,
	record: dict,
	url_prefix: str,
	defaults: dict,
	site_url: str,
	og_type: str = "website",
	slug_field: str = "slug",
	og_image_resolver: Callable[[dict], str] | None = None,
	json_ld: list[dict] | None = None,
	lang: str = "tr",
) -> dict:
	"""Tüm doctype'lar için ortak SEO payload üretici.

	Parametreler:
		record: Doctype kaydı (dict — Document.as_dict() veya _dict)
		url_prefix: Pretty URL prefix (örn. "/urun")
		defaults: Website Settings'ten yüklenen site-wide default'lar dict
		site_url: Mutlak site URL (örn. "https://istoc.com")
		og_type: og:type değeri (Listing="product", diğer="website")
		slug_field: Slug field adı (Product Category'de "url_slug" olabilir)
		og_image_resolver: Boş og_image durumunda kullanılacak fallback fonksiyon

	Döner: SEO payload dict. Anahtarlar: title, description, canonical, robots,
	og_type, og_title, og_description, og_image, og_url, site_name,
	twitter_handle, json_ld.
	"""

	title_text = _pick_title_source(record)
	# Lang-aware meta_title: EN ise meta_title_en fallback TR
	meta_title_raw = get_field_with_fallback(record, "meta_title", lang)
	meta_title = meta_title_raw or defaults.get("title_pattern", "{title}").format(title=title_text)

	description = (
		get_field_with_fallback(record, "meta_description", lang)
		or _pick_description_source(record)
		or defaults.get("description", "")
	).strip()

	# Slug: TR slug ile bul; canonical lang prefix'li URL
	tr_slug = record.get(slug_field) or record.get("slug") or ""
	tr_canonical_path = f"{url_prefix}/{tr_slug}" if tr_slug else ""

	canonical_override = record.get("canonical_url_override")
	if canonical_override:
		canonical = canonical_override
	elif tr_canonical_path:
		canonical = _absolute(localize_url(tr_canonical_path, lang), site_url)
	else:
		canonical = ""

	robots = _resolve_robots(record, defaults.get("robots", "index,follow"))

	# OG image fallback chain
	og_image = record.get("og_image")
	if not og_image and og_image_resolver is not None:
		og_image = og_image_resolver(record) or ""
	if not og_image:
		og_image = defaults.get("og_image", "")
	if og_image:
		og_image = _absolute(og_image, site_url)

	# OG title/desc lang-aware
	og_title_override = get_field_with_fallback(record, "og_title_override", lang)
	og_desc_override = get_field_with_fallback(record, "og_description_override", lang)

	# Hreflang links (her zaman üretilir — admin tek dilliyse bile fallback iyi)
	hreflang_links = (
		build_hreflang_links(tr_canonical_path, site_url)
		if tr_canonical_path else []
	)

	return {
		"title": meta_title,
		"description": description,
		"canonical": canonical,
		"robots": robots,
		"og_type": og_type,
		"og_title": og_title_override or meta_title,
		"og_description": og_desc_override or description,
		"og_image": og_image,
		"og_url": canonical,
		"site_name": defaults.get("site_name", ""),
		"twitter_handle": defaults.get("twitter_handle", ""),
		"json_ld": json_ld or [],
		"lang": lang,
		"hreflang_links": hreflang_links,
	}


# Frappe-aware wrappers ------------------------------------------------------


def _load_site_defaults() -> dict:
	"""Website Settings singleton'undan SEO default'larını yükle."""
	import frappe

	ws = frappe.get_single("Website Settings")
	return {
		"title_pattern": ws.get("seo_meta_title_pattern") or "{title}",
		"description": ws.get("seo_meta_description") or "",
		"og_image": ws.get("seo_og_image") or "",
		"site_name": ws.get("seo_site_name") or "",
		"twitter_handle": ws.get("seo_twitter_handle") or "",
		"robots": ws.get("seo_robots_directive") or "index,follow",
	}


def _site_url() -> str:
	import frappe

	return frappe.utils.get_url()


def build_for_listing(listing: dict, lang: str = "tr") -> dict:
	from tradehub_core.seo.og_image import ensure_og_image
	from tradehub_core.seo.schema_builder import compose_for_listing

	site_url = _site_url()
	defaults = _load_site_defaults()
	json_ld = compose_for_listing(listing, defaults, site_url)

	return compose_seo_payload(
		record=listing,
		url_prefix="/urun",
		defaults=defaults,
		site_url=site_url,
		og_type="product",
		slug_field="slug",
		og_image_resolver=lambda r: ensure_og_image(r, source_field="primary_image"),
		json_ld=json_ld,
		lang=lang,
	)


def build_for_category(category: dict, lang: str = "tr") -> dict:
	from tradehub_core.seo.og_image import ensure_og_image
	from tradehub_core.seo.schema_builder import compose_for_category

	site_url = _site_url()
	defaults = _load_site_defaults()
	json_ld = compose_for_category(category, defaults, site_url)

	return compose_seo_payload(
		record=category,
		url_prefix="/kategori",
		defaults=defaults,
		site_url=site_url,
		og_type="website",
		slug_field="url_slug",
		og_image_resolver=lambda r: ensure_og_image(r, source_field="image"),
		json_ld=json_ld,
		lang=lang,
	)


def build_for_brand(brand: dict, lang: str = "tr") -> dict:
	from tradehub_core.seo.og_image import ensure_og_image
	from tradehub_core.seo.schema_builder import compose_for_brand

	site_url = _site_url()
	defaults = _load_site_defaults()
	json_ld = compose_for_brand(brand, defaults, site_url)

	return compose_seo_payload(
		record=brand,
		url_prefix="/marka",
		defaults=defaults,
		site_url=site_url,
		og_type="website",
		slug_field="slug",
		og_image_resolver=lambda r: ensure_og_image(r, source_field="logo"),
		json_ld=json_ld,
		lang=lang,
	)


def build_for_seller(seller: dict, lang: str = "tr") -> dict:
	from tradehub_core.seo.og_image import ensure_og_image
	from tradehub_core.seo.schema_builder import compose_for_seller

	site_url = _site_url()
	defaults = _load_site_defaults()
	json_ld = compose_for_seller(seller, defaults, site_url)

	return compose_seo_payload(
		record=seller,
		url_prefix="/magaza",
		defaults=defaults,
		site_url=site_url,
		og_type="profile",
		slug_field="slug",
		og_image_resolver=lambda r: ensure_og_image(r, source_field="logo"),
		json_ld=json_ld,
		lang=lang,
	)


def build_for_static_page(
	record: dict,
	page_meta: dict,
	defaults: dict | None = None,
	site_url: str | None = None,
	lang: str = "tr",
) -> dict:
	"""Statik sayfa için SEO meta payload (Faz 4c).

	record: Static Page SEO doctype as_dict() (override değerleri).
	page_meta: STATIC_PAGES_REGISTRY entry (path, title, ...).

	Statik sayfaların URL'i zaten tam path olduğu için compose_seo_payload'a
	url_prefix="" geçilir ve canonical sonradan tam path ile override edilir.
	"""
	if defaults is None:
		defaults = _load_site_defaults()
	if site_url is None:
		site_url = _site_url()

	# meta_title fallback: record > page_meta.title > site_name
	working_record = dict(record)
	if not working_record.get("meta_title"):
		working_record["meta_title"] = page_meta.get("title") or defaults.get("site_name", "")

	# title field — compose_seo_payload _pick_title_source kullanır; "title" olmazsa
	# meta_title'a düşer ama biz emin olalım
	if not working_record.get("title"):
		working_record["title"] = page_meta.get("title", "")

	seo = compose_seo_payload(
		record=working_record,
		url_prefix="",
		defaults=defaults,
		site_url=site_url,
		og_type="website",
		slug_field="page_path",
		og_image_resolver=None,
		json_ld=None,
		lang=lang,
	)

	# Canonical'ı path-bazlı yeniden inşa et (slug zaten / içeriyor, prefix yok)
	page_path = working_record.get("page_path") or page_meta.get("path") or ""
	canonical_override = working_record.get("canonical_url_override")
	if canonical_override:
		seo["canonical"] = canonical_override
		seo["og_url"] = canonical_override
	elif page_path:
		from tradehub_core.seo.i18n import localize_url

		canonical = f"{site_url.rstrip('/')}{localize_url(page_path, lang)}"
		seo["canonical"] = canonical
		seo["og_url"] = canonical

	return seo
