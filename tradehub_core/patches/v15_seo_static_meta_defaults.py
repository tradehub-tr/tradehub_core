"""Onaylı title/description varsayılanlarını mevcut Static Page SEO kayıtlarına uygular.

Idempotent; admin'in panelden girdiği değerlere dokunmaz
(kural: meta_title yalnız boş/kısa-registry-başlığıysa, meta_description yalnız boşsa doldurulur).
"""

import frappe


def execute():
	if not frappe.db.table_exists("Static Page SEO"):
		return
	from tradehub_core.setup.seed_static_pages import apply_meta_defaults

	frappe.logger().info(apply_meta_defaults())
