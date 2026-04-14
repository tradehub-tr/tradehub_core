"""Related Products recommendation engine (Related Listing Cache pipeline).

Public surface:
  * engine.compute_for_listing(listing_id) — score a single listing across
    all 4 relation types and persist to Related Listing Cache.
  * engine.compute_all() — rebuild the full similarity matrix.
  * tasks.rebuild_related_matrix / refresh_copurchase_lift /
    rebuild_price_tiers / autoflag_accessory_categories — scheduler entry
    points wired in hooks.py.

Scoring weights live in the `Related Products Settings` single DocType —
modules read them through `tradehub_core.tradehub_core.doctype.related_products_settings.related_products_settings.get_settings()`.
"""
