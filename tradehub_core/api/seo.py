"""Faz 5 — SEO: schema.org Review markup.

Google'da yıldızlı rich result için yapılandırılmış veri üretir.
JSON-LD format. AggregateRating + Review array.

Storefront ürün detay sayfasında `<script type="application/ld+json">` içinde
inline kullanılır.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

MAX_REVIEWS_IN_SCHEMA = 10  # Google önerisi: en güncel 10


@frappe.whitelist(allow_guest=True)
def get_public_page_seo(page_type: str, slug: str | None = None, lang: str = "tr") -> dict:
	"""Client storefront için allowlist'li backend SEO/JSON-LD payload'u.

	Product/brand/seller kendi detay API'lerinden `seo` alır. Burada yalnız
	ayrı bir detay payload'u olmayan ana sayfa ve kategori pretty route'u
	açılır; keyfi doctype veya document erişimine izin verilmez.
	"""
	from tradehub_core.seo.i18n import normalize_lang
	from tradehub_core.seo.meta_builder import build_for_category, build_home_json_ld

	lang = normalize_lang(lang)
	page_type = (page_type or "").strip().lower()

	if page_type == "home":
		return {"json_ld": build_home_json_ld(), "lang": lang}

	if page_type == "category":
		slug = (slug or "").strip()
		if not slug:
			frappe.throw(_("Kategori slug zorunludur"), frappe.ValidationError)
		category_name = frappe.db.get_value(
			"Product Category",
			{"url_slug": slug, "is_active": 1},
			"name",
		)
		if not category_name:
			frappe.throw(_("Kategori bulunamadı"), frappe.DoesNotExistError)
		category = frappe.get_doc("Product Category", category_name).as_dict()
		return build_for_category(category, lang=lang)

	frappe.throw(_("Geçersiz SEO sayfa türü"), frappe.ValidationError)


@frappe.whitelist(allow_guest=True)
def get_review_schema_jsonld(listing: str) -> dict:
	"""Belirli bir Listing için schema.org Product + AggregateRating + Review JSON-LD."""
	if not listing or not frappe.db.exists("Listing", listing):
		frappe.throw(_("Ürün bulunamadı"), frappe.DoesNotExistError)

	row = frappe.db.get_value(
		"Listing",
		listing,
		["title", "weighted_rating", "average_rating", "review_count", "weighted_review_count"],
		as_dict=True,
	)

	# Tercih: weighted (ML) rating — gerçek değer
	rating_value = float(row.weighted_rating or row.average_rating or 0)
	rating_count = int(row.weighted_review_count or row.review_count or 0)

	schema = {
		"@context": "https://schema.org",
		"@type": "Product",
		"name": row.title or listing,
		"sku": listing,
	}

	# AggregateRating yalnız review varsa
	if rating_count > 0 and rating_value > 0:
		schema["aggregateRating"] = {
			"@type": "AggregateRating",
			"ratingValue": round(rating_value, 2),
			"bestRating": 5,
			"worstRating": 1,
			"ratingCount": rating_count,
			"reviewCount": rating_count,
		}

	# En güncel 10 Approved review
	reviews = frappe.get_all(
		"Listing Review",
		filters={"listing": listing, "status": "Approved"},
		fields=["name", "reviewer_display_name", "rating", "title", "body", "published_at"],
		order_by="published_at DESC",
		limit=MAX_REVIEWS_IN_SCHEMA,
	)
	if reviews:
		schema["review"] = []
		for r in reviews:
			review_obj = {
				"@type": "Review",
				"author": {
					"@type": "Organization",  # B2B
					"name": r["reviewer_display_name"] or "Anonim Alıcı",
				},
				"reviewRating": {
					"@type": "Rating",
					"ratingValue": int(r["rating"] or 0),
					"bestRating": 5,
				},
			}
			if r.get("published_at"):
				review_obj["datePublished"] = str(r["published_at"])[:10]
			if r.get("title"):
				review_obj["name"] = r["title"]
			if r.get("body"):
				# Schema'da reviewBody opsiyonel ama önerilir
				body = (r["body"] or "").strip()
				if len(body) > 500:
					body = body[:497] + "..."
				review_obj["reviewBody"] = body
			schema["review"].append(review_obj)

	return schema


@frappe.whitelist(allow_guest=True)
def get_review_schema_html(listing: str) -> str:
	"""Storefront SSR için hazır `<script type="application/ld+json">` tag.

	Returns: HTML string (script tag dahil).
	"""
	schema = get_review_schema_jsonld(listing=listing)
	return '<script type="application/ld+json">' + json.dumps(schema, ensure_ascii=False) + "</script>"


# ── Legacy URL → Pretty URL 301 redirect ────────────────────────────────────
# Eski URL formatları:
#   /pages/product-detail.html?product=<id>   → /urun/<slug>
#   /pages/brand.html?brand=<id>               → /marka/<slug>
#   /pages/seller/seller-shop.html?seller=<id> → /magaza/<slug>
#   /pages/category-detail.html?category=<id>  → /kategori/<slug>

_LEGACY_PREFIX_MAP = {
	"Listing": "/urun",
	"Product Category": "/kategori",
	"Brand": "/marka",
	"Seller Profile": "/magaza",
}

_LEGACY_SLUG_FIELD_MAP = {
	"Listing": "slug",
	"Product Category": "url_slug",
	"Brand": "slug",
	"Seller Profile": "slug",
}

# slug bazı doctype'larda kendi tablosunda değil, eşlenik yönetim doctype'ında
# tutulur: Seller Profile'ın slug alanı Admin Seller Profile'da yaşar (name'ler
# 1:1). Burada anahtar yoksa slug doctype'ın kendisinden okunur.
_LEGACY_SLUG_SOURCE_MAP = {
	"Seller Profile": "Admin Seller Profile",
}


@frappe.whitelist(allow_guest=True)
def resolve_legacy_url(doctype: str, legacy_id: str) -> dict:
	"""Eski URL formatından yeni pretty URL'i çözer (JSON response).

	Returns: {"new_url": "/urun/iphone-15-pro", "status_code": 301} veya
	         {"status_code": 404} kayıt yoksa.
	"""
	prefix = _LEGACY_PREFIX_MAP.get(doctype)
	slug_field = _LEGACY_SLUG_FIELD_MAP.get(doctype)
	if not prefix or not slug_field:
		return {"status_code": 404}

	slug_source = _LEGACY_SLUG_SOURCE_MAP.get(doctype, doctype)
	slug = frappe.db.get_value(slug_source, legacy_id, slug_field)
	if not slug:
		return {"status_code": 404}

	return {"new_url": f"{prefix}/{slug}", "status_code": 301}


@frappe.whitelist(allow_guest=True)
def legacy_redirect_handler(doctype: str, legacy_id: str):
	"""Nginx tarafından çağrılan endpoint: doğrudan 301 redirect response döner.

	Eğer kayıt bulunamazsa 404 sayfasına redirect (storefront fallback)."""
	from werkzeug.wrappers import Response

	result = resolve_legacy_url(doctype=doctype, legacy_id=legacy_id)
	if result.get("new_url"):
		return Response(
			"",
			status=301,
			headers={"Location": result["new_url"]},
		)

	return Response("Not Found", status=404, mimetype="text/plain")


# ── Sitemap + robots.txt endpoint'leri (Faz 2) ──────────────────────────────


def _xml_response(xml: str):
	from werkzeug.wrappers import Response

	response = Response(xml, mimetype="application/xml")
	response.headers["Cache-Control"] = "public, max-age=3600"
	return response


@frappe.whitelist(allow_guest=True)
def get_sitemap_index():
	"""GET /sitemap.xml → disk → Redis → on-demand build sırasıyla index XML."""
	from tradehub_core.seo.sitemap_cache import get_default_cache, read_sitemap_file
	from tradehub_core.seo.sitemap_generator import build_index

	xml = read_sitemap_file("sitemap-index.xml")
	if not xml:
		cache = get_default_cache()
		xml = cache.get_xml("index")
	if not xml:
		xml = build_index()
		get_default_cache().set_xml("index", xml)

	return _xml_response(xml)


@frappe.whitelist(allow_guest=True)
def get_sitemap(name: str):
	"""GET /sitemap-<name>.xml → alt-sitemap XML (parçalı).

	`name`: 'products' | 'products-2' | 'categories' | ... —
	`parse_sitemap_name` guard'ı bilinmeyen/keyfi adları 404'ler
	(path traversal koruması; disk'ten yalnız beklenen dosya adı okunur)."""
	from werkzeug.wrappers import Response

	from tradehub_core.seo.sitemap_cache import get_default_cache, read_sitemap_file
	from tradehub_core.seo.sitemap_generator import build_for_type, parse_sitemap_name

	doctype, part = parse_sitemap_name(name or "")
	if not doctype:
		return Response("Not Found", status=404, mimetype="text/plain")

	# Disk (rebuild çıktısı) — parçalı adların tek kaynağı
	xml = read_sitemap_file(f"sitemap-{name}.xml")
	if xml:
		return _xml_response(xml)

	# Fallback yalnız 1. parça için: Redis → on-demand build (küçük site /
	# rebuild henüz koşmadı). Yüksek parçalar diske yazılmadan var olamaz.
	if part != 1:
		return Response("Not Found", status=404, mimetype="text/plain")

	cache = get_default_cache()
	xml = cache.get_xml(doctype)
	if not xml:
		xml = build_for_type(doctype)
		cache.set_xml(doctype, xml)

	return _xml_response(xml)


@frappe.whitelist(allow_guest=True)
def get_robots():
	"""GET /robots.txt → environment-aware content."""
	from werkzeug.wrappers import Response

	from tradehub_core.seo.robots_generator import get_robots_txt

	content = get_robots_txt()
	response = Response(content, mimetype="text/plain")
	response.headers["Cache-Control"] = "public, max-age=3600"
	return response
