"""Yönlendirme adaptörü — `SEO Redirect` (tradehub_core) okunur/yazılır; bizim `SEO Redirect Rule`
üst modeldir. Kaynak-hedef eşlemesi tek yönlü: Rule → tradehub `SEO Redirect` kaydı (storefront
router onu okuyor); tersine okuma `find_matching`."""

from __future__ import annotations

import frappe


def find_matching(path: str) -> dict | None:
	from tradehub_core.seo.redirect_resolver import _get_active_redirects, find_matching_redirect

	return find_matching_redirect(path, _get_active_redirects())


def upsert_storefront_redirect(
	source_path: str, target_path: str, status_code: int = 301, active: bool = True
) -> str:
	"""tradehub `SEO Redirect` kaydını aynala (storefront ve Cloudflare bu tabloyu kullanır)."""
	name = frappe.db.get_value("SEO Redirect", {"source_path": source_path}, "name")
	if name:
		doc = frappe.get_doc("SEO Redirect", name)
	else:
		doc = frappe.new_doc("SEO Redirect")
		doc.source_path = source_path
	for f, v in (
		("target_path", target_path),
		("status_code", str(status_code)),
		("is_active", 1 if active else 0),
	):
		if doc.meta.has_field(f):
			doc.set(f, v)
	doc.flags.ignore_permissions = True  # sistem aynası; kaynak Rule izinle yazıldı
	doc.save()
	return doc.name


def remove_storefront_redirect(source_path: str) -> None:
	name = frappe.db.get_value("SEO Redirect", {"source_path": source_path}, "name")
	if name:
		frappe.delete_doc("SEO Redirect", name, ignore_permissions=True, force=True)
