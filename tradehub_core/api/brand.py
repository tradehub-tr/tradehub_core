import frappe
from frappe import _
from frappe.utils import now_datetime


APPROVER_ROLES = {"System Manager", "Marketplace Admin"}


def _ensure_approver():
	user = frappe.session.user
	if user == "Administrator":
		return
	roles = set(frappe.get_roles(user))
	if not (roles & APPROVER_ROLES):
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)


@frappe.whitelist()
def approve(name: str) -> dict:
	_ensure_approver()
	doc = frappe.get_doc("Brand", name)
	if doc.status == "Approved":
		return {"name": doc.name, "status": doc.status}
	doc.status = "Approved"
	doc.reviewed_by = frappe.session.user
	doc.reviewed_at = now_datetime()
	doc.rejection_reason = None
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def reject(name: str, reason: str) -> dict:
	_ensure_approver()
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Ret için gerekçe zorunludur."))
	doc = frappe.get_doc("Brand", name)
	doc.status = "Rejected"
	doc.rejection_reason = reason
	doc.reviewed_by = frappe.session.user
	doc.reviewed_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def pending_count() -> int:
	if frappe.session.user == "Guest":
		return 0
	return frappe.db.count("Brand", {"status": "Pending Approval"})


@frappe.whitelist(allow_guest=True)
def get_brand_detail(slug=None, code=None, page=1, page_size=20, sort_by="modified", sort_order="DESC"):
	"""Public brand storefront endpoint.

	Returns:
		{
		  "brand": { code, name, slug, logo, description, foundedYear, website,
		             country, isOfficial, brandOwner (seller code if verified),
		             brandOwnerName },
		  "listings": [ProductListingCard...],
		  "total": N, "page": 1, "totalPages": M
		}
	"""
	if not slug and not code:
		frappe.throw(_("slug veya code parametresi gerekli"))

	# Resolve brand
	brand_filters = {"status": "Approved", "is_active": 1}
	if slug:
		brand_filters["slug"] = slug
	else:
		brand_filters["name"] = code

	brand = frappe.db.get_value(
		"Brand",
		brand_filters,
		[
			"name", "brand_code", "brand_name", "slug", "logo", "description",
			"founded_year", "website", "country", "official_status",
			"brand_owner",
			"tagline", "hero_banner", "theme_color", "video_url",
			"about_title", "about_content",
			"instagram_url", "facebook_url", "twitter_url", "linkedin_url", "youtube_url",
		],
		as_dict=True,
	)
	if not brand:
		frappe.throw(_("Marka bulunamadı"), frappe.DoesNotExistError)

	# Resolve brand_owner seller info (display name)
	owner_info = None
	if brand.brand_owner:
		seller = frappe.db.get_value(
			"Admin Seller Profile",
			brand.brand_owner,
			["seller_name", "company_name", "country", "logo"],
			as_dict=True,
		)
		if seller:
			owner_info = {
				"code": brand.brand_owner,
				"name": seller.get("seller_name") or seller.get("company_name") or brand.brand_owner,
				"country": seller.get("country") or "",
				"logo": seller.get("logo") or "",
			}

	# Country name resolution
	country_name = ""
	if brand.country:
		country_name = frappe.db.get_value("Country", brand.country, "name") or brand.country

	# Socials dict (skip empty)
	socials = {}
	for platform, url in (
		("instagram", brand.instagram_url),
		("facebook", brand.facebook_url),
		("twitter", brand.twitter_url),
		("linkedin", brand.linkedin_url),
		("youtube", brand.youtube_url),
	):
		if url:
			socials[platform] = url

	brand_payload = {
		"code": brand.name,
		"name": brand.brand_name or brand.name,
		"slug": brand.slug or frappe.scrub(brand.name).replace("_", "-"),
		"logo": brand.logo or "",
		"description": brand.description or "",
		"foundedYear": brand.founded_year or None,
		"website": brand.website or "",
		"country": country_name,
		"isOfficial": brand.official_status == "Verified",
		"officialStatus": brand.official_status or "Unverified",
		"owner": owner_info,
		"tagline": brand.tagline or "",
		"heroBanner": brand.hero_banner or "",
		"themeColor": brand.theme_color or "",
		"videoUrl": brand.video_url or "",
		"aboutTitle": brand.about_title or "",
		"aboutContent": brand.about_content or "",
		"socials": socials,
		"listingCount": frappe.db.count(
			"Listing", {"brand": brand.name, "status": "Active", "is_visible": 1}
		),
	}

	# Fetch brand listings via shared helper
	from tradehub_core.api.listing import get_listings, _format_listing_card

	listings_result = get_listings(
		brands=brand.name,
		page=page,
		page_size=page_size,
		sort_by=sort_by,
		sort_order=sort_order,
	)

	# Featured listings — pinned by brand_owner/admin, shown at top
	featured_cards = []
	featured_rows = frappe.get_all(
		"Brand Featured Listing",
		filters={"parent": brand.name, "parenttype": "Brand"},
		fields=["listing", "display_order"],
		order_by="display_order ASC, idx ASC",
	)
	if featured_rows:
		listing_ids = [r.listing for r in featured_rows if r.listing]
		if listing_ids:
			listings_map = {}
			for lst in frappe.get_all(
				"Listing",
				filters=[
					["name", "in", listing_ids],
					["status", "=", "Active"],
					["is_visible", "=", 1],
				],
				fields=[
					"name", "listing_code", "title", "primary_image",
					"selling_price", "base_price", "currency",
					"discount_percentage", "min_order_qty", "stock_uom",
					"order_count", "average_rating", "review_count",
					"seller_profile", "supplier_display_name",
					"ships_from_country", "country_of_origin",
					"is_free_shipping", "is_featured", "is_best_seller",
					"is_new_arrival", "selling_point",
					"b2b_enabled", "has_variants", "category", "category_name",
					"brand", "brand_name", "modified", "creation",
				],
			):
				listings_map[lst.name] = lst
			# Preserve order from featured_rows
			for r in featured_rows:
				lst = listings_map.get(r.listing)
				if lst:
					featured_cards.append(_format_listing_card(lst))

	return {
		"brand": brand_payload,
		"featured": featured_cards,
		"listings": listings_result.get("data", []),
		"total": listings_result.get("total", 0),
		"page": listings_result.get("page", 1),
		"totalPages": listings_result.get("total_pages", 1),
		"hasNext": listings_result.get("has_next", False),
		"hasPrev": listings_result.get("has_prev", False),
	}
