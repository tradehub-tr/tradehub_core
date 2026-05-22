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

	slug = frappe.db.get_value(doctype, legacy_id, slug_field)
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


@frappe.whitelist(allow_guest=True)
def get_sitemap_index():
	"""GET /sitemap.xml → cache'ten index XML."""
	from werkzeug.wrappers import Response

	from tradehub_core.seo.sitemap_cache import get_default_cache
	from tradehub_core.seo.sitemap_generator import build_index

	cache = get_default_cache()
	xml = cache.get_xml("index")
	if not xml:
		xml = build_index()
		cache.set_xml("index", xml)

	response = Response(xml, mimetype="application/xml")
	response.headers["Cache-Control"] = "public, max-age=3600"
	return response


@frappe.whitelist(allow_guest=True)
def get_sitemap(name: str):
	"""GET /sitemap-<name>.xml → cache'ten alt-sitemap XML.

	`name`: 'products' | 'categories' | 'brands' | 'sellers'."""
	from werkzeug.wrappers import Response

	from tradehub_core.seo.sitemap_cache import get_default_cache
	from tradehub_core.seo.sitemap_generator import DOCTYPE_CONFIG, build_for_type

	name_to_doctype = {
		cfg["sub_sitemap_name"]: dt for dt, cfg in DOCTYPE_CONFIG.items()
	}
	doctype = name_to_doctype.get(name)
	if not doctype:
		return Response("Not Found", status=404, mimetype="text/plain")

	cache = get_default_cache()
	xml = cache.get_xml(doctype)
	if not xml:
		xml = build_for_type(doctype)
		cache.set_xml(doctype, xml)

	response = Response(xml, mimetype="application/xml")
	response.headers["Cache-Control"] = "public, max-age=3600"
	return response


@frappe.whitelist(allow_guest=True)
def get_robots():
	"""GET /robots.txt → environment-aware content."""
	from werkzeug.wrappers import Response

	from tradehub_core.seo.robots_generator import get_robots_txt

	content = get_robots_txt()
	response = Response(content, mimetype="text/plain")
	response.headers["Cache-Control"] = "public, max-age=3600"
	return response
