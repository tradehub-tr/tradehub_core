"""Statik sayfa SEO kayıtlarını seed eder (Faz 4c).

Çalıştırma:
  bench --site tradehub.localhost execute tradehub_core.setup.seed_static_pages.run

Idempotent: mevcut kayıtlar atlanır, sadece yeni path'ler eklenir.
"""

import frappe

from tradehub_core.seo.static_pages_registry import STATIC_PAGES


def run() -> str:
	created = 0
	skipped = 0
	for entry in STATIC_PAGES:
		path = entry["path"]
		if frappe.db.exists("Static Page SEO", path):
			skipped += 1
			continue
		doc = frappe.new_doc("Static Page SEO")
		doc.page_path = path
		doc.page_title = entry["title"]
		doc.lang = "tr"
		# Onaylı SEO seti registry'de varsayılan olarak durur (2026-07-23);
		# admin panelden istediği zaman ezebilir.
		doc.meta_title = entry.get("meta_title") or entry["title"]
		doc.meta_description = entry.get("meta_description", "")
		doc.noindex = 0 if entry.get("indexable_default") else 1
		doc.sitemap_priority = float(entry.get("sitemap_priority", "0.5"))
		doc.sitemap_changefreq = entry.get("sitemap_changefreq", "monthly")
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created += 1
	frappe.db.commit()
	return f"Static Page SEO seed: {created} oluşturuldu, {skipped} zaten vardı"


def apply_meta_defaults() -> str:
	"""MEVCUT kayıtlarda boş/registry-kısa-başlık kalmış meta alanlarını
	onaylı varsayılanlarla doldurur. Admin'in panelden girdiği değerlere
	DOKUNMAZ (meta_description doluysa ve meta_title kısa başlıktan
	farklıysa atlanır). Idempotent — patch ve bench execute ile çağrılır."""
	updated = 0
	for entry in STATIC_PAGES:
		default_title = entry.get("meta_title")
		default_desc = entry.get("meta_description", "")
		if not default_title:
			continue
		name = frappe.db.get_value("Static Page SEO", {"page_path": entry["path"]})
		if not name:
			continue
		row = frappe.db.get_value(
			"Static Page SEO", name, ["meta_title", "meta_description"], as_dict=True
		)
		changes = {}
		if not row.meta_title or row.meta_title == entry["title"]:
			changes["meta_title"] = default_title
		if not row.meta_description and default_desc:
			changes["meta_description"] = default_desc
		if changes:
			frappe.db.set_value("Static Page SEO", name, changes)
			updated += 1
	frappe.db.commit()
	return f"Static Page SEO meta varsayılanları: {updated} kayıt güncellendi"
