"""Cross-table cleanup handlers for the Related Products derived data.

These run on demand from doc_events (Product Category on_trash) and from
the weekly rebuild orphan sweep. The Listing-side hooks live in
engine.cleanup_cache_on_listing_remove / cleanup_cache_if_deactivated —
this module focuses on category lifecycle and full-table sweeps.
"""

from __future__ import annotations

import frappe

from . import neighbour_cache, swap


def on_product_category_trash(doc, method=None) -> None:
	"""Product Category.on_trash hook.

	Cascading cleanup:
	  1. Drop the category's Category Embedding row (no-op if absent)
	  2. Drop every Category Neighbour Cache edge touching this category
	     (as either source or target)
	  3. Drop Related Listing Cache rows for listings under this category,
	     since their recommendations were computed against a now-stale
	     category context

	All deletes are best-effort — the category trash itself must succeed
	even if a downstream cleanup fails. Errors are logged but not raised.
	"""
	if not doc or not getattr(doc, "name", None):
		return
	category = doc.name

	try:
		_drop_embedding(category)
	except Exception as exc:
		frappe.log_error(
			title="cleanup: drop_embedding failed",
			message=f"category={category}: {exc}",
		)

	try:
		neighbour_cache.invalidate_for_category(category)
	except Exception as exc:
		frappe.log_error(
			title="cleanup: invalidate_neighbours failed",
			message=f"category={category}: {exc}",
		)

	try:
		affected = _drop_related_cache_for_category_listings(category)
		if affected:
			frappe.logger("related-products").info(
				f"category {category} trashed: cleared {affected} cache rows"
			)
	except Exception as exc:
		frappe.log_error(
			title="cleanup: drop_listing_cache failed",
			message=f"category={category}: {exc}",
		)


def sweep_orphan_cache_rows() -> dict[str, int]:
	"""Maintenance sweep — removes Related Listing Cache rows whose source
	or target listing no longer exists or is inactive.

	Idempotent. Safe to run from a daily scheduler or ad-hoc console call.
	Returns {orphan_source: N, orphan_target: M, deleted: N+M}.
	"""
	_ = frappe.db.sql(
		f"""
        DELETE rlc FROM `{swap.PROD_TABLE}` rlc
        LEFT JOIN `tabListing` l ON l.name = rlc.source_listing
        WHERE l.name IS NULL
           OR l.status != 'Active'
           OR l.is_visible != 1
        """
	)
	src_count = frappe.db.sql("SELECT ROW_COUNT()")[0][0] or 0

	_ = frappe.db.sql(
		f"""
        DELETE rlc FROM `{swap.PROD_TABLE}` rlc
        LEFT JOIN `tabListing` l ON l.name = rlc.target_listing
        WHERE l.name IS NULL
           OR l.status != 'Active'
           OR l.is_visible != 1
        """
	)
	tgt_count = frappe.db.sql("SELECT ROW_COUNT()")[0][0] or 0

	frappe.db.commit()
	return {
		"orphan_source": int(src_count),
		"orphan_target": int(tgt_count),
		"deleted": int(src_count) + int(tgt_count),
	}


# ─── internals ──────────────────────────────────────────────────────────


def _drop_embedding(category: str) -> None:
	if frappe.db.exists("Category Embedding", category):
		frappe.db.delete("Category Embedding", {"name": category})


def _drop_related_cache_for_category_listings(category: str) -> int:
	"""Find every listing under `category` and drop its cache rows."""
	listings = frappe.db.sql_list(
		"SELECT name FROM `tabListing` WHERE product_category = %s",
		(category,),
	)
	if not listings:
		return 0
	placeholders = ",".join(["%s"] * len(listings))
	frappe.db.sql(
		f"""
        DELETE FROM `{swap.PROD_TABLE}`
        WHERE source_listing IN ({placeholders})
           OR target_listing IN ({placeholders})
        """,
		tuple(listings) + tuple(listings),
	)
	rows = frappe.db.sql("SELECT ROW_COUNT()")
	return int(rows[0][0]) if rows else 0
