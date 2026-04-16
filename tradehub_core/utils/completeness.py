"""Listing Completeness Score — Alibaba-style 0-100 quality score.

Calculated on every Listing save. Weights are calibrated for B2B marketplace
buyer discovery and trust.

Categories:
  basic_info    (25)  — title, description, category, brand
  pricing       (20)  — prices, MOQ, bulk tiers
  media         (20)  — images, video
  attributes    (12)  — required attribute fill rate
  shipping      (10)  — weight, origin, lead times
  seo           ( 8)  — meta fields, route
  certifications( 5)  — product certifications
"""

import frappe
from frappe.utils import cint, flt, strip_html

WEIGHTS = {
	"basic_info": 25,
	"pricing": 20,
	"media": 20,
	"attributes": 12,
	"shipping": 10,
	"seo": 8,
	"certifications": 5,
}

LABELS = {
	"basic_info": "Temel Bilgiler",
	"pricing": "Fiyatlandırma",
	"media": "Medya",
	"attributes": "Özellikler",
	"shipping": "Kargo & Lojistik",
	"seo": "SEO",
	"certifications": "Sertifikalar",
}


def calculate_completeness_score(doc) -> int:
	"""Return 0-100 integer score for a Listing document."""
	total = 0.0
	for key, weight in WEIGHTS.items():
		fn = _SCORERS[key]
		ratio = max(0.0, min(1.0, fn(doc)))
		total += ratio * weight

	total += _variant_penalty(doc)
	return max(0, min(100, int(round(total))))


def get_score_breakdown(doc) -> dict:
	"""Return detailed breakdown for admin panel UI."""
	categories = {}
	total = 0.0
	missing = []

	for key, weight in WEIGHTS.items():
		fn = _SCORERS[key]
		ratio = max(0.0, min(1.0, fn(doc)))
		score = round(ratio * weight, 1)
		total += score
		categories[key] = {
			"score": int(round(score)),
			"max": weight,
			"pct": int(round(ratio * 100)),
			"label": LABELS[key],
		}

	penalty = _variant_penalty(doc)
	total += penalty

	# Collect missing fields
	missing = _collect_missing_fields(doc)

	return {
		"total": max(0, min(100, int(round(total)))),
		"categories": categories,
		"variant_penalty": penalty,
		"missing_fields": missing,
	}


# ── Category scorers ─────────────────────────────────────────────────────────


def _score_basic_info(doc) -> float:
	s = 0.0
	title = (doc.title or "").strip()
	if title and len(title) >= 10:
		s += 0.15

	short_desc = strip_html(doc.short_description or "").strip() if hasattr(doc, "short_description") else ""
	if short_desc and len(short_desc) >= 50:
		s += 0.15

	desc = strip_html(doc.description or "").strip()
	if desc and len(desc) >= 100:
		s += 0.20

	if doc.product_category:
		s += 0.15
	if getattr(doc, "category", None):
		s += 0.10
	if doc.brand:
		s += 0.10
	if doc.product_type or doc.product_family:
		s += 0.10
	if doc.attribute_set:
		s += 0.05
	return s


def _score_pricing(doc) -> float:
	s = 0.0
	if flt(doc.base_price) > 0:
		s += 0.25
	if flt(doc.selling_price) > 0:
		s += 0.25
	if cint(doc.min_order_qty) >= 1:
		s += 0.15

	tiers = doc.pricing_tiers or []
	if doc.b2b_enabled and len(tiers) >= 2:
		s += 0.20
	elif not doc.b2b_enabled:
		s += 0.20  # no tiers needed

	if flt(getattr(doc, "sample_price", 0)) > 0:
		s += 0.15
	return s


def _score_media(doc) -> float:
	s = 0.0
	if doc.primary_image:
		s += 0.40

	images = doc.listing_images or []
	img_count = len(images)
	s += min(0.30, img_count * 0.10)  # 0.10 per image up to 3
	if img_count >= 5:
		s += 0.10  # bonus

	if doc.video_url:
		s += 0.20
	return s


def _score_attributes(doc) -> float:
	filled = {row.attribute_name for row in (doc.attribute_values or []) if row.attribute_value}
	if not doc.attribute_set:
		return 1.0 if filled else 0.0

	required = frappe.get_all(
		"Attribute Set Item",
		filters={"parent": doc.attribute_set, "is_required": 1},
		fields=["attribute"],
		limit_page_length=0,
	)
	if not required:
		return 1.0 if filled else 0.3

	required_names = {r.attribute for r in required}
	filled_required = filled & required_names
	ratio = len(filled_required) / len(required_names) if required_names else 1.0
	return 0.30 + (0.70 * ratio)


def _score_shipping(doc) -> float:
	s = 0.0
	if flt(doc.shipping_weight) > 0:
		s += 0.20
	if doc.ships_from_country:
		s += 0.15
	if cint(doc.handling_days) > 0:
		s += 0.15
	if doc.lead_time_ranges and len(doc.lead_time_ranges) >= 1:
		s += 0.20
	if getattr(doc, "package_type", None):
		s += 0.15
	if getattr(doc, "country_of_origin", None):
		s += 0.15
	return s


def _score_seo(doc) -> float:
	s = 0.0
	if doc.meta_title:
		s += 0.35
	if doc.meta_description:
		s += 0.35
	if doc.route:
		s += 0.30
	return s


def _score_certifications(doc) -> float:
	certs = doc.product_certifications or []
	return 1.0 if len(certs) >= 1 else 0.0


def _variant_penalty(doc) -> int:
	"""Deduct 5 points if variants enabled but no variant items defined."""
	if cint(getattr(doc, "has_variants", 0)) and not (doc.variant_items or []):
		return -5
	return 0


# ── Missing field collector ───────────────────────────────────────────────────


def _collect_missing_fields(doc) -> list:
	missing = []
	title = (doc.title or "").strip()
	if not title or len(title) < 10:
		missing.append("Başlık (min 10 karakter)")

	desc = strip_html(doc.description or "").strip()
	if not desc or len(desc) < 100:
		missing.append("Açıklama (min 100 karakter)")

	if not doc.product_category:
		missing.append("Kategori")
	if not doc.brand:
		missing.append("Marka")
	if not doc.primary_image:
		missing.append("Ana Görsel")

	images = doc.listing_images or []
	if len(images) < 3:
		missing.append(f"Ek Görseller ({len(images)}/3)")

	if not doc.video_url:
		missing.append("Video")
	if flt(doc.base_price) <= 0:
		missing.append("Listeleme Fiyatı")
	if flt(doc.selling_price) <= 0:
		missing.append("Satış Fiyatı")
	if not doc.meta_title:
		missing.append("SEO Başlık")
	if not doc.meta_description:
		missing.append("SEO Açıklama")
	if flt(doc.shipping_weight) <= 0:
		missing.append("Kargo Ağırlığı")
	if not doc.ships_from_country:
		missing.append("Kargolanan Ülke")

	certs = doc.product_certifications or []
	if len(certs) == 0:
		missing.append("Sertifika")

	return missing


# ── Scorer registry ───────────────────────────────────────────────────────────

_SCORERS = {
	"basic_info": _score_basic_info,
	"pricing": _score_pricing,
	"media": _score_media,
	"attributes": _score_attributes,
	"shipping": _score_shipping,
	"seo": _score_seo,
	"certifications": _score_certifications,
}
