"""Add composite index on (product_category, view_count) for the
Top Ranking "Most Popular" sort path.

The Top Ranking pill 'En Popüler' sorts by view_count, which is
incremented in get_listing_detail() on every product detail page hit.
With thousands of listings the GROUP BY product_category + AVG(view_count)
aggregate needs an index to stay fast — same shape as the order_count and
average_rating composites added in add_top_ranking_indexes.py.

Idempotent: frappe.db.add_index is a no-op if the index already exists.
"""
import frappe


def execute():
    frappe.db.add_index(
        "Listing",
        ["product_category", "view_count"],
        index_name="idx_listing_category_views",
    )
    frappe.db.commit()
