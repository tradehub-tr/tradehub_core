"""Assign every active Listing to a price quartile within its leaf category.

The `Listing.price_tier` column caches the bucket (Q1..Q4) so the Similar
and Substitute scorers can test tier equality with an O(1) string compare
instead of re-running quartile math per comparison.

Called by `tasks.rebuild_price_tiers` on a daily schedule, and can be
invoked manually:
    bench --site <site> execute \
        tradehub_core.recommendations.price_tier.recompute_all
"""
from __future__ import annotations

from typing import Iterable

import frappe


TIER_BUCKETS = ("Q1", "Q2", "Q3", "Q4")


def recompute_all() -> dict:
    """Recompute `price_tier` for every active listing, grouped by category.

    Returns a small stat dict suitable for logging.
    """
    categories = frappe.db.sql(
        """
        SELECT DISTINCT product_category
        FROM `tabListing`
        WHERE status = 'Active'
          AND is_visible = 1
          AND selling_price > 0
          AND product_category IS NOT NULL
        """,
        as_dict=True,
    )

    updated = 0
    skipped_small = 0
    for row in categories:
        category = row.get("product_category")
        if not category:
            continue
        n = _recompute_for_category(category)
        if n < 0:
            skipped_small += 1
        else:
            updated += n

    frappe.db.commit()
    return {"categories_processed": len(categories), "listings_updated": updated, "categories_skipped_small": skipped_small}


def _recompute_for_category(category: str) -> int:
    """Compute quartile thresholds within one category and write price_tier.

    Returns the number of listings updated, or -1 if the category has fewer
    than 4 active listings (quartiles would be degenerate — everyone falls
    into Q2 by default).
    """
    rows = frappe.db.sql(
        """
        SELECT name, selling_price
        FROM `tabListing`
        WHERE product_category = %s
          AND status = 'Active'
          AND is_visible = 1
          AND selling_price > 0
        ORDER BY selling_price ASC
        """,
        (category,),
        as_dict=True,
    )
    if len(rows) < 4:
        # Not enough data points — put all of them in Q2 as a safe default.
        for r in rows:
            frappe.db.set_value("Listing", r["name"], "price_tier", "Q2", update_modified=False)
        return -1

    thresholds = _quartile_thresholds([r["selling_price"] for r in rows])
    n = 0
    for r in rows:
        tier = _bucket(r["selling_price"], thresholds)
        frappe.db.set_value("Listing", r["name"], "price_tier", tier, update_modified=False)
        n += 1
    return n


def _quartile_thresholds(prices: list[float]) -> tuple[float, float, float]:
    """Return (q1_max, q2_max, q3_max) — sorted-based quartile cuts."""
    s = sorted(prices)
    n = len(s)
    q1 = s[max(0, n // 4 - 1)]
    q2 = s[max(0, n // 2 - 1)]
    q3 = s[max(0, (3 * n) // 4 - 1)]
    return (q1, q2, q3)


def _bucket(price: float, thresholds: tuple[float, float, float]) -> str:
    q1_max, q2_max, q3_max = thresholds
    if price <= q1_max:
        return "Q1"
    if price <= q2_max:
        return "Q2"
    if price <= q3_max:
        return "Q3"
    return "Q4"


def quartile_equals(a: Iterable, b: Iterable) -> bool:
    """Minor helper used in tests — Q-label string compare."""
    return str(a) == str(b) and str(a) in TIER_BUCKETS
