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
		doc.meta_title = entry["title"]
		doc.meta_description = ""
		doc.noindex = 0 if entry.get("indexable_default") else 1
		doc.sitemap_priority = float(entry.get("sitemap_priority", "0.5"))
		doc.sitemap_changefreq = entry.get("sitemap_changefreq", "monthly")
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created += 1
	frappe.db.commit()
	return f"Static Page SEO seed: {created} oluşturuldu, {skipped} zaten vardı"
