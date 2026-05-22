"""
JSON-LD structured data schema builder'ları (5 schema türü).

Pure fonksiyonlar Frappe runtime'a bağımlı değildir. Composer'lar
(`compose_for_*`) Frappe wrapper olarak DB'den ek veri çeker.
"""

import html

SCHEMA_CONTEXT = "https://schema.org"


def build_product_schema(
	*,
	listing: dict,
	site_url: str,
	brand: dict | None,
	category_name: str | None,
	aggregate_rating: dict | None,
	reviews: list[dict] | None,
	currency: str = "TRY",
	lang: str = "tr",
) -> dict:
	"""Product schema üret. Pure: I/O yok."""
	slug = listing.get("slug", "")
	url = f"{site_url.rstrip('/')}/urun/{slug}"

	primary_image = listing.get("primary_image")
	images = [primary_image] if primary_image else []

	schema = {
		"@context": SCHEMA_CONTEXT,
		"@type": "Product",
		"name": listing.get("title", ""),
		"image": images,
		"description": listing.get("description", "") or "",
		"sku": listing.get("name", ""),
		"inLanguage": lang,
		"offers": {
			"@type": "Offer",
			"url": url,
			"priceCurrency": currency,
			"price": str(listing.get("base_price", "0")),
			"availability": f"{SCHEMA_CONTEXT}/InStock",
		},
	}

	if brand and brand.get("name"):
		brand_slug = brand.get("slug") or ""
		schema["brand"] = {
			"@type": "Brand",
			"name": brand["name"],
			"url": f"{site_url.rstrip('/')}/marka/{brand_slug}",
		}

	if category_name:
		schema["category"] = category_name

	if aggregate_rating and aggregate_rating.get("count"):
		schema["aggregateRating"] = {
			"@type": "AggregateRating",
			"ratingValue": str(aggregate_rating["value"]),
			"reviewCount": str(aggregate_rating["count"]),
		}

	if reviews:
		schema["review"] = reviews

	return schema


def build_breadcrumb_schema(*, items: list[dict]) -> dict:
	"""BreadcrumbList schema üret. items: [{"name", "url"}, ...]"""
	return {
		"@context": SCHEMA_CONTEXT,
		"@type": "BreadcrumbList",
		"itemListElement": [
			{
				"@type": "ListItem",
				"position": idx + 1,
				"name": item.get("name", ""),
				"item": item.get("url", ""),
			}
			for idx, item in enumerate(items)
		],
	}


def build_organization_schema(
	*,
	site_name: str,
	site_url: str,
	logo_url: str | None,
	same_as: list[str] | None,
) -> dict:
	"""Organization schema üret."""
	schema = {
		"@context": SCHEMA_CONTEXT,
		"@type": "Organization",
		"name": site_name,
		"url": site_url.rstrip("/"),
	}
	if logo_url:
		schema["logo"] = logo_url
	if same_as:
		schema["sameAs"] = list(same_as)
	return schema


def build_website_schema(*, site_url: str, search_url_template: str | None = None) -> dict:
	"""WebSite schema üret (SearchAction içerir, sitelinks searchbox için)."""
	site_url = site_url.rstrip("/")
	template = search_url_template or f"{site_url}/?q={{search_term_string}}"
	return {
		"@context": SCHEMA_CONTEXT,
		"@type": "WebSite",
		"url": site_url,
		"potentialAction": {
			"@type": "SearchAction",
			"target": template,
			"query-input": "required name=search_term_string",
		},
	}


def build_faq_schema(*, questions: list[dict]) -> dict | None:
	"""FAQ schema üret. questions: [{"question", "answer"}, ...]

	Empty list → None (atlanır)."""
	if not questions:
		return None

	return {
		"@context": SCHEMA_CONTEXT,
		"@type": "FAQPage",
		"mainEntity": [
			{
				"@type": "Question",
				"name": html.escape(q.get("question", "")),
				"acceptedAnswer": {
					"@type": "Answer",
					"text": html.escape(q.get("answer", "")),
				},
			}
			for q in questions
		],
	}


# ── Composer'lar (pure) ────────────────────────────────────────────────────


def _same_as_from_defaults(defaults: dict) -> list[str]:
	"""defaults dict'inden sosyal medya URL'leri toplar."""
	result = []
	for key in ("twitter", "facebook", "linkedin", "instagram", "youtube"):
		val = defaults.get(key)
		if val and val.startswith("http"):
			result.append(val)
	return result


def _pure_compose_for_listing(*, ctx: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Listing için tüm schema setini üret. Pure: ctx tüm input verisi."""
	listing = ctx["listing"]
	schemas: list[dict] = []

	# 1. Product
	schemas.append(
		build_product_schema(
			listing=listing,
			site_url=site_url,
			brand=ctx.get("brand"),
			category_name=ctx.get("category_name"),
			aggregate_rating=ctx.get("aggregate_rating"),
			reviews=ctx.get("reviews"),
		)
	)

	# 2. BreadcrumbList: Home → Category → Listing
	items = [{"name": "Anasayfa", "url": f"{site_url.rstrip('/')}/"}]
	if ctx.get("category_name") and ctx.get("category_url"):
		items.append({"name": ctx["category_name"], "url": ctx["category_url"]})
	items.append(
		{
			"name": listing.get("title", ""),
			"url": f"{site_url.rstrip('/')}/urun/{listing.get('slug', '')}",
		}
	)
	schemas.append(build_breadcrumb_schema(items=items))

	# 3. Organization
	schemas.append(
		build_organization_schema(
			site_name=defaults.get("site_name", ""),
			site_url=site_url,
			logo_url=defaults.get("logo"),
			same_as=defaults.get("same_as") or _same_as_from_defaults(defaults),
		)
	)

	# 4. FAQ (varsa)
	faq = build_faq_schema(questions=ctx.get("questions", []))
	if faq:
		schemas.append(faq)

	return schemas


def _pure_compose_for_category(*, category: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Product Category için: Breadcrumb + Organization."""
	slug = category.get("url_slug", "")
	items = [
		{"name": "Anasayfa", "url": f"{site_url.rstrip('/')}/"},
		{"name": "Kategoriler", "url": f"{site_url.rstrip('/')}/kategoriler"},
		{"name": category.get("category_name", ""), "url": f"{site_url.rstrip('/')}/kategori/{slug}"},
	]
	return [
		build_breadcrumb_schema(items=items),
		build_organization_schema(
			site_name=defaults.get("site_name", ""),
			site_url=site_url,
			logo_url=defaults.get("logo"),
			same_as=_same_as_from_defaults(defaults),
		),
	]


def _pure_compose_for_brand(*, brand: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Brand için: Organization (Brand-as-Org) + Breadcrumb."""
	slug = brand.get("slug", "")
	brand_url = f"{site_url.rstrip('/')}/marka/{slug}"

	org = build_organization_schema(
		site_name=brand.get("brand_name", ""),
		site_url=brand_url,
		logo_url=brand.get("logo"),
		same_as=None,
	)

	items = [
		{"name": "Anasayfa", "url": f"{site_url.rstrip('/')}/"},
		{"name": "Markalar", "url": f"{site_url.rstrip('/')}/markalar"},
		{"name": brand.get("brand_name", ""), "url": brand_url},
	]
	breadcrumb = build_breadcrumb_schema(items=items)

	return [org, breadcrumb]


def _pure_compose_for_seller(*, seller: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Admin Seller Profile için: Organization + Breadcrumb."""
	slug = seller.get("slug", "")
	seller_url = f"{site_url.rstrip('/')}/magaza/{slug}"

	org = build_organization_schema(
		site_name=seller.get("seller_name", ""),
		site_url=seller_url,
		logo_url=seller.get("logo"),
		same_as=None,
	)

	items = [
		{"name": "Anasayfa", "url": f"{site_url.rstrip('/')}/"},
		{"name": "Mağazalar", "url": f"{site_url.rstrip('/')}/magazalar"},
		{"name": seller.get("seller_name", ""), "url": seller_url},
	]
	breadcrumb = build_breadcrumb_schema(items=items)

	return [org, breadcrumb]


# ── Frappe-aware composer wrapper'lar ─────────────────────────────────────


def _fetch_answered_questions_for(listing_name: str) -> list[dict]:
	"""status='Answered' Listing Question'lardan ilk 10'unu çek."""
	import frappe

	try:
		rows = frappe.get_all(
			"Listing Question",
			filters={"listing": listing_name, "status": "Answered"},
			fields=["question", "answer"],
			limit_page_length=10,
			order_by="creation asc",
		)
		return [
			{"question": r.get("question") or "", "answer": r.get("answer") or ""}
			for r in rows
			if r.get("answer")
		]
	except Exception:
		return []


def _get_listing_extra_context(listing_name: str) -> dict:
	"""Listing için brand + category + rating + reviews + questions topla."""
	import frappe

	ctx = {
		"brand": None,
		"category_name": None,
		"category_url": None,
		"aggregate_rating": None,
		"reviews": None,
		"questions": [],
	}

	listing = frappe.db.get_value(
		"Listing",
		listing_name,
		["brand", "brand_name", "category", "category_name", "average_rating", "review_count"],
		as_dict=True,
	)
	if not listing:
		return ctx

	# Brand
	if listing.get("brand"):
		brand_slug = frappe.db.get_value("Brand", listing["brand"], "slug")
		ctx["brand"] = {
			"name": listing.get("brand_name") or "",
			"slug": brand_slug or "",
		}

	# Category
	if listing.get("category_name"):
		ctx["category_name"] = listing["category_name"]
		site_url = frappe.utils.get_url().rstrip("/")
		ctx["category_url"] = f"{site_url}/kategori/{listing.get('category', '')}"

	# AggregateRating
	if listing.get("review_count"):
		ctx["aggregate_rating"] = {
			"value": listing.get("average_rating") or 0,
			"count": listing["review_count"],
		}

	# Reviews (mevcut endpoint'ten alınır)
	try:
		from tradehub_core.api.seo import get_review_schema_jsonld

		review_schema = get_review_schema_jsonld(listing=listing_name)
		if isinstance(review_schema, dict) and review_schema.get("review"):
			ctx["reviews"] = review_schema["review"]
	except Exception:
		pass

	# FAQ (Listing Question)
	ctx["questions"] = _fetch_answered_questions_for(listing_name)

	return ctx


def _frappe_defaults() -> dict:
	"""Website Settings SEO defaults + sosyal medya URL'leri."""
	import frappe

	ws = frappe.get_single("Website Settings")
	twitter_handle = (ws.get("seo_twitter_handle") or "").lstrip("@")
	return {
		"site_name": ws.get("seo_site_name") or "İstoç",
		"logo": ws.get("seo_og_image") or "",
		"twitter": (f"https://twitter.com/{twitter_handle}" if twitter_handle else None),
	}


def compose_for_listing(listing: dict, defaults: dict, site_url: str) -> list[dict]:
	"""Frappe wrapper: Listing için tüm schema setini üret."""
	ctx = {"listing": listing}
	ctx.update(_get_listing_extra_context(listing.get("name", "")))
	merged_defaults = {**defaults, **_frappe_defaults()}
	return _pure_compose_for_listing(ctx=ctx, defaults=merged_defaults, site_url=site_url)


def compose_for_category(category: dict, defaults: dict, site_url: str) -> list[dict]:
	merged_defaults = {**defaults, **_frappe_defaults()}
	return _pure_compose_for_category(category=category, defaults=merged_defaults, site_url=site_url)


def compose_for_brand(brand: dict, defaults: dict, site_url: str) -> list[dict]:
	merged_defaults = {**defaults, **_frappe_defaults()}
	return _pure_compose_for_brand(brand=brand, defaults=merged_defaults, site_url=site_url)


def compose_for_seller(seller: dict, defaults: dict, site_url: str) -> list[dict]:
	merged_defaults = {**defaults, **_frappe_defaults()}
	return _pure_compose_for_seller(seller=seller, defaults=merged_defaults, site_url=site_url)
