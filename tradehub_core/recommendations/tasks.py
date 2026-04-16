"""Scheduler entry points wired from hooks.py.

All tasks are idempotent and safe to run twice in a row.
"""

from __future__ import annotations

import frappe

from . import embeddings, engine, neighbour_cache, price_tier


def rebuild_price_tiers() -> None:
	"""Daily: recompute `Listing.price_tier` per category."""
	stats = price_tier.recompute_all()
	frappe.logger("related-products").info(f"price_tier.recompute_all: {stats}")


def rebuild_related_matrix() -> None:
	"""Weekly (long): shard active listings, fan out to long queue, atomic
	swap on completion. Dispatcher returns immediately; the actual work
	runs across N parallel chunk workers and finalises via the last
	chunk's continuation handoff (see engine.dispatch_full_rebuild docs).
	"""
	stats = engine.dispatch_full_rebuild()
	frappe.logger("related-products").info(f"engine.dispatch_full_rebuild: {stats}")


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
	"""Weekly / one-time: rebuild every Category Embedding vector.

	Tail-calls neighbour_cache.rebuild_all internally so the Complementary
	fallback always reads from a fresh pre-computed index.
	"""
	stats = embeddings.build_all()
	frappe.logger("related-products").info(f"embeddings.build_all: {stats}")


def rebuild_category_neighbours() -> None:
	"""Manual / ad-hoc: rebuild Category Neighbour Cache without touching
	the underlying embedding vectors. Faster than build_category_embeddings
	when only the threshold or top_k tuning has changed.
	"""
	written = neighbour_cache.rebuild_all()
	frappe.logger("related-products").info(f"neighbour_cache.rebuild_all: wrote {written} edges")
