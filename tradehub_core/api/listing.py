import datetime
import hashlib
import json

import frappe
from frappe import _

from tradehub_core.api._input import safe_float, safe_int
from tradehub_core.api._pagination import normalize_pagination
from tradehub_core.seo.i18n import (
	CONTENT_LANGS,
	format_discount_badge,
	normalize_lang,
	resolve_content_field,
	translate_platform_term,
)


def _cache_key(prefix: str, **kwargs) -> str:
	"""Generate a deterministic cache key from parameters."""
	raw = json.dumps(kwargs, sort_keys=True, default=str)
	h = hashlib.md5(raw.encode()).hexdigest()[:12]
	return f"{prefix}:{h}"


# Storefront-visible statuses. "Out of Stock" listings still appear on the
# storefront as browsable, but with a "stokta yok" badge and zeroed stock so
# that nothing can be added to cart. Flipping back to "Active" restores
# everything automatically (no data is mutated, only filtered/zeroed in the
# response).
STOREFRONT_VISIBLE_STATUSES = ("Active", "Out of Stock")
STOREFRONT_STATUS_FILTER = ["in", list(STOREFRONT_VISIBLE_STATUSES)]

# Listing silinirken otomatik temizlenecek saf analitik/cache doctype'ları
# (doctype, link_fieldname). Bunların iş değeri yok ve her görüntülemede/öneri
# hesabında otomatik oluşur; temizlenmezse Frappe LinkExistsError ile silmeyi
# spurious biçimde bloklar (bir kez görüntülenen HER ürün silinemez, hep arşive
# düşerdi). İş kayıtları (Order Item, Review, Question, Quote, Cart, Favorite...)
# bu listede DEĞİL → onlar varsa ürün yine arşivlenir.
_LISTING_DELETE_ANALYTICS_LINKS = (
	("Listing View Counter", "listing"),
	("User Product View", "listing"),
	("Related Listing Cache", "source_listing"),
	("Related Listing Cache", "target_listing"),
)
# NOT: Cart Item ve Buyer Favorite Item bu listede DEĞİL — iş kaydı niteliğinde.
# Bunların varlığı LinkExistsError üretir → ürün soft-delete (Archived) olur.
# Soft-delete sonrası _cleanup_listing_references() bu kayıtları temizler.


CACHE_TTL = 30  # seconds — short TTL for listing queries

# How long the (listing × client IP) view dedup key lives in Redis.
# A repeat hit from the same IP within this window does NOT bump the
# view counter. Long enough to defeat refresh spam, short enough that
# legitimate return visitors are still counted on subsequent days.
VIEW_DEDUP_TTL = 3600  # 1 hour
# Ürün detayı response cache (per listing × lang). Payload isteyen kullanıcıya
# bağlı değil → paylaşımlı cache güvenli. Invalidation: Listing on_update.
_LISTING_DETAIL_CACHE_TTL = 300  # 5 dk
_LISTING_DETAIL_CACHE_PREFIX = "tradehub:listing_detail:"

# Product Category descendant resolver cache TTL (10 min). The tree rarely
# changes; invalidate_listing_cache drops this alongside listing caches.
CATEGORY_DESC_TTL = 600


def _get_category_descendants(parent_name):
	"""Resolve a Product Category to itself + every descendant in the NSM tree.

	Used so that a "Tümünü Gör" click on a parent category (e.g. "Ev Tekstili
	ve Dekorasyon") returns products assigned to any sub-category (Mobilya,
	Ev Dekorasyonu, …) — not just those directly pinned to the parent.

	Product Category has is_tree=1 with lft/rgt columns; one range query
	covers the whole subtree regardless of depth. Result cached for
	CATEGORY_DESC_TTL seconds.
	"""
	cache_key = f"pc_desc:{parent_name}"
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		return cached

	parent = frappe.db.get_value("Product Category", parent_name, ["lft", "rgt"], as_dict=True)

	if parent and parent.get("lft") is not None and parent.get("rgt") is not None:
		names = frappe.get_all(
			"Product Category",
			filters={
				"lft": [">=", parent.lft],
				"rgt": ["<=", parent.rgt],
				"is_active": 1,
			},
			pluck="name",
		)
		result = names or [parent_name]
	else:
		# NSM columns missing (e.g. tree not yet rebuilt) — safe fallback.
		result = [parent_name]

	frappe.cache.set_value(cache_key, result, expires_in_sec=CATEGORY_DESC_TTL)
	return result


# Statuses that are NOT visible on the storefront. Cache invalidation for
# these is a no-op because the cached lists never include them. Skipping
# the Redis delete_keys storm matters during bulk import (1000 ürün ×
# 8 pattern × Redis KEYS+DEL = significant load); single-edit flow gains
# a small win too.
_INVISIBLE_STATUSES = ("Pending", "Draft", "Rejected", "Archived")


def invalidate_listing_cache(doc=None, method=None):
	"""Drop every cached listing query so storefront reflects writes within
	a request, not after the 30s TTL expires.

	Wired from hooks.py for Listing on_update / after_insert / on_trash. Safe
	to call with no args (e.g. from a console). The deletion patterns cover
	every cache_key prefix used by this module.

	Storefront-invisible statuses (Pending/Draft/Rejected/Archived) skip
	invalidation entirely — their writes don't affect any cached query.
	"""
	# Skip storefront-invisible statuses: they're never in the cached lists,
	# so dropping the cache yields no observable change but burns Redis CPU.
	# Critical for bulk import (1000 Pending insert = 8000 wasted KEYS+DEL).
	if doc is not None and getattr(doc, "status", None) in _INVISIBLE_STATUSES:
		return

	try:
		# Patterns must match the prefixes passed to _cache_key in this file.
		for pattern in (
			"listings:*",
			"top_deals_grouped:*",  # legacy key, kept for safety
			"top_ranking_categories:*",
			"top_ranking_grouped:*",
			"search_suggestions:*",
			"filter_facets:*",
			"tailored:*",  # Tailored Selections (user + global)
			"pc_desc:*",  # Product Category descendant lookup
		):
			try:
				frappe.cache.delete_keys(pattern)
			except Exception:
				# delete_keys is best-effort; never block a doc save on cache
				frappe.log_error(f"Cache key deletion failed for pattern {pattern}", "listing")
				pass
		# Per-listing ürün detayı response cache'i hedefli düş (listing_detail:{name}:{lang}).
		if doc is not None and getattr(doc, "name", None):
			try:
				frappe.cache.delete_keys(f"{_LISTING_DETAIL_CACHE_PREFIX}{doc.name}:*")
			except Exception:
				frappe.log_error(f"Listing detail cache deletion failed for {doc.name}", "listing")
				pass
	except Exception:
		frappe.log_error("invalidate_listing_cache failed", "listing")
		pass


def invalidate_category_cache(doc=None, method=None):
	"""Product Category yazımında kategori-bağımlı storefront cache'lerini düşür.

	Wired: Product Category on_update / after_insert / on_trash (hooks.py).
	Kategori adı/ağaç değişimi; descendant lookup (pc_desc), facet sayımları
	(filter_facets), top-ranking ve listing kartlarındaki kategori adını
	etkilediği için invalidate_listing_cache (bu anahtarların hepsini temizler)
	yeniden kullanılır. Kategori yazımı nadir olduğundan geniş temizlik ucuz.

	Bulk kategori import'unda (binlerce upsert) per-doc invalidate ETME — importer
	`frappe.flags.in_category_import` set eder ve sonunda TEK sefer temizler
	(bkz. api/category.import_categories / _run_category_import). Aksi halde
	11.919 kategori × ~8 delete_keys = gereksiz Redis SCAN fırtınası."""
	if (
		getattr(frappe.flags, "in_category_import", False)
		or frappe.flags.in_import
		or frappe.flags.in_migrate
		or frappe.flags.in_install
	):
		return
	invalidate_listing_cache()


# ── Order → Listing.order_count pipeline ──
#
# Wired from hooks.py as a `before_save` hook on Order. We deliberately use
# before_save (NOT on_update / after_insert) because:
#
#   1. before_save runs BEFORE Frappe's db_update, so we can mutate
#      doc.metrics_credited in memory and let db_update persist it in the
#      same transaction. No second SQL write needed.
#
#   2. The Frappe Desk form does not include hidden read-only fields in the
#      submitted form payload. When `frappe.client.save({...})` constructs
#      the in-memory Order from that dict, doc.metrics_credited defaults to
#      0 even if the DB row currently holds 1. If we trusted the in-memory
#      value, every form save (e.g. adding a tracking number to a shipped
#      order) would re-credit the same items and inflate the count.
#
#      Our fix: read the *true* pre-save credit state from the DB inside
#      the hook (DB still holds the old value because db_update hasn't run
#      yet). This ignores the corrupted in-memory value entirely.
#
# Idempotency model:
#
#   not credited (DB) + status now SOLD     →  +qty per item,  set credited=1
#   credited     (DB) + status NOT SOLD     →  -qty per item,  set credited=0
#   no transition                            →  no quantity change, but we
#                                               still re-stamp doc.metrics_credited
#                                               so db_update doesn't reset it
#
# Item edit limitation: changing item quantities on an already-credited
# order does NOT re-tally listing.order_count. Cancel + recreate the order
# (or fix the count manually via SQL) if that's needed.

# Order statuses that count as a sale. Configurable here so a future
# product decision can flip the threshold without touching call sites.
SOLD_STATES = {"Kargoda", "Tamamlandı"}


def bump_listing_order_counts(doc, method=None):
	"""Order before_save hook: keep Listing.order_count in sync with the
	order's status transitions.

	See the module-level comment block above for the full design rationale.
	"""
	if not doc:
		return

	is_sold_now = (doc.status or "") in SOLD_STATES

	# Read the TRUE pre-save credit state from DB. We can't trust
	# `doc.metrics_credited` because Frappe's form save drops hidden
	# read-only fields and they default to 0 on doc construction.
	if doc.get("name"):
		db_value = frappe.db.get_value("Order", doc.name, "metrics_credited")
		was_credited = bool(db_value or 0)
	else:
		# Brand-new order, not yet in DB
		was_credited = False

	if is_sold_now != was_credited:
		sign = 1 if is_sold_now else -1
		for item in doc.get("items") or []:
			listing_name = item.get("listing") if isinstance(item, dict) else getattr(item, "listing", None)
			qty = item.get("quantity") if isinstance(item, dict) else getattr(item, "quantity", None)
			if not listing_name or not qty:
				continue
			try:
				qty_int = int(qty)
			except (TypeError, ValueError):
				continue
			delta = sign * qty_int
			# GREATEST clamps the counter at zero so a faulty decrement
			# never produces a negative best-seller score.
			frappe.db.sql(
				"UPDATE `tabListing` "
				"SET order_count = GREATEST(0, COALESCE(order_count, 0) + %s) "
				"WHERE name = %s",
				(delta, listing_name),
			)
		invalidate_listing_cache()

	# Always re-stamp the in-memory doc so db_update writes the correct
	# value back. Without this, form saves that omit the hidden field
	# would silently reset metrics_credited to 0 even when the order is
	# still in a SOLD state.
	doc.metrics_credited = 1 if is_sold_now else 0


# ── Seller Review → Admin Seller Profile aggregate (satıcı bazlı) ──
#
# Wired from hooks.py:
#   doc_events["Seller Review"]["after_insert"] → recompute_seller_rating_proxy
#   doc_events["Seller Review"]["on_update"]   → recompute_seller_rating_proxy
#   doc_events["Seller Review"]["on_trash"]    → recompute_seller_rating_proxy
#
# Faz 1 değişikliği: Listing.average_rating artık Listing Review'dan
# (ürün bazlı) hesaplanıyor (bkz. tradehub_core.api.review.recompute_listing_rating).
# Bu fonksiyon yalnızca Admin Seller Profile.rating + review_count alanlarını
# satıcı bazlı agregat olarak güncel tutar; Listing tablosuna yazmaz.


def recompute_seller_rating_proxy(doc, method=None):
	"""Seller Review değişiminde satıcı bazlı agregayı günceller.

	Yalnızca `status='Published'` review'lar ortalamaya katılır.
	Listing.average_rating Faz 1'den itibaren Listing Review'dan beslenir.
	"""
	if not doc:
		return
	seller = doc.get("seller") if isinstance(doc, dict) else getattr(doc, "seller", None)
	if not seller:
		return

	# Aggregate from Published reviews only.
	stats = frappe.db.sql(
		"""
		SELECT
			COALESCE(AVG(rating), 0) AS avg_rating,
			COUNT(*)                 AS cnt
		FROM `tabSeller Review`
		WHERE seller = %s AND status = 'Published'
		""",
		(seller,),
		as_dict=True,
	)

	if stats:
		avg = float(stats[0].avg_rating or 0)
		cnt = int(stats[0].cnt or 0)
	else:
		avg = 0.0
		cnt = 0

	# Round rating to one decimal place — matches what the storefront UI shows.
	avg = round(avg, 1)

	# Update the seller profile aggregate. (Listing'lere yazma KALDIRILDI.)
	if frappe.db.exists("Admin Seller Profile", seller):
		frappe.db.set_value(
			"Admin Seller Profile",
			seller,
			{"rating": avg, "review_count": cnt},
			update_modified=False,
		)

	invalidate_listing_cache()


@frappe.whitelist(allow_guest=True)
def get_listings(
	query=None,
	category=None,
	min_price=None,
	max_price=None,
	min_order=None,
	supplier=None,
	sort_by="modified",
	sort_order="DESC",
	page=1,
	page_size=20,
	is_featured=None,
	is_best_seller=None,
	is_new_arrival=None,
	is_deal=None,
	verified_supplier=None,
	min_rating=None,
	country=None,
	free_shipping=None,
	paid_samples=None,
	certifications=None,
	mgmt_certifications=None,
	product_certifications=None,
	brands=None,
	attrs=None,
	status=None,
	filter_currency=None,
	lang="tr",
):
	"""Get paginated list of active listings for the product listing page.

	Returns data matching the frontend ProductListingCard interface.

	Brand / attribute filters:
	  brands = "NIKE,ADIDAS"                    → brand IN (...)
	  attrs  = "RENK:RED,BLUE|BEDEN:M,L"        → listing has ALL of these attribute values
	"""
	page, page_size, _start = normalize_pagination(page, page_size)
	lang = normalize_lang(lang)

	# Y3 — Fiyat filtresi görüntüleme biriminde gelir; ürünler selling_price_base (TRY)
	# üzerinden filtrelenip sıralandığı için bound'ları baza çevir (kur yoksa filtre atlanır).
	# Çevrilmiş değerler hem cache key'ine hem filtreye girer (doğru dedup).
	min_price = _to_base_price_bound(min_price, filter_currency, _("Minimum fiyat"))
	max_price = _to_base_price_bound(max_price, filter_currency, _("Maksimum fiyat"))

	# ── Cache check ──
	ck = _cache_key(
		"listings",
		lng=lang,
		q=query,
		cat=category,
		minp=min_price,
		maxp=max_price,
		mo=min_order,
		sup=supplier,
		sb=sort_by,
		so=sort_order,
		p=page,
		ps=page_size,
		feat=is_featured,
		best=is_best_seller,
		new=is_new_arrival,
		deal=is_deal,
		vs=verified_supplier,
		mr=min_rating,
		co=country,
		fs=free_shipping,
		ps2=paid_samples,
		cert=certifications,
		mc=mgmt_certifications,
		pc=product_certifications,
		br=brands,
		at=attrs,
		st=status,
	)
	cached = frappe.cache.get_value(ck)
	if cached:
		return cached
	start = (page - 1) * page_size

	if status:
		roles = frappe.get_roles()
		if any(r in roles for r in ("System Manager", "Admin", "Seller")):
			allowed_status = {"Active", "Pending", "Rejected", "Paused", "Archived", "Draft", "Out of Stock"}
			if status not in allowed_status:
				frappe.throw(_("Geçersiz status: {0}").format(status))
			filters = {"status": status}
			if status == "Active":
				filters["is_visible"] = 1
		else:
			filters = {"storefront_visible": 1}
	else:
		filters = {"storefront_visible": 1}

	category_display_name = None
	if category:
		# category param is a url_slug from Product Category.
		# Try to resolve it as a platform category first (url_slug lookup),
		# then fall back to exact match on the seller category field.
		cat_row = frappe.db.get_value(
			"Product Category",
			{"url_slug": category},
			[
				"name",
				"category_name",
				"content_default_lang",
				*[f"category_name_{lng}" for lng in CONTENT_LANGS],
			],
			as_dict=True,
		)
		if cat_row:
			# Expand to the full subtree so "Tümünü Gör" on a parent category
			# surfaces products attached to any descendant sub-category.
			descendants = _get_category_descendants(cat_row.name)
			filters["product_category"] = descendants[0] if len(descendants) == 1 else ["in", descendants]
			# Mega menü client'ta 3 seviye — derin kategorilerde frontend slug'ı
			# ada çözemez; görünen adı yanıtla birlikte döndürüyoruz.
			category_display_name = resolve_content_field(
				cat_row, "category_name", lang, cat_row.get("content_default_lang")
			)
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

	# ── Deal filter (Top Deals page) ──
	# A listing is a deal iff discount_percentage > 0. The Listing controller's
	# validate_pricing keeps base_price/selling_price/discount_percentage in
	# sync, so dp > 0 is equivalent to base_price > selling_price at any
	# point in DB. One simple AND filter is enough — no OR group, no Python
	# post-filter, no race with text search.
	if is_deal:
		filters["discount_percentage"] = [">", 0]

	# ── Supplier-level filters (verified, country, certifications) ──
	# These require a sub-query on Admin Seller Profile to get matching seller_profile names.
	seller_profile_filters = {}
	if verified_supplier:
		# Eski is_verified field'ı silindi. Artık "Verified Seller" rolüne sahip
		# user'lara ait Admin Seller Profile'lar filtrelenir (KYB Verified satıcılar).
		verified_user_emails = frappe.db.sql_list(
			"""SELECT parent FROM `tabHas Role`
			   WHERE role = 'Verified Seller' AND parenttype = 'User'"""
		)
		if not verified_user_emails:
			# Hiç KYB Verified satıcı yoksa boş sonuç döndür
			return {
				"data": [],
				"total": 0,
				"page": page,
				"page_size": page_size,
				"total_pages": 1,
				"has_next": False,
				"has_prev": False,
			}
		seller_profile_filters["user"] = ["in", verified_user_emails]
	if country:
		# Multi-select: frontend "Turkey,China" gibi virgül-ayrılmış string gönderir.
		# Tek değer için de geriye uyumlu.
		country_list = [c.strip() for c in str(country).split(",") if c.strip()]
		if len(country_list) == 1:
			seller_profile_filters["country"] = country_list[0]
		elif len(country_list) > 1:
			seller_profile_filters["country"] = ["in", country_list]

	# Management certifications filter: via Seller Certification child table
	# v4: Yalnızca verification_status="Verified" cert'ler hesaba katılır.
	if certifications or mgmt_certifications:
		cert_str = mgmt_certifications or certifications
		cert_list = [c.strip() for c in cert_str.split(",") if c.strip()]
		if cert_list:
			sellers_with_certs = frappe.get_all(
				"Seller Certification",
				filters=[
					["certification_type", "in", cert_list],
					["verification_status", "=", "Verified"],
				],
				fields=["parent"],
				pluck="parent",
			)
			if sellers_with_certs:
				seller_profile_filters["name"] = ["in", list(set(sellers_with_certs))]
			else:
				return {
					"data": [],
					"total": 0,
					"page": page,
					"page_size": page_size,
					"total_pages": 1,
					"has_next": False,
					"has_prev": False,
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
				"data": [],
				"total": 0,
				"page": page,
				"page_size": page_size,
				"total_pages": 1,
				"has_next": False,
				"has_prev": False,
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
					"data": [],
					"total": 0,
					"page": page,
					"page_size": page_size,
					"total_pages": 1,
					"has_next": False,
					"has_prev": False,
				}

	# ── Rating filter ──
	if min_rating:
		filters["average_rating"] = [">=", safe_float(min_rating, label=_("Minimum puan"))]

	# ── Brand filter ──
	if supplier:
		filters["brand"] = ["like", f"%{supplier}%"]

	# ── Brand multi-select filter (from facet sidebar) ──
	if brands:
		brand_list = [b.strip() for b in brands.split(",") if b.strip()]
		if brand_list:
			existing_brand_filter = filters.get("brand")
			if isinstance(existing_brand_filter, list) and existing_brand_filter[0] == "like":
				# combine: must match supplier AND be in brands
				filters["brand"] = ["in", brand_list]
			else:
				filters["brand"] = ["in", brand_list]

	# ── Attribute filters (AND across attributes, OR within values) ──
	# attrs format: "RENK:RED,BLUE|BEDEN:M,L"
	if attrs:
		attr_groups = []
		for chunk in attrs.split("|"):
			if ":" not in chunk:
				continue
			code, vals_str = chunk.split(":", 1)
			code = code.strip()
			vals = [v.strip() for v in vals_str.split(",") if v.strip()]
			if code and vals:
				attr_groups.append((code, vals))

		if attr_groups:
			# For each attribute, find listings that have any of the values.
			# Final set = intersection across attributes.
			matching_listings: set | None = None
			for code, vals in attr_groups:
				rows = frappe.get_all(
					"Listing Attribute Value",
					filters=[
						["attribute", "=", code],
						["attribute_value", "in", vals],
						["parenttype", "=", "Listing"],
					],
					fields=["parent"],
					pluck="parent",
				)
				names = set(rows)
				if matching_listings is None:
					matching_listings = names
				else:
					matching_listings &= names

			if not matching_listings:
				return {
					"data": [],
					"total": 0,
					"page": page,
					"page_size": page_size,
					"total_pages": 1,
					"has_next": False,
					"has_prev": False,
				}

			# Merge with existing name filter if any
			existing_name_filter = filters.get("name")
			if isinstance(existing_name_filter, list) and existing_name_filter[0] == "in":
				filters["name"] = ["in", list(matching_listings & set(existing_name_filter[1]))]
				if not filters["name"][1]:
					return {
						"data": [],
						"total": 0,
						"page": page,
						"page_size": page_size,
						"total_pages": 1,
						"has_next": False,
						"has_prev": False,
					}
			else:
				filters["name"] = ["in", list(matching_listings)]

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
		price_filters.append(
			["Listing", "selling_price_base", ">=", safe_float(min_price, label=_("Minimum fiyat"))]
		)
	if max_price:
		price_filters.append(
			["Listing", "selling_price_base", "<=", safe_float(max_price, label=_("Maksimum fiyat"))]
		)
	# Min order filter — B2B "toptan eşik" mantığı (Alibaba modeli):
	# Kullanıcı "100 adet ve üstü MOQ'lu ürünler arıyorum" der → listing.min_order_qty >= user_input.
	# Filter chip "MSA ≥ 100" olarak gösterilir.
	# 0 ve negatif değerler filter'ı atlar (UX: "0 adet" anlamsız).
	if min_order:
		try:
			min_order_int = safe_int(min_order, label=_("Min. sipariş"))
		except Exception:
			frappe.log_error(f"min_order parse failed (value={min_order})", "listing")
			min_order_int = 0
		if min_order_int > 0:
			price_filters.append(["Listing", "min_order_qty", ">=", min_order_int])

	# ── Sorting ──
	use_relevance_sort = sort_by == "relevance" and bool(query)

	valid_sort_fields = {
		"modified": "modified",
		"price_asc": "selling_price_base",
		"price_desc": "selling_price_base",
		"newest": "creation",
		"rating": "average_rating",
		"orders": "order_count",
		"views": "view_count",
		"relevance": "modified",
		"discount": "discount_percentage",
	}

	# Top Deals: when is_deal is set and the caller didn't pick an explicit sort,
	# surface biggest discounts first.
	if is_deal and sort_by in ("modified", "relevance"):
		sort_by = "discount"

	actual_sort_field = valid_sort_fields.get(sort_by, "modified")
	if sort_by == "price_asc":
		sort_order = "ASC"
	elif sort_by == "price_desc":
		sort_order = "DESC"
	elif sort_by == "rating":
		sort_order = "DESC"
	elif sort_by == "orders":
		sort_order = "DESC"
	elif sort_by == "views":
		sort_order = "DESC"
	elif sort_by == "discount":
		sort_order = "DESC"

	fields = [
		"name",
		"slug",
		"listing_code",
		"title",
		"primary_image",
		"selling_price",
		"base_price",
		"currency",
		"discount_percentage",
		"min_order_qty",
		"stock_uom",
		"order_count",
		"average_rating",
		"review_count",
		"seller_profile",
		"supplier_display_name",
		"ships_from_country",
		"country_of_origin",
		"is_free_shipping",
		"is_featured",
		"is_best_seller",
		"is_new_arrival",
		"selling_point",
		"b2b_enabled",
		"has_variants",
		"category",
		"category_name",
		"brand",
		"brand_name",
		"modified",
		"creation",
		"status",
	]

	# i18n: kart için çevrilebilir alanların dil-sufix kolonları (resolve_content_field).
	fields += ["content_default_lang"]
	fields += [f"title_{lng}" for lng in CONTENT_LANGS]
	fields += [f"selling_point_{lng}" for lng in CONTENT_LANGS]

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
			searchable = " ".join(
				[
					(listing.get("title") or ""),
					(listing.get("short_description") or ""),
					(listing.get("brand") or ""),
				]
			).lower()
			return all(w.lower() in searchable for w in search_words)

		matched = [l for l in all_listings if matches_all_words(l)]
		total = len(matched)

		# Apply relevance sort if requested
		if use_relevance_sort:
			matched = _sort_by_relevance(matched, search_words)

		# Paginate
		paginated = matched[start : start + page_size]

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
			paginated = listings[start : start + page_size]
		else:
			paginated = listings
			# Accurate total count
			count_filters = all_filters[:]
			if or_filters:
				total = len(
					frappe.get_all(
						"Listing",
						filters=count_filters,
						or_filters=or_filters,
						fields=["name"],
					)
				)
			else:
				total = len(frappe.get_all("Listing", filters=count_filters, fields=["name"]))

	# ── Batch prefetch seller profiles, pricing tiers, and brands (N+1 optimization) ──
	seller_ids = list({l.seller_profile for l in paginated if l.get("seller_profile")})
	seller_cache = {}
	verified_seller_users = set()
	if seller_ids:
		for sp in frappe.get_all(
			"Admin Seller Profile",
			filters=[["name", "in", seller_ids]],
			fields=["name", "user", "founded_year", "country", "rating", "review_count"],
		):
			seller_cache[sp.name] = sp
		# Hangi satıcı user'ları "Verified Seller" rolüne sahip — tek SQL ile batch
		seller_users = [sp.user for sp in seller_cache.values() if sp.get("user")]
		if seller_users:
			verified_rows = frappe.db.sql(
				"""SELECT DISTINCT parent FROM `tabHas Role`
				   WHERE role='Verified Seller' AND parenttype='User' AND parent IN %(users)s""",
				{"users": tuple(seller_users)},
				as_dict=False,
			)
			verified_seller_users = {row[0] for row in verified_rows}

	brand_ids = list({l.brand for l in paginated if l.get("brand")})
	brand_cache = {}
	if brand_ids:
		for b in frappe.get_all(
			"Brand",
			filters=[["name", "in", brand_ids]],
			fields=["name", "brand_name", "slug", "logo"],
		):
			brand_cache[b.name] = b

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
		item = _format_listing_card(
			listing,
			seller_cache=seller_cache,
			tier_cache=tier_cache,
			brand_cache=brand_cache,
			verified_seller_users=verified_seller_users,
			lang=lang,
		)
		results.append(item)

	result = {
		"data": results,
		"total": total,
		"page": page,
		"page_size": page_size,
		"total_pages": max(1, -(-total // page_size)),  # ceil division
		"has_next": (start + page_size) < total,
		"has_prev": page > 1,
		"category_name": category_display_name,
	}

	# ── Cache write ──
	frappe.cache.set_value(ck, result, expires_in_sec=CACHE_TTL)

	return result


def _record_listing_view(listing_name):
	"""get_listing_detail'in yan etkileri: görüntülenme sayacı (IP-dedup) +
	per-user view log (Tailored Selections). Response cache'ten AYRI tutulur —
	cache hit'te de çalışsın diye full get_doc yerine hafif db.get_value ile
	view_count/category okur. Payload'u DEĞİŞTİRMEZ."""
	meta = (
		frappe.db.get_value("Listing", listing_name, ["view_count", "product_category"], as_dict=True) or {}
	)
	# Görüntülenme sayacı — per-(listing × client IP) dedup, VIEW_DEDUP_TTL içinde tek sayım.
	try:
		client_ip = (
			frappe.local.request_ip if getattr(frappe.local, "request", None) is not None else None
		) or "no-ip"
		dedup_key = f"view_seen:{listing_name}:{client_ip}"
		if not frappe.cache.get_value(dedup_key):
			frappe.db.set_value(
				"Listing",
				listing_name,
				"view_count",
				(meta.get("view_count") or 0) + 1,
				update_modified=False,
			)
			try:
				frappe.db.commit()
			except Exception:
				frappe.log_error("View count DB commit failed", "listing")
				pass
			frappe.cache.set_value(dedup_key, 1, expires_in_sec=VIEW_DEDUP_TTL)
	except Exception:
		# View counting must never break the detail page render.
		frappe.log_error("View counter update failed", "listing")
		pass

	# Per-user view log — feeds Tailored Selections recommendations.
	try:
		from tradehub_core.api.tailored import log_product_view

		log_product_view(listing_name, category=meta.get("product_category"))
	except Exception:
		frappe.log_error("log_product_view failed", "listing")
		pass


@frappe.whitelist(allow_guest=True)
def get_listing_detail(listing_id, lang="tr"):
	"""Get full listing detail for the product detail page.

	Returns data matching the frontend ProductDetail interface. `lang`: içerik dili
	(tr/en/ar/ru); başlık/açıklama o dile çözülür, eksikse content_default_lang'e düşer.
	"""
	lang = normalize_lang(lang)
	if not listing_id:
		frappe.throw(_("Listing ID is required"))

	# Try to find by name or listing_code
	listing_name = listing_id
	if not frappe.db.exists("Listing", listing_id):
		listings = frappe.get_all("Listing", filters={"listing_code": listing_id}, limit=1)
		if listings:
			listing_name = listings[0].name
		else:
			# Faz 4d: pretty URL slug ile dene
			listings = frappe.get_all("Listing", filters={"slug": listing_id}, limit=1)
			if listings:
				listing_name = listings[0].name
			else:
				frappe.throw(_("Listing not found"), frappe.DoesNotExistError)

	# Yan etkiler (görüntülenme sayacı + per-user log) response cache'ten ÖNCE —
	# cache hit'te de çalışsın diye. Payload'u değiştirmez.
	_record_listing_view(listing_name)

	# Response cache (per listing × lang) — payload isteyen kullanıcıya bağlı değil.
	cache_key = f"{_LISTING_DETAIL_CACHE_PREFIX}{listing_name}:{lang}"
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		return cached

	listing = frappe.get_doc("Listing", listing_name)

	# Üst-seviye sellerKybVerified flag — supplier objesi load fail etse bile
	# (legacy veri vb.) frontend'in KYB rozeti/disabled buton göstermesi için.
	# Verified Seller rolü yoksa False; satın alma kapısı kapalı.
	listing_kyb_verified = False
	try:
		if listing.seller_profile:
			sp_user = frappe.db.get_value("Admin Seller Profile", listing.seller_profile, "user")
			if sp_user:
				listing_kyb_verified = "Verified Seller" in frappe.get_roles(sp_user)
	except Exception:
		frappe.log_error(f"KYB verified check failed for seller_profile {listing.seller_profile}", "listing")
		listing_kyb_verified = False

	# Get supplier info from Admin Seller Profile
	supplier_data = None
	if listing.seller_profile:
		try:
			seller = frappe.get_doc("Admin Seller Profile", listing.seller_profile)
		except Exception as _e:
			frappe.log_error(
				title="get_listing_detail seller load",
				message=f"Failed to load seller {listing.seller_profile}: {_e}",
			)
			seller = None
		if seller:
			try:
				years_in_business = 0
				if seller.founded_year:
					try:
						years_in_business = datetime.datetime.now().year - int(seller.founded_year)
					except (ValueError, TypeError):
						years_in_business = 0
				# KYB doğrulanmış satıcı flag'i — sepete ekleme/sipariş kapısı + storefront
				# rozeti buna bağlı. Eski is_verified ve verification_type field'ları silindi;
				# tek doğruluk kaynağı User.role.Verified Seller.
				seller_kyb_verified = bool(seller.user and "Verified Seller" in frappe.get_roles(seller.user))
				# Defansif split — main_markets ve certifications tablo veya string olabilir
				main_markets_raw = seller.main_markets
				if isinstance(main_markets_raw, str):
					main_products = [p.strip() for p in main_markets_raw.split(",") if p.strip()]
				else:
					main_products = []

				# v4: Storefront yalnız verification_status='Verified' cert'leri
				# döndürür. Pending/Rejected gizli; süresi dolanlar da gizli.
				cert_rows = frappe.db.sql(
					"""
					SELECT sc.certification_type
					FROM `tabSeller Certification` sc
					WHERE sc.parent = %(profile)s
						AND sc.parenttype = 'Admin Seller Profile'
						AND IFNULL(sc.verification_status, 'Pending') = 'Verified'
						AND (sc.expiry_date IS NULL OR sc.expiry_date >= CURDATE())
					ORDER BY sc.idx ASC
					""",
					{"profile": listing.seller_profile},
					as_dict=True,
				)
				certifications = [r.certification_type for r in cert_rows if r.certification_type]

				# Doğrulama rozetleri — batch helper ile N+1 yok.
				from tradehub_core.api.seller import _verifications_by_seller

				seller_verifs = _verifications_by_seller([listing.seller_profile]).get(
					listing.seller_profile, []
				)

				supplier_data = {
					"name": seller.seller_name or seller.company_name,
					"sellerCode": seller.seller_code,
					"companyName": seller.company_name,
					# verified == kybVerified — frontend geriye uyumluluk için her ikisi de döner
					"verified": seller_kyb_verified,
					"kybVerified": seller_kyb_verified,
					"yearsInBusiness": years_in_business,
					"country": seller.country,
					"city": seller.city,
					"logo": seller.logo,
					"responseTime": seller.response_time,
					"responseRate": seller.response_rate or 0,
					"onTimeDelivery": seller.on_time_delivery or 0,
					"mainProducts": main_products,
					"employees": seller.staff_count,
					"annualRevenue": seller.annual_revenue,
					"certifications": certifications,
					"rating": seller.rating or 0,
					"reviewCount": seller.review_count or 0,
					"verifications": seller_verifs,
				}
			except Exception as _e2:
				frappe.log_error(
					title="get_listing_detail supplier_data build",
					message=f"Failed to build supplier_data for {listing.seller_profile}: {_e2}",
				)

	# Build category breadcrumb (prefer platform category, fallback to seller category)
	category_path = _get_category_breadcrumb(listing.product_category or listing.category, lang)
	# `category` (isim listesi) eski clientlar için korunur; slug'lı hali categoryPath.
	category_breadcrumb = [c["name"] for c in category_path]
	category_ranks = _get_category_ranks(listing)

	# Get images — primary_image + listing_images child table
	images = [listing.primary_image] if listing.primary_image else []
	for img in listing.listing_images or []:
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
		image_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
		for f in attachments:
			url = f.get("file_url", "")
			if url and any(url.lower().endswith(ext) for ext in image_exts):
				images.append(url)

	# ── Campaign discount: applied to ALL prices at display time ──
	# Same model as the storefront card: discount_percentage > 0 means an
	# active campaign. selling_price (and every B2B tier price) is multiplied
	# by (1 - dp/100). The original prices are returned alongside as
	# "originalSellingPrice" / each tier's "originalPrice" so the frontend
	# can render strikethrough labels. When dp = 0, no transformation.
	discount_percentage = float(listing.discount_percentage or 0)
	discount_factor = (1 - discount_percentage / 100) if discount_percentage > 0 else 1.0
	has_campaign = discount_percentage > 0

	def _apply_discount(price):
		if not price:
			return price
		if not has_campaign:
			return price
		return round(float(price) * discount_factor, 2)

	# Get pricing tiers (apply campaign discount to each tier)
	price_tiers = []
	if listing.b2b_enabled and listing.pricing_tiers:
		for tier in listing.pricing_tiers:
			tier_entry = {
				"minQty": tier.min_qty,
				"maxQty": tier.max_qty or None,
				"price": _apply_discount(tier.price),
				"currency": listing.currency,
			}
			if has_campaign:
				tier_entry["originalPrice"] = float(tier.price) if tier.price else None
			price_tiers.append(tier_entry)

	if not price_tiers:
		fallback_tier = {
			"minQty": listing.min_order_qty or 1,
			"maxQty": None,
			"price": _apply_discount(listing.selling_price),
			"currency": listing.currency,
		}
		if has_campaign:
			fallback_tier["originalPrice"] = float(listing.selling_price) if listing.selling_price else None
		price_tiers = [fallback_tier]

	# i18n: kaynak/varsayılan dil (specs + variants + title/desc resolve için)
	_dl = listing.get("content_default_lang")

	# Get variants
	variants = _get_listing_variants(listing_name, lang, _dl)

	# When the seller has flipped status to "Out of Stock", we still expose the
	# listing on the storefront (so it remains browsable) but force every stock
	# field to 0 and mark every SKU as unavailable. The DB is NOT mutated —
	# flipping back to "Active" restores the original values automatically.
	is_out_of_stock = listing.status == "Out of Stock"
	if is_out_of_stock:
		for axis in variants:
			for opt in axis.get("options", []) or []:
				opt["available"] = False
				if "stockQty" in opt:
					opt["stockQty"] = 0
			for row in axis.get("skuMatrix", []) or []:
				row["stock"] = 0
				row["available"] = False

	# Get specifications — flat list (backward compat) + grouped by attribute set
	specs = []
	for attr in listing.attribute_values or []:
		specs.append(
			{
				"label": resolve_content_field(attr, "attribute_label", lang, _dl)
				or attr.attribute_label
				or attr.attribute,
				"value": resolve_content_field(attr, "attribute_value", lang, _dl) or attr.attribute_value,
				"group": attr.attribute_group,
			}
		)

	spec_groups = _build_spec_groups(listing, specs, lang)

	# Brand enrichment — name, slug, logo from Brand doctype
	brand_info = None
	if listing.brand:
		try:
			b = frappe.db.get_value(
				"Brand",
				listing.brand,
				["brand_name", "slug", "logo", "status"],
				as_dict=True,
			)
			if b:
				brand_info = {
					"code": listing.brand,
					"name": b.get("brand_name") or listing.brand,
					"slug": b.get("slug") or frappe.scrub(listing.brand).replace("_", "-"),
					"logo": b.get("logo") or "",
					"isApproved": b.get("status") == "Approved",
				}
		except Exception:
			frappe.log_error(f"Brand enrichment failed for brand {listing.brand}", "listing")
			pass

	# Build packaging specs from dedicated fields.
	# Etiketler platform-tanımlı sabit terimler → translate_platform_term ile çevrilir;
	# değerler ölçü/birim (cm/kg/adet) olduğu için dile bağımsız kalır.
	packaging_specs = []
	if listing.package_type:
		packaging_specs.append(
			{
				"label": translate_platform_term("Paket Tipi", lang),
				"value": translate_platform_term(listing.package_type, lang),
			}
		)
	if listing.package_length and listing.package_width and listing.package_height:
		packaging_specs.append(
			{
				"label": translate_platform_term("Paket Boyutu", lang),
				"value": f"{listing.package_length} x {listing.package_width} x {listing.package_height} cm",
			}
		)
	if listing.package_weight:
		packaging_specs.append(
			{
				"label": translate_platform_term("Paket Ağırlığı", lang),
				"value": f"{listing.package_weight} kg",
			}
		)
	if listing.units_per_package:
		packaging_specs.append(
			{
				"label": translate_platform_term("Koli Başına Adet", lang),
				"value": str(listing.units_per_package),
			}
		)
	if listing.carton_length and listing.carton_width and listing.carton_height:
		packaging_specs.append(
			{
				"label": translate_platform_term("Koli Boyutu", lang),
				"value": f"{listing.carton_length} x {listing.carton_width} x {listing.carton_height} cm",
			}
		)
	if listing.carton_gross_weight:
		packaging_specs.append(
			{
				"label": translate_platform_term("Koli Brüt Ağırlığı", lang),
				"value": f"{listing.carton_gross_weight} kg",
			}
		)

	# Get shipping methods
	shipping = []
	for sm in listing.shipping_methods or []:
		shipping.append(
			{
				"method": sm.shipping_method_name or sm.shipping_method,
				"estimatedDays": f"{sm.min_days}-{sm.max_days}" if sm.min_days and sm.max_days else "",
				"cost": sm.cost,
				"currency": listing.currency,
			}
		)

	# Get customization options
	customization_opts = []
	for opt in listing.customization_options or []:
		customization_opts.append(
			{
				"name": opt.option_name,
				"description": opt.description,
				"additionalCost": opt.additional_cost,
				"minQty": opt.min_qty,
			}
		)

	# Build price display (apply campaign discount when active)
	if has_campaign:
		price_range = _format_price(_apply_discount(listing.selling_price), listing.currency)
	else:
		price_range = _get_price_range(listing)

	# Faz 4d: Client-side <head> override için SEO payload
	# (admin'in girdiği meta_title, og_image, canonical, vb.)
	# Dev'de Vite client rendering backend inject'i ezdiği için frontend
	# bu payload'ı document.title + meta tag'leri güncelleyerek uygular.
	try:
		from tradehub_core.seo import meta_builder

		# SEO URL/meta katmanı şimdilik yalnızca tr/en destekliyor → ar/ru için tr canonical.
		seo_payload = meta_builder.build_for_listing(listing.as_dict(), lang=(lang if lang == "en" else "tr"))
	except Exception:
		frappe.log_error("SEO meta_builder.build_for_listing failed", "listing")
		seo_payload = {}

	# i18n: içerik alanlarını istenen dile çöz (eksikse content_default_lang'e fallback).
	_title = resolve_content_field(listing, "title", lang, _dl) or listing.title
	_description = resolve_content_field(listing, "description", lang, _dl) or listing.description
	_short_desc = resolve_content_field(listing, "short_description", lang, _dl) or listing.short_description
	_selling = resolve_content_field(listing, "selling_point", lang, _dl) or listing.selling_point

	result = {
		"id": listing.name,
		"listingCode": listing.listing_code,
		"slug": listing.slug or "",
		"seo": seo_payload,
		"title": _title,
		"category": category_breadcrumb,
		"categoryPath": category_path,
		"productCategoryId": listing.product_category or "",
		"images": images,
		"priceTiers": price_tiers,
		"moq": listing.min_order_qty or 1,
		"sellInMoqMultiples": bool(listing.sell_in_moq_multiples),
		"unit": translate_platform_term(listing.stock_uom, lang) if listing.stock_uom else "piece",
		"samplePrice": listing.sample_price,
		"currency": listing.currency,
		# When a campaign is active, sellingPrice is the campaign price.
		# The seller's untouched day-to-day price is exposed as
		# originalSellingPrice (numeric) and originalPrice (formatted)
		# so the storefront can render a strikethrough above the deal price.
		"sellingPrice": _apply_discount(listing.selling_price),
		"originalSellingPrice": float(listing.selling_price)
		if has_campaign and listing.selling_price
		else None,
		"originalPrice": _format_price(listing.selling_price, listing.currency) if has_campaign else None,
		"discount": format_discount_badge(int(discount_percentage), lang) if has_campaign else None,
		"basePrice": listing.base_price,
		"discountPercentage": listing.discount_percentage,
		"priceRange": price_range,
		"shipping": shipping,
		"leadTime": f"{listing.handling_days or 1} {translate_platform_term('iş günü', lang)}"
		if listing.handling_days
		else "",
		"leadTimeRanges": [
			{
				"quantityRange": f"{r.min_qty}-{r.max_qty}" if r.max_qty else f"{r.min_qty}+",
				"days": f"{r.lead_days} {translate_platform_term('gün', lang)}",
			}
			for r in (listing.lead_time_ranges or [])
		],
		"variants": variants,
		"specs": specs,
		"specGroups": spec_groups,
		"packagingSpecs": packaging_specs,
		"description": _description,
		"shortDescription": _short_desc,
		"rating": listing.average_rating or 0,
		"reviewCount": listing.review_count or 0,
		"orderCount": listing.order_count or 0,
		"categoryRanks": category_ranks,
		"viewCount": listing.view_count or 0,
		"supplier": supplier_data,
		"sellerKybVerified": listing_kyb_verified,
		"customizationOptions": customization_opts,
		"brand": listing.brand,
		"brandInfo": brand_info,
		"productType": listing.product_type,
		"productTypeName": listing.product_type_name,
		"productFamily": listing.product_family,
		"productFamilyName": listing.product_family_name,
		"attributeSet": listing.attribute_set,
		"attributeSetName": listing.attribute_set_name,
		"condition": listing.condition,
		"isFreeShipping": bool(listing.is_free_shipping),
		"shipsFromCountry": listing.ships_from_country,
		"shipsFromCity": listing.ships_from_city,
		"countryOfOrigin": listing.country_of_origin,
		"isFeatured": bool(listing.is_featured),
		"isBestSeller": bool(listing.is_best_seller),
		"isNewArrival": bool(listing.is_new_arrival),
		"sellingPoint": _selling,
		"hasVariants": bool(listing.has_variants),
		"stockQty": 0
		if is_out_of_stock
		else (listing.available_qty if listing.available_qty is not None else (listing.stock_qty or 0)),
		"inStock": False
		if is_out_of_stock
		else ((listing.available_qty if listing.available_qty is not None else (listing.stock_qty or 0)) > 0),
		"videoUrl": listing.video_url,
		"status": listing.status or "",
		"outOfStock": is_out_of_stock,
	}

	response = {"data": result}
	frappe.cache.set_value(cache_key, response, expires_in_sec=_LISTING_DETAIL_CACHE_TTL)
	return response


@frappe.whitelist(allow_guest=True)
def get_categories(parent=None, include_children=True, lang="tr"):
	"""Get product categories, optionally filtered by parent.

	Returns hierarchical category structure. `lang`: içerik dili (tr/en/ar/ru);
	kategori adları o dile çözülür, eksikse content_default_lang'e fallback eder.
	"""
	lang = normalize_lang(lang)
	_name_cols = [f"category_name_{lng}" for lng in CONTENT_LANGS]

	def _cat_name(cat):
		return (
			resolve_content_field(cat, "category_name", lang, cat.get("content_default_lang"))
			or cat.category_name
		)

	filters = {"is_active": 1}
	if parent:
		filters["parent_product_category"] = parent
	else:
		filters["parent_product_category"] = ["is", "not set"]

	categories = frappe.get_all(
		"Product Category",
		filters=filters,
		fields=[
			"name",
			"category_name",
			"content_default_lang",
			*_name_cols,
			"parent_product_category",
			"image",
			"icon_class",
			"url_slug",
		],
		order_by="category_name ASC",
	)

	results = []
	for cat in categories:
		item = {
			"id": cat.name,
			"name": _cat_name(cat),
			"slug": cat.url_slug,
			"image": cat.image,
			"icon": cat.icon_class,
			"parent": cat.parent_product_category,
			"children": [],
			"productCount": frappe.db.count(
				"Listing", {"product_category": cat.name, "storefront_visible": 1}
			),
		}

		if include_children:
			child_cats = frappe.get_all(
				"Product Category",
				filters={"parent_product_category": cat.name, "is_active": 1},
				fields=["name", "category_name", "content_default_lang", *_name_cols, "url_slug", "image"],
				order_by="category_name ASC",
			)
			for child in child_cats:
				item["children"].append(
					{
						"id": child.name,
						"name": _cat_name(child),
						"slug": child.url_slug,
						"image": child.image,
						"productCount": frappe.db.count(
							"Listing",
							{
								"product_category": child.name,
								"storefront_visible": 1,
							},
						),
					}
				)

		results.append(item)

	return {"data": results}


def _to_base_price_bound(value, filter_currency, label):
	"""Görüntüleme birimindeki fiyat bound'unu selling_price_base (TRY) birimine çevirir.

	get_listings + get_filter_facets ortak fiyat-filtresi çevrimi. Kur çifti yoksa None döner →
	çağıran filtreyi ATLAR: yanlış kurla (1:1) yanlış ürün listesi göstermektense fiyat filtresini
	hiç uygulamamak daha güvenli."""
	if not value:
		return None
	val = safe_float(value, label=label)
	if not filter_currency or filter_currency == "TRY":
		return val
	from tradehub_core.api.currency import _get_exchange_rate_strict

	fx = _get_exchange_rate_strict(filter_currency, "TRY")
	if fx is None:
		frappe.log_error(
			f"Kur bulunamadı: {filter_currency}->TRY; fiyat filtresi atlandı.",
			"listing.price_filter",
		)
		return None
	return val * fx


def _build_price_buckets(prices: list, num_buckets: int = 10) -> dict:
	"""Eşit genişlikli fiyat histogramı: min–max aralığını num_buckets eşit dilime böler.

	Fiyatlar selling_price_base (TRY) cinsindedir; frontend görüntüleme birimine çevirir.
	Son bucket üst sınırı kapalı [.., max]; diğerleri yarı-açık [lo, hi)."""
	vals = [float(p) for p in prices if p]
	if not vals:
		return {"min": 0, "max": 0, "buckets": []}
	lo, hi = min(vals), max(vals)
	if lo >= hi:
		return {
			"min": round(lo, 2),
			"max": round(lo, 2),
			"buckets": [{"min": round(lo, 2), "max": round(lo, 2), "count": len(vals)}],
		}
	width = (hi - lo) / num_buckets
	buckets = []
	for i in range(num_buckets):
		b_lo = lo + i * width
		b_hi = hi if i == num_buckets - 1 else lo + (i + 1) * width
		if i == num_buckets - 1:
			count = sum(1 for p in vals if b_lo <= p <= b_hi)
		else:
			count = sum(1 for p in vals if b_lo <= p < b_hi)
		buckets.append({"min": round(b_lo, 2), "max": round(b_hi, 2), "count": count})
	return {"min": round(lo, 2), "max": round(hi, 2), "buckets": buckets}


def _empty_facets() -> dict:
	"""Aktif filtreler kombinasyonu hiç sonuç vermediğinde sidebar'a dönen boş sayım payload'u.
	Frontend bu durumda sidebar count'larını sıfırlar; kullanıcı yine seçimini kaldırabilir."""
	return {
		"data": {
			"countries": [],
			"categories": [],
			"managementCertifications": [],
			"productCertifications": [],
			"brands": [],
			"attributes": [],
			"verifiedSupplierCount": 0,
			"priceRange": {"min": 0, "max": 0, "buckets": []},
		}
	}


@frappe.whitelist(allow_guest=True)
def get_filter_facets(
	query=None,
	category=None,
	min_price=None,
	max_price=None,
	min_order=None,
	verified_supplier=None,
	country=None,
	mgmt_certifications=None,
	product_certifications=None,
	brands=None,
	attrs=None,
	filter_currency=None,
):
	"""Return faceted counts for sidebar filters.

	Aktif filtreleri uygulayarak monotonic narrow sayım döndürür (Trendyol pattern):
	kullanıcı bir filtre seçince geriye kalan seçeneklerin (xx) sayıları azalır.
	Frontend filter değişimi sonrasında bu endpoint'i aktif filtrelerle tekrar çağırır.

	Returns:
	- countries: unique seller country values with listing counts
	- categories: product categories with listing counts
	- managementCertifications / productCertifications
	- brands
	- attributes (dinamik özellikler)
	- priceRange (selling_price_base histogramı)
	"""
	# Fiyat bound'ları görüntüleme biriminden selling_price_base (TRY) birimine çevrilir
	# (get_listings ile ortak helper; kur yoksa filtre atlanır).
	min_price = _to_base_price_bound(min_price, filter_currency, _("Minimum fiyat"))
	max_price = _to_base_price_bound(max_price, filter_currency, _("Maksimum fiyat"))

	# ── Cache check (tüm aktif filtreleri key'e dahil et — yoksa stale data) ──
	fck = _cache_key(
		"facets",
		q=query,
		cat=category,
		minp=min_price,
		maxp=max_price,
		mo=min_order,
		vs=verified_supplier,
		co=country,
		mc=mgmt_certifications,
		pc=product_certifications,
		br=brands,
		at=attrs,
	)
	cached = frappe.cache.get_value(fck)
	if cached:
		return cached

	base_filters = {"storefront_visible": 1}
	if category:
		platform_cat = frappe.db.get_value("Product Category", {"url_slug": category}, "name")
		if platform_cat:
			descendants = _get_category_descendants(platform_cat)
			base_filters["product_category"] = (
				descendants[0] if len(descendants) == 1 else ["in", descendants]
			)

	# ── Supplier-level filters → matching Admin Seller Profile names ──
	# get_listings'deki aynı mantık; burada da uygulayarak count'ları aktif filtreye göre daralt.
	seller_profile_filters: dict = {}
	if verified_supplier:
		verified_user_emails = frappe.db.sql_list(
			"""SELECT parent FROM `tabHas Role`
			   WHERE role = 'Verified Seller' AND parenttype = 'User'"""
		)
		if not verified_user_emails:
			return _empty_facets()
		seller_profile_filters["user"] = ["in", verified_user_emails]
	if country:
		country_list = [c.strip() for c in str(country).split(",") if c.strip()]
		if len(country_list) == 1:
			seller_profile_filters["country"] = country_list[0]
		elif len(country_list) > 1:
			seller_profile_filters["country"] = ["in", country_list]

	if mgmt_certifications:
		cert_list = [c.strip() for c in mgmt_certifications.split(",") if c.strip()]
		if cert_list:
			sellers_with_certs = frappe.get_all(
				"Seller Certification",
				filters=[
					["certification_type", "in", cert_list],
					["verification_status", "=", "Verified"],
				],
				fields=["parent"],
				pluck="parent",
			)
			if sellers_with_certs:
				seller_profile_filters["name"] = ["in", list(set(sellers_with_certs))]
			else:
				return _empty_facets()

	if seller_profile_filters:
		matching_sellers = frappe.get_all(
			"Admin Seller Profile",
			filters=seller_profile_filters,
			fields=["name"],
			pluck="name",
		)
		if matching_sellers:
			base_filters["seller_profile"] = ["in", matching_sellers]
		else:
			return _empty_facets()

	# ── Product certifications → matching Listing names ──
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
				base_filters["name"] = ["in", list(set(listings_with_pcerts))]
			else:
				return _empty_facets()

	# ── Brand multi-select ──
	if brands:
		brand_list = [b.strip() for b in brands.split(",") if b.strip()]
		if brand_list:
			base_filters["brand"] = ["in", brand_list]

	# ── Attribute filters (AND across attributes, OR within values) ──
	if attrs:
		attr_groups: list[tuple[str, list[str]]] = []
		for chunk in attrs.split("|"):
			if ":" not in chunk:
				continue
			code, vals_str = chunk.split(":", 1)
			code = code.strip()
			vals = [v.strip() for v in vals_str.split(",") if v.strip()]
			if code and vals:
				attr_groups.append((code, vals))

		if attr_groups:
			matching_listings: set | None = None
			for code, vals in attr_groups:
				rows = frappe.get_all(
					"Listing Attribute Value",
					filters=[
						["attribute", "=", code],
						["attribute_value", "in", vals],
						["parenttype", "=", "Listing"],
					],
					fields=["parent"],
					pluck="parent",
				)
				names = set(rows)
				matching_listings = names if matching_listings is None else (matching_listings & names)

			if not matching_listings:
				return _empty_facets()
			existing = base_filters.get("name")
			if isinstance(existing, list) and existing[0] == "in":
				narrowed = list(matching_listings & set(existing[1]))
				if not narrowed:
					return _empty_facets()
				base_filters["name"] = ["in", narrowed]
			else:
				base_filters["name"] = ["in", list(matching_listings)]

	# ── Price + min_order: list-of-lists ek filtreler (frappe.get_all formatı) ──
	extra_filters: list[list] = []
	if min_price:
		extra_filters.append(
			["Listing", "selling_price", ">=", safe_float(min_price, label=_("Minimum fiyat"))]
		)
	if max_price:
		extra_filters.append(
			["Listing", "selling_price", "<=", safe_float(max_price, label=_("Maksimum fiyat"))]
		)
	if min_order:
		try:
			min_order_int = safe_int(min_order, label=_("Min. sipariş"))
		except Exception:
			frappe.log_error(f"min_order parse failed (value={min_order})", "listing")
			min_order_int = 0
		if min_order_int > 0:
			extra_filters.append(["Listing", "min_order_qty", ">=", min_order_int])

	or_filters = None
	if query:
		or_filters = [
			["title", "like", f"%{query}%"],
			["short_description", "like", f"%{query}%"],
			["brand", "like", f"%{query}%"],
		]

	# Get all matching listing names first (include seller_profile for cert aggregation)
	base_filters_list = [
		[k, v[0], v[1]] if isinstance(v, list) else [k, "=", v] for k, v in base_filters.items()
	]
	all_filters = list(base_filters_list)
	all_filters.extend(extra_filters)
	# A-4b: yalnızca isim listesi (child-table facet'leri için). Kategori/marka/ülke/
	# cert sayımları artık limitsiz fetch + Python counting yerine group_by ile (yukarıda).
	listing_names = frappe.get_all(
		"Listing",
		filters=all_filters,
		or_filters=or_filters,
		pluck="name",
	)

	# Fiyat histogramı: yalnızca kategorik filtrelere göre (fiyat + MOQ hariç) — kullanıcı
	# slider'ı sürükleyip aralık seçince dağılım sabit kalsın (fiyat filtresi bar'ları kırpmasın).
	price_rows = frappe.get_all(
		"Listing",
		filters=base_filters_list,
		or_filters=or_filters,
		fields=["selling_price_base"],
	)
	price_range = _build_price_buckets([r.get("selling_price_base") for r in price_rows])

	# ── A-4b: facet sayımları DB GROUP BY ile (limitsiz fetch + Python counting yerine) ──
	# Aynı all_filters/or_filters kullanıldığı için SQL GROUP BY count, eski
	# "hepsini çek + Python'da say" ile construction-eşdeğerdir. Kategori/marka
	# doğrudan kolon; seller_profile bazlı boyutlar (ülke/verified/mgmt_cert) için
	# seller_profile başına listing sayısı map'i çıkarılır.
	def _facet_grouped_counts(field):
		rows = frappe.get_all(
			"Listing",
			filters=all_filters,
			or_filters=or_filters,
			fields=[field, "count(name) as cnt"],
			group_by=field,
		)
		return {r.get(field): r.get("cnt") for r in rows if r.get(field)}

	cat_counts_db = _facet_grouped_counts("product_category")
	brand_counts_db = _facet_grouped_counts("brand")
	profile_counts_db = _facet_grouped_counts("seller_profile")

	# Aggregate countries — UI başlığı "Tedarikçi Ülkesi" → satıcının kayıtlı ülkesi
	# (Admin Seller Profile.country) kullanılır. Listing.ships_from_country lojistik
	# alanı; "Ships From" gerekirse ileride ayrı filter olur (DHGate modeli).
	# Filter uygulaması da get_listings içinde aynı alana bağlı — facet ↔ filter tutarlı.
	country_counts: dict[str, int] = {}
	if profile_counts_db:
		profile_country_rows = frappe.get_all(
			"Admin Seller Profile",
			filters=[["name", "in", list(profile_counts_db.keys())]],
			fields=["name", "country"],
		)
		profile_to_country = {r.name: r.country for r in profile_country_rows if r.country}
		for profile, cnt in profile_counts_db.items():
			c = profile_to_country.get(profile)
			if c:
				country_counts[c] = country_counts.get(c, 0) + cnt

	# Verified Seller (KYB Verified) listing sayısı — filter sidebar facet için
	verified_supplier_count = 0
	if profile_counts_db:
		# Bu seller_profile'lerin user'larından "Verified Seller" rolüne sahip olanları bul
		seller_users_rows = frappe.get_all(
			"Admin Seller Profile",
			filters=[["name", "in", list(profile_counts_db.keys())]],
			fields=["name", "user"],
		)
		user_to_profile = {row.user: row.name for row in seller_users_rows if row.user}
		if user_to_profile:
			verified_users = frappe.db.sql_list(
				"""SELECT DISTINCT parent FROM `tabHas Role`
				   WHERE role = 'Verified Seller' AND parenttype = 'User' AND parent IN %(users)s""",
				{"users": tuple(user_to_profile.keys())},
			)
			verified_profiles = {user_to_profile[u] for u in verified_users if u in user_to_profile}
			# Bu profile'lere ait listing sayısı (profile başına DB count)
			verified_supplier_count = sum(
				cnt for profile, cnt in profile_counts_db.items() if profile in verified_profiles
			)

	# Resolve country names
	countries = []
	for country_link, count in sorted(country_counts.items(), key=lambda x: -x[1]):
		country_name = frappe.db.get_value("Country", country_link, "name") or country_link
		code = _get_country_code(country_name)
		countries.append(
			{
				"value": country_link,
				"label": country_name,
				"code": code,
				"count": count,
			}
		)

	# Aggregate categories (A-4b: DB GROUP BY)
	cat_counts = cat_counts_db

	categories = []
	for cat_name, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
		display_name = frappe.db.get_value("Product Category", cat_name, "category_name") or cat_name
		slug = frappe.db.get_value("Product Category", cat_name, "url_slug") or ""
		categories.append(
			{
				"id": cat_name,
				"name": display_name,
				"slug": slug,
				"count": count,
			}
		)

	# Aggregate management certifications from Seller Certification child table
	mgmt_cert_counts: dict[str, int] = {}
	product_cert_counts: dict[str, int] = {}
	# Aşağıdaki `if all_assigned_certs:` bloğu `if listing_names` DIŞINDA kullanılıyor;
	# boş sonuçta (ör. fiyat filtresi tüm ürünleri eledi) tanımlı kalması için default set.
	all_assigned_certs: set = set()

	if listing_names:
		# Seller profiles — group_by seller_profile map'inin anahtarları (A-4b).
		seller_profiles = list(profile_counts_db.keys())

		# Collect all assigned cert IDs from both child tables
		# v4: Sadece verification_status='Verified' mağaza cert'leri facet'ta sayılır.
		if seller_profiles:
			seller_certs = frappe.get_all(
				"Seller Certification",
				filters=[
					["parent", "in", seller_profiles],
					["parenttype", "=", "Admin Seller Profile"],
					["verification_status", "=", "Verified"],
				],
				fields=["certification_type", "parent"],
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
			# Yönetim sertifikaları SATICIYA ait — sayaç, o sertifikaya sahip
			# satıcıların ürün sayısını yansıtmalı (satıcı başına 1 değil).
			# Filtre uygulaması da (bkz. cert filtresi) aynı satıcının tüm
			# listing'lerini döndürdüğü için facet↔filtre tutarlı olsun diye
			# cert_type → o sertifikaya sahip satıcı kümesi kurup listing sayarız.
			mgmt_cert_sellers: dict[str, set] = {}
			for sc in seller_certs:
				info = cert_info_map.get(sc.certification_type)
				if info and info["category"] == "Management":
					mgmt_cert_sellers.setdefault(sc.certification_type, set()).add(sc.parent)
			for cert_type, seller_set in mgmt_cert_sellers.items():
				mgmt_cert_counts[cert_type] = sum(
					cnt for profile, cnt in profile_counts_db.items() if profile in seller_set
				)

		for pc in product_certs:
			info = cert_info_map.get(pc.certification_type)
			if info and info["category"] == "Product":
				product_cert_counts[pc.certification_type] = (
					product_cert_counts.get(pc.certification_type, 0) + 1
				)

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

	# ── Brand facet (A-4b: DB GROUP BY) ──
	brand_counts = brand_counts_db

	brands_list = []
	if brand_counts:
		brand_meta = {
			row.name: row
			for row in frappe.get_all(
				"Brand",
				filters=[
					["name", "in", list(brand_counts.keys())],
					["status", "=", "Approved"],
					["is_active", "=", 1],
				],
				fields=["name", "brand_name", "slug", "logo"],
			)
		}
		for code, count in sorted(brand_counts.items(), key=lambda x: -x[1]):
			meta = brand_meta.get(code)
			if not meta:
				continue  # skip brands that are not Approved+Active
			brands_list.append(
				{
					"code": code,
					"value": code,
					"label": meta.get("brand_name") or code,
					"slug": meta.get("slug") or frappe.scrub(code).replace("_", "-"),
					"logo": meta.get("logo") or "",
					"count": count,
				}
			)

	# ── Dynamic attribute facets (only is_filterable attributes) ──
	attributes_facet: dict[str, dict] = {}
	if listing_names:
		attr_rows = frappe.db.sql(
			"""
			SELECT lav.attribute AS code, lav.attribute_label,
				   lav.attribute_value
			FROM `tabListing Attribute Value` lav
			INNER JOIN `tabProduct Attribute` pa ON pa.name = lav.attribute
			WHERE lav.parent IN %(parents)s
			  AND lav.parenttype = 'Listing'
			  AND lav.attribute IS NOT NULL
			  AND lav.attribute != ''
			  AND pa.is_filterable = 1
			""",
			{"parents": tuple(listing_names) if len(listing_names) > 1 else (listing_names[0],)},
			as_dict=True,
		)
		for r in attr_rows:
			code = r.get("code")
			val = r.get("attribute_value")
			if not code or not val:
				continue
			bucket = attributes_facet.setdefault(
				code,
				{
					"code": code,
					"label": r.get("attribute_label") or code,
					"_options": {},
				},
			)
			bucket["_options"][val] = bucket["_options"].get(val, 0) + 1

		# Resolve option labels + colors from Product Attribute Value Option
		for code, bucket in attributes_facet.items():
			option_meta = {}
			try:
				rows = frappe.get_all(
					"Product Attribute Value Option",
					filters={"parent": code, "parenttype": "Product Attribute"},
					fields=["option_value", "option_label", "color_hex", "sort_order"],
					order_by="sort_order ASC",
				)
				for row in rows:
					option_meta[row.option_value] = {
						"label": row.option_label or row.option_value,
						"color": row.color_hex or "",
						"order": row.sort_order or 0,
					}
			except Exception:
				frappe.log_error(f"Option meta fetch failed for attribute {code}", "listing")
				pass

			options = []
			for val, count in bucket["_options"].items():
				meta = option_meta.get(val, {})
				options.append(
					{
						"value": val,
						"label": meta.get("label") or val,
						"color": meta.get("color") or "",
						"order": meta.get("order", 99999),
						"count": count,
					}
				)
			# Sort by attribute's own sort_order, falling back to count desc
			options.sort(key=lambda o: (o["order"], -o["count"]))
			bucket["options"] = options
			del bucket["_options"]

	attributes_list = list(attributes_facet.values())

	facet_result = {
		"data": {
			"countries": countries,
			"categories": categories,
			"managementCertifications": mgmt_certifications_list,
			"productCertifications": product_certifications_list,
			"brands": brands_list,
			"attributes": attributes_list,
			# Tedarikçi Türleri filter — Onaylanmış Satıcı (KYB Verified) listing sayısı
			"verifiedSupplierCount": verified_supplier_count,
			# Fiyat slider histogramı — selling_price_base (TRY) eşit-genişlikli 10 bucket
			"priceRange": price_range,
		}
	}

	# ── Cache write ──
	frappe.cache.set_value(fck, facet_result, expires_in_sec=CACHE_TTL)

	return facet_result


@frappe.whitelist(allow_guest=True)
def get_shipping_methods(listing_id=None, lang: str = "tr"):
	"""Get available shipping methods, optionally for a specific listing.

	`lang`: teslim süresi metnindeki ("iş günü") sabit terim istenen dile çevrilir;
	kargo firma adları (Yurtiçi Kargo vb.) özel isim olduğundan kaynak kalır.
	"""
	lang = normalize_lang(lang)
	business_days = translate_platform_term("iş günü", lang)

	if listing_id:
		# Get listing-specific shipping methods
		listing = frappe.get_doc("Listing", listing_id)
		shipping = []
		for sm in listing.shipping_methods or []:
			shipping.append(
				{
					"id": sm.shipping_method,
					"method": sm.shipping_method_name or sm.shipping_method,
					"cost": sm.cost,
					"minDays": sm.min_days,
					"maxDays": sm.max_days,
					"estimatedDays": f"{sm.min_days}-{sm.max_days} {business_days}"
					if sm.min_days and sm.max_days
					else "",
					"currency": listing.currency,
				}
			)
		return {"data": shipping}

	# Get all active shipping methods
	methods = frappe.get_all(
		"Shipping Method",
		filters={"is_active": 1},
		fields=[
			"name",
			"method_name",
			"shipping_type",
			"min_days",
			"max_days",
			"base_cost",
			"cost_per_kg",
			"currency",
			"description",
		],
		order_by="base_cost ASC",
	)

	results = []
	for m in methods:
		results.append(
			{
				"id": m.name,
				"method": m.method_name,
				"type": m.shipping_type,
				"minDays": m.min_days,
				"maxDays": m.max_days,
				"estimatedDays": f"{m.min_days}-{m.max_days} {business_days}"
				if m.min_days and m.max_days
				else "",
				"baseCost": m.base_cost,
				"costPerKg": m.cost_per_kg,
				"currency": m.currency,
				"description": m.description,
			}
		)

	return {"data": results}


@frappe.whitelist(allow_guest=True)
def get_featured_listings(limit=10):
	"""Get featured listings for homepage."""
	return get_listings(is_featured=1, page_size=limit)


# ── Top Ranking: best-sellers grouped by category ──

TOP_RANKING_TTL = 60  # seconds — cache TTL for top-ranking endpoints

# Map of valid sort keys → (DB field, default order). Used by both endpoints
# below so the frontend pills (hot-selling / most-popular / best-reviewed)
# resolve to a deterministic SQL order.
#
# - "hot-selling"   → SUM(order_count) — driven by the Order on_update hook
# - "most-popular"  → SUM(view_count)  — incremented in get_listing_detail()
# - "best-reviewed" → AVG(average_rating) — denormalized from seller proxy
_TOP_RANKING_SORTS = {
	"hot-selling": ("order_count", "DESC"),
	"most-popular": ("view_count", "DESC"),
	"best-reviewed": ("average_rating", "DESC"),
}


def _resolve_top_ranking_sort(sort: str | None) -> tuple[str, str]:
	return _TOP_RANKING_SORTS.get((sort or "").strip(), _TOP_RANKING_SORTS["hot-selling"])


@frappe.whitelist(allow_guest=True)
def get_top_ranking_categories(limit=6, sort="hot-selling"):
	"""Return the top N categories ranked by total sales (sum of order_count).

	Drives the homepage "En Çok Satanlar" section: 6 category cards (with
	image + TOP badge + name + "hot selling" subtitle). Designed for prod
	scale (1000+ categories, 1000+ listings) — uses one aggregate SQL query
	instead of fetching every listing in Python.

	Args:
		limit: how many categories to return (clamped to [1, 24]).
		sort: ranking metric. One of:
			- "hot-selling"  → SUM(order_count) DESC   (default)
			- "most-popular" → SUM(review_count) DESC
			- "best-reviewed" → AVG(average_rating) DESC

	Returns:
		{
		  "data": [
			{"id", "name", "slug", "image", "icon", "totalOrders",
			 "totalListings"}, ...
		  ]
		}

	Notes:
		- Cached 60s under a deterministic key.
		- Returned categories always have at least one Active+Visible listing.
		- The aggregate query joins Listing → Product Category, so we rely on
		  the existing index on `product_category` plus the new
		  `idx_listing_category_orders` composite added in
		  patches/add_top_ranking_indexes.py.
	"""
	try:
		limit_int = max(1, min(int(limit), 24))
	except (TypeError, ValueError):
		limit_int = 6

	sort_field, sort_order = _resolve_top_ranking_sort(sort)

	ck = _cache_key("top_ranking_categories", lim=limit_int, srt=sort_field)
	cached = frappe.cache.get_value(ck)
	if cached:
		return cached

	# Aggregate per category. Using frappe.db.sql here because Frappe ORM
	# doesn't expose SUM/AVG group-bys in get_all. Parameter binding via %s
	# placeholders only — no string interpolation of user input.
	if sort_field == "average_rating":
		agg_expr = "AVG(l.average_rating)"
	else:
		agg_expr = f"SUM(l.{sort_field})"

	rows = frappe.db.sql(
		f"""
		SELECT
			l.product_category AS cat_id,
			{agg_expr} AS metric,
			COUNT(l.name) AS listing_count
		FROM `tabListing` l
		WHERE l.storefront_visible = 1
		  AND l.product_category IS NOT NULL
		  AND l.product_category != ''
		GROUP BY l.product_category
		HAVING metric > 0
		ORDER BY metric {sort_order}
		LIMIT %s
		""",
		(limit_int,),
		as_dict=True,
	)

	if not rows:
		result = {"data": []}
		frappe.cache.set_value(ck, result, expires_in_sec=TOP_RANKING_TTL)
		return result

	cat_ids = [r["cat_id"] for r in rows]

	# Batch load category metadata.
	cat_meta_rows = frappe.get_all(
		"Product Category",
		filters=[["name", "in", cat_ids]],
		fields=["name", "category_name", "url_slug", "image", "icon_class"],
	)
	cat_meta = {c.name: c for c in cat_meta_rows}

	# Per-category fan-out: pull the #1 listing's primary_image for each
	# category so the homepage card shows the actual hot-selling product
	# rather than the generic Product Category image. Bounded — at most
	# `limit` (≤24) tiny queries, each served by the composite index
	# (product_category, sort_field) added in add_top_ranking_indexes.py.
	top_listing_image = {}
	for cat_id in cat_ids:
		top = frappe.get_all(
			"Listing",
			filters=[
				["storefront_visible", "=", 1],
				["product_category", "=", cat_id],
				[sort_field, ">", 0],
			],
			fields=["primary_image"],
			order_by=f"{sort_field} {sort_order}, modified DESC",
			limit=1,
		)
		if top and top[0].get("primary_image"):
			top_listing_image[cat_id] = top[0]["primary_image"]

	# Build the response preserving the SQL ordering (already best→worst).
	# Card image priority: top listing's primary_image > category's own image.
	data = []
	for r in rows:
		meta = cat_meta.get(r["cat_id"])
		if not meta:
			continue
		data.append(
			{
				"id": r["cat_id"],
				"name": meta.category_name or r["cat_id"],
				"slug": meta.url_slug or r["cat_id"],
				"image": top_listing_image.get(r["cat_id"]) or meta.image or "",
				"icon": meta.icon_class or "",
				"totalOrders": float(r["metric"] or 0),
				"totalListings": int(r["listing_count"] or 0),
			}
		)

	result = {"data": data}
	frappe.cache.set_value(ck, result, expires_in_sec=TOP_RANKING_TTL)
	return result


@frappe.whitelist(allow_guest=True)
def get_top_ranking_grouped(
	page=1,
	page_size=12,
	products_per_category=3,
	category=None,
	sort="hot-selling",
):
	"""Return paginated category groups, each holding a small ranked preview.

	Drives the Top Ranking page when the "Tümü" tab (or any specific tab) is
	active. Each card shows a category name + the top N best-sellers (default 3)
	inside that category, ranked #1/#2/#3.

	Args:
		page: 1-indexed page of categories.
		page_size: how many category cards per page (clamped to [1, 30]).
		products_per_category: ranked preview slots per card (clamped to [1, 10]).
		category: optional filter — restrict to a single tab. Accepts either a
			url_slug, a Product Category name, or "all" / None for everything.
			For 1000+ categories the "all" path streams pages, the per-category
			path returns just that category's groups.
		sort: ranking metric. Same options as get_top_ranking_categories.

	Returns:
		{
		  "data": [
			{"id", "name", "slug", "categoryId", "products": [...]},
			...
		  ],
		  "page", "page_size", "total_categories", "has_next"
		}
	"""
	try:
		page = max(1, int(page))
	except (TypeError, ValueError):
		page = 1
	try:
		page_size = max(1, min(int(page_size), 30))
	except (TypeError, ValueError):
		page_size = 12
	try:
		products_per_category = max(1, min(int(products_per_category), 10))
	except (TypeError, ValueError):
		products_per_category = 3

	sort_field, sort_order = _resolve_top_ranking_sort(sort)

	# Resolve "category" param. Accept either a url_slug or a tab id (which is
	# often the slug of a top-level category, e.g. consumer-electronics).
	resolved_parent_cat = None
	if category and category != "all":
		# Slug lookup first.
		resolved_parent_cat = frappe.db.get_value("Product Category", {"url_slug": category}, "name")
		if not resolved_parent_cat:
			# Fall back to direct name match.
			if frappe.db.exists("Product Category", category):
				resolved_parent_cat = category

	ck = _cache_key(
		"top_ranking_grouped",
		p=page,
		ps=page_size,
		ppc=products_per_category,
		cat=resolved_parent_cat or "all",
		srt=sort_field,
	)
	cached = frappe.cache.get_value(ck)
	if cached:
		return cached

	start = (page - 1) * page_size

	# Phase 1: discover candidate categories.
	# If a parent category was given, restrict to its descendants (via
	# Product Category tree) so a top-level "Consumer Electronics" tab returns
	# all of its leaf categories. Otherwise span the whole catalog.
	candidate_cat_ids: list[str] | None = None
	if resolved_parent_cat:
		descendants = frappe.get_all(
			"Product Category",
			filters=[
				["lft", ">=", frappe.db.get_value("Product Category", resolved_parent_cat, "lft") or 0],
				["rgt", "<=", frappe.db.get_value("Product Category", resolved_parent_cat, "rgt") or 0],
				["is_active", "=", 1],
			],
			fields=["name"],
			pluck="name",
		)
		# Always include the parent itself.
		candidate_cat_ids = list({*(descendants or []), resolved_parent_cat})
		if not candidate_cat_ids:
			result = {
				"data": [],
				"page": page,
				"page_size": page_size,
				"total_categories": 0,
				"has_next": False,
			}
			frappe.cache.set_value(ck, result, expires_in_sec=TOP_RANKING_TTL)
			return result

	# Phase 2: aggregate per-category metric over Active+Visible listings.
	# Use frappe.db.sql with parameter binding (no string interpolation).
	if sort_field == "average_rating":
		agg_expr = "AVG(l.average_rating)"
	else:
		agg_expr = f"SUM(l.{sort_field})"

	if candidate_cat_ids:
		# IN clause via dynamic placeholders — values come from internal cat IDs,
		# not user input, but we still bind via params for safety.
		placeholders = ", ".join(["%s"] * len(candidate_cat_ids))
		where_extra = f"AND l.product_category IN ({placeholders})"
		params = list(candidate_cat_ids)
	else:
		where_extra = ""
		params = []

	agg_rows = frappe.db.sql(
		f"""
		SELECT
			l.product_category AS cat_id,
			{agg_expr} AS metric
		FROM `tabListing` l
		WHERE l.storefront_visible = 1
		  AND l.product_category IS NOT NULL
		  AND l.product_category != ''
		  {where_extra}
		GROUP BY l.product_category
		HAVING metric > 0
		ORDER BY metric {sort_order}
		""",
		tuple(params),
		as_dict=True,
	)

	total_categories = len(agg_rows)
	page_rows = agg_rows[start : start + page_size]

	if not page_rows:
		result = {
			"data": [],
			"page": page,
			"page_size": page_size,
			"total_categories": total_categories,
			"has_next": False,
		}
		frappe.cache.set_value(ck, result, expires_in_sec=TOP_RANKING_TTL)
		return result

	page_cat_ids = [r["cat_id"] for r in page_rows]

	# Phase 3: batch-load category metadata (name + slug) for the page.
	cat_meta_rows = frappe.get_all(
		"Product Category",
		filters=[["name", "in", page_cat_ids]],
		fields=["name", "category_name", "url_slug"],
	)
	cat_meta = {c.name: c for c in cat_meta_rows}

	# Phase 4: per-category, fetch top N listings ordered by the metric.
	# Bounded fan-out: page_size (≤30) small queries each returning ≤10 rows,
	# all served by the (product_category, order_count) composite index.
	fields = [
		"name",
		"slug",
		"listing_code",
		"title",
		"primary_image",
		"selling_price",
		"base_price",
		"currency",
		"discount_percentage",
		"min_order_qty",
		"stock_uom",
		"order_count",
		"average_rating",
		"review_count",
		"seller_profile",
		"supplier_display_name",
		"ships_from_country",
		"country_of_origin",
		"is_free_shipping",
		"is_featured",
		"is_best_seller",
		"is_new_arrival",
		"selling_point",
		"b2b_enabled",
		"has_variants",
		"category",
		"category_name",
		"brand",
		"brand_name",
		"modified",
		"creation",
		"status",
	]

	# Per-category sort order_by — use the same metric, fall back to modified.
	per_cat_order_by = f"{sort_field} {sort_order}, modified DESC"

	groups_raw = []
	all_listings_for_prefetch = []
	for cat_id in page_cat_ids:
		listings = frappe.get_all(
			"Listing",
			filters=[
				["storefront_visible", "=", 1],
				["product_category", "=", cat_id],
				[sort_field, ">", 0],
			],
			fields=fields,
			order_by=per_cat_order_by,
			limit=products_per_category,
		)
		if not listings:
			continue
		all_listings_for_prefetch.extend(listings)
		groups_raw.append(
			{
				"cat_id": cat_id,
				"_listings": listings,
			}
		)

	# Batch prefetch seller profiles + tier pricing for the whole page (avoids N+1).
	seller_ids = list({l.seller_profile for l in all_listings_for_prefetch if l.get("seller_profile")})
	seller_cache = {}
	if seller_ids:
		for sp in frappe.get_all(
			"Admin Seller Profile",
			filters=[["name", "in", seller_ids]],
			fields=["name", "founded_year", "country", "rating", "review_count"],
		):
			seller_cache[sp.name] = sp

	b2b_listing_names = [l.name for l in all_listings_for_prefetch if l.get("b2b_enabled")]
	tier_cache: dict[str, list] = {}
	if b2b_listing_names:
		for tier in frappe.get_all(
			"Listing Bulk Pricing Tier",
			filters=[["parent", "in", b2b_listing_names], ["parenttype", "=", "Listing"]],
			fields=["parent", "min_qty", "max_qty", "price"],
			order_by="price ASC",
		):
			tier_cache.setdefault(tier.parent, []).append(tier)

	# Format the cards and assemble the final group list.
	final_groups = []
	for g in groups_raw:
		meta = cat_meta.get(g["cat_id"])
		cards = []
		for idx, listing in enumerate(g["_listings"]):
			card = _format_listing_card(listing, seller_cache=seller_cache, tier_cache=tier_cache)
			# Add a 1/2/3 rank for the frontend badge.
			card["rank"] = idx + 1
			cards.append(card)
		final_groups.append(
			{
				"id": g["cat_id"],
				"name": (meta.category_name if meta else g["cat_id"]) or g["cat_id"],
				"slug": (meta.url_slug if meta else g["cat_id"]) or g["cat_id"],
				"categoryId": g["cat_id"],
				"products": cards,
			}
		)

	result = {
		"data": final_groups,
		"page": page,
		"page_size": page_size,
		"total_categories": total_categories,
		"has_next": (start + page_size) < total_categories,
	}
	frappe.cache.set_value(ck, result, expires_in_sec=TOP_RANKING_TTL)
	return result


@frappe.whitelist(allow_guest=True)
def get_related_listings(listing_id, limit=8):
	"""Get related listings based on category."""
	if not listing_id:
		return {"data": []}

	listing = frappe.db.get_value("Listing", listing_id, ["category", "brand"], as_dict=True)
	if not listing:
		return {"data": []}

	filters = {
		"storefront_visible": 1,
		"name": ["!=", listing_id],
	}

	if listing.category:
		filters["category"] = listing.category

	listings = frappe.get_all(
		"Listing",
		filters=filters,
		fields=[
			"name",
			"slug",
			"listing_code",
			"title",
			"primary_image",
			"selling_price",
			"base_price",
			"currency",
			"discount_percentage",
			"min_order_qty",
			"stock_uom",
			"order_count",
			"average_rating",
			"review_count",
			"seller_profile",
			"supplier_display_name",
			"ships_from_country",
			"country_of_origin",
			"is_free_shipping",
			"selling_point",
			"b2b_enabled",
			"category_name",
			"brand",
			"status",
		],
		order_by="order_count DESC",
		limit=int(limit),
	)

	results = [_format_listing_card(l) for l in listings]
	return {"data": results}


@frappe.whitelist(allow_guest=True)
def get_related_listings_grouped(listing_id: str):
	"""Storefront API: return the 4-tab Related Products payload.

	Reads from the pre-computed `Related Listing Cache` populated by the
	nightly recommendations batch. Any relation_type with zero rows returns
	an empty list — the storefront hides that tab (and hides the entire
	section when all four are empty).
	"""
	empty = {"similar": [], "substitute": [], "complementary": [], "accessory": []}
	if not listing_id:
		return {"data": empty}

	# One query, grouped locally. Cache table is indexed on
	# (source_listing, relation_type, final_score DESC).
	rows = frappe.db.sql(
		"""
		SELECT target_listing, relation_type, final_score
		FROM `tabRelated Listing Cache`
		WHERE source_listing = %s
		ORDER BY relation_type, final_score DESC
		""",
		(listing_id,),
		as_dict=True,
	)
	if not rows:
		return {"data": empty}

	# Group target IDs by relation_type
	grouped_ids: dict[str, list[str]] = {
		"Similar": [],
		"Substitute": [],
		"Complementary": [],
		"Accessory": [],
	}
	for r in rows:
		rt = r.get("relation_type")
		if rt in grouped_ids:
			grouped_ids[rt].append(r["target_listing"])

	# Resolve target listing cards in a single batched fetch
	all_ids = {tid for ids in grouped_ids.values() for tid in ids}
	if not all_ids:
		return {"data": empty}

	listings = frappe.get_all(
		"Listing",
		filters={
			"name": ["in", list(all_ids)],
			"storefront_visible": 1,
		},
		fields=[
			"name",
			"slug",
			"listing_code",
			"title",
			"primary_image",
			"selling_price",
			"base_price",
			"currency",
			"discount_percentage",
			"min_order_qty",
			"stock_uom",
			"order_count",
			"average_rating",
			"review_count",
			"seller_profile",
			"supplier_display_name",
			"ships_from_country",
			"country_of_origin",
			"is_free_shipping",
			"selling_point",
			"b2b_enabled",
			"category_name",
			"brand",
			"status",
		],
	)
	card_by_id = {lst["name"]: _format_listing_card(lst) for lst in listings}

	out = {
		"similar": [card_by_id[tid] for tid in grouped_ids["Similar"] if tid in card_by_id],
		"substitute": [card_by_id[tid] for tid in grouped_ids["Substitute"] if tid in card_by_id],
		"complementary": [card_by_id[tid] for tid in grouped_ids["Complementary"] if tid in card_by_id],
		"accessory": [card_by_id[tid] for tid in grouped_ids["Accessory"] if tid in card_by_id],
	}
	return {"data": out}


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
		{
			"user": user,
			"query": query_trimmed,
			"creation": [">=", frappe.utils.add_to_date(None, minutes=-5)],
		},
		"name",
	)
	if recent_same:
		# Touch the existing record to move it to top
		frappe.db.set_value(
			"Search History",
			recent_same,
			{
				"category": category_trimmed,
				"modified": frappe.utils.now_datetime(),
				"creation": frappe.utils.now_datetime(),
			},
			update_modified=False,
		)
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
				"Search History",
				{"user": user},
				"creation",
				order_by="creation DESC",
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
				filters={
					"storefront_visible": 1,
					"title": ["like", f"%{q_text}%"],
				},
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
				cat_ids = [
					frappe.db.get_value("Product Category", {"url_slug": c}, "name") or c
					for c in user_categories[:5]
				]
				cat_ids = [c for c in cat_ids if c]
				if cat_ids:
					cat_listings = frappe.get_all(
						"Listing",
						filters=[
							["product_category", "in", cat_ids],
							["storefront_visible", "=", 1],
						],
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
			cart_cats = frappe.db.sql(
				"""
				SELECT DISTINCT l.product_category
				FROM `tabCart Item` ci
				JOIN `tabCart` c ON c.name = ci.parent
				JOIN `tabListing` l ON l.name = ci.listing
				WHERE c.user = %s AND l.product_category IS NOT NULL AND l.product_category != ''
				LIMIT 5
			""",
				(user,),
				as_dict=True,
			)
			for cc in cart_cats:
				cat_info = frappe.db.get_value(
					"Product Category",
					cc.product_category,
					["category_name", "url_slug"],
					as_dict=True,
				)
				if cat_info:
					personalized_cat_chips.append(
						{
							"text": cat_info.category_name,
							"type": "category",
							"slug": cat_info.url_slug or cc.product_category,
						}
					)
				if len(personalized_cat_chips) >= 3:
					break
		except Exception:
			frappe.log_error("Personalized category chips build failed", "listing")
			pass

	# ── Popular pool (guests + fill remaining for logged-in) ──
	pool_size = max(limit * 3, 20)
	listing_pool = frappe.get_all(
		"Listing",
		filters={"storefront_visible": 1},
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
	top_cats = frappe.db.sql(
		"""
		SELECT pc.category_name, pc.url_slug, pc.name, COUNT(*) as cnt
		FROM `tabListing` l
		JOIN `tabProduct Category` pc ON pc.name = l.product_category
		WHERE l.storefront_visible = 1 AND pc.is_active = 1
		GROUP BY pc.name
		HAVING cnt > 0
		ORDER BY cnt DESC
		LIMIT 10
	""",
		as_dict=True,
	)

	random.shuffle(top_cats)
	general_chips = [
		{"text": c.category_name, "type": "category", "slug": c.url_slug or c.name} for c in top_cats[:3]
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
		frappe.cache.set_value(
			cache_key,
			{
				"_result": result,
				"_cached_at": str(frappe.utils.now_datetime()),
			},
			expires_in_sec=900,
		)

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


def _format_listing_card(
	listing,
	seller_cache=None,
	tier_cache=None,
	brand_cache=None,
	verified_seller_users=None,
	lang="tr",
):
	"""Format a listing record into the ProductListingCard structure for frontend.

	Args:
		seller_cache: Pre-fetched seller profiles dict {name: record} to avoid N+1
		tier_cache: Pre-fetched pricing tiers dict {listing_name: [tiers]} to avoid N+1
		verified_seller_users: Set of user emails who have 'Verified Seller' role
			(KYB doğrulanmış satıcılar). Bu sette olmayan satıcının kartında
			seller_kyb_verified=False döner; storefront "Doğrulanmamış Satıcı"
			rozeti gösterir, "Sepete Ekle" disabled olur.
	"""
	# Get supplier info — use cache if available, else individual query (fallback)
	supplier_years = 0
	supplier_country = ""
	supplier_verified = False
	supplier_rating = 0
	supplier_review_count = 0
	seller_kyb_verified = False

	if listing.get("seller_profile"):
		try:
			sp = (seller_cache or {}).get(listing.get("seller_profile"))
			if sp is None and seller_cache is None:
				sp = frappe.db.get_value(
					"Admin Seller Profile",
					listing.get("seller_profile"),
					["user", "founded_year", "country", "rating", "review_count"],
					as_dict=True,
				)
			if sp:
				if sp.get("founded_year"):
					try:
						supplier_years = datetime.datetime.now().year - int(sp.founded_year)
					except (ValueError, TypeError):
						supplier_years = 0
				supplier_country = _get_country_code(sp.get("country")) if sp.get("country") else ""
				supplier_rating = sp.get("rating") or 0
				supplier_review_count = sp.get("review_count") or 0
				# KYB doğrulanmış satıcı flag'i — eski is_verified field'ı silindi.
				# verified == kybVerified, tek doğruluk kaynağı User.role.Verified Seller.
				sp_user = sp.get("user")
				if sp_user:
					if verified_seller_users is not None:
						seller_kyb_verified = sp_user in verified_seller_users
					else:
						seller_kyb_verified = "Verified Seller" in frappe.get_roles(sp_user)
				supplier_verified = seller_kyb_verified
		except Exception:
			frappe.log_error(f"Supplier info fetch failed for seller_profile {listing.get('seller_profile')}", "listing")
			pass

	# Get price range from pricing tiers — use cache if available
	selling_price = listing.get("selling_price") or 0
	discount_percentage = float(listing.get("discount_percentage") or 0)

	# Campaign price (effective): selling × (1 − dp/100). Computed at display
	# time only — DB never stores it. Setting dp back to 0 makes the storefront
	# automatically revert to selling_price without admin touching the price.
	if discount_percentage > 0 and selling_price > 0:
		effective_price = round(selling_price * (1 - discount_percentage / 100), 2)
	else:
		effective_price = None

	# The "displayed" price the customer sees and that the frontend formats:
	# campaign price when there's a campaign, otherwise the day-to-day selling.
	displayed_price = effective_price if effective_price is not None else selling_price

	min_price_val = displayed_price
	max_price_val = displayed_price
	price_display = _format_price(displayed_price, listing.get("currency"))

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
			cur = listing.get("currency")
			if min_price_val != max_price_val:
				price_display = f"{_format_price(min_price_val, cur)}-{_format_price(max_price_val, cur)}"
			else:
				price_display = _format_price(min_price_val, cur)

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

	listing_slug = listing.get("slug") or ""
	listing_href = (
		f"/urun/{listing_slug}" if listing_slug else f"/pages/product-detail.html?id={listing.name}"
	)

	# i18n: çevrilebilir alanları istenen dile çöz (eksikse content_default_lang'e fallback).
	_default_lang = listing.get("content_default_lang")
	_title = resolve_content_field(listing, "title", lang, _default_lang) or listing.title
	_selling = resolve_content_field(listing, "selling_point", lang, _default_lang) or listing.get(
		"selling_point", ""
	)

	return {
		"id": listing.name,
		"listingCode": listing.get("listing_code", ""),
		"slug": listing_slug,
		"name": _title,
		"href": listing_href,
		"price": price_display,
		# sellingPrice in the API response means "the price the customer sees
		# right now" — campaign price when there's a campaign, otherwise the
		# day-to-day price. The frontend currency-aware formatter uses this.
		"sellingPrice": displayed_price,
		"minPrice": min_price_val,
		"maxPrice": max_price_val,
		# Strikethrough fields. Only emitted when a campaign is active. The
		# strikethrough source is selling_price (the seller's regular price);
		# base_price (Listeleme Fiyatı) is the MSRP/upper bound and stays
		# invisible on the storefront per the Option B (B1) decision.
		"originalSellingPrice": float(selling_price) if effective_price is not None else None,
		"originalPrice": (
			_format_price(selling_price, listing.get("currency")) if effective_price is not None else None
		),
		"discount": (
			format_discount_badge(int(discount_percentage), lang) if discount_percentage > 0 else None
		),
		"moq": f"{listing.get('min_order_qty', 1)} {translate_platform_term(listing.get('stock_uom') or 'Adet', lang)}",
		"stats": f"{_format_number(listing.get('order_count', 0))} {translate_platform_term('adet satıldı', lang)}"
		if listing.get("order_count")
		else None,
		"imageSrc": primary_image,
		"images": all_images,
		"supplierName": (
			listing.get("supplier_display_name")
			or ((seller_cache or {}).get(listing.get("seller_profile"), {}) or {}).get("seller_name")
			or ((seller_cache or {}).get(listing.get("seller_profile"), {}) or {}).get("name")
			or ""
		),
		"verified": supplier_verified,
		"sellerKybVerified": seller_kyb_verified,
		# Kartta marka adını satıcı mağazasına linklemek için — /magaza/<name>
		# (Admin Seller Profile docname'i page_resolver.render_seller slug'ı olarak çözülür).
		"supplierSlug": listing.get("seller_profile") or "",
		"supplierYears": supplier_years,
		"supplierCountry": supplier_country,
		"rating": listing.get("average_rating", 0),
		"reviewCount": listing.get("review_count", 0),
		"supplierRating": supplier_rating,
		"supplierReviewCount": supplier_review_count,
		"sellingPoint": _selling,
		"promo": _selling,
		"isFreeShipping": bool(listing.get("is_free_shipping")),
		"isFeatured": bool(listing.get("is_featured")),
		"isBestSeller": bool(listing.get("is_best_seller")),
		"isNewArrival": bool(listing.get("is_new_arrival")),
		"discountPercentage": float(listing.get("discount_percentage") or 0),
		"category": listing.get("category_name", ""),
		"brand": listing.get("brand", ""),
		"brandName": _brand_name(listing, brand_cache),
		"brandSlug": _brand_slug(listing.get("brand"), brand_cache),
		"brandLogo": _brand_logo(listing.get("brand"), brand_cache),
		"baseCurrency": listing.get("currency", "USD"),
		# Out-of-stock badge: when the seller has flipped status to "Out of Stock"
		# the card still appears in storefront grids, but the frontend should
		# render a "stokta yok" badge and disable add-to-cart on detail page.
		"outOfStock": listing.get("status") == "Out of Stock",
		"status": listing.get("status", ""),
	}


def _brand_name(listing, brand_cache=None):
	code = listing.get("brand")
	if not code:
		return ""
	if brand_cache and code in brand_cache:
		return brand_cache[code].get("brand_name") or code
	return listing.get("brand_name") or code


def _brand_logo(brand_code, brand_cache=None):
	if not brand_code:
		return ""
	if brand_cache and brand_code in brand_cache:
		return brand_cache[brand_code].get("logo") or ""
	return frappe.db.get_value("Brand", brand_code, "logo") or ""


def _build_spec_groups(listing, specs, lang="tr"):
	"""Group specs by attribute_group, honoring Attribute Set group order/labels when available.

	`lang`: grup başlıkları platform-tanımlı sabit terimler (Genel/Teknik/Uyum...);
	`translate_platform_term` ile istenen dile çevrilir, bilinmeyen grup kaynak kalır.
	"""
	if not specs:
		return []

	# Map group_code -> (label, display_order) from Attribute Set
	group_meta: dict[str, dict] = {}
	set_code = getattr(listing, "attribute_set", None)
	if set_code:
		try:
			rows = frappe.get_all(
				"Attribute Set Group",
				filters={"parent": set_code, "parenttype": "Attribute Set"},
				fields=["group_code", "group_label", "display_order"],
				order_by="display_order ASC",
			)
			for i, r in enumerate(rows):
				group_meta[r.group_code or ""] = {
					"label": r.group_label or r.group_code or "Genel",
					"order": r.display_order if r.display_order is not None else i,
				}
		except Exception:
			frappe.log_error(f"Attribute Set group meta fetch failed for set {set_code}", "listing")
			pass

	# Bucket specs by group_code
	buckets: dict[str, list] = {}
	for s in specs:
		code = s.get("group") or ""
		buckets.setdefault(code, []).append({"label": s["label"], "value": s["value"]})

	# Build output: prefer Attribute Set ordering, append untracked groups at end
	seen = set()
	result = []
	for code, meta in sorted(group_meta.items(), key=lambda kv: kv[1]["order"]):
		if code in buckets:
			result.append(
				{
					"code": code,
					"label": translate_platform_term(meta["label"], lang),
					"items": buckets[code],
				}
			)
			seen.add(code)
	for code, items in buckets.items():
		if code in seen:
			continue
		result.append({"code": code, "label": translate_platform_term(code or "Genel", lang), "items": items})
	return result


_BRAND_SLUG_CACHE: dict[str, str] = {}


def _brand_slug(brand_code, brand_cache=None):
	if not brand_code:
		return ""
	if brand_cache and brand_code in brand_cache:
		slug = brand_cache[brand_code].get("slug")
		if slug:
			return slug
	if brand_code in _BRAND_SLUG_CACHE:
		return _BRAND_SLUG_CACHE[brand_code]
	slug = frappe.db.get_value("Brand", brand_code, "slug") or frappe.scrub(brand_code).replace("_", "-")
	_BRAND_SLUG_CACHE[brand_code] = slug
	return slug


def _get_listing_variants(listing_name, lang="tr", default_lang=None):
	"""Get variants grouped by attribute name for the product detail page.

	Source: Listing.variant_items child table (inline — the only supported path).
	`lang`/`default_lang`: varyant eksen adları + değerleri için ÇEVİRİ DISPLAY'i
	üretilir; ID/eşleşme alanları (value/name) KAYNAK dilde kalır — varyant ID'leri
	(`LST-..-Renk-Siyah`), snapshot ve sepet eşleşmesi kaynak değere bağlıdır.
	"""
	i18n_cols = [
		f"{f}_{lng}"
		for f in ("attribute_type", "attribute_value", "attribute_type_2", "attribute_value_2")
		for lng in CONTENT_LANGS
	]
	inline_variants = frappe.get_all(
		"Listing Variant Item",
		filters={"parent": listing_name, "parenttype": "Listing"},
		fields=[
			"attribute_type",
			"attribute_value",
			"attribute_type_2",
			"attribute_value_2",
			*i18n_cols,
			"axis_values_json",
			"is_default",
			"variant_image",
			"variant_gallery",
			"variant_video_url",
			"variant_price",
			"variant_stock",
			"variant_sku",
		],
		order_by="idx ASC",
	)

	if inline_variants:
		return _build_variants_from_inline(listing_name, inline_variants, lang, default_lang)

	return []


def _build_variant_xlat(rows, lang, default_lang):
	"""inline varyant satırlarından kaynak-metin → çeviri haritaları üret.

	(eksen adı haritası, değer haritası). ID/eşleşme kaynak metne bağlı olduğundan
	yalnızca DISPLAY (displayName/label) için kullanılır.
	"""
	names: dict[str, str] = {}
	values: dict[str, str] = {}
	for v in rows:
		for nf in ("attribute_type", "attribute_type_2"):
			src = (v.get(nf) or "").strip()
			if src and src not in names:
				names[src] = resolve_content_field(v, nf, lang, default_lang) or src
		for vf in ("attribute_value", "attribute_value_2"):
			src = (v.get(vf) or "").strip()
			if src and src not in values:
				values[src] = resolve_content_field(v, vf, lang, default_lang) or src
	return names, values


def _build_variants_from_inline(listing_name, inline_variants, lang="tr", default_lang=None):
	"""Build variant groups from Listing Variant Item child table rows.

	Supports N axes: axis1 (e.g. Color — with images) + axis2 (e.g. Size — text)
	+ additional axes from axis_values_json (e.g. Material, Length).
	Returns:
	  - For axis1: variant group with color thumbnails + images[]
	  - For axis2: variant group with text buttons
	  - For axis3+: additional variant groups with text buttons
	  - skuMatrix: flat list of all combinations with stock/price/availability
	The storefront uses skuMatrix to cross-disable (e.g. "Red-M out of stock").
	"""
	import json as _json

	listing_data = frappe.db.get_value(
		"Listing",
		listing_name,
		[
			"selling_price",
			"stock_qty",
			"track_inventory",
			"title",
			"primary_image",
			"video_url",
			"available_qty",
			"variant_axes_config",
		],
		as_dict=True,
	)
	base_price = listing_data.selling_price if listing_data else 0
	track_inventory = listing_data.track_inventory if listing_data else 0
	listing_title = listing_data.title if listing_data else ""

	# Parse variant_axes_config to determine which axes have images
	image_axes = set()
	axes_config_raw = listing_data.variant_axes_config if listing_data else ""
	if axes_config_raw:
		try:
			axes_config = _json.loads(axes_config_raw)
			for ac in axes_config:
				if ac.get("hasImage"):
					image_axes.add((ac.get("name") or "").strip())
		except Exception:
			frappe.log_error("variant_axes_config JSON parse failed", "listing")
			pass
	# Fallback: if no config, axis1 is image by default
	if not image_axes:
		image_axes.add(((inline_variants[0].attribute_type if inline_variants else "") or "Renk").strip())

	# Determine if 2-axis mode
	has_axis2 = any(
		(v.get("attribute_type_2") if hasattr(v, "get") else getattr(v, "attribute_type_2", ""))
		for v in inline_variants
	)

	# ── Build axis1 group (images/colors) ──
	axis1_name = ((inline_variants[0].attribute_type if inline_variants else "") or "Renk").strip()
	axis1_options = {}  # value → option dict
	axis1_order = []

	# ── Build axis2 group (sizes/text) if present ──
	axis2_name = ""
	axis2_values_set = set()
	axis2_order = []

	# ── Extra axes (3+) from axis_values_json ──
	extra_axes = {}  # axis_name → ordered list of unique values
	extra_axes_set = {}  # axis_name → set (for dedup)
	extra_axes_order = []  # ordered list of extra axis names (discovery order)

	# ── SKU matrix (all combinations) ──
	sku_matrix = []

	for v in inline_variants:
		val1 = (v.attribute_value or "").strip()
		val2 = (
			v.get("attribute_value_2") if hasattr(v, "get") else getattr(v, "attribute_value_2", "")
		) or ""
		val2 = val2.strip()

		if not val1:
			continue

		if not axis2_name and has_axis2:
			axis2_name = (
				(v.get("attribute_type_2") if hasattr(v, "get") else getattr(v, "attribute_type_2", "")) or ""
			).strip()

		# Parse extra axes from axis_values_json
		extra_vals = {}
		axis_json_raw = (
			v.get("axis_values_json") if hasattr(v, "get") else getattr(v, "axis_values_json", "")
		) or ""
		if axis_json_raw:
			try:
				axis_obj = _json.loads(axis_json_raw)
				if isinstance(axis_obj, dict):
					for ax_name, ax_val in axis_obj.items():
						ax_name = (ax_name or "").strip()
						ax_val = (ax_val or "").strip() if ax_val else ""
						# Skip axis1 and axis2 (already handled by dedicated fields)
						if ax_name == axis1_name or ax_name == axis2_name:
							continue
						if not ax_name or not ax_val:
							continue
						extra_vals[ax_name] = ax_val
						if ax_name not in extra_axes:
							extra_axes[ax_name] = []
							extra_axes_set[ax_name] = set()
							extra_axes_order.append(ax_name)
						if ax_val not in extra_axes_set[ax_name]:
							extra_axes_set[ax_name].add(ax_val)
							extra_axes[ax_name].append(ax_val)
			except Exception:
				frappe.log_error("axis_values_json parse failed for variant", "listing")
				pass

		# Parse images for axis1
		video_url = (
			v.get("variant_video_url") if hasattr(v, "get") else getattr(v, "variant_video_url", None)
		) or None
		images = [v.variant_image] if v.variant_image else []
		gallery_raw = (
			v.get("variant_gallery") if hasattr(v, "get") else getattr(v, "variant_gallery", None)
		) or ""
		if gallery_raw:
			try:
				extra = _json.loads(gallery_raw)
				if isinstance(extra, list):
					for u in extra:
						if u and u not in images:
							images.append(u)
			except Exception:
				frappe.log_error("variant_gallery JSON parse failed", "listing")
				pass

		is_default = bool(v.get("is_default") if hasattr(v, "get") else getattr(v, "is_default", 0))
		variant_price = v.variant_price if v.variant_price and v.variant_price > 0 else base_price
		stock = v.variant_stock or 0
		if not track_inventory:
			available = True
		elif stock > 0:
			available = True
		else:
			available = False

		# Axis1 option (only first occurrence per val1)
		if val1 not in axis1_options:
			composed_title = f"{val1} {listing_title}".strip() if listing_title else val1
			axis1_options[val1] = {
				"label": val1,
				"value": val1,
				"available": available,
				"isDefault": is_default,
				"image": images[0] if images else None,
				"images": images,
				"videoUrl": video_url,
				"title": composed_title,
				"price": variant_price,
				"priceAddon": v.variant_price if v.variant_price and v.variant_price > 0 else 0,
				"stockQty": stock,
				"variantId": f"{listing_name}-{axis1_name}-{val1}",
				"sku": v.variant_sku or "",
			}
			axis1_order.append(val1)
		else:
			# Aggregate: if any combination of this color is available, color is available
			if available:
				axis1_options[val1]["available"] = True
			# Aggregate stock
			axis1_options[val1]["stockQty"] = (axis1_options[val1]["stockQty"] or 0) + stock
			# Keep isDefault if any combo is default
			if is_default:
				axis1_options[val1]["isDefault"] = True

		# Axis2 values
		if val2 and val2 not in axis2_values_set:
			axis2_values_set.add(val2)
			axis2_order.append(val2)

		# SKU matrix row — includes extra axis values for N-axis cross-disable
		# Build a unique variantId that includes ALL axes (stable ordering via extra_axes_order)
		extra_suffix = ""
		if extra_vals:
			extra_suffix = "-" + "-".join(extra_vals[k] for k in extra_axes_order if k in extra_vals)
		variant_id = (
			f"{listing_name}-{val1}-{val2}{extra_suffix}"
			if val2
			else f"{listing_name}-{axis1_name}-{val1}{extra_suffix}"
		)

		sku_entry = {
			"axis1": val1,
			"axis2": val2,
			"stock": stock,
			"price": variant_price,
			"available": available,
			"sku": v.variant_sku or "",
			"variantId": variant_id,
		}
		if extra_vals:
			sku_entry["extraAxes"] = extra_vals
		sku_matrix.append(sku_entry)

	# Build result
	result = []

	# Axis1 group
	axis1_group = {
		"name": axis1_name,
		"type": "image"
		if (axis1_name in image_axes and any(o.get("image") for o in axis1_options.values()))
		else "button",
		"options": [axis1_options[k] for k in axis1_order],
	}
	# Sort default first
	axis1_group["options"].sort(key=lambda o: 0 if o.get("isDefault") else 1)
	result.append(axis1_group)

	# Axis2 group (if present)
	if axis2_name and axis2_order:
		axis2_options = []
		for val2 in axis2_order:
			# Available if ANY combination with this size has stock
			any_available = any(s["available"] for s in sku_matrix if s["axis2"] == val2)
			axis2_options.append(
				{
					"label": val2,
					"value": val2,
					"available": any_available,
					"isDefault": False,
				}
			)
		result.append(
			{
				"name": axis2_name,
				"type": "button",
				"options": axis2_options,
			}
		)

	# Extra axis groups (3+)
	for ax_name in extra_axes_order:
		ax_values = extra_axes[ax_name]
		ax_options = []
		for ax_val in ax_values:
			# Available if ANY SKU with this extra axis value has stock
			any_available = any(
				s["available"] for s in sku_matrix if s.get("extraAxes", {}).get(ax_name) == ax_val
			)
			ax_options.append(
				{
					"label": ax_val,
					"value": ax_val,
					"available": any_available,
					"isDefault": False,
				}
			)
		result.append(
			{
				"name": ax_name,
				"type": "image" if ax_name in image_axes else "button",
				"options": ax_options,
			}
		)

	# Attach skuMatrix to first group (storefront reads it for cross-disable)
	if sku_matrix:
		result[0]["skuMatrix"] = sku_matrix

	# i18n: çevrilmiş DISPLAY alanları EKLE — name/label/value/variantId + skuMatrix
	# tümüyle KAYNAK kalır (varyant ID, snapshot, sepet eşleşmesi, cross-disable kaynak
	# değere bağlı). Storefront `displayName`/`displayLabel`'ı YALNIZCA gösterimde kullanır.
	name_xlat, value_xlat = _build_variant_xlat(inline_variants, lang, default_lang)
	for group in result:
		group["displayName"] = name_xlat.get(group.get("name"), group.get("name"))
		for opt in group.get("options", []) or []:
			opt["displayLabel"] = value_xlat.get(opt.get("value"), opt.get("label") or opt.get("value"))

	return result


def _category_rank_counts(category_id, my_orders):
	"""(rank, total) — `category_id` alt-ağacında, `my_orders`'a göre.

	rank = alt-ağaçta benden daha çok satan görünür ürün sayısı + 1
	       (eşit satışlar aynı rank'i paylaşır — competition ranking).
	total = alt-ağaçtaki görünür ürün sayısı.
	Sonuç `cat_rank:{category_id}:{my_orders}` anahtarıyla 1 saat cache'lenir.
	"""
	rank_key = f"cat_rank:{category_id}:{my_orders}"
	cached = frappe.cache.get_value(rank_key)
	if cached is not None:
		return cached["rank"], cached["total"]

	descendants = _get_category_descendants(category_id)
	base = {
		"product_category": ["in", descendants],
		"storefront_visible": 1,
	}
	total = frappe.db.count("Listing", base)
	higher = frappe.db.count("Listing", {**base, "order_count": [">", my_orders]})
	rank = higher + 1

	frappe.cache.set_value(rank_key, {"rank": rank, "total": total}, expires_in_sec=3600)
	return rank, total


def _get_category_ranks(listing):
	"""Ürünün ait olduğu her ata kategoride satış sıralamasını (Best Sellers Rank)
	hesaplar. Metrik: tüm-zaman order_count.

	Döner: yapraktan sektöre sıralı —
	  [{category_id, category_name, slug, rank, total, level}, ...]  (level 0 = yaprak)
	product_category yoksa boş liste.
	"""
	leaf_cat = listing.product_category
	if not leaf_cat:
		return []

	my_orders = listing.order_count or 0

	# Ata zinciri: yaprak → kök (guest-safe; parent_product_category yürüyüşü).
	chain = []
	current = leaf_cat
	depth = 10  # cycle guard
	while current and depth > 0:
		cat = frappe.db.get_value(
			"Product Category",
			current,
			["name", "category_name", "url_slug", "parent_product_category"],
			as_dict=True,
		)
		if not cat:
			break
		chain.append(cat)
		current = cat.parent_product_category
		depth -= 1

	ranks = []
	for level, cat in enumerate(chain):
		rank, total = _category_rank_counts(cat.name, my_orders)
		ranks.append(
			{
				"category_id": cat.name,
				"category_name": cat.category_name,
				"slug": cat.url_slug or "",
				"rank": rank,
				"total": total,
				"level": level,
			}
		)
	return ranks


def _get_category_breadcrumb(category_name, lang="tr"):
	"""Build category breadcrumb path as [{"name": ..., "slug": ...}].

	`lang`: kategori adları çok-dilli suffix kolonlarından istenen dile çözülür.
	`slug`: Product Category.url_slug — frontend breadcrumb'ı kategori listeleme
	sayfasına (`/pages/products.html?cat=<slug>`) bağlayabilsin diye eklendi.
	"""
	if not category_name:
		return []

	lang = normalize_lang(lang)
	breadcrumb = []
	current = category_name
	max_depth = 10  # prevent infinite loops

	while current and max_depth > 0:
		cat = frappe.db.get_value(
			"Product Category",
			current,
			[
				"category_name",
				"url_slug",
				"content_default_lang",
				*[f"category_name_{lng}" for lng in CONTENT_LANGS],
				"parent_product_category",
			],
			as_dict=True,
		)
		if cat:
			breadcrumb.insert(
				0,
				{
					"name": resolve_content_field(cat, "category_name", lang, cat.get("content_default_lang"))
					or cat.category_name,
					"slug": cat.url_slug or "",
				},
			)
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
			cur = listing.currency
			if min_p != max_p:
				return f"{_format_price(min_p, cur)}-{_format_price(max_p, cur)}"
			return _format_price(min_p, cur)

	return _format_price(listing.selling_price, listing.currency)


# ─── Moderasyon Endpoint'leri ──────────────────────────


@frappe.whitelist()
def get_pending_listings(page=1, page_size=20, bulk_job=None):
	"""Admin: Onay bekleyen listing'leri listele.

	`bulk_job`: opsiyonel — yalnızca bu Bulk Import Job tarafından
	oluşturulan listing'leri döndürür (BIJ-XXX).
	"""
	if "System Manager" not in frappe.get_roles() and frappe.session.user != "Administrator":
		frappe.throw(_("Yetki hatası"), frappe.PermissionError)

	page = int(page)
	page_size = int(page_size)
	filters: dict = {"status": "Pending"}
	if bulk_job:
		filters["created_by_bulk_job"] = bulk_job
	total = frappe.db.count("Listing", filters)
	listings = frappe.get_all(
		"Listing",
		filters=filters,
		fields=[
			"name",
			"title",
			"status",
			"seller_profile",
			"creation",
			"modified",
			"selling_price",
			"currency",
			"stock_qty",
			"listing_code",
			"primary_image",
			"description",
			"listing_type",
			"category",
			"category_name",
			"product_category",
			"created_by_bulk_job",
		],
		order_by="creation asc",
		start=(page - 1) * page_size,
		page_length=page_size,
	)
	for l in listings:
		if l.get("seller_profile"):
			l["seller_name"] = (
				frappe.db.get_value("Admin Seller Profile", l["seller_profile"], "seller_name")
				or l["seller_profile"]
			)
		else:
			l["seller_name"] = "-"
		# Kategori görünen adı: önce category_name (seller category), yoksa product_category
		l["display_category"] = (
			l.get("category_name") or l.get("product_category") or l.get("category") or "—"
		)
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


# Enterprise tablo (DataTable) için sütun-başı filtre + çoklu sıralamada izin
# verilen alanlar. Kullanıcıdan gelen `sort` payload'ı bu kümeyle kısıtlanır —
# keyfi alan adı (SQL injection / izinsiz alan sızıntısı) engellenir.
SELLER_LISTING_SORT_FIELDS = {
	"title",
	"status",
	"selling_price",
	"stock_qty",
	"available_qty",
	"completeness_score",
	"product_category_name",
	"listing_code",
	"min_order_qty",
	"published_at",
	"modified",
	"creation",
}

# Satıcının hücre-içi (inline) düzenleyebileceği alanlar — admin/sistem alanları
# (status, listing_code, completeness vb.) bilinçli olarak HARİÇ.
SELLER_LISTING_EDITABLE_FIELDS = {
	"title",
	"selling_price",
	"stock_qty",
	"min_order_qty",
	"product_category",
}


def _seller_listing_sort_clause(sort) -> str:
	"""Frontend'den gelen çoklu-sıralama payload'ını güvenli `order_by`'a çevir.

	`sort`: JSON list — `[{"field": "selling_price", "desc": true}, ...]`.
	Geçersiz/izinsiz alanlar atlanır; hiçbiri kalmazsa varsayılan döner.
	"""
	if not sort:
		return "creation desc"
	if isinstance(sort, str):
		try:
			sort = json.loads(sort)
		except (ValueError, TypeError):
			return "creation desc"
	parts = []
	for entry in sort if isinstance(sort, list) else []:
		field = (entry or {}).get("field")
		if field in SELLER_LISTING_SORT_FIELDS:
			parts.append(f"{field} {'desc' if (entry or {}).get('desc') else 'asc'}")
	return ", ".join(parts) or "creation desc"


def _num(value):
	"""Opsiyonel sayısal query parametresini float'a çevir (boş/None → None)."""
	if value is None or value == "":
		return None
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def build_seller_listing_filters(
	seller_profile,
	*,
	status=None,
	bulk_job=None,
	source=None,
	product_category=None,
	title=None,
	listing_code=None,
	price_min=None,
	price_max=None,
	stock_min=None,
	stock_max=None,
	completeness_min=None,
	completeness_max=None,
	moq_min=None,
	moq_max=None,
	published_from=None,
	published_to=None,
	modified_from=None,
	modified_to=None,
	search=None,
):
	"""Satıcı liste + export ortak filtre üreticisi → (filters, or_filters).

	get_seller_listings ve export_seller_listings aynı filtre mantığını paylaşır;
	böylece export, ekrandaki aktif filtre/arama sonucunu birebir yansıtır.
	"""
	# Tenant izolasyonu list-of-lists filtre ile korunur (range için tek alanda
	# iki koşul gerektiğinden dict yerine liste kullanıyoruz).
	filters = [["seller_profile", "=", seller_profile]]

	if status and status != "all":
		statuses = [s.strip() for s in str(status).split(",") if s.strip()]
		if len(statuses) == 1:
			filters.append(["status", "=", statuses[0]])
		elif statuses:
			filters.append(["status", "in", statuses])

	if bulk_job:
		filters.append(["created_by_bulk_job", "=", bulk_job])
	elif source == "feed":
		filters.append(["created_by_bulk_job", "is", "set"])
	elif source == "manual":
		filters.append(["created_by_bulk_job", "is", "not set"])

	if product_category and str(product_category) != "all":
		cats = [c.strip() for c in str(product_category).split(",") if c.strip()]
		if len(cats) == 1:
			filters.append(["product_category", "=", cats[0]])
		elif cats:
			filters.append(["product_category", "in", cats])

	if title and str(title).strip():
		filters.append(["title", "like", f"%{str(title).strip()}%"])
	if listing_code and str(listing_code).strip():
		filters.append(["listing_code", "like", f"%{str(listing_code).strip()}%"])

	price_min, price_max = _num(price_min), _num(price_max)
	stock_min, stock_max = _num(stock_min), _num(stock_max)
	completeness_min, completeness_max = _num(completeness_min), _num(completeness_max)
	moq_min, moq_max = _num(moq_min), _num(moq_max)
	if price_min is not None:
		filters.append(["selling_price", ">=", price_min])
	if price_max is not None:
		filters.append(["selling_price", "<=", price_max])
	if stock_min is not None:
		filters.append(["stock_qty", ">=", stock_min])
	if stock_max is not None:
		filters.append(["stock_qty", "<=", stock_max])
	if completeness_min is not None:
		filters.append(["completeness_score", ">=", completeness_min])
	if completeness_max is not None:
		filters.append(["completeness_score", "<=", completeness_max])
	if moq_min is not None:
		filters.append(["min_order_qty", ">=", moq_min])
	if moq_max is not None:
		filters.append(["min_order_qty", "<=", moq_max])

	# Tarih aralıkları — "to" gün sonuna kadar kapsasın (yyyy-mm-dd → 23:59:59).
	if published_from:
		filters.append(["published_at", ">=", str(published_from)])
	if published_to:
		filters.append(["published_at", "<=", f"{published_to} 23:59:59"])
	if modified_from:
		filters.append(["modified", ">=", str(modified_from)])
	if modified_to:
		filters.append(["modified", "<=", f"{modified_to} 23:59:59"])

	or_filters = None
	if search and str(search).strip():
		term = f"%{str(search).strip()}%"
		or_filters = [
			["title", "like", term],
			["seller_sku", "like", term],
			["listing_code", "like", term],
		]

	return filters, or_filters


@frappe.whitelist()
def get_seller_listings(
	page=1,
	page_size=20,
	status=None,
	bulk_job=None,
	source=None,
	search=None,
	sort=None,
	title=None,
	listing_code=None,
	product_category=None,
	price_min=None,
	price_max=None,
	stock_min=None,
	stock_max=None,
	completeness_min=None,
	completeness_max=None,
	moq_min=None,
	moq_max=None,
	published_from=None,
	published_to=None,
	modified_from=None,
	modified_to=None,
):
	"""Satıcı: kendi listing'lerini listele (enterprise tablo destekli).

	`status`: opsiyonel filtre. "all"/boş → tüm durumlar. Tek değer veya
	virgülle ayrılmış çoklu değer (sütun multiselect) kabul eder. Geçerli
	değerler: Draft, Pending, Active, Paused, Out of Stock, Rejected.
	`bulk_job`: opsiyonel — yalnızca bu Bulk Import Job'tan eklenenler (BIJ-XXX).
	`source`: "feed" / "manual"; `bulk_job` verilmişse yok sayılır.
	`search`: title / seller_sku / listing_code üzerinde kısmi arama (OR, global).
	`title` / `listing_code`: ilgili sütunda kısmi arama (sütun-başı filtre).
	`category`: virgülle ayrılmış kategori (Link) değerleri — multiselect.
	`sort`: JSON çoklu-sıralama payload'ı; `_seller_listing_sort_clause` süzer.
	`price/stock/completeness/moq_min/max`: sayısal aralık filtreleri.
	`published_from/to`, `modified_from/to`: tarih aralığı filtreleri (yyyy-mm-dd).
	"""
	# FAZ 1.5 sub-user fix: sub-user'lar `tradehub_tenant` üzerinden Owner'ın
	# mağazasına bağlıdır — Co-Owner / Finance Staff / Operations vs. hepsi
	# aynı listing listesini görmeli.
	seller_profile = (
		frappe.db.get_value("User", frappe.session.user, "tradehub_tenant")
		or frappe.db.get_value("Admin Seller Profile", {"owner": frappe.session.user}, "name")
		or frappe.db.get_value("Admin Seller Profile", {"email": frappe.session.user}, "name")
	)
	if not seller_profile:
		return {"success": True, "listings": [], "total": 0}

	page, page_size, start = normalize_pagination(page, page_size)

	filters, or_filters = build_seller_listing_filters(
		seller_profile,
		status=status,
		bulk_job=bulk_job,
		source=source,
		product_category=product_category,
		title=title,
		listing_code=listing_code,
		price_min=price_min,
		price_max=price_max,
		stock_min=stock_min,
		stock_max=stock_max,
		completeness_min=completeness_min,
		completeness_max=completeness_max,
		moq_min=moq_min,
		moq_max=moq_max,
		published_from=published_from,
		published_to=published_to,
		modified_from=modified_from,
		modified_to=modified_to,
		search=search,
	)

	# or_filters varken frappe.db.count uygulanamadığından isim listesiyle say;
	# satıcının kendi ürünleriyle sınırlı (tenant filtresi) olduğundan bounded.
	if or_filters:
		total = len(
			frappe.get_all("Listing", filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0)
		)
	else:
		total = frappe.db.count("Listing", filters)

	listings = frappe.get_all(
		"Listing",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"title",
			"status",
			"selling_price",
			"currency",
			"stock_qty",
			"available_qty",
			"creation",
			"modified",
			"published_at",
			"listing_code",
			"seller_sku",
			"primary_image",
			"product_category",
			"product_category_name",
			"min_order_qty",
			"rejection_reason",
			"completeness_score",
			"created_by_bulk_job",
		],
		order_by=_seller_listing_sort_clause(sort),
		start=start,
		page_length=page_size,
	)

	# Mobil özet şerit: satıcının TÜM portföyünün durum dağılımı (aktif filtre/
	# aramadan bağımsız). get_all tenant filtresiyle sınırlı olduğundan güvenli.
	status_rows = frappe.get_all(
		"Listing",
		filters={"seller_profile": seller_profile},
		fields=["status", "count(name) as count"],
		group_by="status",
	)
	status_counts = {r.status: r.count for r in status_rows}

	return {"success": True, "listings": listings, "total": total, "status_counts": status_counts}


@frappe.whitelist()
def get_seller_listing_categories():
	"""Satıcının listing'lerinde fiilen KULLANDIĞI platform kategorilerini döndür.

	Kategori filtresi dropdown'ı bununla doldurulur — satıcı 15 kategoriye
	sahip olsa da yalnızca ürün yüklediği kategoriler görünür.
	"""
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	seller_profile = _get_seller_profile_for_user(frappe.session.user)
	if not seller_profile:
		return {"success": True, "categories": []}

	rows = frappe.get_all(
		"Listing",
		filters={"seller_profile": seller_profile, "product_category": ["is", "set"]},
		fields=["product_category", "product_category_name"],
		distinct=True,
	)
	seen = {}
	for r in rows:
		if r.product_category and r.product_category not in seen:
			seen[r.product_category] = r.product_category_name or r.product_category
	categories = [{"value": k, "label": v} for k, v in sorted(seen.items(), key=lambda kv: kv[1].lower())]
	return {"success": True, "categories": categories}


@frappe.whitelist()
def update_listing_field(listing_name: str, fieldname: str, value=None):
	"""Satıcı: kendi listing'inin tek bir alanını hücre-içi (inline) güncelle.

	Yalnızca `SELLER_LISTING_EDITABLE_FIELDS` izinli — admin/sistem alanları
	(status, listing_code, completeness vb.) reddedilir. Sahiplik + capability
	kontrolü update_listing_status ile aynı deseni izler. save() çağrısı
	doğrulama + completeness yeniden-hesaplama hook'larını tetikler.
	"""
	from tradehub_core.utils.seller_capabilities import require_seller_capability
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	require_seller_capability("listing.write")

	if fieldname not in SELLER_LISTING_EDITABLE_FIELDS:
		frappe.throw(_("Bu alan düzenlenemez."))

	listing = frappe.get_doc("Listing", listing_name)

	seller_profile = _get_seller_profile_for_user(frappe.session.user)
	if listing.seller_profile != seller_profile:
		frappe.throw(_("Bu listing size ait değil."), frappe.PermissionError)

	# Sayısal alanlar negatif olamaz; metin alanı boş olamaz.
	if fieldname in ("selling_price", "stock_qty", "min_order_qty"):
		num = _num(value)
		if num is None or num < 0:
			frappe.throw(_("Geçerli bir sayı girin (negatif olamaz)."))
		value = num
	elif fieldname == "title":
		value = (value or "").strip()
		if not value:
			frappe.throw(_("Ürün adı boş bırakılamaz."))
	elif fieldname == "product_category":
		if value and not frappe.db.exists("Product Category", value):
			frappe.throw(_("Geçersiz kategori."))

	setattr(listing, fieldname, value)
	listing.save()

	return {
		"success": True,
		"listing": {
			"name": listing.name,
			"title": listing.title,
			"selling_price": listing.selling_price,
			"stock_qty": listing.stock_qty,
			"available_qty": listing.available_qty,
			"min_order_qty": listing.min_order_qty,
			"product_category": listing.product_category,
			"product_category_name": listing.product_category_name,
			"completeness_score": listing.completeness_score,
		},
	}


@frappe.whitelist()
def update_listing_status(listing_name, status):
	"""Satıcı: onaylanan listing'in durumunu değiştir."""
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("listing.publish")

	allowed = {"Active", "Paused", "Out of Stock"}
	if status not in allowed:
		frappe.throw(_("Geçersiz durum"))

	listing = frappe.get_doc("Listing", listing_name)
	if listing.status in ("Pending", "Rejected", "Draft"):
		frappe.throw(_("Bu listing henüz onaylanmamış."))

	# Sahiplik kontrolü — sub-user'lar Owner'ın listing'ini görür (aynı tenant)
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	seller_profile = _get_seller_profile_for_user(frappe.session.user)
	if listing.seller_profile != seller_profile:
		frappe.throw(_("Bu listing size ait değil."), frappe.PermissionError)

	# storefront_visible flag'ini status ile birlikte güncelle: set_value validate'i
	# atladığı için controller _set_storefront_visible çalışmaz → yoksa flag drift eder
	# ve storefront sorguları (storefront_visible=1) bu ürünü yanlış filtreler.
	storefront_visible = 1 if (status in STOREFRONT_VISIBLE_STATUSES and listing.is_visible) else 0
	frappe.db.set_value(
		"Listing",
		listing_name,
		{"status": status, "storefront_visible": storefront_visible},
	)
	return {"success": True}


def _cleanup_listing_references(listing_name: str) -> None:
	"""Arşivlenen/silinen ürüne ait sepet, favori ve stok reservation kayıtlarını temizle.

	Soft-delete (Archived) sonrası çağrılır — kullanıcılar kopuk referans görmez,
	stok sayıları tutarlı kalır. Hard delete'te Frappe on_trash zaten cascade yapar.
	"""
	# 1) Sepetteki Cart Item'ları sil — kullanıcı sepete girdiğinde "ürün bulunamadı" önlenir
	frappe.db.delete("Cart Item", {"listing": listing_name})

	# 2) Favorilerden kaldır — favori listesinde kopuk referans önlenir
	frappe.db.delete("Buyer Favorite Item", {"listing": listing_name})

	# 3) Stok reservation'ı sıfırla — arşivlenen ürünün reserved_qty phantom stok tutmasını önle
	frappe.db.sql(
		"UPDATE `tabListing` SET reserved_qty = 0 WHERE name = %s AND reserved_qty > 0",
		(listing_name,),
	)


@frappe.whitelist()
def delete_listing(listing_name: str) -> dict:
	"""Satıcı: kendi ürününü sil (akıllı silme).

	Önce saf analitik/cache referansları (görüntülenme sayacı, öneri cache'i)
	temizlenir. Ardından ürüne GERÇEK iş kaydı (Order Item, Review, Question,
	Quote, Cart, Favorite...) bağlı DEĞİLSE kayıt kalıcı silinir. Bağlıysa Frappe
	`LinkExistsError` fırlatır → geçmiş korunmak için ürün 'Archived' statüsüne
	çekilir (soft-delete). Her iki durumda da ürün listeden ve storefront'tan kalkar.

	Sahiplik + capability kontrolü update_listing_status ile aynı deseni izler.
	"""
	from tradehub_core.utils.seller_capabilities import require_seller_capability
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	require_seller_capability("listing.delete")

	if not frappe.db.exists("Listing", listing_name):
		frappe.throw(_("Ürün bulunamadı."), frappe.DoesNotExistError)

	listing = frappe.get_doc("Listing", listing_name)

	# Admin/System Manager tüm ürünleri yönetebilir (admin liste görünümü toplu silme).
	# Satıcı ise yalnızca kendi ürününü siler: sub-user'lar Owner'ın ürününü yönetir
	# (aynı tenant); profile boşsa None == None sızıntısına düşmemek için dolu olduğunu
	# da doğrula.
	is_admin = frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()
	seller_profile = _get_seller_profile_for_user(frappe.session.user)
	if not is_admin and (not seller_profile or listing.seller_profile != seller_profile):
		frappe.throw(_("Bu ürün size ait değil."), frappe.PermissionError)

	# Silmeyi bloklayan ama iş değeri olmayan otomatik analitik/cache kayıtlarını
	# önce temizle (aksi halde görüntülenmiş her ürün spurious LinkExistsError alır).
	for _doctype, _field in _LISTING_DELETE_ANALYTICS_LINKS:
		frappe.db.delete(_doctype, {_field: listing_name})

	# Sonra kalıcı silmeyi dene. Gerçek iş kaydı varsa Frappe link kontrolü
	# LinkExistsError fırlatır (destructive işlemden ÖNCE). Ownership yukarıda
	# doğrulandığı için ignore_permissions gerekçeli (bkz. seller_addresses.delete_address).
	frappe.db.savepoint("before_listing_delete")
	try:
		frappe.delete_doc("Listing", listing_name, ignore_permissions=True)
		frappe.db.commit()
		# on_trash hook'u cache + ReBAC tuple temizliğini otomatik yapar.
		return {"action": "deleted", "listing": listing_name}
	except frappe.LinkExistsError:
		# Sipariş/sepet/favori bağımlılığı → kalıcı silinemez; geçmişi koru, arşivle.
		frappe.db.rollback(save_point="before_listing_delete")

	# Soft-delete: db.set_value hem validate'i (satıcı 'Archived'a geçemez kuralı)
	# hem _set_storefront_visible'ı atlar → storefront_visible'ı manuel 0'la
	# (update_listing_status ile aynı desen; aksi halde flag drift eder).
	frappe.db.set_value(
		"Listing",
		listing_name,
		{"status": "Archived", "is_visible": 0, "storefront_visible": 0},
	)

	# Arşivlenen ürünün sepet/favori/stok reservation'ını temizle — kullanıcılar
	# kopuk referans görmez, stok sayıları tutarlı kalır.
	_cleanup_listing_references(listing_name)

	frappe.db.commit()
	# set_value doc_event tetiklemez → arşivlenen ürünü cache'li 'Active'
	# listelerinden düşürmek için invalidation'ı manuel çağır.
	invalidate_listing_cache()
	return {"action": "archived", "listing": listing_name}


@frappe.whitelist()
def get_listing_meta():
	"""Satıcı için Listing doctype meta verilerini döndür (field tanımları)."""
	from frappe.model.meta import get_meta

	meta = get_meta("Listing")
	# Sadece UI'da gösterilecek alanları filtrele
	skip_types = {"Section Break", "Tab Break", "Column Break", "HTML", "Button"}
	skip_fields = {
		"listing_code",
		"seller_profile",
		"supplier_display_name",
		"status",
		"reserved_qty",
		"available_qty",
		"published_at",
		"erpnext_item",
		"naming_series",
		"variants_html",
		"view_count",
		"wishlist_count",
		"order_count",
		"average_rating",
		"review_count",
	}
	fields = []
	for f in meta.fields:
		if f.fieldtype in skip_types:
			continue
		if f.fieldname in skip_fields:
			continue
		if f.read_only:
			continue
		fields.append(
			{
				"fieldname": f.fieldname,
				"fieldtype": f.fieldtype,
				"label": f.label,
				"reqd": f.reqd,
				"options": f.options,
				"default": f.default,
				"depends_on": f.depends_on,
				"description": f.description,
			}
		)
	return {"success": True, "fields": fields}


@frappe.whitelist()
def recalculate_completeness_score(listing_name):
	"""Recalculate and persist the completeness score for a single listing."""
	from tradehub_core.utils.completeness import calculate_completeness_score
	from tradehub_core.utils.seller_capabilities import require_seller_capability
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	require_seller_capability("listing.write")

	doc = frappe.get_doc("Listing", listing_name)

	# Ownership check (önceden eksikti — herkes herhangi listing'in skorunu tetikleyebiliyordu)
	seller_profile = _get_seller_profile_for_user(frappe.session.user)
	if doc.seller_profile != seller_profile:
		frappe.throw(_("Bu listing size ait değil."), frappe.PermissionError)

	score = calculate_completeness_score(doc)
	doc.db_set("completeness_score", score, update_modified=False)
	return {"success": True, "completeness_score": score}


@frappe.whitelist()
def get_completeness_breakdown(listing_name):
	"""Return detailed score breakdown for admin panel display."""
	from tradehub_core.utils.completeness import get_score_breakdown
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	doc = frappe.get_doc("Listing", listing_name)
	# M12 fix — recalculate_completeness_score ile aynı sahiplik kontrolü; eskiden
	# herhangi bir kullanıcı başka satıcının (Draft dahil) listing skor detayını okuyabiliyordu.
	roles = set(frappe.get_roles(frappe.session.user))
	if not (roles & {"System Manager", "Marketplace Admin", "Administrator"}):
		seller_profile = _get_seller_profile_for_user(frappe.session.user)
		if doc.seller_profile != seller_profile:
			frappe.throw(_("Bu listing size ait değil."), frappe.PermissionError)
	return get_score_breakdown(doc)
