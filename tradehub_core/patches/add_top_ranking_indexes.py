"""Add composite indexes on Listing for the Top Ranking (best-sellers) queries.

The Top Ranking page filters listings by (product_category) and ranks by
order_count / review_count / average_rating. With thousands of listings the
naïve table scan becomes the bottleneck — a covering composite index lets
MySQL serve both the GROUP BY aggregate and the per-category preview query
without touching the heap.

Idempotent: frappe.db.add_index is a no-op when the index already exists.
"""

import frappe


def execute():
	# Composite index for the per-category best-seller preview query
	# (Phase 4 of get_top_ranking_grouped). Each category card runs:
	#   WHERE product_category = ? AND status='Active' AND is_visible=1
	#   ORDER BY order_count DESC, modified DESC LIMIT 3
	frappe.db.add_index(
		"Listing",
		["product_category", "order_count"],
		index_name="idx_listing_category_orders",
	)

	# Composite index for the "most popular" sort path (review_count metric).
	frappe.db.add_index(
		"Listing",
		["product_category", "review_count"],
		index_name="idx_listing_category_reviews",
	)

	# Composite index for the "best reviewed" sort path (average_rating metric).
	frappe.db.add_index(
		"Listing",
		["product_category", "average_rating"],
		index_name="idx_listing_category_rating",
	)

	frappe.db.commit()
