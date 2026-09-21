"""
Pretty URL → Frappe doctype kaydı → meta enjeksiyonlu HTML response.

Whitelist endpoint'leri (Nginx tarafından çağrılır):
  - render_listing(slug)   → /urun/<slug>
  - render_category(slug)  → /kategori/<slug>
  - render_brand(slug)     → /marka/<slug>
  - render_seller(slug)    → /magaza/<slug>
  - render_media_watch(slug) → /medya/v/<slug> (bilinmeyen eski slug → 301)

Storefront HTML template'leri Frappe container'ında volume mount ile
erişilebilir: `site_config.storefront_dist_path` ile path konfigüre edilir
(default: `/storefront`). Template bulunamazsa minimal inline fallback
HTML üretilir — yine de meta tag'ler tam dolu olur.
"""

import os
from typing import TYPE_CHECKING

from tradehub_core.seo import meta_builder, seo_html_injector

if TYPE_CHECKING:
	from werkzeug.wrappers import Response

DEFAULT_STOREFRONT_DIST = "/storefront"

# Doctype → storefront HTML template eşlemesi (Vite multi-page entry path'leri)
TEMPLATE_MAP = {
	"Listing": "pages/product-detail.html",
	"Product Category": "pages/category-detail.html",
	"Brand": "pages/brand.html",
	"Admin Seller Profile": "pages/seller/seller-storefront.html",
}

# Doctype → slug taşıyıcı field eşlemesi. Frontend bu field'ın değerini URL
# slug olarak gönderir; backend DB sorgusu da bu field üzerinde yapılır.
# - Admin Seller Profile'da `slug` kolonu yok; gerçek taşıyıcı `seller_code`
#   (örn. "DEMO-001"). API endpoint'leri response'ta `seller.slug = seller_code`
#   ile yumuşak alias üretir, ama DB lookup için asıl kolon adı zorunlu.
SLUG_FIELD_MAP = {
	"Listing": "slug",
	"Product Category": "url_slug",
	"Brand": "slug",
	"Admin Seller Profile": "seller_code",
}


# Pure helpers ---------------------------------------------------------------


def _minimal_fallback_html() -> str:
	"""Storefront template bulunamadığında kullanılan en küçük HTML iskeleti.

	`<!-- {{__SEO_HEAD__}} -->` placeholder'ı dolacak; gerçek storefront
	deploy edildiğinde bu fallback devreye girmez.
	"""
	return (
		"<!doctype html>\n"
		'<html lang="tr"><head>\n'
		'<meta charset="utf-8">\n'
		'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
		f"{seo_html_injector.PLACEHOLDER}\n"
		"</head><body>\n"
		"<noscript>JavaScript gerekli.</noscript>\n"
		"</body></html>"
	)


def _build_404_seo(site_url: str, site_name: str = "iStoc") -> dict:
	"""404 sayfası için SEO payload — noindex zorunlu."""
	return {
		"title": f"Sayfa Bulunamadı | {site_name}",
		"description": "Aradığınız sayfa bulunamadı.",
		"canonical": "",
		"robots": "noindex,nofollow",
		"og_type": "website",
		"og_title": "Sayfa Bulunamadı",
		"og_description": "",
		"og_image": "",
		"og_url": "",
		"site_name": site_name,
		"twitter_handle": "",
		"json_ld": [],
	}


# Frappe-aware helpers -------------------------------------------------------


def _storefront_dist_path() -> str:
	"""site_config.storefront_dist_path veya default `/storefront`."""
	import frappe

	cfg = frappe.get_site_config() or {}
	return cfg.get("storefront_dist_path") or DEFAULT_STOREFRONT_DIST


def _read_template(template_relpath: str) -> str:
	"""Storefront dist altından template oku; bulunmazsa minimal fallback."""
	dist = _storefront_dist_path()
	full = os.path.join(dist, template_relpath)
	if os.path.exists(full):
		try:
			with open(full, encoding="utf-8") as f:
				return f.read()
		except OSError:
			pass
	return _minimal_fallback_html()


def _find_record_by_slug(doctype: str, slug: str):
	"""Slug'a göre doctype kaydını bul; yoksa None döner."""
	import frappe

	slug_field = SLUG_FIELD_MAP.get(doctype, "slug")
	name = frappe.db.get_value(doctype, {slug_field: slug}, "name")
	if not name:
		return None
	# Tüm field'larla doc nesnesi
	return frappe.get_doc(doctype, name)


def _html_response(html: str, status_code: int = 200, cdn_cache_seconds: int = 300):
	"""HTML string'i Werkzeug Response olarak sarıp döner.

	Frappe whitelist endpoint string return ederse JSON ile sarar; Response
	objesi return edersek doğrudan body olarak yazar.

	Cache stratejisi: CDN (Cloudflare) ``s-maxage`` ile cache'ler ve admin
	değişikliğinde purge edilir. Browser ``max-age=0`` ile her zaman CDN'e
	sorar → admin değişikliği anında yansır."""
	from werkzeug.wrappers import Response

	response = Response(html, status=status_code, mimetype="text/html")
	if status_code == 200 and cdn_cache_seconds > 0:
		response.headers["Cache-Control"] = (
			f"public, s-maxage={cdn_cache_seconds}, max-age=0, must-revalidate"
		)
	else:
		response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
	return response


def _build_response_html(seo: dict, template_relpath: str) -> str:
	"""Storefront HTML'i oku + SEO meta enjekte et."""
	html = _read_template(template_relpath)
	return seo_html_injector.inject_meta_into_html(html, seo)


def _render_404_response():
	from tradehub_core.seo.site_url import storefront_url

	seo = _build_404_seo(storefront_url())
	html = _read_template("404.html")
	rendered = seo_html_injector.inject_meta_into_html(html, seo)
	return _html_response(rendered, status_code=404, cdn_cache_seconds=0)


def _render_for(doctype: str, slug: str, builder_fn, lang: str = "tr"):
	"""Tüm doctype'lar için ortak render flow. Werkzeug Response döner."""

	record = _find_record_by_slug(doctype, slug)
	if not record:
		return _render_404_response()

	seo = builder_fn(record.as_dict(), lang=lang)
	template = TEMPLATE_MAP[doctype]
	html = _build_response_html(seo, template)
	return _html_response(html, status_code=200, cdn_cache_seconds=300)


# Whitelist endpoints --------------------------------------------------------


def render_listing(slug: str, lang: str = "tr") -> str:
	"""GET /urun/<slug> → HTML response with meta'lar."""
	return _render_for("Listing", slug, meta_builder.build_for_listing, lang=lang)


def render_category(slug: str, lang: str = "tr") -> str:
	"""GET /kategori/<slug>."""
	return _render_for("Product Category", slug, meta_builder.build_for_category, lang=lang)


def render_brand(slug: str, lang: str = "tr") -> str:
	"""GET /marka/<slug>."""
	return _render_for("Brand", slug, meta_builder.build_for_brand, lang=lang)


def render_seller(slug: str, lang: str = "tr") -> str:
	"""GET /magaza/<slug>."""
	return _render_for("Admin Seller Profile", slug, meta_builder.build_for_seller, lang=lang)


# Medya izleme sayfası ---------------------------------------------------


def _absolute_media_url(url: str, site_url: str) -> str:
	"""Göreli medya adresini (`/files/...`) mutlak URL'e çevirir.

	`schema_builder._absolute_url`/`meta_builder._absolute` ile aynı fikir —
	her modül kendi private mutlaklaştırıcısını taşır (repo deseni), burada
	yalnız `og:image`/`og:video` için kullanılıyor."""
	if not url:
		return ""
	if url.startswith(("http://", "https://")):
		return url
	return f"{site_url.rstrip('/')}/{url.lstrip('/')}"


def _watch_video_seo(data: dict, slug: str, site_url: str) -> dict:
	"""`media_public._watch_data` çıktısından `seo_head.html` payload'ı üretir.

	Poster HER ZAMAN `og:image`'e girer (indexlenemeyen video da sayfaya
	girer — yalnız aranmaz). JSON-LD `build_video_object`'in KENDİ kapısına
	bırakılır: poster ya da oynatılabilir kaynak (`content_url`/`embed_url`)
	yoksa fonksiyon `None` döner, burada tekrar aynı koşul İMPLEMENTE
	EDİLMEZ (Task 3 brief: "poster yoksa JSON-LD atlanır, sayfa yine döner").
	"""
	from tradehub_core.seo.schema_builder import SCHEMA_CONTEXT, build_video_object

	title = data.get("title") or ""
	description = data.get("description") or data.get("caption") or ""
	poster = data.get("posterUrl") or ""
	sources = data.get("sources") or []
	content_url = sources[0].get("src", "") if sources else ""
	content_type = sources[0].get("type", "") if sources else ""

	json_ld: list[dict] = []
	video_obj = build_video_object(
		{
			"title": title,
			"caption": data.get("caption") or "",
			"description": description,
			"poster_url": poster,
			"duration": data.get("durationSec") or 0,
			"transcript": data.get("transcript") or "",
		},
		site_url,
		content_url=content_url,
		upload_date=data.get("uploadDate") or "",
		seek_to_action_url_template=f"{site_url.rstrip('/')}/medya/v/{slug}?t={{seek_to_second_number}}",
	)
	if video_obj:
		json_ld.append({"@context": SCHEMA_CONTEXT, **video_obj})

	canonical = data.get("canonical") or ""
	og_video = _absolute_media_url(content_url, site_url)
	# og:video:secure_url yalnız SİTE https ise eklenir (Facebook/LinkedIn kartı
	# https sayfada http kaynak kabul etmiyor) — video'nun kendi URL'i zaten
	# `og_video` ile aynı mutlak adres, ikinci bir dönüşüm YOK.
	og_video_secure_url = og_video if og_video and site_url.startswith("https://") else ""
	return {
		"title": title,
		"description": description,
		"canonical": canonical,
		"robots": data.get("robots") or "noindex,follow",
		"og_type": "video.other",
		"og_title": title,
		"og_description": description,
		"og_image": _absolute_media_url(poster, site_url),
		"og_video": og_video,
		"og_video_type": content_type if og_video else "",
		"og_video_secure_url": og_video_secure_url,
		"og_url": canonical,
		"site_name": "",
		"twitter_handle": "",
		"json_ld": json_ld,
		"hreflang_links": [],
	}


def _find_media_redirect_target(source_path: str) -> str | None:
	"""Bilinmeyen `/medya/v/<slug>` için canlı `Media URL Redirect` hedefi.

	Süresi dolmuş satırlar döndürülmez — `media/redirect_renderer.py`'deki
	`expires_at` kontrolüyle AYNI kural (cron sonunda gerçek 404'e düşer)."""
	import frappe
	from frappe.utils import now_datetime

	return frappe.db.get_value(
		"Media URL Redirect",
		{"source_url": source_path, "expires_at": (">", now_datetime())},
		"target_url",
	)


#: 301 hedefi olarak kabul edilen TEK path ailesi. `Media URL Redirect.validate`
#: (`media_url_redirect.py`) normalde `target_url`'in host taşımadığını
#: doğruluyor, ama `watch_slug.change_slug` gibi sistem yazımları
#: `frappe.db.set_value` ile controller `validate()`'i BAYPAS EDER — ORM
#: invariant'ına TEK BAŞINA güvenilmez (görev denetimi bulgusu, düzeltme turu
#: 1). Burası ikinci, bağımsız savunma katmanı: DB'den ne gelirse gelsin,
#: bu iki prefix dışına Location header YAZILMAZ.
_SAFE_REDIRECT_TARGET_PREFIXES: tuple[str, ...] = ("/files/", "/medya/v/")


def _is_safe_redirect_target(target_url: str) -> bool:
	"""`target_url` bilinen güvenli path ailelerinden biri mi."""
	return target_url.startswith(_SAFE_REDIRECT_TARGET_PREFIXES)


def _redirect_response(target_url: str, site_url: str):
	"""Eski `/medya/v/<slug>` adresi için 301 Werkzeug Response.

	`media/redirect_renderer.py::MediaRedirectRenderer` sayfa-render zinciri
	(`RedirectPage`) üzerinden 301 üretiyor; bu fonksiyon whitelist uçundan
	doğrudan Response döndüğü için aynı 301 fikrini Werkzeug ile taşır."""
	from werkzeug.wrappers import Response

	if not target_url.startswith(("http://", "https://")):
		target_url = f"{site_url.rstrip('/')}{target_url}"
	response = Response(status=301)
	response.headers["Location"] = target_url
	response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
	return response


def render_media_watch(slug: str, lang: str = "tr") -> "Response":
	"""GET /medya/v/<slug> → izleme sayfası HTML + VideoObject/SeekToAction JSON-LD.

	Akış: `media_public._watch_data(slug)` (HTTP zarfı yok) → bulunamazsa
	(`frappe.DoesNotExistError`) bilinen eski slug mı diye `Media URL
	Redirect`'e bak (koordinatör ruling, Task 1 devri — `change_slug` 301
	köprüsü burada tüketilir) → orada da yoksa 404. Bulunan hedef
	`_is_safe_redirect_target` ile İKİNCİ KEZ doğrulanır (DB satırına elle/
	bypass yazılmış host'lu bir adres asla `Location`'a yansımaz).

	`lang` şu an kullanılmıyor (izleme sayfası tek dilli) ama diğer
	`render_*` fonksiyonlarıyla aynı imzayı taşır — Nginx/route katmanı
	hepsine aynı çağrı biçimiyle gidiyor."""
	import frappe

	from tradehub_core.api import media_public
	from tradehub_core.seo.site_url import storefront_url

	slug = (slug or "").strip()
	site_url = storefront_url()
	try:
		data = media_public._watch_data(slug)
	except frappe.DoesNotExistError:
		target = _find_media_redirect_target(f"/medya/v/{slug}")
		if target and _is_safe_redirect_target(target):
			return _redirect_response(target, site_url)
		return _render_404_response()

	seo = _watch_video_seo(data, slug, site_url)
	html = _build_response_html(seo, "pages/media-watch.html")
	return _html_response(html, status_code=200, cdn_cache_seconds=300)


def _resolve_static_page(path: str, lang: str = "tr") -> dict | None:
	"""STATIC_PAGES_REGISTRY'den entry döner; yoksa None. Faz 4c."""
	from tradehub_core.seo.static_pages_registry import find_entry

	return find_entry(path)


def _normalize_static_seo_language(lang: str) -> str:
	"""Public static-page metadata supports Turkish and English only."""
	return "en" if lang == "en" else "tr"


def _load_static_page_seo(path: str, lang: str = "tr") -> dict | None:
	"""Kayıtlı statik sayfa için SEO payload'ını yükle."""
	lang = _normalize_static_seo_language(lang)
	entry = _resolve_static_page(path, lang=lang)
	if not entry:
		return None

	import frappe

	override = {}
	if frappe.db.exists("Static Page SEO", path):
		override = frappe.get_doc("Static Page SEO", path).as_dict()

	if not override:
		override = {
			"page_path": path,
			"page_title": entry["title"],
			"meta_title": entry["title"],
			"meta_description": "",
			"noindex": 1,
		}
	return meta_builder.build_for_static_page(record=override, page_meta=entry, lang=lang)


def get_static_page_meta(path: str, lang: str = "tr") -> dict | None:
	"""Return public SEO metadata for a registered static storefront path."""
	return _load_static_page_seo(path, lang=lang)


def render_static_page(path: str, lang: str = "tr") -> str:
	"""GET /<static-path> → HTML response with SEO meta'lar (Faz 4c).

	Path STATIC_PAGES_REGISTRY'den lookup edilir; varsa HTML template
	okunup Static Page SEO override'larıyla render edilir; yoksa 404."""
	entry = _resolve_static_page(path, lang=lang)
	seo = _load_static_page_seo(path, lang=lang)
	if seo is None:
		return _render_404_response()

	html = _read_template(entry["html_path"])
	rendered = seo_html_injector.inject_meta_into_html(html, seo)
	return _html_response(rendered, status_code=200, cdn_cache_seconds=300)


# Frappe whitelist decorator'ları en sona — module-import sırasında frappe
# import'unu tetiklemesin (standalone unit test edilebilirlik için).
def _register_whitelists():
	"""Whitelist decorator'larını programatik olarak uygula.

	Modül Frappe runtime altında ilk import edildiğinde çağrılır.
	Standalone unittest'te _register_whitelists() çağrılmaz."""
	import frappe

	globals()["render_listing"] = frappe.whitelist(allow_guest=True)(render_listing)
	globals()["render_category"] = frappe.whitelist(allow_guest=True)(render_category)
	globals()["render_brand"] = frappe.whitelist(allow_guest=True)(render_brand)
	globals()["render_seller"] = frappe.whitelist(allow_guest=True)(render_seller)
	globals()["render_media_watch"] = frappe.whitelist(allow_guest=True)(render_media_watch)
	globals()["render_static_page"] = frappe.whitelist(allow_guest=True)(render_static_page)
	globals()["get_static_page_meta"] = frappe.whitelist(allow_guest=True)(get_static_page_meta)


try:
	import frappe  # noqa: F401

	_register_whitelists()
except ImportError:
	# Standalone (Frappe yokken) — whitelist atla.
	pass
