"""
Admin panel SEO editör endpoint'leri (whitelist + role check).

3 endpoint:
  - check_slug_unique(doctype, slug, exclude_name) → çakışma kontrolü
  - get_seo_fields(doctype, name) → mevcut SEO field değerleri
  - save_seo_fields(doctype, name, fields) → permission check + doc.save()
"""

import json
from collections.abc import Callable

import frappe
from frappe import _

# Doctype → editable SEO field listesi (Faz 7: _en fields dahil)
SEO_FIELDS_BY_DOCTYPE = {
	"Listing": [
		"slug",
		"meta_title",
		"meta_description",
		"focus_keyword",
		"noindex",
		"og_image",
		"og_title_override",
		"og_description_override",
		"canonical_url_override",
		"robots_directive_override",
		# Ana görsel alt metni (Faz 4b sonrası): SEO sekmesinden düzenlenebilir
		"primary_image_alt",
		# Faz 7 EN fields
		"slug_en",
		"meta_title_en",
		"meta_description_en",
		"og_title_override_en",
		"og_description_override_en",
	],
	"Product Category": [
		"url_slug",
		"meta_title",
		"meta_description",
		"focus_keyword",
		"noindex",
		"og_image",
		"og_title_override",
		"og_description_override",
		"canonical_url_override",
		"robots_directive_override",
		"sitemap_priority",
		"sitemap_changefreq",
		# Faz 7 EN fields
		"url_slug_en",
		"meta_title_en",
		"meta_description_en",
		"og_title_override_en",
		"og_description_override_en",
	],
	"Brand": [
		"slug",
		"meta_title",
		"meta_description",
		"focus_keyword",
		"noindex",
		"og_image",
		"og_title_override",
		"og_description_override",
		"canonical_url_override",
		"robots_directive_override",
		# Faz 7 EN fields
		"slug_en",
		"meta_title_en",
		"meta_description_en",
		"og_title_override_en",
		"og_description_override_en",
	],
	"Admin Seller Profile": [
		"slug",
		"meta_title",
		"meta_description",
		"focus_keyword",
		"noindex",
		"og_image",
		"og_title_override",
		"og_description_override",
		"canonical_url_override",
		"robots_directive_override",
		# Faz 7 EN fields
		"slug_en",
		"meta_title_en",
		"meta_description_en",
		"og_title_override_en",
		"og_description_override_en",
	],
	"Static Page SEO": [
		"page_title",
		"meta_title",
		"meta_description",
		"focus_keyword",
		"noindex",
		"og_image",
		"og_title_override",
		"og_description_override",
		"canonical_url_override",
		"robots_directive_override",
		"sitemap_priority",
		"sitemap_changefreq",
		# Faz 7 EN fields
		"meta_title_en",
		"meta_description_en",
		"og_title_override_en",
		"og_description_override_en",
	],
}

ALLOWED_ROLES = ["System Manager", "Marketplace Admin", "Marketplace Seller"]


# Pure helper ----------------------------------------------------------------


def _suggest_unique_slug(
	base: str,
	is_taken: Callable[[str], bool],
	max_tries: int = 100,
) -> str | None:
	"""Çakışan slug için unique öneri üret. Pure: is_taken DI."""
	if not is_taken(base):
		return base
	for i in range(2, max_tries + 1):
		candidate = f"{base}-{i}"
		if not is_taken(candidate):
			return candidate
	return None


def _slug_field_for(doctype: str) -> str:
	"""Doctype → slug field adı."""
	return "url_slug" if doctype == "Product Category" else "slug"


def _auto_create_static_page_seo(path: str) -> None:
	"""Registry'de tanımlı statik sayfa için SEO kaydını lazy oluşturur."""
	from tradehub_core.seo.static_pages_registry import find_entry

	entry = find_entry(path)
	if not entry:
		frappe.throw(_("Bilinmeyen statik sayfa yolu: {0}").format(path))
	doc = frappe.new_doc("Static Page SEO")
	doc.page_path = entry["path"]
	doc.page_title = entry["title"]
	doc.lang = "tr"
	doc.meta_title = entry["title"]
	doc.meta_description = ""
	doc.noindex = 0 if entry.get("indexable_default") else 1
	doc.sitemap_priority = float(entry.get("sitemap_priority", "0.5"))
	doc.sitemap_changefreq = entry.get("sitemap_changefreq", "monthly")
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	frappe.db.commit()


# Whitelist endpoint'ler -----------------------------------------------------


@frappe.whitelist()
def check_slug_unique(doctype: str, slug: str, exclude_name: str = "") -> dict:
	"""Slug çakışma kontrolü. Returns {unique, suggestion}."""
	if doctype not in SEO_FIELDS_BY_DOCTYPE:
		frappe.throw(_("Geçersiz doctype: {0}").format(doctype))

	if not slug:
		return {"unique": False, "suggestion": None}

	slug_field = _slug_field_for(doctype)

	def _is_taken(s: str) -> bool:
		filters = {slug_field: s}
		if exclude_name:
			filters["name"] = ["!=", exclude_name]
		return bool(frappe.db.exists(doctype, filters))

	if not _is_taken(slug):
		return {"unique": True, "suggestion": None}

	suggestion = _suggest_unique_slug(slug, _is_taken)
	return {"unique": False, "suggestion": suggestion}


@frappe.whitelist()
def get_seo_fields(doctype: str, name: str) -> dict:
	"""SEO field değerlerini doctype kaydından çek.

	Static Page SEO için kayıt yoksa registry'den otomatik oluşturur
	(lazy seed — deploy'da seed script'ine gerek kalmaz).
	"""
	if doctype not in SEO_FIELDS_BY_DOCTYPE:
		frappe.throw(_("Geçersiz doctype: {0}").format(doctype))

	frappe.only_for(ALLOWED_ROLES)

	if doctype == "Static Page SEO" and not frappe.db.exists(doctype, name):
		_auto_create_static_page_seo(name)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")

	fields = SEO_FIELDS_BY_DOCTYPE[doctype]
	return {f: doc.get(f) for f in fields}


@frappe.whitelist()
def list_redirects(enabled_only: int = 1) -> list[dict]:
	"""Tüm SEO Redirect kayıtlarını liste."""
	frappe.only_for(ALLOWED_ROLES)
	filters = {}
	if int(enabled_only):
		filters["enabled"] = 1
	return frappe.get_all(
		"SEO Redirect",
		filters=filters,
		fields=[
			"name",
			"source_path",
			"target_path",
			"match_type",
			"status_code",
			"enabled",
			"hit_count",
			"last_hit_at",
		],
		order_by="hit_count desc",
		limit_page_length=500,
	)


@frappe.whitelist()
def list_404s(resolved: int = 0, limit: int = 100) -> list[dict]:
	"""En sık 404'leri liste (default: çözülmemiş)."""
	frappe.only_for(ALLOWED_ROLES)
	return frappe.get_all(
		"SEO 404 Log",
		filters={"resolved": int(resolved)},
		fields=["name", "path", "hit_count", "first_seen_at", "last_hit_at", "last_referer", "resolved"],
		order_by="hit_count desc",
		limit_page_length=int(limit),
	)


@frappe.whitelist()
def add_redirect_from_404(log_name: str, target_path: str, status_code: str = "301") -> dict:
	"""404 log → SEO Redirect oluştur + log'u resolved işaretle."""
	frappe.only_for(ALLOWED_ROLES)

	log = frappe.get_doc("SEO 404 Log", log_name)

	# Mevcut redirect var mı?
	existing = frappe.db.exists("SEO Redirect", {"source_path": log.path})
	if existing:
		log.resolved = 1
		log.save(ignore_permissions=True)
		frappe.db.commit()
		return {"ok": True, "redirect": existing, "log_resolved": True}

	redirect = frappe.new_doc("SEO Redirect")
	redirect.source_path = log.path
	redirect.target_path = target_path
	redirect.status_code = status_code
	redirect.match_type = "exact"
	redirect.enabled = 1
	redirect.insert(ignore_permissions=True)

	log.resolved = 1
	log.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "redirect": redirect.name, "log_resolved": True}


@frappe.whitelist(allow_guest=True)
def handle_404_endpoint(path: str = ""):
	"""Nginx error_page'den çağrılan wrapper.

	tradehub_core.seo.redirect_resolver.handle_404 ile aynı, sadece
	endpoint path'i tutarlı (api/seo_admin)."""
	from tradehub_core.seo.redirect_resolver import handle_404

	return handle_404(path=path)


@frappe.whitelist()
def save_seo_fields(doctype: str, name: str, fields: str | dict) -> dict:
	"""SEO field'larını güncelle. doc.save() tetiklenir → hook'lar çalışır."""
	if doctype not in SEO_FIELDS_BY_DOCTYPE:
		frappe.throw(_("Geçersiz doctype: {0}").format(doctype))

	frappe.only_for(ALLOWED_ROLES)

	if isinstance(fields, str):
		fields = json.loads(fields)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")

	allowed_fields = SEO_FIELDS_BY_DOCTYPE[doctype]
	for key, value in fields.items():
		if key in allowed_fields:
			doc.set(key, value)

	doc.save()
	frappe.db.commit()

	return {"ok": True, "name": doc.name}


@frappe.whitelist()
def list_static_pages() -> list[dict]:
	"""Admin paneli için statik sayfa listesi (Faz 4c).

	Registry + Static Page SEO DB kayıtlarından override durumu döner.
	Her satır: {path, title, indexable_default, override_exists,
		meta_title, meta_description, noindex}"""
	from tradehub_core.seo.static_pages_registry import STATIC_PAGES

	frappe.only_for(ALLOWED_ROLES)

	overrides = {
		row["name"]: row
		for row in frappe.get_all(
			"Static Page SEO",
			fields=["name", "page_path", "meta_title", "meta_description", "noindex"],
			limit_page_length=0,
		)
	}

	result = []
	for entry in STATIC_PAGES:
		ov = overrides.get(entry["path"])
		default_noindex = 0 if entry["indexable_default"] else 1
		result.append(
			{
				"path": entry["path"],
				"title": entry["title"],
				"indexable_default": entry["indexable_default"],
				"override_exists": ov is not None,
				"meta_title": (ov.get("meta_title") if ov else "") or "",
				"meta_description": (ov.get("meta_description") if ov else "") or "",
				"noindex": (ov.get("noindex") if ov else default_noindex),
			}
		)
	return result
