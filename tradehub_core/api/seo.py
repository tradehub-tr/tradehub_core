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
