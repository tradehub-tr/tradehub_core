import frappe
from frappe.query_builder import DocType

from tradehub_core.api.listing import STOREFRONT_VISIBLE_STATUSES

CACHE_TTL = 60
MIN_Q_LEN = 2
MAX_Q_LEN = 64
DEFAULT_LIMIT = 5


@frappe.whitelist(allow_guest=True)
def unified_suggest(q: str = "", limit_per_group: int = DEFAULT_LIMIT) -> dict:
	"""Storefront header arama autocomplete'i — 4 grupta sonuç döner.

	q boş veya tek karakter → popüler/en yeni kayıtlar (LIKE filtresi yok).
	q ≥ 2 karakter → LIKE %q% ile filtreli sonuçlar.

	Public endpoint; yalnızca yayında / approved kayıtları döner.
	"""
	q_clean = (q or "").strip()
	if len(q_clean) > MAX_Q_LEN:
		return _empty()

	# q boş veya 1 karakter → popüler mode (filter atlanır). q ≥ MIN_Q_LEN → LIKE.
	q_filter = q_clean if len(q_clean) >= MIN_Q_LEN else ""

	limit = max(1, min(int(limit_per_group), 10))
	cache_key = f"search:unified:{q_filter.lower()}:{limit}"
	cached = frappe.cache.get_value(cache_key)
	if cached:
		return cached

	result = {
		"products": _search_products(q_filter, limit),
		"categories": _search_categories(q_filter, limit),
		"brands": _search_brands(q_filter, limit),
		"sellers": _search_sellers(q_filter, limit),
	}
	frappe.cache.set_value(cache_key, result, expires_in_sec=CACHE_TTL)
	return result


def _empty() -> dict:
	return {"products": [], "categories": [], "brands": [], "sellers": []}


def _search_products(q: str, limit: int) -> list[dict]:
	Listing = DocType("Listing")
	qb = (
		frappe.qb.from_(Listing)
		.select(Listing.name, Listing.title, Listing.primary_image)
		.where(Listing.status.isin(list(STOREFRONT_VISIBLE_STATUSES)))
		.where(Listing.is_visible == 1)
	)
	if q:
		qb = qb.where(Listing.title.like(f"%{q}%"))
	rows = qb.orderby(Listing.modified, order=frappe.qb.desc).limit(limit).run(as_dict=True)
	return [{"id": r.name, "name": r.title or "", "image": r.primary_image or ""} for r in rows]


def _search_categories(q: str, limit: int) -> list[dict]:
	Cat = DocType("Product Category")
	qb = frappe.qb.from_(Cat).select(Cat.name, Cat.category_name, Cat.url_slug).where(Cat.is_active == 1)
	if q:
		qb = qb.where(Cat.category_name.like(f"%{q}%"))
	rows = qb.orderby(Cat.category_name).limit(limit).run(as_dict=True)
	return [
		{
			"name": r.category_name or "",
			"slug": r.url_slug or _slugify(r.category_name or ""),
		}
		for r in rows
	]


def _search_brands(q: str, limit: int) -> list[dict]:
	Brand = DocType("Brand")
	qb = (
		frappe.qb.from_(Brand)
		.select(Brand.name, Brand.brand_name, Brand.slug, Brand.logo)
		.where(Brand.status == "Approved")
		.where(Brand.is_active == 1)
	)
	if q:
		qb = qb.where(Brand.brand_name.like(f"%{q}%"))
	rows = qb.orderby(Brand.brand_name).limit(limit).run(as_dict=True)
	return [
		{
			"code": r.name,
			"name": r.brand_name or "",
			"slug": r.slug or "",
			"logo": r.logo or "",
		}
		for r in rows
	]


def _search_sellers(q: str, limit: int) -> list[dict]:
	Seller = DocType("Admin Seller Profile")
	qb = (
		frappe.qb.from_(Seller)
		.select(Seller.name, Seller.seller_name, Seller.seller_code, Seller.logo)
		.where(Seller.status == "Active")
	)
	if q:
		qb = qb.where(Seller.seller_name.like(f"%{q}%"))
	rows = qb.orderby(Seller.seller_name).limit(limit).run(as_dict=True)
	return [
		{
			"id": r.name,
			"name": r.seller_name or "",
			"slug": r.seller_code or "",
			"logo": r.logo or "",
		}
		for r in rows
	]


def _slugify(text: str) -> str:
	"""Basit slug fallback — url_slug null'sa kullan."""
	import re

	return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
