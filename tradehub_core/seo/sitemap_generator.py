"""
XML sitemap üretici (index + alt-sitemap'ler + pagination).

Pure builder fonksiyonları Frappe runtime'a bağımlı değildir; DB sorgu
yapan `build_for_type()` ve `build_index()` Frappe wrapper'lar.
"""

from collections.abc import Iterable
from xml.sax.saxutils import escape

from tradehub_core.seo.i18n import SUPPORTED_LANGS, build_hreflang_links

MAX_URLS_PER_SITEMAP = 50_000
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML_NS = "http://www.w3.org/1999/xhtml"

DOCTYPE_CONFIG = {
	"Listing": {
		"url_prefix": "/urun",
		"priority": "0.9",
		"changefreq": "weekly",
		"slug_field": "slug",
		"sub_sitemap_name": "products",
	},
	"Product Category": {
		"url_prefix": "/kategori",
		"priority": "0.8",
		"changefreq": "monthly",
		"slug_field": "url_slug",
		"sub_sitemap_name": "categories",
	},
	"Brand": {
		"url_prefix": "/marka",
		"priority": "0.7",
		"changefreq": "monthly",
		"slug_field": "slug",
		"sub_sitemap_name": "brands",
	},
	"Admin Seller Profile": {
		"url_prefix": "/magaza",
		"priority": "0.6",
		"changefreq": "weekly",
		"slug_field": "slug",
		"sub_sitemap_name": "sellers",
	},
	"Static Page SEO": {
		"url_prefix": "",  # page_path zaten / ile başlar
		"priority": "0.5",
		"changefreq": "monthly",
		"slug_field": "page_path",
		"sub_sitemap_name": "static-pages",
	},
}


def urlentry(*, loc: str, lastmod: str, priority: str = "0.5", changefreq: str = "monthly") -> dict:
	"""URL entry dict üretir (sitemap_generator için canonical format)."""
	return {
		"loc": loc,
		"lastmod": lastmod,
		"priority": priority,
		"changefreq": changefreq,
	}


def build_urlset_xml(urls: Iterable[dict], include_hreflang: bool = True) -> str:
	"""URL listesinden <urlset> XML üret. Pure: I/O yok.

	`include_hreflang=True` ise her URL'ye xhtml:link hreflang annotation
	eklenir (Faz 7). URL entry'sinde `hreflang_links` varsa onu kullanır,
	yoksa otomatik üretilmez (entry zaten TR URL'i olduğu için)."""
	xmlns = f'xmlns="{SITEMAP_NS}"'
	if include_hreflang:
		xmlns += f' xmlns:xhtml="{XHTML_NS}"'

	lines = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		f'<urlset {xmlns}>',
	]
	for u in urls:
		loc = escape(u.get("loc", ""))
		lastmod = escape(u.get("lastmod", ""))
		changefreq = escape(u.get("changefreq", "monthly"))
		priority = escape(u.get("priority", "0.5"))
		lines.append("  <url>")
		lines.append(f"    <loc>{loc}</loc>")
		# Hreflang annotations (xhtml:link)
		hreflang_links = u.get("hreflang_links") or []
		for alt in hreflang_links:
			hreflang_attr = escape(alt.get("hreflang", ""))
			href_attr = escape(alt.get("href", ""))
			lines.append(
				f'    <xhtml:link rel="alternate" hreflang="{hreflang_attr}" href="{href_attr}"/>'
			)
		if lastmod:
			lines.append(f"    <lastmod>{lastmod}</lastmod>")
		lines.append(f"    <changefreq>{changefreq}</changefreq>")
		lines.append(f"    <priority>{priority}</priority>")
		lines.append("  </url>")
	lines.append("</urlset>")
	return "\n".join(lines)


def build_index_xml(sitemaps: Iterable[dict]) -> str:
	"""Sub-sitemap listesinden <sitemapindex> XML üret. Pure."""
	lines = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		f'<sitemapindex xmlns="{SITEMAP_NS}">',
	]
	for sm in sitemaps:
		loc = escape(sm.get("loc", ""))
		lastmod = escape(sm.get("lastmod", ""))
		lines.append("  <sitemap>")
		lines.append(f"    <loc>{loc}</loc>")
		if lastmod:
			lines.append(f"    <lastmod>{lastmod}</lastmod>")
		lines.append("  </sitemap>")
	lines.append("</sitemapindex>")
	return "\n".join(lines)


def chunk_urls_for_pagination(urls: list[dict]) -> list[list[dict]]:
	"""URL listesini MAX_URLS_PER_SITEMAP boyutunda parçalara böl."""
	chunks = []
	for i in range(0, len(urls), MAX_URLS_PER_SITEMAP):
		chunks.append(urls[i : i + MAX_URLS_PER_SITEMAP])
	return chunks or [[]]


# Frappe wrappers ------------------------------------------------------------


def _site_url() -> str:
	import frappe
	return frappe.utils.get_url().rstrip("/")


def _fetch_records_for(doctype: str) -> list[dict]:
	"""DB'den sitemap'e dahil edilecek kayıtları çek."""
	import frappe

	cfg = DOCTYPE_CONFIG[doctype]
	slug_field = cfg["slug_field"]

	filters: dict = {"noindex": 0}
	if doctype == "Listing":
		filters["status"] = "Active"
	elif doctype == "Brand":
		filters["status"] = "Approved"

	fields = ["name", slug_field, "modified"]
	if doctype in ("Product Category", "Static Page SEO"):
		fields.extend(["sitemap_priority", "sitemap_changefreq"])

	rows = frappe.get_all(doctype, filters=filters, fields=fields, limit_page_length=0)
	return [r for r in rows if r.get(slug_field)]


def build_for_type(doctype: str) -> str:
	"""Tek doctype için <urlset> XML üret (DB'den okur)."""
	cfg = DOCTYPE_CONFIG[doctype]
	rows = _fetch_records_for(doctype)
	site = _site_url()

	urls = []
	for row in rows:
		slug = row.get(cfg["slug_field"])
		# Static Page SEO: page_path zaten / ile başlıyor (örn. "/kvkk")
		# Diğerleri: prefix + "/" + slug (örn. "/urun" + "/" + "iphone")
		if cfg["url_prefix"]:
			tr_path = f"{cfg['url_prefix']}/{slug}"
		else:
			tr_path = slug if slug.startswith("/") else f"/{slug}"
		loc = f"{site}{tr_path}"
		lastmod = str(row.get("modified", ""))[:10]

		priority = row.get("sitemap_priority") or cfg["priority"]
		changefreq = row.get("sitemap_changefreq") or cfg["changefreq"]

		entry = urlentry(
			loc=loc,
			lastmod=lastmod,
			priority=str(priority),
			changefreq=str(changefreq),
		)
		# Faz 7: hreflang annotations (xhtml:link) — her TR URL'sine tr+en+x-default
		entry["hreflang_links"] = build_hreflang_links(tr_path, site)
		urls.append(entry)

	chunks = chunk_urls_for_pagination(urls)
	return build_urlset_xml(chunks[0])


def build_index() -> str:
	"""Sitemap index'i üret — 4 sub-sitemap loc'una işaret eder."""
	from datetime import date

	site = _site_url()
	today = date.today().isoformat()

	sitemaps = []
	for _doctype, cfg in DOCTYPE_CONFIG.items():
		sitemaps.append({
			"loc": f"{site}/sitemap-{cfg['sub_sitemap_name']}.xml",
			"lastmod": today,
		})

	return build_index_xml(sitemaps)
