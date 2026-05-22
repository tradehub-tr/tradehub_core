"""
Pretty URL → Frappe doctype kaydı → meta enjeksiyonlu HTML response.

Whitelist endpoint'leri (Nginx tarafından çağrılır):
  - render_listing(slug)   → /urun/<slug>
  - render_category(slug)  → /kategori/<slug>
  - render_brand(slug)     → /marka/<slug>
  - render_seller(slug)    → /magaza/<slug>

Storefront HTML template'leri Frappe container'ında volume mount ile
erişilebilir: `site_config.storefront_dist_path` ile path konfigüre edilir
(default: `/storefront`). Template bulunamazsa minimal inline fallback
HTML üretilir — yine de meta tag'ler tam dolu olur.
"""

import os

from tradehub_core.seo import meta_builder, seo_html_injector

DEFAULT_STOREFRONT_DIST = "/storefront"

# Doctype → storefront HTML template eşlemesi (Vite multi-page entry path'leri)
TEMPLATE_MAP = {
	"Listing": "pages/product-detail.html",
	"Product Category": "pages/category-detail.html",
	"Brand": "pages/brand.html",
	"Admin Seller Profile": "pages/seller/seller-storefront.html",
}

# Doctype → slug taşıyıcı field eşlemesi. Frontend bu field'ın değerini URL
# slug olarak gönderir; backend DB sorgusu da bu field üzerinde yapılır.
# - Admin Seller Profile'da `slug` kolonu yok; gerçek taşıyıcı `seller_code`
#   (örn. "DEMO-001"). API endpoint'leri response'ta `seller.slug = seller_code`
#   ile yumuşak alias üretir, ama DB lookup için asıl kolon adı zorunlu.
SLUG_FIELD_MAP = {
	"Listing": "slug",
	"Product Category": "url_slug",
	"Brand": "slug",
	"Admin Seller Profile": "seller_code",
}


# Pure helpers ---------------------------------------------------------------


def _minimal_fallback_html() -> str:
	"""Storefront template bulunamadığında kullanılan en küçük HTML iskeleti.

	`<!-- {{__SEO_HEAD__}} -->` placeholder'ı dolacak; gerçek storefront
	deploy edildiğinde bu fallback devreye girmez.
	"""
	return (
		"<!doctype html>\n"
		'<html lang="tr"><head>\n'
		'<meta charset="utf-8">\n'
		'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
		f"{seo_html_injector.PLACEHOLDER}\n"
		"</head><body>\n"
		"<noscript>JavaScript gerekli.</noscript>\n"
		"</body></html>"
	)


def _build_404_seo(site_url: str, site_name: str = "İstoç") -> dict:
	"""404 sayfası için SEO payload — noindex zorunlu."""
	return {
		"title": f"Sayfa Bulunamadı | {site_name}",
		"description": "Aradığınız sayfa bulunamadı.",
		"canonical": "",
		"robots": "noindex,nofollow",
		"og_type": "website",
		"og_title": "Sayfa Bulunamadı",
		"og_description": "",
		"og_image": "",
		"og_url": "",
		"site_name": site_name,
		"twitter_handle": "",
		"json_ld": [],
	}


# Frappe-aware helpers -------------------------------------------------------


def _storefront_dist_path() -> str:
	"""site_config.storefront_dist_path veya default `/storefront`."""
	import frappe

	cfg = frappe.get_site_config() or {}
	return cfg.get("storefront_dist_path") or DEFAULT_STOREFRONT_DIST


def _read_template(template_relpath: str) -> str:
	"""Storefront dist altından template oku; bulunmazsa minimal fallback."""
	dist = _storefront_dist_path()
	full = os.path.join(dist, template_relpath)
	if os.path.exists(full):
		try:
			with open(full, encoding="utf-8") as f:
				return f.read()
		except OSError:
			pass
	return _minimal_fallback_html()


def _find_record_by_slug(doctype: str, slug: str):
	"""Slug'a göre doctype kaydını bul; yoksa None döner."""
	import frappe

	slug_field = SLUG_FIELD_MAP.get(doctype, "slug")
	name = frappe.db.get_value(doctype, {slug_field: slug}, "name")
	if not name:
		return None
	# Tüm field'larla doc nesnesi
	return frappe.get_doc(doctype, name)


def _html_response(html: str, status_code: int = 200, cache_seconds: int = 300):
	"""HTML string'i Werkzeug Response olarak sarıp döner.

	Frappe whitelist endpoint string return ederse JSON ile sarar; Response
	objesi return edersek doğrudan body olarak yazar."""
	from werkzeug.wrappers import Response

	response = Response(html, status=status_code, mimetype="text/html")
	response.headers["Cache-Control"] = f"public, max-age={cache_seconds}"
	return response


def _build_response_html(seo: dict, template_relpath: str) -> str:
	"""Storefront HTML'i oku + SEO meta enjekte et."""
	html = _read_template(template_relpath)
	return seo_html_injector.inject_meta_into_html(html, seo)


def _render_404_response():
	import frappe

	seo = _build_404_seo(frappe.utils.get_url())
	html = _read_template("404.html")
	rendered = seo_html_injector.inject_meta_into_html(html, seo)
	return _html_response(rendered, status_code=404, cache_seconds=0)


def _render_for(doctype: str, slug: str, builder_fn, lang: str = "tr"):
	"""Tüm doctype'lar için ortak render flow. Werkzeug Response döner."""

	record = _find_record_by_slug(doctype, slug)
	if not record:
		return _render_404_response()

	seo = builder_fn(record.as_dict(), lang=lang)
	template = TEMPLATE_MAP[doctype]
	html = _build_response_html(seo, template)
	return _html_response(html, status_code=200, cache_seconds=300)


# Whitelist endpoints --------------------------------------------------------


def render_listing(slug: str, lang: str = "tr") -> str:
	"""GET /urun/<slug> veya /en/urun/<slug> → HTML response with meta'lar."""
	return _render_for("Listing", slug, meta_builder.build_for_listing, lang=lang)


def render_category(slug: str, lang: str = "tr") -> str:
	"""GET /kategori/<slug> veya /en/kategori/<slug>."""
	return _render_for("Product Category", slug, meta_builder.build_for_category, lang=lang)


def render_brand(slug: str, lang: str = "tr") -> str:
	"""GET /marka/<slug> veya /en/marka/<slug>."""
	return _render_for("Brand", slug, meta_builder.build_for_brand, lang=lang)


def render_seller(slug: str, lang: str = "tr") -> str:
	"""GET /magaza/<slug> veya /en/magaza/<slug>."""
	return _render_for("Admin Seller Profile", slug, meta_builder.build_for_seller, lang=lang)


def _resolve_static_page(path: str, lang: str = "tr") -> dict | None:
	"""STATIC_PAGES_REGISTRY'den entry döner; yoksa None. Faz 4c."""
	from tradehub_core.seo.static_pages_registry import find_entry

	return find_entry(path)


def render_static_page(path: str, lang: str = "tr") -> str:
	"""GET /<static-path> → HTML response with SEO meta'lar (Faz 4c).

	Path STATIC_PAGES_REGISTRY'den lookup edilir; varsa HTML template
	okunup Static Page SEO override'larıyla render edilir; yoksa 404."""
	import frappe

	entry = _resolve_static_page(path, lang=lang)
	if not entry:
		return _render_404_response()

	# Static Page SEO doctype'tan override çek (varsa)
	override = {}
	if frappe.db.exists("Static Page SEO", path):
		override = frappe.get_doc("Static Page SEO", path).as_dict()

	# Override yoksa güvenli default: noindex=1
	if not override:
		override = {
			"page_path": path,
			"page_title": entry["title"],
			"meta_title": entry["title"],
			"meta_description": "",
			"noindex": 1,
		}

	seo = meta_builder.build_for_static_page(
		record=override,
		page_meta=entry,
		lang=lang,
	)

	html = _read_template(entry["html_path"])
	rendered = seo_html_injector.inject_meta_into_html(html, seo)
	return _html_response(rendered, status_code=200, cache_seconds=300)


# Frappe whitelist decorator'ları en sona — module-import sırasında frappe
# import'unu tetiklemesin (standalone unit test edilebilirlik için).
def _register_whitelists():
	"""Whitelist decorator'larını programatik olarak uygula.

	Modül Frappe runtime altında ilk import edildiğinde çağrılır.
	Standalone unittest'te _register_whitelists() çağrılmaz."""
	import frappe

	globals()["render_listing"] = frappe.whitelist(allow_guest=True)(render_listing)
	globals()["render_category"] = frappe.whitelist(allow_guest=True)(render_category)
	globals()["render_brand"] = frappe.whitelist(allow_guest=True)(render_brand)
	globals()["render_seller"] = frappe.whitelist(allow_guest=True)(render_seller)
	globals()["render_static_page"] = frappe.whitelist(allow_guest=True)(render_static_page)


try:
	import frappe  # noqa: F401

	_register_whitelists()
except ImportError:
	# Standalone (Frappe yokken) — whitelist atla.
	pass
