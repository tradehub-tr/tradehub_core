"""Ana görseli boş ama ek görseli olan listing'lere primary_image ata.

Kart/sepet/liste primary_image kullanır; satıcı görseli yalnızca "ek görsel"
olarak eklediğinde primary_image boş kalıyor ve ürün fotoğrafsız görünüyordu.
Bu patch mevcut kayıtlar için ilk ek görseli (sort_order, sonra idx) ana
görsel yapar. Yeni kayıtlarda Listing.validate._ensure_primary_image halleder.

İdempotent: primary_image zaten dolu olanlar atlanır.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	listings = frappe.get_all(
		"Listing",
		filters={"primary_image": ["in", [None, ""]]},
		pluck="name",
	)
	if not listings:
		return {"updated": []}

	imgs = frappe.get_all(
		"Listing Image",
		filters={"parenttype": "Listing", "parent": ["in", listings]},
		fields=["parent", "image"],
		order_by="parent asc, sort_order asc, idx asc",
	)
	first_by_parent: dict[str, str] = {}
	for r in imgs:
		if r.parent not in first_by_parent and r.image:
			first_by_parent[r.parent] = r.image

	for name, image in first_by_parent.items():
		frappe.db.set_value("Listing", name, "primary_image", image, update_modified=False)

	frappe.db.commit()

	# Storefront liste/kart cache'ini temizle ki fotoğraflar hemen görünsün.
	try:
		from tradehub_core.api.listing import invalidate_listing_cache

		invalidate_listing_cache()
	except Exception:
		frappe.log_error("invalidate_listing_cache failed", "v15_9_2_backfill_primary_image")

	return {"updated": list(first_by_parent.keys())}
