"""`storefront_visible` denormalize flag'ini backfill et + composite index'ler ekle.

Listing.validate() artık `storefront_visible = 1 if (is_visible AND status
storefront-görünür) else 0` hesaplıyor, ama bu yalnızca YENİ save'lerde çalışır.
Bu patch mevcut satırları tek seferde doldurur.

Ayrıca (storefront_visible, <sort>) composite index'lerini ekler: tek-eşitlik
`storefront_visible=1` prefix'i + sıralama kolonu → filesort'suz, index-ordered
tarama. (add_storefront_global_sort_indexes'teki (is_visible, status, <sort>)
index'leri 2-değerli status IN yüzünden filesort'u tam kaldıramıyordu.)

[post_model_sync]: DocType field schema sync'inden SONRA çalışır ki kolon var olsun.
Idempotent: UPDATE tekrar çalışsa da aynı sonucu verir; add_index no-op'tur.
"""

import frappe

from tradehub_core.api.listing import STOREFRONT_VISIBLE_STATUSES

# storefront-görünür sıralama alanları — add_storefront_global_sort_indexes ile aynı küme.
_SORT_COLUMNS = (
	"modified",
	"creation",
	"selling_price_base",
	"order_count",
	"average_rating",
	"discount_percentage",
	"view_count",
)


def execute():
	# Kolon henüz yoksa (schema sync sırası beklenmedik şekilde bozulduysa) sessiz çık.
	if not frappe.db.has_column("Listing", "storefront_visible"):
		return

	# Backfill — placeholder'lar yalnızca %s, değer enjeksiyonu yok (status'lar sabit).
	placeholders = ", ".join(["%s"] * len(STOREFRONT_VISIBLE_STATUSES))
	frappe.db.sql(
		f"""
		UPDATE `tabListing`
		SET storefront_visible = IF(is_visible = 1 AND status IN ({placeholders}), 1, 0)
		""",
		tuple(STOREFRONT_VISIBLE_STATUSES),
	)

	# (storefront_visible, <sort>) composite index'ler
	for sort_col in _SORT_COLUMNS:
		frappe.db.add_index(
			"Listing",
			["storefront_visible", sort_col],
			index_name=f"idx_listing_sfv_{sort_col}",
		)

	frappe.db.commit()
