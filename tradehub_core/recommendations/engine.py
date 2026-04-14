"""Orchestrator: runs all four scorers for a given listing (or all listings)
and persists the top-N results per relation type into Related Listing Cache.

Two entry points:
  * compute_for_listing(listing_id) — targeted recompute; called from the
    API for on-demand refresh and by Listing.on_update hooks.
  * compute_all() — full-matrix rebuild; called from the daily scheduler.

Cache replacement strategy: delete-then-insert per (source_listing) so a
listing with zero new matches ends up with zero rows in the cache — the
storefront API then returns [] for each tab and the section auto-hides.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe

from ..tradehub_core.doctype.related_products_settings.related_products_settings import (
    get_settings,
)
from . import similar, substitute, complementary, accessory
from .common import (
    ScoreRow,
    clear_attribute_cache,
    fetch_all_active_listings,
)


def compute_for_listing(listing_id: str) -> dict[str, int]:
    """Recompute all 4 relation types for a single source listing.

    Returns a count breakdown per relation type.
    """
    settings = get_settings()
    source = frappe.db.get_value(
        "Listing",
        listing_id,
        [
            "name",
            "seller_profile",
            "price_tier",
            "selling_price",
            "average_rating",
            "title",
            "brand",
            "product_category",
            "status",
            "is_visible",
        ],
        as_dict=True,
    )
    if not source or source.get("status") != "Active" or not source.get("is_visible"):
        _clear_source(listing_id)
        return {"similar": 0, "substitute": 0, "complementary": 0, "accessory": 0}

    rows = _score_all(source, settings)
    _replace_cache(listing_id, rows)
    return {
        "similar": sum(1 for r in rows if r.relation_type == "Similar"),
        "substitute": sum(1 for r in rows if r.relation_type == "Substitute"),
        "complementary": sum(1 for r in rows if r.relation_type == "Complementary"),
        "accessory": sum(1 for r in rows if r.relation_type == "Accessory"),
    }


def compute_all() -> dict[str, Any]:
    """Full rebuild. Truncates the cache and re-fills for every active listing."""
    settings = get_settings()
    clear_attribute_cache()

    frappe.db.sql("TRUNCATE TABLE `tabRelated Listing Cache`")

    listings = fetch_all_active_listings(batch_size=20000)
    total_rows = 0
    processed = 0
    for src in listings:
        rows = _score_all(src, settings)
        if rows:
            _insert_rows(rows)
            total_rows += len(rows)
        processed += 1
    frappe.db.commit()
    clear_attribute_cache()
    return {"listings_processed": processed, "cache_rows_written": total_rows}


# ─── internals ──────────────────────────────────────────────────────────

def _score_all(source: dict[str, Any], settings: dict[str, Any]) -> list[ScoreRow]:
    max_results = int(settings["max_results_per_tab"])
    min_score = float(settings["min_score_threshold"])

    rows: list[ScoreRow] = []
    rows.extend(
        similar.score_for_listing(source, settings["similar"], max_results, min_score)
    )
    rows.extend(
        substitute.score_for_listing(source, settings["substitute"], max_results, min_score)
    )
    rows.extend(
        complementary.score_for_listing(
            source,
            settings["complementary"],
            max_results,
            min_score,
            float(settings["copurchase_lift_threshold"]),
            float(settings["embedding_cosine_threshold"]),
        )
    )
    rows.extend(
        accessory.score_for_listing(
            source,
            settings["accessory"],
            max_results,
            min_score,
            float(settings["accessory_price_ratio_threshold"]),
        )
    )
    return rows


def _replace_cache(source_id: str, rows: list[ScoreRow]) -> None:
    """Delete existing rows for the source, then insert the new ones."""
    _clear_source(source_id)
    if not rows:
        return
    _insert_rows(rows)
    frappe.db.commit()


def _clear_source(source_id: str) -> None:
    frappe.db.sql(
        "DELETE FROM `tabRelated Listing Cache` WHERE source_listing = %s",
        (source_id,),
    )


def _insert_rows(rows: list[ScoreRow]) -> None:
    """Batch insert with a single multi-row INSERT for throughput."""
    if not rows:
        return
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Assign display_order per (source, relation_type) by score rank
    by_group: dict[tuple[str, str], int] = {}
    values: list[list[Any]] = []
    for r in rows:
        key = (r.source_listing, r.relation_type)
        by_group[key] = by_group.get(key, 0) + 1
        display_order = by_group[key]
        values.append(
            [
                frappe.generate_hash(length=10),  # name
                now, now,  # creation, modified
                "Administrator",  # owner
                "Administrator",  # modified_by
                r.source_listing,
                r.target_listing,
                r.relation_type,
                r.base_score,
                0.0,  # ctr_boost (Faz 2)
                r.base_score,  # final_score = base + boost (0 in MVP)
                display_order,
                now,  # computed_at
            ]
        )

    frappe.db.sql(
        """
        INSERT INTO `tabRelated Listing Cache`
        (name, creation, modified, owner, modified_by,
         source_listing, target_listing, relation_type,
         base_score, ctr_boost, final_score, display_order, computed_at)
        VALUES
        """
        + ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"] * len(values)),
        [v for row in values for v in row],
    )


# ─── Cleanup hooks ──────────────────────────────────────────────────────

def cleanup_cache_on_listing_remove(doc, method=None) -> None:
    """Listing.on_trash hook: drop every cache row referencing this listing
    (as either source or target)."""
    name = doc.name
    frappe.db.sql(
        "DELETE FROM `tabRelated Listing Cache` WHERE source_listing = %s OR target_listing = %s",
        (name, name),
    )


def cleanup_cache_if_deactivated(doc, method=None) -> None:
    """Listing.on_update hook: if the listing went to Inactive or is_visible=0,
    remove it from the cache so storefront stops suggesting it. Reactivation
    will be picked up by the next nightly batch."""
    status = (getattr(doc, "status", "") or "").lower()
    is_visible = int(getattr(doc, "is_visible", 0) or 0)
    if status != "active" or is_visible != 1:
        cleanup_cache_on_listing_remove(doc)
