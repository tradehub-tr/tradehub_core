"""Katalog aynası — Listing/Category/Brand → SEO Entity (14.2 "SEO Entity").

tradehub_core kendi cache/sitemap düşürmesini yapıyor (hooks); burada yalnız SEO Entity
kaydı güncellenir ve `data_version` artar. Ağır iş yok; on_update içinde tek upsert.
"""

from __future__ import annotations

import frappe

ENTITY_TYPES = {
	"Listing": "listing",
	"Product Category": "category",
	"Brand": "brand",
	"Admin Seller Profile": "seller",
}


def upsert_entity(
	ref_doctype: str,
	ref_name: str,
	*,
	store: str | None,
	canonical_path: str,
	indexable: bool,
	domain: str | None = None,
) -> str:
	name = frappe.db.get_value("SEO Entity", {"ref_doctype": ref_doctype, "ref_name": ref_name}, "name")
	doc = frappe.get_doc("SEO Entity", name) if name else frappe.new_doc("SEO Entity")
	doc.update(
		{
			"entity_type": ENTITY_TYPES.get(ref_doctype, "page"),
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"store": store,
			"domain": domain or frappe.db.get_value("SEO Domain", {"is_primary": 1}, "name"),
			"canonical_path": canonical_path,
			"indexable": 1 if indexable else 0,
			"last_synced_at": frappe.utils.now_datetime(),
		}
	)
	doc.flags.ignore_permissions = True  # ayna; kaynak kaydın izni zaten uygulandı
	doc.save()
	frappe.db.sql(
		"UPDATE `tabSEO Entity` SET data_version = COALESCE(data_version,0)+1 WHERE name=%s", (doc.name,)
	)
	return doc.name


def on_listing_update(doc, method=None):
	try:
		from tradehub_core.api.listing import STOREFRONT_VISIBLE_STATUSES

		gorunur = bool(doc.get("is_visible")) and doc.status in STOREFRONT_VISIBLE_STATUSES
		slug = doc.get("route") or doc.get("slug") or doc.name
		upsert_entity(
			"Listing", doc.name, store=doc.seller_profile, canonical_path=f"/urun/{slug}", indexable=gorunur
		)
	except Exception:  # noqa: BLE001 — ayna hatası ürün kaydını düşürmez
		frappe.log_error(title="seo_helper Listing aynası", message=frappe.get_traceback())


def mirror_job(ref_doctype: str, ref_name: str, **_):
	doc = frappe.get_doc(ref_doctype, ref_name)
	if ref_doctype == "Listing":
		on_listing_update(doc)
	return {"mirrored": ref_name}
