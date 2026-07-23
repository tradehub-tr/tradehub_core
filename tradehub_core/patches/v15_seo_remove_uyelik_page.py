"""/uyelik (Üyelik Programı) statik sayfası kaldırıldı (idempotent).

Sayfa frontend'den ve static_pages_registry'den silindi; seed edilmiş
Static Page SEO kaydı kalırsa sitemap'e 404 URL sızdırır.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Static Page SEO"):
		return

	name = frappe.db.get_value("Static Page SEO", {"page_path": "/uyelik"})
	if name:
		frappe.delete_doc("Static Page SEO", name, ignore_permissions=True, force=True)
