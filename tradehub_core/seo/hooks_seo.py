"""
SEO ile ilgili doc_event hook'ları.

- `auto_generate_slug(doc, method=None)`: before_save hook — slug boşsa
  title_field'den otomatik üretir, çakışmada suffix ekler.
- `validate_seo_lengths(doc, method=None)`: validate hook — meta_title/
  meta_description sınır aşıyorsa warn (throw değil).

Pure yardımcı fonksiyonlar (`_build_slug`, `_check_seo_lengths`) Frappe
runtime'a bağımlı değildir; standalone unittest ile koşulabilir.
"""

from collections.abc import Callable

from tradehub_core.seo.slugify import slugify_tr

META_TITLE_LIMIT = 70
META_DESCRIPTION_LIMIT = 160


def _build_slug(title_source: str, fallback_name: str, slug_exists: Callable[[str], bool]) -> str:
	"""Slug üret + çakışmada `-<son 6 char of name>` suffix ekle.

	Frappe runtime'a bağımlı değil — `slug_exists` callable parametresi ile
	dependency injection."""
	# Önce title_source'tan dene, slugify sonrası boş kalırsa fallback_name'i dene
	base = slugify_tr(title_source or "")
	if not base:
		base = slugify_tr(fallback_name or "")
	if not base:
		return ""
	if slug_exists(base):
		suffix = (fallback_name or "")[-6:] or "x"
		return f"{base}-{suffix}"
	return base


def _check_seo_lengths(meta_title: str, meta_description: str) -> list[str]:
	"""Sınır aşan field'ları liste olarak döner; throw yapmaz."""
	warnings: list[str] = []
	title = (meta_title or "").strip()
	if len(title) > META_TITLE_LIMIT:
		warnings.append(f"meta_title {len(title)} karakter (önerilen ≤ {META_TITLE_LIMIT})")
	desc = (meta_description or "").strip()
	if len(desc) > META_DESCRIPTION_LIMIT:
		warnings.append(f"meta_description {len(desc)} karakter (önerilen ≤ {META_DESCRIPTION_LIMIT})")
	return warnings


def auto_generate_slug(doc, method=None):
	"""before_save: slug boşsa title_field'den üretir, unique kontrol yapar."""
	if doc.get("slug"):
		return

	# Frappe runtime gerekli: title_field'i doc.meta üzerinden çek
	import frappe

	title_field = (getattr(doc, "meta", None) and doc.meta.get("title_field")) or "name"
	source = doc.get(title_field) or doc.get("name") or ""

	def _exists(slug: str) -> bool:
		return bool(
			frappe.db.exists(
				doc.doctype,
				{
					"slug": slug,
					"name": ["!=", doc.name or ""],
				},
			)
		)

	doc.slug = _build_slug(source, doc.name, _exists)


def validate_seo_lengths(doc, method=None):
	"""validate: meta_title/meta_description sınır aşıyorsa warn (throw etmez)."""
	import frappe

	warnings = _check_seo_lengths(doc.get("meta_title"), doc.get("meta_description"))
	if not warnings:
		return

	frappe.logger().warning(f"[SEO] {doc.doctype} {doc.name or '<new>'}: " + ", ".join(warnings))


# ── Cloudflare cache invalidation ─────────────────────────────────────────

_DOCTYPE_URL_PREFIX_MAP = {
	"Listing": "/urun",
	"Product Category": "/kategori",
	"Brand": "/marka",
	"Admin Seller Profile": "/magaza",
	"Static Page SEO": "",
}

_DOCTYPE_SLUG_FIELD_MAP = {
	"Listing": "slug",
	"Product Category": "url_slug",
	"Brand": "slug",
	"Admin Seller Profile": "slug",
	"Static Page SEO": "page_path",
}


def invalidate_url_cache(doc, method=None):
	"""on_update hook: bu kaydın canonical URL'ini Cloudflare cache'ten temizle.

	Cloudflare credential yoksa sessizce no-op (dev ortamı güvenli)."""
	from tradehub_core.seo.cloudflare_api import purge_urls

	if doc.doctype not in _DOCTYPE_URL_PREFIX_MAP:
		return
	prefix = _DOCTYPE_URL_PREFIX_MAP[doc.doctype]
	slug_field = _DOCTYPE_SLUG_FIELD_MAP.get(doc.doctype)
	if not slug_field:
		return

	slug = doc.get(slug_field)
	if not slug:
		return

	from tradehub_core.seo.site_url import storefront_url

	site_url = storefront_url()
	# Static Page SEO: page_path zaten / ile başlar; prefix boş → site_url + slug
	if prefix:
		canonical = f"{site_url}{prefix}/{slug}"
	else:
		canonical = f"{site_url}{slug if slug.startswith('/') else '/' + slug}"
	purge_urls([canonical])


# ── Sitemap dirty flag invalidation (Faz 2) ────────────────────────────────

_SITEMAP_TRACKED_DOCTYPES = {
	"Listing",
	"Product Category",
	"Brand",
	"Admin Seller Profile",
	"Static Page SEO",
}


def invalidate_sitemap_for(doc, method=None):
	"""on_update hook: bu doctype için sitemap'i dirty olarak işaretle.

	Cron çalıştığında dirty olan tip için sitemap yeniden üretilir."""
	if doc.doctype not in _SITEMAP_TRACKED_DOCTYPES:
		return

	from tradehub_core.seo.sitemap_cache import get_default_cache

	cache = get_default_cache()
	cache.mark_dirty(doc.doctype)
