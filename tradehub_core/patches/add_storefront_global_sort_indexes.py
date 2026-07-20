"""Kategori-siz storefront yolları için composite index'ler ekle.

Ana listeleme / "Tüm Ürünler" / global sıralama sorguları şu biçimde çalışıyor:

    WHERE is_visible = 1 AND status IN ('Active', 'Out of Stock')
    ORDER BY <sort> DESC LIMIT n

Mevcut idx_listing_category_* index'lerinin tümü `product_category` prefix'i ile
başladığı için bu kategori-siz sorgular HİÇBİRİNİ kullanamıyor → EXPLAIN
`type=ALL` (full table scan) + `Using filesort` gösteriyor. Binlerce/on binlerce
listing'de her istek tüm tabloyu tarayıp bellekte sıralar.

Bu patch (is_visible, status, <sort>) composite index'lerini ekler: leading
(is_visible, status) filtresi index'ten karşılanır, üçüncü kolon sıralama
alanıdır. is_visible önce çünkü daima tekil eşitlik (=1); status 2-değerli IN.

Not: 2-değerli `status IN(...)` üçüncü kolonun sıralama garantisini index'ten
tam vermeyebilir (bazı sorgularda filesort kalabilir), ama index yine de
examined-rows'u tüm katalogdan yalnızca görünür alt kümeye indirir — büyük
kazanç. Filesort'u tamamen öldüren denormalize `storefront_visible` flag'i
ayrı bir P1 patch'inde ele alınacak.

Idempotent: frappe.db.add_index mevcut index'te no-op'tur.
"""

import frappe


def execute():
	# Varsayılan yol: modified DESC (get_listings sort_by="modified")
	frappe.db.add_index(
		"Listing",
		["is_visible", "status", "modified"],
		index_name="idx_listing_vis_status_modified",
	)

	# newest → creation DESC
	frappe.db.add_index(
		"Listing",
		["is_visible", "status", "creation"],
		index_name="idx_listing_vis_status_creation",
	)

	# price_asc / price_desc → selling_price_base (sıralama base kolonundan yapılır,
	# kart selling_price gösterse de — bkz. api/listing.py sort mapping).
	frappe.db.add_index(
		"Listing",
		["is_visible", "status", "selling_price_base"],
		index_name="idx_listing_vis_status_price",
	)

	# orders → order_count DESC (global "en çok satan")
	frappe.db.add_index(
		"Listing",
		["is_visible", "status", "order_count"],
		index_name="idx_listing_vis_status_orders",
	)

	# rating → average_rating DESC
	frappe.db.add_index(
		"Listing",
		["is_visible", "status", "average_rating"],
		index_name="idx_listing_vis_status_rating",
	)

	# discount → discount_percentage DESC (Top Deals kategori-siz)
	frappe.db.add_index(
		"Listing",
		["is_visible", "status", "discount_percentage"],
		index_name="idx_listing_vis_status_discount",
	)

	# views → view_count DESC
	frappe.db.add_index(
		"Listing",
		["is_visible", "status", "view_count"],
		index_name="idx_listing_vis_status_views",
	)

	frappe.db.commit()
