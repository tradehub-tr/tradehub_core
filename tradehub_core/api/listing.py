import frappe
from frappe import _
import json
import datetime
import hashlib


def _cache_key(prefix: str, **kwargs) -> str:
    """Generate a deterministic cache key from parameters."""
    raw = json.dumps(kwargs, sort_keys=True, default=str)
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"{prefix}:{h}"


CACHE_TTL = 30  # seconds — short TTL for listing queries


@frappe.whitelist(allow_guest=True)
def get_listings(
    query=None,
    category=None,
    min_price=None,
    max_price=None,
    supplier=None,
    sort_by="modified",
    sort_order="DESC",
    page=1,
    page_size=20,
    is_featured=None,
    is_best_seller=None,
    is_new_arrival=None,
    verified_supplier=None,
    min_rating=None,
    country=None,
    free_shipping=None,
    paid_samples=None,
    certifications=None,
    mgmt_certifications=None,
    product_certifications=None,
):
    """Get paginated list of active listings for the product listing page.

    Returns data matching the frontend ProductListingCard interface.
    """
    page = int(page)
    page_size = min(int(page_size), 100)

    # ── Cache check ──
    ck = _cache_key("listings", q=query, cat=category, minp=min_price, maxp=max_price,
                     sup=supplier, sb=sort_by, so=sort_order, p=page, ps=page_size,
                     feat=is_featured, best=is_best_seller, new=is_new_arrival,
                     vs=verified_supplier, mr=min_rating, co=country, fs=free_shipping,
                     ps2=paid_samples, cert=certifications,
                     mc=mgmt_certifications, pc=product_certifications)
    cached = frappe.cache.get_value(ck)
    if cached:
        return cached
    start = (page - 1) * page_size

    filters = {
        "status": "Active",
        "is_visible": 1,
    }

    if category:
        # category param is a url_slug from Product Category.
        # Try to resolve it as a platform category first (url_slug lookup),
        # then fall back to exact match on the seller category field.
        platform_cat = frappe.db.get_value(
            "Product Category", {"url_slug": category}, "name"
        )
        if platform_cat:
            # Filter by platform category (product_category field)
            filters["product_category"] = platform_cat
        else:
            # Fallback: treat as seller category name/id
            filters["category"] = category
    if is_featured:
        filters["is_featured"] = 1
    if is_best_seller:
        filters["is_best_seller"] = 1
    if is_new_arrival:
        filters["is_new_arrival"] = 1
    if free_shipping:
        filters["is_free_shipping"] = 1
    if paid_samples:
        filters["sample_price"] = [">", 0]

    # ── Supplier-level filters (verified, country, certifications) ──
    # These require a sub-query on Admin Seller Profile to get matching seller_profile names.
    seller_profile_filters = {}
    seller_or_filters = None
    if verified_supplier:
        seller_profile_filters["is_verified"] = 1
    if country:
        seller_profile_filters["country"] = country

    # Management certifications filter: via Seller Certification child table
    if certifications or mgmt_certifications:
        cert_str = mgmt_certifications or certifications
        cert_list = [c.strip() for c in cert_str.split(",") if c.strip()]
        if cert_list:
            # Find sellers who have ANY of these certifications
            sellers_with_certs = frappe.get_all(
                "Seller Certification",
                filters=[["certification_type", "in", cert_list]],
                fields=["parent"],
                pluck="parent",
            )
            if sellers_with_certs:
                seller_profile_filters["name"] = ["in", list(set(sellers_with_certs))]
            else:
                return {
                    "data": [], "total": 0, "page": page, "page_size": page_size,
                    "total_pages": 1, "has_next": False, "has_prev": False,
                }

    if seller_profile_filters:
        matching_sellers = frappe.get_all(
            "Admin Seller Profile",
            filters=seller_profile_filters,
            fields=["name"],
            pluck="name",
        )
        if matching_sellers:
            filters["seller_profile"] = ["in", matching_sellers]
        else:
            return {
                "data": [], "total": 0, "page": page, "page_size": page_size,
                "total_pages": 1, "has_next": False, "has_prev": False,
            }

    # Product certifications filter: via Listing Certification child table
    if product_certifications:
        pcert_list = [c.strip() for c in product_certifications.split(",") if c.strip()]
        if pcert_list:
            listings_with_pcerts = frappe.get_all(
                "Listing Certification",
                filters=[["certification_type", "in", pcert_list]],
                fields=["parent"],
                pluck="parent",
            )
            if listings_with_pcerts:
                filters["name"] = ["in", list(set(listings_with_pcerts))]
            else:
                return {
                    "data": [], "total": 0, "page": page, "page_size": page_size,
                    "total_pages": 1, "has_next": False, "has_prev": False,
                }

    # ── Rating filter ──
    if min_rating:
        filters["average_rating"] = [">=", float(min_rating)]

    # ── Brand filter ──
    if supplier:
        filters["brand"] = ["like", f"%{supplier}%"]

    # ── Text search (split into words for AND matching) ──
    or_filters = None
    search_words = []
    if query:
        search_words = [w.strip() for w in query.split() if w.strip()]
        if len(search_words) <= 1:
            # Single word: original OR across fields
            or_filters = [
                ["title", "like", f"%{query}%"],
                ["short_description", "like", f"%{query}%"],
                ["brand", "like", f"%{query}%"],
            ]
        # Multi-word handled after main query via Python filter

    # ── Price range filter ──
    price_filters = []
    if min_price:
        price_filters.append(["Listing", "selling_price", ">=", float(min_price)])
    if max_price:
        price_filters.append(["Listing", "selling_price", "<=", float(max_price)])

    # ── Sorting ──
    use_relevance_sort = sort_by == "relevance" and bool(query)

    valid_sort_fields = {
        "modified": "modified",
        "price_asc": "selling_price",
        "price_desc": "selling_price",
        "newest": "creation",
        "rating": "average_rating",
        "orders": "order_count",
        "relevance": "modified",
    }

    actual_sort_field = valid_sort_fields.get(sort_by, "modified")
    if sort_by == "price_asc":
        sort_order = "ASC"
    elif sort_by == "price_desc":
        sort_order = "DESC"
    elif sort_by == "rating":
        sort_order = "DESC"
    elif sort_by == "orders":
        sort_order = "DESC"

    fields = [
        "name", "listing_code", "title", "primary_image",
        "selling_price", "base_price", "compare_at_price", "currency",
        "discount_percentage", "min_order_qty", "stock_uom",
        "order_count", "average_rating", "review_count",
        "seller_profile", "supplier_display_name",
        "ships_from_country", "country_of_origin",
        "is_free_shipping", "is_featured", "is_best_seller",
        "is_new_arrival", "is_on_sale", "selling_point",
        "b2b_enabled", "has_variants", "category", "category_name",
        "brand", "modified", "creation",
    ]

    # Convert dict filters to list-of-lists and append price filters
    all_filters = [[k, v[0], v[1]] if isinstance(v, list) else [k, "=", v] for k, v in filters.items()]
    all_filters.extend(price_filters)

    # ── Multi-word search: fetch broader set then filter in Python ──
    if len(search_words) > 1:
        # Fetch all matching ANY word (broad), then narrow to ALL words
        broad_or = []
        for word in search_words:
            broad_or.append(["title", "like", f"%{word}%"])
            broad_or.append(["short_description", "like", f"%{word}%"])
            broad_or.append(["brand", "like", f"%{word}%"])

        all_listings = frappe.get_all(
            "Listing",
            filters=all_filters,
            or_filters=broad_or,
            fields=fields + ["short_description"],
            order_by=f"{actual_sort_field} {sort_order}",
        )

        # Filter: every word must appear in at least one searchable field
        def matches_all_words(listing):
            searchable = " ".join([
                (listing.get("title") or ""),
                (listing.get("short_description") or ""),
                (listing.get("brand") or ""),
            ]).lower()
            return all(w.lower() in searchable for w in search_words)

        matched = [l for l in all_listings if matches_all_words(l)]
        total = len(matched)

        # Apply relevance sort if requested
        if use_relevance_sort:
            matched = _sort_by_relevance(matched, search_words)

        # Paginate
        paginated = matched[start:start + page_size]

    else:
        # Single word or no query — use standard DB query
        listings = frappe.get_all(
            "Listing",
            filters=all_filters,
            or_filters=or_filters,
            fields=fields,
            order_by=f"{actual_sort_field} {sort_order}",
            start=start if not use_relevance_sort else 0,
            page_length=page_size if not use_relevance_sort else 0,
        )

        if use_relevance_sort:
            listings = _sort_by_relevance(listings, search_words or [query])
            total = len(listings)
            paginated = listings[start:start + page_size]
        else:
            paginated = listings
            # Accurate total count
            count_filters = all_filters[:]
            if or_filters:
                total = len(frappe.get_all(
                    "Listing", filters=count_filters, or_filters=or_filters, fields=["name"],
                ))
            else:
                total = len(frappe.get_all("Listing", filters=count_filters, fields=["name"]))

    # ── Batch prefetch seller profiles and pricing tiers (N+1 optimization) ──
    seller_ids = list({l.seller_profile for l in paginated if l.get("seller_profile")})
    seller_cache = {}
    if seller_ids:
        for sp in frappe.get_all(
            "Admin Seller Profile",
            filters=[["name", "in", seller_ids]],
            fields=["name", "founded_year", "country", "is_verified", "rating", "review_count"],
        ):
            seller_cache[sp.name] = sp

    b2b_listing_names = [l.name for l in paginated if l.get("b2b_enabled")]
    tier_cache: dict[str, list] = {}
    if b2b_listing_names:
        for tier in frappe.get_all(
            "Listing Bulk Pricing Tier",
            filters=[["parent", "in", b2b_listing_names], ["parenttype", "=", "Listing"]],
            fields=["parent", "min_qty", "max_qty", "price"],
            order_by="price ASC",
        ):
            tier_cache.setdefault(tier.parent, []).append(tier)

    # Enrich listings with prefetched data
    results = []
    for listing in paginated:
        item = _format_listing_card(listing, seller_cache=seller_cache, tier_cache=tier_cache)
        results.append(item)

    result = {
        "data": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),  # ceil division
        "has_next": (start + page_size) < total,
        "has_prev": page > 1,
    }

    # ── Cache write ──
    frappe.cache.set_value(ck, result, expires_in_sec=CACHE_TTL)

    return result


@frappe.whitelist(allow_guest=True)
def get_listing_detail(listing_id):
    """Get full listing detail for the product detail page.

    Returns data matching the frontend ProductDetail interface.
    """
    if not listing_id:
        frappe.throw(_("Listing ID is required"))

    # Try to find by name or listing_code
    listing_name = listing_id
    if not frappe.db.exists("Listing", listing_id):
        listings = frappe.get_all("Listing", filters={"listing_code": listing_id}, limit=1)
        if listings:
            listing_name = listings[0].name
        else:
            frappe.throw(_("Listing not found"), frappe.DoesNotExistError)

    listing = frappe.get_doc("Listing", listing_name)

    # Increment view count
    frappe.db.set_value("Listing", listing_name, "view_count", (listing.view_count or 0) + 1, update_modified=False)

    # Get supplier info from Admin Seller Profile
    supplier_data = None
    if listing.seller_profile:
        try:
            seller = frappe.get_doc("Admin Seller Profile", listing.seller_profile)
            years_in_business = 0
            if seller.founded_year:
                try:
                    years_in_business = datetime.datetime.now().year - int(seller.founded_year)
                except (ValueError, TypeError):
                    years_in_business = 0
            supplier_data = {
                "name": seller.seller_name or seller.company_name,
                "companyName": seller.company_name,
                "verified": bool(seller.is_verified),
                "verificationType": seller.verification_type,
                "yearsInBusiness": years_in_business,
                "country": seller.country,
                "city": seller.city,
                "logo": seller.logo,
                "responseTime": seller.response_time,
                "responseRate": seller.response_rate or 0,
                "onTimeDelivery": seller.on_time_delivery or 0,
                "mainProducts": [p.strip() for p in (seller.main_markets or "").split(",") if p.strip()],
                "employees": seller.staff_count,
                "annualRevenue": seller.annual_revenue,
                "certifications": [c.strip() for c in (seller.certifications or "").split(",") if c.strip()],
                "rating": seller.rating or 0,
                "reviewCount": seller.review_count or 0,
            }
        except Exception:
            pass

    # Build category breadcrumb (prefer platform category, fallback to seller category)
    category_breadcrumb = _get_category_breadcrumb(listing.product_category or listing.category)

    # Get images — primary_image + listing_images child table
    images = [listing.primary_image] if listing.primary_image else []
    for img in (listing.listing_images or []):
        if img.image:
            images.append(img.image)

    # Fallback: if no images found, check Frappe sidebar attachments (File doctype)
    if not images:
        attachments = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Listing",
                "attached_to_name": listing_name,
                "is_private": 0,
            },
            fields=["file_url"],
            order_by="creation asc",
        )
        image_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg")
        for f in attachments:
            url = f.get("file_url", "")
            if url and any(url.lower().endswith(ext) for ext in image_exts):
                images.append(url)

    # Get pricing tiers
    price_tiers = []
    if listing.b2b_enabled and listing.pricing_tiers:
        for tier in listing.pricing_tiers:
            price_tiers.append({
                "minQty": tier.min_qty,
                "maxQty": tier.max_qty or None,
                "price": tier.price,
                "currency": listing.currency,
            })

    if not price_tiers:
        price_tiers = [{
            "minQty": listing.min_order_qty or 1,
            "maxQty": None,
            "price": listing.selling_price,
            "currency": listing.currency,
        }]

    # Get variants
    variants = _get_listing_variants(listing_name)

    # Get specifications
    specs = []
    for attr in (listing.attribute_values or []):
        specs.append({
            "label": attr.attribute_name,
            "value": attr.attribute_value,
            "group": attr.attribute_group,
        })

    # Build packaging specs from dedicated fields
    packaging_specs = []
    if listing.package_type:
        packaging_specs.append({"label": "Paket Tipi", "value": listing.package_type})
    if listing.package_length and listing.package_width and listing.package_height:
        packaging_specs.append({"label": "Paket Boyutu", "value": f"{listing.package_length} x {listing.package_width} x {listing.package_height} cm"})
    if listing.package_weight:
        packaging_specs.append({"label": "Paket Ağırlığı", "value": f"{listing.package_weight} kg"})
    if listing.units_per_package:
        packaging_specs.append({"label": "Koli Başına Adet", "value": str(listing.units_per_package)})
    if listing.carton_length and listing.carton_width and listing.carton_height:
        packaging_specs.append({"label": "Koli Boyutu", "value": f"{listing.carton_length} x {listing.carton_width} x {listing.carton_height} cm"})
    if listing.carton_gross_weight:
        packaging_specs.append({"label": "Koli Brüt Ağırlığı", "value": f"{listing.carton_gross_weight} kg"})

    # Get shipping methods
    shipping = []
    for sm in (listing.shipping_methods or []):
        shipping.append({
            "method": sm.shipping_method_name or sm.shipping_method,
            "estimatedDays": f"{sm.min_days}-{sm.max_days}" if sm.min_days and sm.max_days else "",
            "cost": sm.cost,
            "currency": listing.currency,
        })

    # Get customization options
    customization_opts = []
    for opt in (listing.customization_options or []):
        customization_opts.append({
            "name": opt.option_name,
            "description": opt.description,
            "additionalCost": opt.additional_cost,
            "minQty": opt.min_qty,
        })

    # Build price display
    price_range = _get_price_range(listing)

    result = {
        "id": listing.name,
        "listingCode": listing.listing_code,
        "title": listing.title,
        "category": category_breadcrumb,
        "productCategoryId": listing.product_category or "",
        "images": images,
        "priceTiers": price_tiers,
        "moq": listing.min_order_qty or 1,
        "unit": listing.stock_uom or "piece",
        "samplePrice": listing.sample_price,
        "currency": listing.currency,
        "sellingPrice": listing.selling_price,
        "basePrice": listing.base_price,
        "compareAtPrice": listing.compare_at_price,
        "discountPercentage": listing.discount_percentage,
        "priceRange": price_range,
        "shipping": shipping,
        "leadTime": f"{listing.handling_days or 1} iş günü" if listing.handling_days else "",
        "leadTimeRanges": [
            {
                "quantityRange": f"{r.min_qty}-{r.max_qty}" if r.max_qty else f"{r.min_qty}+",
                "days": f"{r.lead_days} gün",
            }
            for r in (listing.lead_time_ranges or [])
        ],
        "variants": variants,
        "specs": specs,
        "packagingSpecs": packaging_specs,
        "description": listing.description,
        "shortDescription": listing.short_description,
        "rating": listing.average_rating or 0,
        "reviewCount": listing.review_count or 0,
        "orderCount": listing.order_count or 0,
        "viewCount": listing.view_count or 0,
        "supplier": supplier_data,
        "customizationOptions": customization_opts,
        "brand": listing.brand,
        "condition": listing.condition,
        "isFreeShipping": bool(listing.is_free_shipping),
        "shipsFromCountry": listing.ships_from_country,
        "shipsFromCity": listing.ships_from_city,
        "countryOfOrigin": listing.country_of_origin,
        "isFeatured": bool(listing.is_featured),
        "isBestSeller": bool(listing.is_best_seller),
        "isNewArrival": bool(listing.is_new_arrival),
        "isOnSale": bool(listing.is_on_sale),
        "sellingPoint": listing.selling_point,
        "hasVariants": bool(listing.has_variants),
        "stockQty": listing.available_qty or listing.stock_qty,
        "inStock": (listing.available_qty or listing.stock_qty or 0) > 0,
        "videoUrl": listing.video_url,
    }

    return {"data": result}


@frappe.whitelist(allow_guest=True)
def get_categories(parent=None, include_children=True):
    """Get product categories, optionally filtered by parent.

    Returns hierarchical category structure.
    """
    filters = {"is_active": 1}
    if parent:
        filters["parent_product_category"] = parent
    else:
        filters["parent_product_category"] = ["is", "not set"]

    categories = frappe.get_all(
        "Product Category",
        filters=filters,
        fields=["name", "category_name", "parent_product_category", "image", "icon_class", "url_slug"],
        order_by="category_name ASC",
    )

    results = []
    for cat in categories:
        item = {
            "id": cat.name,
            "name": cat.category_name,
            "slug": cat.url_slug,
            "image": cat.image,
            "icon": cat.icon_class,
            "parent": cat.parent_product_category,
            "children": [],
            "productCount": frappe.db.count("Listing", {"product_category": cat.name, "status": "Active", "is_visible": 1}),
        }

        if include_children:
            child_cats = frappe.get_all(
                "Product Category",
                filters={"parent_product_category": cat.name, "is_active": 1},
                fields=["name", "category_name", "url_slug", "image"],
                order_by="category_name ASC",
            )
            for child in child_cats:
                item["children"].append({
                    "id": child.name,
                    "name": child.category_name,
                    "slug": child.url_slug,
                    "image": child.image,
                    "productCount": frappe.db.count("Listing", {"product_category": child.name, "status": "Active", "is_visible": 1}),
                })

        results.append(item)

    return {"data": results}


@frappe.whitelist(allow_guest=True)
def get_filter_facets(query=None, category=None):
    """Return faceted counts for sidebar filters.

    Given optional query/category context, returns:
    - countries: unique ships_from_country values with listing counts
    - categories: product categories with listing counts
    """
    # ── Cache check ──
    fck = _cache_key("facets", q=query, cat=category)
    cached = frappe.cache.get_value(fck)
    if cached:
        return cached

    base_filters = {"status": "Active", "is_visible": 1}
    if category:
        platform_cat = frappe.db.get_value(
            "Product Category", {"url_slug": category}, "name"
        )
        if platform_cat:
            base_filters["product_category"] = platform_cat

    or_filters = None
    if query:
        or_filters = [
            ["title", "like", f"%{query}%"],
            ["short_description", "like", f"%{query}%"],
            ["brand", "like", f"%{query}%"],
        ]

    # Get all matching listing names first (include seller_profile for cert aggregation)
    all_filters = [[k, v[0], v[1]] if isinstance(v, list) else [k, "=", v] for k, v in base_filters.items()]
    listings = frappe.get_all(
        "Listing",
        filters=all_filters,
        or_filters=or_filters,
        fields=["name", "ships_from_country", "product_category", "seller_profile"],
    )

    # Aggregate countries
    country_counts: dict[str, int] = {}
    for l in listings:
        c = l.get("ships_from_country")
        if c:
            country_counts[c] = country_counts.get(c, 0) + 1

    # Resolve country names
    countries = []
    for country_link, count in sorted(country_counts.items(), key=lambda x: -x[1]):
        country_name = frappe.db.get_value("Country", country_link, "name") or country_link
        code = _get_country_code(country_name)
        countries.append({
            "value": country_link,
            "label": country_name,
            "code": code,
            "count": count,
        })

    # Aggregate categories
    cat_counts: dict[str, int] = {}
    for l in listings:
        pc = l.get("product_category")
        if pc:
            cat_counts[pc] = cat_counts.get(pc, 0) + 1

    categories = []
    for cat_name, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        display_name = frappe.db.get_value("Product Category", cat_name, "category_name") or cat_name
        slug = frappe.db.get_value("Product Category", cat_name, "url_slug") or ""
        categories.append({
            "id": cat_name,
            "name": display_name,
            "slug": slug,
            "count": count,
        })

    # Aggregate management certifications from Seller Certification child table
    listing_names = [l.name for l in listings] if listings else []
    mgmt_cert_counts: dict[str, int] = {}
    product_cert_counts: dict[str, int] = {}

    if listing_names:
        # Get seller profiles directly from already-fetched listings
        seller_profiles = list({
            l.seller_profile for l in listings if l.get("seller_profile")
        })

        # Build a lookup of Certification Type → category for filtering
        all_assigned_certs = set()

        # Collect all assigned cert IDs from both child tables
        if seller_profiles:
            seller_certs = frappe.get_all(
                "Seller Certification",
                filters=[["parent", "in", seller_profiles], ["parenttype", "=", "Admin Seller Profile"]],
                fields=["certification_type"],
            )
            for sc in seller_certs:
                all_assigned_certs.add(sc.certification_type)

        product_certs = frappe.get_all(
            "Listing Certification",
            filters=[["parent", "in", listing_names], ["parenttype", "=", "Listing"]],
            fields=["certification_type"],
        )
        for pc in product_certs:
            all_assigned_certs.add(pc.certification_type)

    # Resolve certification types with category — only Approved
    cert_info_map = {}  # {name: {label, category}}
    if all_assigned_certs:
        for ct in frappe.get_all(
            "Certification Type",
            filters=[["name", "in", list(all_assigned_certs)], ["status", "=", "Approved"]],
            fields=["name", "certification_name", "category"],
        ):
            cert_info_map[ct.name] = {
                "label": ct.certification_name or ct.name,
                "category": ct.category,
            }

    # Count by actual category from Certification Type master
    if listing_names:
        if seller_profiles:
            for sc in seller_certs:
                info = cert_info_map.get(sc.certification_type)
                if info and info["category"] == "Management":
                    mgmt_cert_counts[sc.certification_type] = mgmt_cert_counts.get(sc.certification_type, 0) + 1

        for pc in product_certs:
            info = cert_info_map.get(pc.certification_type)
            if info and info["category"] == "Product":
                product_cert_counts[pc.certification_type] = product_cert_counts.get(pc.certification_type, 0) + 1

    mgmt_certifications_list = [
        {"label": cert_info_map[cert]["label"], "value": cert, "count": count}
        for cert, count in sorted(mgmt_cert_counts.items(), key=lambda x: -x[1])
        if cert in cert_info_map
    ]
    product_certifications_list = [
        {"label": cert_info_map[cert]["label"], "value": cert, "count": count}
        for cert, count in sorted(product_cert_counts.items(), key=lambda x: -x[1])
        if cert in cert_info_map
    ]

    facet_result = {
        "data": {
            "countries": countries,
            "categories": categories,
            "managementCertifications": mgmt_certifications_list,
            "productCertifications": product_certifications_list,
        }
    }

    # ── Cache write ──
    frappe.cache.set_value(fck, facet_result, expires_in_sec=CACHE_TTL)

    return facet_result


@frappe.whitelist(allow_guest=True)
def get_shipping_methods(listing_id=None):
    """Get available shipping methods, optionally for a specific listing."""

    if listing_id:
        # Get listing-specific shipping methods
        listing = frappe.get_doc("Listing", listing_id)
        shipping = []
        for sm in (listing.shipping_methods or []):
            shipping.append({
                "id": sm.shipping_method,
                "method": sm.shipping_method_name or sm.shipping_method,
                "cost": sm.cost,
                "minDays": sm.min_days,
                "maxDays": sm.max_days,
                "estimatedDays": f"{sm.min_days}-{sm.max_days} iş günü" if sm.min_days and sm.max_days else "",
                "currency": listing.currency,
            })
        return {"data": shipping}

    # Get all active shipping methods
    methods = frappe.get_all(
        "Shipping Method",
        filters={"is_active": 1},
        fields=["name", "method_name", "shipping_type", "min_days", "max_days", "base_cost", "cost_per_kg", "currency", "description"],
        order_by="base_cost ASC",
    )

    results = []
    for m in methods:
        results.append({
            "id": m.name,
            "method": m.method_name,
            "type": m.shipping_type,
            "minDays": m.min_days,
            "maxDays": m.max_days,
            "estimatedDays": f"{m.min_days}-{m.max_days} iş günü" if m.min_days and m.max_days else "",
            "baseCost": m.base_cost,
            "costPerKg": m.cost_per_kg,
            "currency": m.currency,
            "description": m.description,
        })

    return {"data": results}


@frappe.whitelist(allow_guest=True)
def get_featured_listings(limit=10):
    """Get featured listings for homepage."""
    return get_listings(is_featured=1, page_size=limit)


@frappe.whitelist(allow_guest=True)
def get_related_listings(listing_id, limit=8):
    """Get related listings based on category."""
    if not listing_id:
        return {"data": []}

    listing = frappe.db.get_value("Listing", listing_id, ["category", "brand"], as_dict=True)
    if not listing:
        return {"data": []}

    filters = {
        "status": "Active",
        "is_visible": 1,
        "name": ["!=", listing_id],
    }

    if listing.category:
        filters["category"] = listing.category

    listings = frappe.get_all(
        "Listing",
        filters=filters,
        fields=[
            "name", "listing_code", "title", "primary_image",
            "selling_price", "base_price", "compare_at_price", "currency",
            "discount_percentage", "min_order_qty", "stock_uom",
            "order_count", "average_rating", "review_count",
            "seller_profile", "supplier_display_name",
            "ships_from_country", "country_of_origin",
            "is_free_shipping", "selling_point",
            "b2b_enabled", "category_name", "brand",
        ],
        order_by="order_count DESC",
        limit=int(limit),
    )

    results = [_format_listing_card(l) for l in listings]
    return {"data": results}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def log_search(query: str, category: str = ""):
    """Log a search query for the current user. Guest searches are ignored."""
    if frappe.session.user == "Guest":
        return {"success": True}

    query = (query or "").strip()
    if not query:
        return {"success": True}

    user = frappe.session.user
    query_trimmed = query[:200]
    category_trimmed = (category or "")[:200]

    # Dedup: if same query was logged within last 5 minutes, update its timestamp instead of creating new
    recent_same = frappe.db.get_value(
        "Search History",
        {"user": user, "query": query_trimmed, "creation": [">=", frappe.utils.add_to_date(None, minutes=-5)]},
        "name",
    )
    if recent_same:
        # Touch the existing record to move it to top
        frappe.db.set_value("Search History", recent_same, {
            "category": category_trimmed,
            "modified": frappe.utils.now_datetime(),
            "creation": frappe.utils.now_datetime(),
        }, update_modified=False)
    else:
        # Create new search history record
        doc = frappe.new_doc("Search History")
        doc.user = user
        doc.query = query_trimmed
        doc.category = category_trimmed
        doc.flags.ignore_permissions = True
        doc.insert()

        # Keep max 50 records per user — delete oldest if exceeded
        records = frappe.get_all(
            "Search History",
            filters={"user": user},
            fields=["name", "creation"],
            order_by="creation DESC",
            limit=100,
        )
        if len(records) > 50:
            to_delete = records[50:]
            for r in to_delete:
                frappe.delete_doc("Search History", r.name, force=True, ignore_permissions=True)

    frappe.db.commit()

    # Invalidate user's suggestion cache so new search influences suggestions immediately
    frappe.cache.delete_value(f"search_suggestions:{frappe.session.user}")

    return {"success": True}


def cleanup_old_search_history():
    """Remove search history records older than 30 days. Runs daily via scheduler."""
    cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -30)
    old_records = frappe.get_all(
        "Search History",
        filters={"creation": ["<", cutoff]},
        fields=["name"],
        limit=1000,
    )
    for r in old_records:
        frappe.delete_doc("Search History", r.name, force=True, ignore_permissions=True)
    if old_records:
        frappe.db.commit()


@frappe.whitelist(allow_guest=True)
def get_search_suggestions(limit=6):
    """Get search suggestions and category chips for the search bar.

    Prod-optimized: minimal queries, no N+1, single GROUP BY for categories.
    Logged-in users get personalized results cached 15 min with timestamp freshness.
    Guests get random popular results (no cache).
    """
    import random

    limit = int(limit)
    user = frappe.session.user
    is_guest = user == "Guest"

    # ── Cache check (logged-in only) ──
    cache_key = None
    if not is_guest:
        cache_key = f"search_suggestions:{user}"
        cached = frappe.cache.get_value(cache_key)
        if cached:
            cached_at = cached.get("_cached_at")
            latest_search = frappe.db.get_value(
                "Search History", {"user": user}, "creation", order_by="creation DESC",
            )
            if cached_at and latest_search and str(latest_search) > str(cached_at):
                frappe.cache.delete_value(cache_key)
            else:
                return cached.get("_result", cached)

    # ── Personalized suggestions (logged-in only) ──
    personalized = []
    personalized_cat_chips = []

    if not is_guest:
        # Get recent search categories + queries in ONE query
        recent = frappe.get_all(
            "Search History",
            filters={"user": user},
            fields=["query", "category"],
            order_by="creation DESC",
            limit=10,
        )

        # PRIORITY 1: Recent queries → title match (preserves search order)
        # Max 3 LIKE queries, most recent first
        seen = {s["text"].lower() for s in personalized}
        queries_tried = 0
        for r in recent:
                if queries_tried >= 3:
                    break
                q_text = (r.query or "").strip()
                if not q_text or len(q_text) < 2:
                    continue
                queries_tried += 1
                matches = frappe.get_all(
                    "Listing",
                    filters={"status": "Active", "is_visible": 1, "title": ["like", f"%{q_text}%"]},
                    fields=["title"],
                    order_by="order_count DESC",
                    limit=2,
                )
                for m in matches:
                    key = m.title.lower()
                    if key not in seen:
                        seen.add(key)
                        personalized.append({"text": _truncate_words(m.title, 5), "type": "product"})
                    if len(personalized) >= limit:
                        break

        # PRIORITY 2: Fill remaining from user's searched categories (indexed, fast)
        if len(personalized) < limit:
            user_categories = []
            for r in recent:
                if r.category and r.category not in user_categories:
                    user_categories.append(r.category)
            if user_categories:
                cat_ids = [frappe.db.get_value("Product Category", {"url_slug": c}, "name") or c for c in user_categories[:5]]
                cat_ids = [c for c in cat_ids if c]
                if cat_ids:
                    cat_listings = frappe.get_all(
                        "Listing",
                        filters=[["product_category", "in", cat_ids], ["status", "=", "Active"], ["is_visible", "=", 1]],
                        fields=["title"],
                        order_by="order_count DESC",
                        limit=limit,
                    )
                    for cl in cat_listings:
                        key = cl.title.lower()
                        if key not in seen:
                            seen.add(key)
                            personalized.append({"text": _truncate_words(cl.title, 5), "type": "product"})
                        if len(personalized) >= limit:
                            break

        # Cart categories — batch query
        try:
            cart_cats = frappe.db.sql("""
                SELECT DISTINCT l.product_category
                FROM `tabCart Item` ci
                JOIN `tabCart` c ON c.name = ci.parent
                JOIN `tabListing` l ON l.name = ci.listing
                WHERE c.user = %s AND l.product_category IS NOT NULL AND l.product_category != ''
                LIMIT 5
            """, (user,), as_dict=True)
            for cc in cart_cats:
                cat_info = frappe.db.get_value(
                    "Product Category", cc.product_category,
                    ["category_name", "url_slug"], as_dict=True,
                )
                if cat_info:
                    personalized_cat_chips.append({
                        "text": cat_info.category_name,
                        "type": "category",
                        "slug": cat_info.url_slug or cc.product_category,
                    })
                if len(personalized_cat_chips) >= 3:
                    break
        except Exception:
            pass

    # ── Popular pool (guests + fill remaining for logged-in) ──
    pool_size = max(limit * 3, 20)
    listing_pool = frappe.get_all(
        "Listing",
        filters={"status": "Active", "is_visible": 1},
        fields=["title"],
        order_by="order_count DESC, view_count DESC",
        limit=pool_size,
    )

    if len(listing_pool) > limit:
        random.shuffle(listing_pool)
        popular_selected = listing_pool[:limit]
    else:
        popular_selected = listing_pool

    popular_suggestions = [{"text": _truncate_words(l.title, 5), "type": "product"} for l in popular_selected]

    # ── Merge suggestions ──
    if personalized:
        seen = {s["text"].lower() for s in personalized}
        for ps in popular_suggestions:
            if ps["text"].lower() not in seen:
                personalized.append(ps)
                seen.add(ps["text"].lower())
            if len(personalized) >= limit:
                break
        suggestions = personalized[:limit]
    else:
        suggestions = popular_suggestions

    # ── Category chips — single GROUP BY query instead of N+1 ──
    top_cats = frappe.db.sql("""
        SELECT pc.category_name, pc.url_slug, pc.name, COUNT(*) as cnt
        FROM `tabListing` l
        JOIN `tabProduct Category` pc ON pc.name = l.product_category
        WHERE l.status = 'Active' AND l.is_visible = 1 AND pc.is_active = 1
        GROUP BY pc.name
        HAVING cnt > 0
        ORDER BY cnt DESC
        LIMIT 10
    """, as_dict=True)

    random.shuffle(top_cats)
    general_chips = [
        {"text": c.category_name, "type": "category", "slug": c.url_slug or c.name}
        for c in top_cats[:3]
    ]

    if personalized_cat_chips:
        seen_slugs = {c["slug"] for c in personalized_cat_chips}
        for gc in general_chips:
            if gc["slug"] not in seen_slugs:
                personalized_cat_chips.append(gc)
                seen_slugs.add(gc["slug"])
            if len(personalized_cat_chips) >= 3:
                break
        chips = personalized_cat_chips[:3]
    else:
        chips = general_chips

    result = {"data": {"suggestions": suggestions, "chips": chips}}

    # ── Cache (logged-in, 15 min) ──
    if not is_guest and cache_key:
        frappe.cache.set_value(cache_key, {
            "_result": result,
            "_cached_at": str(frappe.utils.now_datetime()),
        }, expires_in_sec=900)

    return result


# ---- Helper Functions ----


def _sort_by_relevance(listings, words):
    """Sort listings by relevance score.

    Scoring: title exact > title word match > brand match > description match.
    Higher score = more relevant.
    """
    query_lower = " ".join(words).lower()
    words_lower = [w.lower() for w in words]

    def score(listing):
        title = (listing.get("title") or "").lower()
        brand = (listing.get("brand") or "").lower()
        desc = (listing.get("short_description") or "").lower()
        s = 0

        # Exact title match (highest)
        if query_lower == title:
            s += 100
        # Title contains full query
        elif query_lower in title:
            s += 50
        # Each word in title
        for w in words_lower:
            if w in title:
                s += 10
            if w in brand:
                s += 5
            if w in desc:
                s += 2

        # Boost by popularity
        s += min((listing.get("order_count") or 0) / 100, 10)
        return s

    return sorted(listings, key=score, reverse=True)


def _format_listing_card(listing, seller_cache=None, tier_cache=None):
    """Format a listing record into the ProductListingCard structure for frontend.

    Args:
        seller_cache: Pre-fetched seller profiles dict {name: record} to avoid N+1
        tier_cache: Pre-fetched pricing tiers dict {listing_name: [tiers]} to avoid N+1
    """
    # Get supplier info — use cache if available, else individual query (fallback)
    supplier_years = 0
    supplier_country = ""
    supplier_verified = False
    supplier_rating = 0
    supplier_review_count = 0

    if listing.get("seller_profile"):
        try:
            sp = (seller_cache or {}).get(listing.get("seller_profile"))
            if sp is None and seller_cache is None:
                sp = frappe.db.get_value(
                    "Admin Seller Profile",
                    listing.get("seller_profile"),
                    ["founded_year", "country", "is_verified", "rating", "review_count"],
                    as_dict=True,
                )
            if sp:
                if sp.get("founded_year"):
                    try:
                        supplier_years = datetime.datetime.now().year - int(sp.founded_year)
                    except (ValueError, TypeError):
                        supplier_years = 0
                supplier_country = _get_country_code(sp.get("country")) if sp.get("country") else ""
                supplier_verified = bool(sp.get("is_verified"))
                supplier_rating = sp.get("rating") or 0
                supplier_review_count = sp.get("review_count") or 0
        except Exception:
            pass

    # Get price range from pricing tiers — use cache if available
    selling_price = listing.get("selling_price") or 0
    min_price_val = selling_price
    max_price_val = selling_price
    price_display = _format_price(selling_price, listing.get("currency"))

    if listing.get("b2b_enabled"):
        tiers = (tier_cache or {}).get(listing.name)
        if tiers is None and tier_cache is None:
            tiers = frappe.get_all(
                "Listing Bulk Pricing Tier",
                filters={"parent": listing.name, "parenttype": "Listing"},
                fields=["min_qty", "max_qty", "price"],
                order_by="price ASC",
            )
        if tiers:
            min_price_val = min(t.price for t in tiers)
            max_price_val = max(t.price for t in tiers)
            if min_price_val != max_price_val:
                price_display = f"${min_price_val:.2f}-{max_price_val:.2f}"
            else:
                price_display = f"${min_price_val:.2f}"

    # Get images (primary + child table)
    primary_image = listing.get("primary_image", "")
    all_images = []
    child_imgs = frappe.get_all(
        "Listing Image",
        filters={"parent": listing.name, "parenttype": "Listing"},
        fields=["image"],
        order_by="idx ASC",
        limit=5,
    )
    if primary_image:
        all_images.append(primary_image)
    for ci in child_imgs:
        if ci.image and ci.image not in all_images:
            all_images.append(ci.image)
    if not primary_image and all_images:
        primary_image = all_images[0]

    return {
        "id": listing.name,
        "listingCode": listing.get("listing_code", ""),
        "name": listing.title,
        "href": f"/pages/product-detail.html?id={listing.name}",
        "price": price_display,
        "sellingPrice": selling_price,
        "minPrice": min_price_val,
        "maxPrice": max_price_val,
        "originalPrice": _format_price(listing.get("compare_at_price"), listing.get("currency")) if listing.get("compare_at_price") else None,
        "discount": f"%{int(listing.get('discount_percentage', 0))} indirim" if listing.get("discount_percentage") else None,
        "moq": f"{listing.get('min_order_qty', 1)} {listing.get('stock_uom', 'Adet')}",
        "stats": f"{_format_number(listing.get('order_count', 0))} adet satıldı" if listing.get("order_count") else None,
        "imageSrc": primary_image,
        "images": all_images,
        "supplierName": listing.get("supplier_display_name", ""),
        "verified": supplier_verified,
        "supplierYears": supplier_years,
        "supplierCountry": supplier_country,
        "rating": listing.get("average_rating", 0),
        "reviewCount": listing.get("review_count", 0),
        "supplierRating": supplier_rating,
        "supplierReviewCount": supplier_review_count,
        "sellingPoint": listing.get("selling_point", ""),
        "promo": listing.get("selling_point", ""),
        "isFreeShipping": bool(listing.get("is_free_shipping")),
        "isFeatured": bool(listing.get("is_featured")),
        "isBestSeller": bool(listing.get("is_best_seller")),
        "isNewArrival": bool(listing.get("is_new_arrival")),
        "category": listing.get("category_name", ""),
        "brand": listing.get("brand", ""),
        "baseCurrency": listing.get("currency", "USD"),
    }


def _get_listing_variants(listing_name):
    """Get variants grouped by attribute name for the product detail page.

    Sources (checked in order):
    1. Listing Variant Item child table (inline in Listing form)
    2. Listing Variant separate DocType (legacy)
    """
    # First check inline variant items (child table)
    inline_variants = frappe.get_all(
        "Listing Variant Item",
        filters={"parent": listing_name, "parenttype": "Listing"},
        fields=["attribute_type", "attribute_value", "variant_image", "variant_price", "variant_stock", "variant_sku"],
        order_by="idx ASC",
    )

    if inline_variants:
        return _build_variants_from_inline(listing_name, inline_variants)

    # Fallback to separate Listing Variant DocType
    variants = frappe.get_all(
        "Listing Variant",
        filters={"listing": listing_name},
        fields=["name", "variant_name", "sku", "price", "stock_qty", "is_active", "primary_image"],
        order_by="variant_name ASC",
    )

    if not variants:
        return []

    # Get listing's base price and stock for fallback
    listing_data = frappe.db.get_value(
        "Listing", listing_name,
        ["selling_price", "stock_qty", "track_inventory"],
        as_dict=True,
    )
    base_price = listing_data.selling_price if listing_data else 0
    listing_stock = listing_data.stock_qty if listing_data else 0
    track_inventory = listing_data.track_inventory if listing_data else 0

    # Group variants by attribute
    variant_groups = {}
    for v in variants:
        attrs = frappe.get_all(
            "Listing Variant Attribute",
            filters={"parent": v.name, "parenttype": "Listing Variant"},
            fields=["attribute_name", "attribute_value"],
            order_by="idx ASC",
        )
        for attr in attrs:
            group_name = (attr.attribute_name or '').strip()
            if group_name not in variant_groups:
                variant_groups[group_name] = {
                    "name": group_name,
                    "type": "button",
                    "options": [],
                    "_seen_values": set(),
                }

            if attr.attribute_value not in variant_groups[group_name]["_seen_values"]:
                variant_groups[group_name]["_seen_values"].add(attr.attribute_value)

                # Determine availability:
                # - If track_inventory is off, always available
                # - If variant has stock > 0, available
                # - If variant stock is 0 but listing has stock, available (shared stock)
                if not track_inventory:
                    is_available = True
                elif (v.stock_qty or 0) > 0:
                    is_available = True
                elif (listing_stock or 0) > 0:
                    is_available = True
                else:
                    is_available = False

                # Use variant price, fallback to listing base price
                variant_price = v.price if v.price and v.price > 0 else base_price

                # For legacy DocType, addon is the difference from base
                price_addon = (variant_price - base_price) if variant_price > base_price else 0

                option = {
                    "label": attr.attribute_value,
                    "value": attr.attribute_value,
                    "available": is_available,
                    "image": v.primary_image if v.primary_image else None,
                    "price": variant_price,
                    "priceAddon": price_addon,
                    "stockQty": v.stock_qty or 0,
                    "variantId": v.name,
                }
                variant_groups[group_name]["options"].append(option)

    # Clean up and return
    result = []
    for group in variant_groups.values():
        del group["_seen_values"]
        # If any option has an image, mark type as "image"
        if any(opt.get("image") for opt in group["options"]):
            group["type"] = "image"
        result.append(group)

    return result


def _build_variants_from_inline(listing_name, inline_variants):
    """Build variant groups from Listing Variant Item child table rows."""
    listing_data = frappe.db.get_value(
        "Listing", listing_name,
        ["selling_price", "stock_qty", "track_inventory"],
        as_dict=True,
    )
    base_price = listing_data.selling_price if listing_data else 0
    listing_stock = listing_data.stock_qty if listing_data else 0
    track_inventory = listing_data.track_inventory if listing_data else 0

    variant_groups = {}
    for v in inline_variants:
        group_name = (v.attribute_type or "Diğer").strip()
        if group_name not in variant_groups:
            variant_groups[group_name] = {
                "name": group_name,
                "type": "button",
                "options": [],
                "_seen": set(),
            }

        if v.attribute_value and v.attribute_value not in variant_groups[group_name]["_seen"]:
            variant_groups[group_name]["_seen"].add(v.attribute_value)

            # Availability
            if not track_inventory:
                is_available = True
            elif (v.variant_stock or 0) > 0:
                is_available = True
            elif (listing_stock or 0) > 0:
                is_available = True
            else:
                is_available = False

            variant_price = v.variant_price if v.variant_price and v.variant_price > 0 else base_price

            option = {
                "label": v.attribute_value,
                "value": v.attribute_value,
                "available": is_available,
                "image": v.variant_image if v.variant_image else None,
                "price": variant_price,
                "priceAddon": v.variant_price if v.variant_price and v.variant_price > 0 else 0,
                "stockQty": v.variant_stock or 0,
                "variantId": f"{listing_name}-{v.attribute_type}-{v.attribute_value}",
            }
            variant_groups[group_name]["options"].append(option)

    result = []
    for group in variant_groups.values():
        del group["_seen"]
        if any(opt.get("image") for opt in group["options"]):
            group["type"] = "image"
        result.append(group)

    return result


def _get_category_breadcrumb(category_name):
    """Build category breadcrumb path."""
    if not category_name:
        return []

    breadcrumb = []
    current = category_name
    max_depth = 10  # prevent infinite loops

    while current and max_depth > 0:
        cat = frappe.db.get_value(
            "Product Category",
            current,
            ["category_name", "parent_product_category"],
            as_dict=True,
        )
        if cat:
            breadcrumb.insert(0, cat.category_name)
            current = cat.parent_product_category
        else:
            break
        max_depth -= 1

    return breadcrumb


def _get_country_code(country_name):
    """Get 2-letter country code from country name."""
    if not country_name:
        return ""

    country_map = {
        "Turkey": "TR",
        "China": "CN",
        "United States": "US",
        "Germany": "DE",
        "United Kingdom": "GB",
        "Japan": "JP",
        "South Korea": "KR",
        "India": "IN",
        "Italy": "IT",
        "France": "FR",
        "Spain": "ES",
        "Brazil": "BR",
        "Canada": "CA",
        "Australia": "AU",
        "Russia": "RU",
        "Netherlands": "NL",
        "Belgium": "BE",
        "Poland": "PL",
        "Thailand": "TH",
        "Vietnam": "VN",
        "Indonesia": "ID",
        "Malaysia": "MY",
        "Taiwan": "TW",
        "Hong Kong": "HK",
        "Singapore": "SG",
        "Pakistan": "PK",
        "Bangladesh": "BD",
        "Mexico": "MX",
        "Egypt": "EG",
        "Saudi Arabia": "SA",
        "United Arab Emirates": "AE",
    }

    return country_map.get(country_name, country_name[:2].upper() if country_name else "")


def _format_price(price, currency="USD"):
    """Format price for display."""
    if not price:
        return ""

    symbols = {"USD": "$", "EUR": "€", "TRY": "₺", "GBP": "£", "CNY": "¥", "JPY": "¥"}
    symbol = symbols.get(currency, currency + " ")

    return f"{symbol}{price:.2f}"


def _truncate_words(text, max_words=5):
    """Truncate text to max_words words."""
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."

def _format_number(num):
    """Format number for display (e.g., 19070 -> 19.070)."""
    if not num:
        return "0"
    if num >= 1000:
        return f"{num:,.0f}".replace(",", ".")
    return str(num)


def _get_price_range(listing):
    """Get price range string from listing pricing tiers."""
    if listing.b2b_enabled and listing.pricing_tiers:
        prices = [t.price for t in listing.pricing_tiers if t.price]
        if prices:
            min_p = min(prices)
            max_p = max(prices)
            if min_p != max_p:
                return f"${min_p:.2f}-${max_p:.2f}"
            return f"${min_p:.2f}"

    return _format_price(listing.selling_price, listing.currency)


# ─── Moderasyon Endpoint'leri ──────────────────────────

@frappe.whitelist()
def get_pending_listings(page=1, page_size=20):
    """Admin: Onay bekleyen listing'leri listele."""
    if "System Manager" not in frappe.get_roles() and frappe.session.user != "Administrator":
        frappe.throw(_("Yetki hatası"), frappe.PermissionError)

    page = int(page)
    page_size = int(page_size)
    total = frappe.db.count("Listing", {"status": "Pending"})
    listings = frappe.get_all(
        "Listing",
        filters={"status": "Pending"},
        fields=[
            "name", "title", "status", "seller_profile", "creation", "modified",
            "selling_price", "currency", "stock_qty", "listing_code",
            "primary_image", "description", "listing_type",
            "category", "category_name", "product_category",
        ],
        order_by="creation asc",
        start=(page - 1) * page_size,
        page_length=page_size,
    )
    for l in listings:
        if l.get("seller_profile"):
            l["seller_name"] = frappe.db.get_value(
                "Admin Seller Profile", l["seller_profile"], "seller_name"
            ) or l["seller_profile"]
        else:
            l["seller_name"] = "-"
        # Kategori görünen adı: önce category_name (seller category), yoksa product_category
        l["display_category"] = l.get("category_name") or l.get("product_category") or l.get("category") or "—"
    return {"success": True, "listings": listings, "total": total}


@frappe.whitelist()
def approve_listing(listing_name, action="approve", reject_reason=""):
    """Admin: listing'i onayla (Active) veya reddet (Rejected)."""
    if "System Manager" not in frappe.get_roles() and frappe.session.user != "Administrator":
        frappe.throw(_("Yetki hatası"), frappe.PermissionError)

    listing = frappe.get_doc("Listing", listing_name)
    if action == "approve":
        listing.status = "Active"
        listing.rejection_reason = ""
        listing.flags.ignore_validate = False
    elif action == "reject":
        listing.status = "Rejected"
        listing.rejection_reason = reject_reason or ""
    else:
        frappe.throw(_("Geçersiz işlem"))

    listing.flags.from_admin = True
    listing.save(ignore_permissions=True)
    return {"success": True, "status": listing.status}


@frappe.whitelist()
def get_seller_listings(page=1, page_size=20):
    """Satıcı: kendi listing'lerini listele (tüm durumlar)."""
    seller_profile = frappe.db.get_value(
        "Admin Seller Profile", {"owner": frappe.session.user}, "name"
    ) or frappe.db.get_value(
        "Admin Seller Profile", {"email": frappe.session.user}, "name"
    )
    if not seller_profile:
        return {"success": True, "listings": [], "total": 0}

    page = int(page)
    page_size = int(page_size)
    total = frappe.db.count("Listing", {"seller_profile": seller_profile})
    listings = frappe.get_all(
        "Listing",
        filters={"seller_profile": seller_profile},
        fields=["name", "title", "status", "selling_price", "currency",
                "stock_qty", "available_qty", "creation", "listing_code",
                "rejection_reason"],
        order_by="creation desc",
        start=(page - 1) * page_size,
        page_length=page_size,
    )
    return {"success": True, "listings": listings, "total": total}


@frappe.whitelist()
def update_listing_status(listing_name, status):
    """Satıcı: onaylanan listing'in durumunu değiştir."""
    allowed = {"Active", "Paused", "Out of Stock"}
    if status not in allowed:
        frappe.throw(_("Geçersiz durum"))

    listing = frappe.get_doc("Listing", listing_name)
    if listing.status in ("Pending", "Rejected", "Draft"):
        frappe.throw(_("Bu listing henüz onaylanmamış."))

    # Sahiplik kontrolü
    seller_profile = frappe.db.get_value(
        "Admin Seller Profile", {"owner": frappe.session.user}, "name"
    ) or frappe.db.get_value(
        "Admin Seller Profile", {"email": frappe.session.user}, "name"
    )
    if listing.seller_profile != seller_profile:
        frappe.throw(_("Bu listing size ait değil."), frappe.PermissionError)

    frappe.db.set_value("Listing", listing_name, "status", status)
    return {"success": True}


@frappe.whitelist()
def get_listing_meta():
    """Satıcı için Listing doctype meta verilerini döndür (field tanımları)."""
    from frappe.model.meta import get_meta
    meta = get_meta("Listing")
    # Sadece UI'da gösterilecek alanları filtrele
    skip_types = {"Section Break", "Tab Break", "Column Break", "HTML", "Button"}
    skip_fields = {"listing_code", "seller_profile", "supplier_display_name",
                   "status", "reserved_qty", "available_qty", "published_at",
                   "erpnext_item", "naming_series", "variants_html",
                   "view_count", "wishlist_count", "order_count",
                   "average_rating", "review_count"}
    fields = []
    for f in meta.fields:
        if f.fieldtype in skip_types:
            continue
        if f.fieldname in skip_fields:
            continue
        if f.read_only:
            continue
        fields.append({
            "fieldname": f.fieldname,
            "fieldtype": f.fieldtype,
            "label": f.label,
            "reqd": f.reqd,
            "options": f.options,
            "default": f.default,
            "depends_on": f.depends_on,
            "description": f.description,
        })
    return {"success": True, "fields": fields}
