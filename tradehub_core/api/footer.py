"""Footer SEO bölgesi — gerçek marka / mağaza / kategori linkleri.

Storefront footer'ındaki "Popüler Üreticiler ve Mağazalar" + "Popüler Sayfalar"
bölümü eskiden sabit `?q=` aramalarına gidiyordu. Bu endpoint, linkleri gerçek
pretty sayfalara (`/marka/<slug>`, `/magaza/<seller_code>`,
`/pages/products.html?cat=<url_slug>`) bağlamak için veriyi DB'den üretir.

Kural: yalnızca **aktif ilanı olan** marka/mağaza/kategori döner — böylece
footer asla boş/dead-end sayfaya link vermez. Popülerlik = aktif ilan sayısı.
Storefront her sayfada footer render ettiği için sonuç 1 saat cache'lenir
(popülerlik yavaş değişir; TTL yeterli, ayrı invalidation gerekmez).
"""

import frappe
from frappe.query_builder import DocType, Order
from frappe.query_builder.functions import Count

from tradehub_core.seo.i18n import CONTENT_LANGS, normalize_lang, resolve_content_field

CACHE_KEY = "tc:footer_seo_links"
CACHE_TTL = 3600  # 1 saat

BRAND_LIMIT = 10
STORE_LIMIT = 6
CATEGORY_LIMIT = 15


@frappe.whitelist(allow_guest=True)
def get_footer_seo_links(lang: str = "tr") -> dict:
	"""Footer SEO linkleri: en çok aktif ilanı olan marka/mağaza/kategori.

	Returns: {"brands": [{label, slug}], "stores": [{label, slug}],
	          "categories": [{label, slug}]}
	brand slug → /marka/<slug>, store slug → seller_code (/magaza/<code>),
	category slug → url_slug (/pages/products.html?cat=<slug>).
	"""
	lang = normalize_lang(lang)
	key = f"{CACHE_KEY}:{lang}"
	cached = frappe.cache.get_value(key)
	if cached is not None:
		return cached

	result = {
		"brands": _top_brands(),
		"stores": _top_stores(),
		"categories": _top_categories(lang),
	}
	frappe.cache.set_value(key, result, expires_in_sec=CACHE_TTL)
	return result


def _top_brands() -> list[dict]:
	listing = DocType("Listing")
	brand = DocType("Brand")
	rows = (
		frappe.qb.from_(listing)
		.inner_join(brand)
		.on(listing.brand == brand.name)
		.select(brand.brand_name.as_("label"), brand.slug.as_("slug"))
		.where((listing.status == "Active") & (brand.status == "Approved") & (brand.is_active == 1))
		.groupby(brand.name)
		.orderby(Count(listing.name), order=Order.desc)
		.limit(BRAND_LIMIT)
	).run(as_dict=True)
	return [{"label": r.label, "slug": r.slug} for r in rows if r.slug and r.label]


def _top_stores() -> list[dict]:
	listing = DocType("Listing")
	seller = DocType("Admin Seller Profile")
	rows = (
		frappe.qb.from_(listing)
		.inner_join(seller)
		.on(listing.seller_profile == seller.name)
		.select(
			seller.company_name.as_("company"),
			seller.seller_name.as_("seller_name"),
			seller.seller_code.as_("code"),
		)
		.where((listing.status == "Active") & (seller.status == "Active"))
		.groupby(seller.name)
		.orderby(Count(listing.name), order=Order.desc)
		.limit(STORE_LIMIT)
	).run(as_dict=True)
	return [
		{"label": r.company or r.seller_name, "slug": r.code}
		for r in rows
		if r.code and (r.company or r.seller_name)
	]


def _top_categories(lang: str) -> list[dict]:
	listing = DocType("Listing")
	cat = DocType("Product Category")
	# inner_join + group by → yalnızca aktif ilanı olan kategoriler döner
	rows = (
		frappe.qb.from_(listing)
		.inner_join(cat)
		.on(listing.product_category == cat.name)
		.select(cat.name.as_("id"))
		.where((listing.status == "Active") & (cat.is_active == 1))
		.groupby(cat.name)
		.orderby(Count(listing.name), order=Order.desc)
		.limit(CATEGORY_LIMIT)
	).run(as_dict=True)
	ids = [r.id for r in rows]
	if not ids:
		return []

	# Etiket + slug'ı tek batch'te çek (N+1 yok); ad aktif dile çözülür.
	meta = {
		c.name: c
		for c in frappe.get_all(
			"Product Category",
			filters={"name": ["in", ids]},
			fields=[
				"name",
				"category_name",
				"url_slug",
				"content_default_lang",
				*[f"category_name_{lng}" for lng in CONTENT_LANGS],
			],
		)
	}
	out = []
	for cid in ids:  # qb popülerlik sıralamasını koru
		c = meta.get(cid)
		if not c or not c.get("url_slug"):
			continue
		label = (
			resolve_content_field(c, "category_name", lang, c.get("content_default_lang")) or c.category_name
		)
		out.append({"label": label, "slug": c.url_slug})
	return out
