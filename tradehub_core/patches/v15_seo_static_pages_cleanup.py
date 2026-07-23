"""NGX-1 hayalet path temizliği (idempotent).

static_pages_registry'den silinen 9 hayalet path'in seed edilmiş
Static Page SEO kayıtlarını siler ve /markalar kaydını /ureticiler'e taşır
(nginx'te /markalar → 301 /ureticiler). Hayalet kayıtlar sitemap'e 404 URL
sızdırır — "yalnız istoc.com indexlensin" hedefini GSC coverage'da zehirler.
"""

import frappe

GHOST_PATHS = [
	"/blog",
	"/kariyer",
	"/kurumsal-sorumluluk",
	"/izleme",
	"/haberler",
	"/ortakliklar",
	"/kargo-koruma",
	"/vergi",
	"/satici/dogrulama",
	"/uyelik",  # membership sayfası kaldırıldı (2026-07-23)
]


def execute():
	if not frappe.db.table_exists("Static Page SEO"):
		return

	for path in GHOST_PATHS:
		name = frappe.db.get_value("Static Page SEO", {"page_path": path})
		if name:
			frappe.delete_doc("Static Page SEO", name, ignore_permissions=True, force=True)

	# /markalar → /ureticiler taşıma (hedef kayıt zaten varsa eskiyi sil).
	# autoname=field:page_path → doc adı da path'tir; rename_doc + field update.
	markalar = frappe.db.get_value("Static Page SEO", {"page_path": "/markalar"})
	if markalar:
		if frappe.db.get_value("Static Page SEO", {"page_path": "/ureticiler"}):
			frappe.delete_doc("Static Page SEO", markalar, ignore_permissions=True, force=True)
		else:
			frappe.rename_doc("Static Page SEO", markalar, "/ureticiler", force=True)
			frappe.db.set_value("Static Page SEO", "/ureticiler", "page_path", "/ureticiler")

	frappe.db.commit()
