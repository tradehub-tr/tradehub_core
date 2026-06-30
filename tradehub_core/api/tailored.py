"""
Tailored Selections API — kullanıcı aktivitesine dayalı kategori önerileri.

Endpoint'ler:
- get_tailored_selections(limit=9)  → Landing sayfasında 9 grup kartı
- get_tailored_group_detail(...)    → "Daha fazla göster" detay sayfası

Skor formülü (son 30 gün kullanıcı aktivitesi):
    skor(kat, user) = 3 × orders + 1.5 × searches + 1 × views

Cold-start:
- Anonim kullanıcı veya < MIN_INTERACTIONS etkileşimli kullanıcı →
  global top kategoriler (tüm Listing'lerin view_count + order_count toplamı).

Hybrid kategori seviyesi:
- Alt kategori skoru ≥ %40 × ana kategori skoru ise alt kategori gösterilir.
- Aksi halde ana kategori (sinyal dağınık).
"""

import hashlib
import json

import frappe
from frappe import _

# ── Tuning constants (MVP: hard-coded; ileride System Settings'ten okunacak) ──

# Sinyal ağırlıkları
TAILORED_ORDER_WEIGHT = 3.0
TAILORED_SEARCH_WEIGHT = 1.5
TAILORED_VIEW_WEIGHT = 1.0

# Alt kategori skoru, ana skorunun %X'i üstündeyse alt göster
TAILORED_SUB_CATEGORY_THRESHOLD = 0.40

# Bu sayıdan az etkileşim varsa cold-start fallback devreye girer
TAILORED_MIN_INTERACTIONS = 5

# Aktivite pencere (gün)
TAILORED_LOOKBACK_DAYS = 30

# View log retention (gün)
TAILORED_VIEW_RETENTION_DAYS = 30

# Kullanıcı bazlı view dedup penceresi (saniye).
# Aynı kullanıcı aynı ürünü bu süre içinde tekrar açarsa yeni kayıt oluşmaz.
USER_VIEW_DEDUP_TTL = 3600  # 1 saat

# Cache TTL
CACHE_TTL_USER = 3600  # 1 saat
CACHE_TTL_GLOBAL = 900  # 15 dakika

# Her grup kartında kaç temsili ürün gösterilecek
PRODUCTS_PER_GROUP = 2


def _cache_key(prefix: str, **kwargs) -> str:
	raw = json.dumps(kwargs, sort_keys=True, default=str)
	h = hashlib.md5(raw.encode()).hexdigest()[:12]
	return f"{prefix}:{h}"


def _listing_to_card(l) -> dict:
	"""Shared listing row → ProductListingCard dict.
	Applies active campaign discount (discount_percentage > 0) the same way
	api.listing.get_listing_detail does, so prices stay consistent across
	the storefront (Tailored cards ↔ product detail ↔ top ranking)."""
	image_src = (
		frappe.db.get_value(
			"Listing Image",
			{"parent": l.name},
			"image",
			order_by="idx ASC",
		)
		or ""
	)
	selling = float(l.selling_price or 0)
	dp = float(getattr(l, "discount_percentage", 0) or 0)
	has_campaign = dp > 0
	effective = round(selling * (1 - dp / 100), 2) if has_campaign else selling

	from tradehub_core.api.listing import _format_price

	listing_currency = getattr(l, "currency", None) or "USD"
	card = {
		"id": l.name,
		"listingCode": l.listing_code,
		"name": getattr(l, "name_display", None) or l.name,
		# Currency-aware sembol (eskiden hardcoded ₺); frontend zaten sellingPrice
		# + baseCurrency ile formatlıyor, bu yalnız fallback string.
		"price": _format_price(effective, listing_currency),
		"sellingPrice": effective,
		"originalSellingPrice": selling if has_campaign and selling > 0 else None,
		"discount": f"%{int(dp)} indirim" if has_campaign else None,
		"baseCurrency": listing_currency,
		"moq": f"{l.min_order_qty or 1} {l.stock_uom or 'Adet'}",
		"imageSrc": image_src,
		"stats": {
			"views": l.view_count or 0,
			"orders": l.order_count or 0,
		},
		"href": f"/pages/product-detail.html?id={l.name}",
	}
	return card


# ─── View Logging ─────────────────────────────────────────────────────────────


def log_product_view(listing_name: str, category: str = None):
	"""Log a product view for the current logged-in user. Guest views are
	ignored (they only bump the global Listing.view_count).

	Called from api.listing.get_listing_detail inside the view-count block.
	Idempotent within USER_VIEW_DEDUP_TTL per (user, listing).
	"""
	try:
		user = frappe.session.user
		if user == "Guest":
			return

		# Dedup: same user + same listing within TTL counts as one view
		dedup_key = f"user_view_seen:{user}:{listing_name}"
		if frappe.cache.get_value(dedup_key):
			return

		doc = frappe.new_doc("User Product View")
		doc.user = user
		doc.listing = listing_name
		if category:
			doc.category = category
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()

		frappe.cache.set_value(dedup_key, 1, expires_in_sec=USER_VIEW_DEDUP_TTL)

		# Invalidate tailored cache so new view affects recommendations next time
		frappe.cache.delete_value(f"tailored:user:{user}")
	except Exception:
		# View logging is best-effort — never break the detail page
		pass


def cleanup_old_user_product_views():
	"""Scheduler job: remove User Product View rows older than retention.
	Runs daily via hooks.py scheduler_events.daily.
	"""
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -TAILORED_VIEW_RETENTION_DAYS)
	old_records = frappe.get_all(
		"User Product View",
		filters={"creation": ["<", cutoff]},
		fields=["name"],
		limit=5000,
	)
	for r in old_records:
		frappe.delete_doc("User Product View", r.name, force=True, ignore_permissions=True)
	if old_records:
		frappe.db.commit()


# ─── Cache Invalidation ───────────────────────────────────────────────────────


def invalidate_tailored_user_cache(doc, method=None):
	"""Order before_save hook companion: when an order transitions into a sold
	state, drop the buyer's tailored cache so next visit reflects the purchase.

	Wired from hooks.py (Order before_save). Kept best-effort; recommendation
	freshness is not worth blocking an order save.
	"""
	try:
		if method is None:
			return
		status = (doc.get("status") or "").strip()
		if status not in ("Kargoda", "Tamamlandı"):
			return
		buyer = doc.get("buyer") or doc.get("owner")
		if buyer:
			frappe.cache.delete_value(f"tailored:user:{buyer}")
	except Exception:
		pass


# ─── Scoring ──────────────────────────────────────────────────────────────────


def _compute_category_scores(user: str) -> dict:
	"""Return {category_slug: {'score': float, 'parent': slug_or_none}} for the
	given user, aggregating the last TAILORED_LOOKBACK_DAYS of orders,
	searches, and views.

	Guest users get an empty dict (cold-start path handled by caller).
	"""
	if not user or user == "Guest":
		return {}

	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -TAILORED_LOOKBACK_DAYS)
	scores = {}

	# 1) Order history → listings purchased → product_category
	# Order has `buyer` Link to User. Order Item is a child table with listing Link.
	try:
		order_rows = frappe.db.sql(
			"""
            SELECT l.product_category AS category, COUNT(*) AS cnt
            FROM `tabOrder Item` oi
            INNER JOIN `tabOrder` o ON o.name = oi.parent
            INNER JOIN `tabListing` l ON l.name = oi.listing
            WHERE o.buyer = %(user)s
              AND o.creation >= %(cutoff)s
              AND l.product_category IS NOT NULL
            GROUP BY l.product_category
            """,
			{"user": user, "cutoff": cutoff},
			as_dict=True,
		)
		for r in order_rows:
			cat = r.category
			if not cat:
				continue
			scores.setdefault(cat, 0.0)
			scores[cat] += TAILORED_ORDER_WEIGHT * (r.cnt or 0)
	except Exception:
		pass

	# 2) Search history → category aggregation
	try:
		search_rows = frappe.db.sql(
			"""
            SELECT category, COUNT(*) AS cnt
            FROM `tabSearch History`
            WHERE user = %(user)s
              AND creation >= %(cutoff)s
              AND category IS NOT NULL AND category != ''
            GROUP BY category
            """,
			{"user": user, "cutoff": cutoff},
			as_dict=True,
		)
		for r in search_rows:
			cat = r.category
			if not cat:
				continue
			scores.setdefault(cat, 0.0)
			scores[cat] += TAILORED_SEARCH_WEIGHT * (r.cnt or 0)
	except Exception:
		pass

	# 3) View history (User Product View)
	try:
		view_rows = frappe.db.sql(
			"""
            SELECT category, COUNT(*) AS cnt
            FROM `tabUser Product View`
            WHERE user = %(user)s
              AND creation >= %(cutoff)s
              AND category IS NOT NULL AND category != ''
            GROUP BY category
            """,
			{"user": user, "cutoff": cutoff},
			as_dict=True,
		)
		for r in view_rows:
			cat = r.category
			if not cat:
				continue
			scores.setdefault(cat, 0.0)
			scores[cat] += TAILORED_VIEW_WEIGHT * (r.cnt or 0)
	except Exception:
		pass

	# Attach parent info for hybrid decision
	if scores:
		cats = frappe.get_all(
			"Product Category",
			filters={"name": ["in", list(scores.keys())]},
			fields=["name", "parent_product_category", "category_name", "url_slug"],
		)
		parent_map = {c.name: c.parent_product_category for c in cats}
		return {c: {"score": scores[c], "parent": parent_map.get(c)} for c in scores}
	return {}


def _pick_hybrid_categories(scored: dict, limit: int) -> list:
	"""Decide per ana-kategori whether to surface the main category itself or
	its top-scored sub-category based on the 40% threshold. Returns a list of
	category names (length <= limit), sorted by descending effective score.
	"""
	if not scored:
		return []

	# Partition into main categories (no parent) and subs (with parent)
	mains = {c: v for c, v in scored.items() if not v.get("parent")}
	subs = {}  # parent -> list of (name, score)
	for c, v in scored.items():
		p = v.get("parent")
		if p:
			subs.setdefault(p, []).append((c, v["score"]))

	final = []  # list of (category, score)

	# Ana kategoriler: kendi skoru + tüm çocuklarının skoru
	for main, v in mains.items():
		main_score = v["score"]
		# Toplam skor = kendi + alt kategori skorları
		child_scores = [s for _, s in subs.get(main, [])]
		main_score_agg = main_score + sum(child_scores)

		# En yüksek alt kategori varsa → eşik kontrol
		if subs.get(main):
			subs[main].sort(key=lambda x: x[1], reverse=True)
			top_sub, top_sub_score = subs[main][0]
			if main_score_agg > 0 and top_sub_score >= TAILORED_SUB_CATEGORY_THRESHOLD * main_score_agg:
				final.append((top_sub, top_sub_score))
				continue
		final.append((main, main_score_agg))

	# Orphan alt kategoriler (ana skorsuz) — yine de önerilecek
	for parent, lst in subs.items():
		if parent not in mains:
			for name, score in lst:
				final.append((name, score))

	# Azalan skorla sırala, top N al
	final.sort(key=lambda x: x[1], reverse=True)
	return [name for name, _ in final[:limit]]


def _get_global_top_categories(limit: int) -> list:
	"""Cold-start fallback: return top categories by aggregate Listing
	popularity (view_count + order_count). Uses only active, leaf-or-main
	categories that have at least one Listing.
	"""
	rows = frappe.db.sql(
		"""
        SELECT l.product_category AS category,
               SUM(COALESCE(l.view_count, 0) + COALESCE(l.order_count, 0)) AS score
        FROM `tabListing` l
        WHERE l.product_category IS NOT NULL
          AND l.status = 'Active'
        GROUP BY l.product_category
        HAVING score > 0
        ORDER BY score DESC
        LIMIT %(limit)s
        """,
		{"limit": limit},
		as_dict=True,
	)
	return [r.category for r in rows if r.category]


def _top_listings_for_category(category: str, limit: int) -> list:
	"""Return top N listings in a category sorted by popularity.
	Flat list of ProductListingCard-shaped dicts (subset of fields).
	"""
	listings = frappe.db.sql(
		"""
        SELECT l.name, l.listing_code, l.title AS name_display,
               l.selling_price, l.discount_percentage, l.currency,
               l.view_count, l.order_count,
               l.min_order_qty, l.stock_uom
        FROM `tabListing` l
        WHERE l.product_category = %(category)s
          AND l.status = 'Active'
        ORDER BY (COALESCE(l.order_count, 0) + COALESCE(l.view_count, 0)) DESC
        LIMIT %(limit)s
        """,
		{"category": category, "limit": limit},
		as_dict=True,
	)

	return [_listing_to_card(l) for l in listings]


def _build_editorial(category_name: str, user: str = None) -> dict:
	"""Return {editorialText, badge} for a category card.

	Badge koşulları (öncelik sırasıyla):
	  - "personal"   → user'ın son 30g aktivitesinde bu kategorinin toplam view'ı >= 50
	  - "trend"      → son 30g içinde bu kategorideki Listing'lerin order_count artışı >= 50
	  - "quality"    → bu kategorideki Listing'lerin avg(average_rating) >= 4.5
	  - None          → hiçbiri değilse

	editorialText: sayısal istatistiklerle template doldurur. Hiç istatistik
	yoksa düşük-key bir fallback döner ("{name} altında seçkin ürünler").
	"""
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -TAILORED_LOOKBACK_DAYS)

	# Kategori geneli agregasyon (tüm active listing'ler)
	agg = frappe.db.sql(
		"""
        SELECT
            COUNT(*)                                     AS product_count,
            COUNT(DISTINCT l.seller_profile)             AS seller_count,
            COALESCE(SUM(l.view_count), 0)               AS total_views,
            COALESCE(SUM(l.order_count), 0)              AS total_orders,
            COALESCE(AVG(NULLIF(l.average_rating, 0)), 0) AS avg_rating,
            COALESCE(SUM(l.review_count), 0)             AS total_reviews,
            COALESCE(AVG(NULLIF(l.discount_percentage, 0)), 0) AS avg_discount
        FROM `tabListing` l
        WHERE l.product_category = %(cat)s AND l.status = 'Active'
        """,
		{"cat": category_name},
		as_dict=True,
	)
	stats = agg[0] if agg else {}

	# Kullanıcıya özel son 30g view sayısı (varsa)
	user_views = 0
	if user and user != "Guest":
		try:
			rows = frappe.db.sql(
				"""
                SELECT COUNT(*) AS cnt FROM `tabUser Product View`
                WHERE user = %(u)s AND category = %(cat)s AND creation >= %(cutoff)s
                """,
				{"u": user, "cat": category_name, "cutoff": cutoff},
				as_dict=True,
			)
			user_views = int(rows[0].cnt) if rows else 0
		except Exception:
			user_views = 0

	# Rozet seçimi (öncelik sırası)
	badge = None
	if user_views >= 50:
		badge = "personal"
	elif (stats.get("total_orders") or 0) >= 50:
		badge = "trend"
	elif float(stats.get("avg_rating") or 0) >= 4.5 and int(stats.get("total_reviews") or 0) >= 10:
		badge = "quality"

	# Editorial metin — hangi template kullanılacak
	product_count = int(stats.get("product_count") or 0)
	seller_count = int(stats.get("seller_count") or 0)
	total_views = int(stats.get("total_views") or 0)
	total_orders = int(stats.get("total_orders") or 0)
	avg_rating = float(stats.get("avg_rating") or 0)
	total_reviews = int(stats.get("total_reviews") or 0)
	avg_discount = float(stats.get("avg_discount") or 0)

	def _fmt_num(n):
		if n >= 1000:
			return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "K+"
		return str(n)

	text = ""
	if badge == "personal" and user_views > 0:
		text = f"{_fmt_num(user_views)} görüntüleme aldığın {product_count} ürün"
		if avg_discount > 0:
			text += f", ortalama %{int(avg_discount)} indirim"
	elif badge == "trend":
		text = f"Son 30 gün {_fmt_num(total_orders)} sipariş — {product_count} aktif ürün"
		if seller_count > 0:
			text += f", {seller_count} tedarikçi"
	elif badge == "quality":
		text = f"⭐ {avg_rating:.1f} ortalama — {_fmt_num(total_reviews)} yorum, {product_count} seçkin ürün"
	else:
		# Nötr fallback (cold-start veya zayıf sinyal)
		parts = [f"{product_count} ürün"]
		if seller_count > 0:
			parts.append(f"{seller_count} tedarikçi")
		if total_views > 0:
			parts.append(f"{_fmt_num(total_views)} görüntüleme")
		text = " · ".join(parts) if parts else "Seçkin ürünler"

	return {"editorialText": text, "badge": badge}


def _category_display(category_name: str) -> dict:
	"""Return minimal category info for card header: {slug, name, image, parent, viewsCount}."""
	cat = frappe.db.get_value(
		"Product Category",
		category_name,
		["name", "category_name", "url_slug", "image", "parent_product_category"],
		as_dict=True,
	)
	if not cat:
		return {"slug": category_name, "name": category_name, "image": "", "parent": None, "viewsCount": 0}
	# Kategori toplam görüntüleme sayısı: o kategorideki aktif tüm listing'lerin view_count toplamı
	total_views = frappe.db.sql(
		"""
        SELECT COALESCE(SUM(view_count), 0) AS total
        FROM `tabListing`
        WHERE product_category = %(cat)s AND status = 'Active'
        """,
		{"cat": category_name},
		as_dict=True,
	)
	views_count = int(total_views[0].total) if total_views else 0
	return {
		"slug": cat.url_slug or cat.name,
		"name": cat.category_name or cat.name,
		"image": cat.image or "",
		"parent": cat.parent_product_category,
		"categoryId": cat.name,
		"viewsCount": views_count,
	}


# ─── Public Endpoints ─────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True)
def get_tailored_selections(limit: int = 9):
	"""Landing bloğu için 9 "grup kartı" döner.

	Giriş yapmış ve yeterli aktivitesi olan kullanıcılar için kişiselleştirilmiş
	kategoriler; aksi halde global top kategoriler. Her grup kartı:
	{slug, name, image, products: [ProductListingCard × PRODUCTS_PER_GROUP]}
	"""
	try:
		limit = max(1, min(int(limit), 30))
	except (TypeError, ValueError):
		limit = 9

	user = frappe.session.user
	is_guest = user == "Guest"

	# Cache layer
	cache_key = "tailored:global" if is_guest else f"tailored:user:{user}"
	cache_ttl = CACHE_TTL_GLOBAL if is_guest else CACHE_TTL_USER
	cached = frappe.cache.get_value(cache_key)
	if cached:
		try:
			payload = json.loads(cached)
			if payload.get("limit") == limit:
				return payload
		except Exception:
			pass

	# 1) Category selection
	personalized = False
	if not is_guest:
		scored = _compute_category_scores(user)
		total_signals = sum(v["score"] for v in scored.values())
		if total_signals >= TAILORED_MIN_INTERACTIONS:
			categories = _pick_hybrid_categories(scored, limit)
			personalized = True
		else:
			categories = _get_global_top_categories(limit)
	else:
		categories = _get_global_top_categories(limit)

	# 2) Build group cards
	groups = []
	for cat_name in categories:
		display = _category_display(cat_name)
		products = _top_listings_for_category(cat_name, PRODUCTS_PER_GROUP)
		if not products:
			# Skip empty categories rather than show a blank card
			continue
		editorial = _build_editorial(cat_name, user=user if not is_guest else None)
		groups.append(
			{
				"slug": display["slug"],
				"categoryId": display.get("categoryId", cat_name),
				"name": display["name"],
				"image": display["image"],
				"parent": display["parent"],
				"viewsCount": display.get("viewsCount", 0),
				"editorialText": editorial["editorialText"],
				"badge": editorial["badge"],
				"products": products,
			}
		)

	payload = {
		"limit": limit,
		"personalized": personalized,
		"isGuest": is_guest,
		"groups": groups,
		"total": len(groups),
	}

	try:
		frappe.cache.set_value(cache_key, json.dumps(payload), expires_in_sec=cache_ttl)
	except Exception:
		pass

	return payload


@frappe.whitelist(allow_guest=True)
def get_tailored_group_detail(category: str, subcategory: str = None, page: int = 1, page_size: int = 20):
	""" "Daha fazla göster" detay sayfası için bir grubun ürünleri.

	Args:
	    category: Ana kategori slug veya name
	    subcategory: Opsiyonel alt kategori filtresi (slug veya name)
	    page: 1-based sayfa numarası
	    page_size: sayfa başına ürün (max 50)
	"""
	if not category:
		frappe.throw(_("Category is required"))

	try:
		page = max(1, int(page))
		page_size = max(1, min(int(page_size), 50))
	except (TypeError, ValueError):
		page, page_size = 1, 20

	# Slug'tan name'e çözümle
	def _resolve_category(value):
		if not value:
			return None
		# Önce slug olarak dene
		name = frappe.db.get_value("Product Category", {"url_slug": value}, "name")
		if name:
			return name
		# Sonra name olarak
		if frappe.db.exists("Product Category", value):
			return value
		return None

	active_category = _resolve_category(subcategory) or _resolve_category(category)
	if not active_category:
		return {"page": page, "page_size": page_size, "products": [], "hasNext": False, "total": 0}

	offset = (page - 1) * page_size

	# Aktif kategori + tüm alt kategorileri kapsa (drill-down mantığı)
	descendants = frappe.get_all(
		"Product Category",
		filters={"parent_product_category": active_category},
		pluck="name",
	)
	target_categories = [active_category] + list(descendants)

	listings = frappe.db.sql(
		"""
        SELECT l.name, l.listing_code, l.title AS name_display,
               l.selling_price, l.discount_percentage, l.currency,
               l.view_count, l.order_count,
               l.min_order_qty, l.stock_uom, l.product_category
        FROM `tabListing` l
        WHERE l.product_category IN %(cats)s
          AND l.status = 'Active'
        ORDER BY (COALESCE(l.order_count, 0) + COALESCE(l.view_count, 0)) DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
		{"cats": tuple(target_categories), "limit": page_size + 1, "offset": offset},
		as_dict=True,
	)

	has_next = len(listings) > page_size
	listings = listings[:page_size]

	products = [_listing_to_card(l) for l in listings]

	# Alt kategori seçenekleri (filter UI için)
	sub_categories = frappe.get_all(
		"Product Category",
		filters={"parent_product_category": active_category, "is_active": 1},
		fields=["name", "category_name", "url_slug"],
		order_by="sort_order ASC, category_name ASC",
	)

	display = _category_display(active_category)
	return {
		"page": page,
		"page_size": page_size,
		"hasNext": has_next,
		"products": products,
		"category": {
			"slug": display["slug"],
			"name": display["name"],
			"image": display["image"],
			"categoryId": display.get("categoryId", active_category),
		},
		"subCategories": [
			{"slug": s.url_slug or s.name, "name": s.category_name or s.name} for s in sub_categories
		],
	}
