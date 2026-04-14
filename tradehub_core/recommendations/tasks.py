"""Scheduler entry points wired from hooks.py.

All tasks are idempotent and safe to run twice in a row.
"""
from __future__ import annotations

import frappe

from . import embeddings, engine, price_tier


def rebuild_price_tiers() -> None:
    """Daily: recompute `Listing.price_tier` per category."""
    stats = price_tier.recompute_all()
    frappe.logger("related-products").info(f"price_tier.recompute_all: {stats}")


def rebuild_related_matrix() -> None:
    """Daily: full rebuild of Related Listing Cache."""
    stats = engine.compute_all()
    frappe.logger("related-products").info(f"engine.compute_all: {stats}")


def refresh_copurchase_lift() -> None:
    """Hourly: recompute only the Complementary rows (lift is the only
    signal that changes inside a day).

    Implemented as a lightweight pass over listings that already have
    Complementary rows in the cache — others will pick up changes at the
    next nightly batch.
    """
    sources = frappe.db.sql(
        """
        SELECT DISTINCT source_listing
        FROM `tabRelated Listing Cache`
        WHERE relation_type = 'Complementary'
        """,
        as_dict=True,
    )
    refreshed = 0
    for row in sources:
        try:
            engine.compute_for_listing(row["source_listing"])
            refreshed += 1
        except Exception as exc:
            frappe.log_error(
                title="refresh_copurchase_lift failed",
                message=f"listing={row['source_listing']}: {exc}",
            )
    frappe.logger("related-products").info(
        f"refresh_copurchase_lift: refreshed {refreshed}/{len(sources)} listings"
    )


def autoflag_accessory_categories() -> None:
    """Daily: set Product Category.is_accessory_category based on keyword scan."""
    stats = embeddings.autoflag_accessory_categories()
    frappe.logger("related-products").info(f"autoflag_accessory_categories: {stats}")


def build_category_embeddings() -> None:
    """Weekly / one-time: rebuild every Category Embedding vector."""
    stats = embeddings.build_all()
    frappe.logger("related-products").info(f"embeddings.build_all: {stats}")
