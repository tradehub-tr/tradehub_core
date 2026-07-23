"""4 yasal sayfayı noindex yap (kullanıcı kararı 2026-07-23, idempotent).

/kvkk, /iade-kosullari, /fikri-mulkiyet, /yasal-uyari: Google'a kapalı,
sitede erişilebilir kalır (yasal zorunluluk). Registry indexable_default'ları
False'a çekildi; bu patch seed edilmiş Static Page SEO kayıtlarını günceller —
sitemap üretimi noindex=0 filtresiyle bunları otomatik dışlar.
"""

import frappe

NOINDEX_PATHS = ["/kvkk", "/iade-kosullari", "/fikri-mulkiyet", "/yasal-uyari"]


def execute():
	if not frappe.db.table_exists("Static Page SEO"):
		return

	for path in NOINDEX_PATHS:
		name = frappe.db.get_value("Static Page SEO", {"page_path": path})
		if name:
			frappe.db.set_value("Static Page SEO", name, "noindex", 1)

	frappe.db.commit()
