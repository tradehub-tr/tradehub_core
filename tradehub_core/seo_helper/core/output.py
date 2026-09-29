"""Tek SEO çıktı üreticisi (MOGEM-653 §4.3) — Builder sayfalarının head'i buradan belirlenir.

Ölçülen sıra (frappe v15 `TemplatePage.get_html`): `init_context` → `update_context`
(Builder `get_context`: title/canonical/disable_indexing/metatags/_head_html) → `post_process_context`
(Frappe MetaTags) → **`update_website_context` hook'ları (biz)** → şablon. Kancamız EN SON koşar ve
Builder şablonunun okuduğu bağlam alanlarını tek elden belirler:

- `context.title`, `context.canonical_url`, `context.metatags` (description/og/twitter) → Builder
  şablonu bunları basar; ikinci bir başlık/canonical/description üretilmez.
- `context.disable_indexing = 0` + robots meta'yı biz `_head_html`'e yazarız ("noindex,follow" gibi
  Builder'ın ifade edemediği değerler için) → tek robots etiketi.
- hreflang `<link rel="alternate">` ve JSON-LD `_head_html`'e eklenir.

Builder çekirdeğine/şablonuna patch yok. Cache: `shc:head:*` `data_version` damgalı.
"""

from __future__ import annotations

import frappe

from tradehub_core.seo_helper.adapters.tradehub import meta as meta_ad
from tradehub_core.seo_helper.adapters.tradehub import schema as schema_ad
from tradehub_core.seo_helper.core import cache as cache_

HEAD_TTL = 300
PAGE_FIELDS = [
	"name",
	"lang",
	"domain",
	"store",
	"title",
	"meta_description",
	"effective_canonical",
	"effective_robots",
	"publish_state",
	"data_version",
	"locale_cluster",
	"builder_page",
	"og_image",
	"route",
]


def _page_for_route(route: str, lang: str | None):
	route = "/" + (route or "").strip("/")
	if lang:
		row = frappe.db.get_value("SEO Page", {"route": route, "lang": lang}, PAGE_FIELDS, as_dict=True)
		if row:
			return row
	return frappe.db.get_value("SEO Page", {"route": route}, PAGE_FIELDS, as_dict=True)


def build_head_parts(page: dict) -> dict:
	"""{title, canonical, robots, metatags, extras_html, data_version} — adaptörler üzerinden."""
	site = meta_ad.site_url()
	canonical = page.get("effective_canonical") or f"{site}{page.get('route') or '/'}"
	robots = page.get("effective_robots") or "noindex,follow"
	seo = meta_ad.compose(
		{
			"title": page.get("title"),
			"description": page.get("meta_description"),
			"og_image": page.get("og_image"),
		},
		lang=page.get("lang") or "tr",
		route=canonical.replace(site, "") or "/",
		robots=robots,
	)
	seo["canonical"], seo["robots"] = canonical, robots
	metatags = {
		"description": seo.get("description") or "",
		"og:type": seo.get("og_type") or "website",
		"og:title": seo.get("og_title") or seo.get("title") or "",
		"og:description": seo.get("og_description") or seo.get("description") or "",
		"og:url": canonical,
		"og:image": seo.get("og_image") or "",
		"og:site_name": seo.get("site_name") or "",
		"twitter:card": "summary_large_image" if seo.get("og_image") else "summary",
	}
	extras = f'<meta name="robots" content="{robots}">'
	if page.get("locale_cluster"):
		extras += _hreflang_html(page["locale_cluster"])
	extras += schema_ad.to_script_tags(
		schema_ad.web_page(
			url=canonical,
			title=seo.get("title") or "",
			description=seo.get("description") or "",
			lang=page.get("lang") or "tr",
		)
	)
	return {
		"title": seo.get("title") or page.get("title") or "",
		"canonical": canonical,
		"robots": robots,
		"metatags": {k: v for k, v in metatags.items() if v},
		"extras_html": extras,
		"data_version": int(page.get("data_version") or 0),
	}


def _hreflang_html(cluster: str) -> str:
	"""Aynı kümedeki yayındaki SEO Page'lerden hreflang bağlantıları (14.2 Locale Cluster)."""
	site = meta_ad.site_url()
	rows = frappe.get_all(
		"SEO Page",
		filters={"locale_cluster": cluster, "publish_state": "published"},
		fields=["lang", "effective_canonical", "route"],
	)
	if len(rows) < 2:
		return ""
	out = ""
	for r in rows:
		out += f'<link rel="alternate" hreflang="{r.lang}" href="{r.effective_canonical or site + r.route}">'
	tr = next((r for r in rows if r.lang == "tr"), rows[0])
	out += f'<link rel="alternate" hreflang="x-default" href="{tr.effective_canonical or site + tr.route}">'
	return out


def head_for_route(route: str, lang: str | None = None) -> dict:
	"""{"status": 200|404|410, "parts": {...}} — cache'li; sürüm uyuşmazsa yeniden üretir."""
	page = _page_for_route(route, lang)
	if not page:
		return {"status": 404, "parts": None}
	if page.publish_state in ("suspended", "archived"):
		return {"status": 410, "parts": None, "data_version": int(page.data_version or 0)}
	k = cache_.key(
		"head", domain=page.domain or "*", lang=page.lang or "*", store=page.store or "*", ref=page.route
	)
	cached = cache_.get(k)
	if cached and cached.get("data_version") == int(page.data_version or 0):
		return {"status": 200, "parts": cached}
	parts = build_head_parts(page)
	cache_.set_(k, parts, ttl=HEAD_TTL)
	return {"status": 200, "parts": parts}


def update_website_context(context):
	"""Frappe `update_website_context` — Builder sayfası için head alanlarını tek elden belirler."""
	route = context.get("route") or context.get("path")
	if not route and getattr(frappe.local, "request", None):
		route = frappe.local.request.path
	if not route:
		return context
	try:
		out = head_for_route(route, getattr(frappe.local, "lang", None))
	except Exception:  # noqa: BLE001 — SEO çıktısı sayfayı düşürmez
		frappe.log_error(title="seo_helper head üretimi", message=frappe.get_traceback())
		return context
	if out["status"] != 200:
		if out["status"] == 410:
			context["disable_indexing"] = 1  # Builder zaten yayından kaldırdı (bridge published=0)
		return context
	p = out["parts"]
	context["title"] = p["title"]
	context["canonical_url"] = p["canonical"]
	context["disable_indexing"] = 0  # robots etiketi tek yerden (_head_html), çift etiket yok
	context["metatags"] = p["metatags"]
	context["_head_html"] = (context.get("_head_html") or "") + p["extras_html"]
	context["seo_data_version"] = p["data_version"]
	return context
