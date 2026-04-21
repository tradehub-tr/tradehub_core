"""Orchestrator: runs all four scorers for a given listing (or all listings)
and persists the top-N results per relation type into Related Listing Cache.

Three entry points:

  * `compute_for_listing(listing_id)` — targeted recompute; called from
    the API for on-demand refresh and by Listing.on_update hooks. Writes
    directly to the production table (per-listing replace).

  * `dispatch_full_rebuild()` — production weekly rebuild. Shards active
    listings into chunks, fans them out across the long queue, and finalises
    with an atomic shadow→prod swap. Tracks chunk progress via Redis.

  * `compute_all()` — legacy single-process full rebuild. Preserved for
    `bench execute` use; production scheduler uses the dispatcher.

Cache invariants:
  * PROD `Related Listing Cache` is never empty during a rebuild — the
    swap is the only moment of change, and it's atomic at the metadata
    level (sub-millisecond).
  * Per-listing replace deletes only the source listing's rows then
    inserts new ones — never touches other listings' recommendations.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

import frappe

from ..tradehub_core.doctype.related_products_settings.related_products_settings import (
	get_settings,
)
from . import accessory, complementary, similar, substitute, swap
from .common import (
	ScoreRow,
	clear_attribute_cache,
	fetch_all_active_listings,
)

# Production rebuild tunables. Sized for a 100K-listing target with a
# typical Cronbi long-worker pool of 2-4 concurrency.
CHUNK_SIZE = 1000
CHUNK_TIMEOUT = 1800  # 30 min/chunk hard cap (RQ death penalty)
DISPATCH_TIMEOUT = 600  # dispatcher itself returns fast after enqueue
FINALIZE_TIMEOUT = 600
REBUILD_TTL_SECONDS = 7200  # Redis tracker keys auto-expire after 2h
REBUILD_KEY_PREFIX = "tradehub_recos:rebuild"
LISTING_STREAM_BATCH = 5000  # keyset pagination page size
MAX_CHUNK_RETRIES = 3  # transient-failure retry budget per chunk


# ─── Public API ──────────────────────────────────────────────────────────


def compute_for_listing(listing_id: str) -> dict[str, int]:
	"""Recompute all 4 relation types for a single source listing and
	write into PROD (per-listing replace). Idempotent.
	"""
	settings = get_settings()
	source = _load_source(listing_id)
	if not source or source.get("status") != "Active" or not source.get("is_visible"):
		_clear_source_in(listing_id, swap.PROD_TABLE)
		return {"similar": 0, "substitute": 0, "complementary": 0, "accessory": 0}

	rows = _score_all(source, settings)
	_replace_in_prod(listing_id, rows)
	return {
		"similar": sum(1 for r in rows if r.relation_type == "Similar"),
		"substitute": sum(1 for r in rows if r.relation_type == "Substitute"),
		"complementary": sum(1 for r in rows if r.relation_type == "Complementary"),
		"accessory": sum(1 for r in rows if r.relation_type == "Accessory"),
	}


def compute_all() -> dict[str, Any]:
	"""Legacy in-process full rebuild — single transaction over PROD.

	Production scheduler should call `dispatch_full_rebuild` instead;
	this entry point is preserved for `bench execute` and one-off backfills
	on small datasets where the dispatcher overhead isn't worth it.
	"""
	settings = get_settings()
	clear_attribute_cache()

	swap.ensure_shadow_table()
	listings = fetch_all_active_listings(batch_size=200000)
	total_rows = 0
	processed = 0
	for src in listings:
		rows = _score_all(src, settings)
		if rows:
			_insert_rows_to(rows, swap.SHADOW_TABLE)
			total_rows += len(rows)
		processed += 1
	frappe.db.commit()
	swap.swap_tables()
	clear_attribute_cache()
	return {"listings_processed": processed, "cache_rows_written": total_rows}


def dispatch_full_rebuild() -> dict[str, Any]:
	"""Production weekly rebuild entry point. Returns immediately after
	dispatching all chunks; chunks run async on the long queue.

	Pipeline:
	  1. Drop any stale shadow from a prior aborted rebuild
	  2. Create empty shadow with same schema as PROD
	  3. Snapshot the rebuild start time (for catch-up of in-flight changes)
	  4. Stream active listing IDs via keyset pagination (bounded memory)
	  5. Initialise Redis counters with sentinel "total" so chunks finishing
	     mid-enumeration don't trigger early finalize
	  6. Enqueue each chunk worker; after enumeration, set the real total.
	     The last chunk to finish triggers `finalize_rebuild` via
	     SETNX-protected handoff (or this function does the trigger if all
	     chunks already finished by the time enumeration ends).
	"""
	snapshot_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
	swap.ensure_shadow_table()

	rebuild_id = frappe.generate_hash(length=10)
	cache = frappe.cache()
	# Sentinel total prevents premature finalize during enumeration
	cache.set(_rk(rebuild_id, "total"), 1 << 30, ex=REBUILD_TTL_SECONDS)
	cache.set(_rk(rebuild_id, "completed"), 0, ex=REBUILD_TTL_SECONDS)
	cache.set(_rk(rebuild_id, "failed"), 0, ex=REBUILD_TTL_SECONDS)

	chunk_count = 0
	listing_count = 0
	for chunk in _chunkify(_iter_active_listing_ids(), CHUNK_SIZE):
		listing_count += len(chunk)
		chunk_count += 1
		frappe.enqueue(
			"tradehub_core.recommendations.engine.compute_chunk_worker",
			queue="long",
			timeout=CHUNK_TIMEOUT,
			chunk_listing_ids=chunk,
			rebuild_id=rebuild_id,
			snapshot_time=snapshot_time,
			attempt=1,
		)

	if chunk_count == 0:
		swap.cleanup_shadow()
		_redis_cleanup(rebuild_id)
		return {"status": "no_listings", "chunks": 0}

	# Enumeration complete — write the real total. From here on, the last
	# chunk to finish will trigger finalize_rebuild.
	cache.set(_rk(rebuild_id, "total"), chunk_count, ex=REBUILD_TTL_SECONDS)

	# If chunks completed faster than we could enumerate, claim finalize here.
	completed = int(cache.get(_rk(rebuild_id, "completed")) or 0)
	failed = int(cache.get(_rk(rebuild_id, "failed")) or 0)
	if completed + failed >= chunk_count:
		if cache.set(_rk(rebuild_id, "finalized"), 1, nx=True, ex=REBUILD_TTL_SECONDS):
			frappe.enqueue(
				"tradehub_core.recommendations.engine.finalize_rebuild",
				queue="long",
				timeout=FINALIZE_TIMEOUT,
				rebuild_id=rebuild_id,
				snapshot_time=snapshot_time,
			)

	return {
		"status": "dispatched",
		"rebuild_id": rebuild_id,
		"chunks": chunk_count,
		"listings": listing_count,
		"snapshot_time": snapshot_time,
	}


def compute_chunk_worker(
	chunk_listing_ids: list[str],
	rebuild_id: str,
	snapshot_time: str,
	attempt: int = 1,
) -> None:
	"""Long-queue wrapper. Computes the chunk, updates Redis counters, and
	hands off to `finalize_rebuild` if this is the last chunk to finish.

	Transient failures retry up to MAX_CHUNK_RETRIES with exponential
	backoff (handled by RQ requeue). The "failed" counter only ticks
	after retries are exhausted, so a flaky DB connection doesn't abort
	an otherwise-healthy rebuild.
	"""
	cache = frappe.cache()
	try:
		compute_chunk(chunk_listing_ids)
		cache.incr(_rk(rebuild_id, "completed"))
	except Exception as exc:
		if attempt < MAX_CHUNK_RETRIES:
			frappe.log_error(
				title="rebuild chunk transient failure (retrying)",
				message=(
					f"rebuild_id={rebuild_id} attempt={attempt} listings={len(chunk_listing_ids)}: {exc}"
				),
			)
			frappe.enqueue(
				"tradehub_core.recommendations.engine.compute_chunk_worker",
				queue="long",
				timeout=CHUNK_TIMEOUT,
				chunk_listing_ids=chunk_listing_ids,
				rebuild_id=rebuild_id,
				snapshot_time=snapshot_time,
				attempt=attempt + 1,
			)
			return
		# Retries exhausted → permanent failure
		frappe.log_error(
			title="rebuild chunk failed (retries exhausted)",
			message=(f"rebuild_id={rebuild_id} attempts={attempt} listings={len(chunk_listing_ids)}: {exc}"),
		)
		cache.incr(_rk(rebuild_id, "failed"))

	completed = int(cache.get(_rk(rebuild_id, "completed")) or 0)
	failed = int(cache.get(_rk(rebuild_id, "failed")) or 0)
	total = int(cache.get(_rk(rebuild_id, "total")) or 0)

	if total > 0 and completed + failed >= total:
		# Last chunk to finish — try to claim the finalize handoff.
		# SETNX ensures only one chunk wins the race.
		claimed = cache.set(_rk(rebuild_id, "finalized"), 1, nx=True, ex=REBUILD_TTL_SECONDS)
		if claimed:
			frappe.enqueue(
				"tradehub_core.recommendations.engine.finalize_rebuild",
				queue="long",
				timeout=FINALIZE_TIMEOUT,
				rebuild_id=rebuild_id,
				snapshot_time=snapshot_time,
			)


def compute_chunk(listing_ids: list[str]) -> None:
	"""Score the given listings and append rows to the shadow table.

	Wrapped by `compute_chunk_worker` for queue + counter handling. Kept
	standalone so it can be invoked from a `bench execute` for diagnostics.
	"""
	if not listing_ids:
		return
	settings = get_settings()
	clear_attribute_cache()

	placeholders = ",".join(["%s"] * len(listing_ids))
	listings = frappe.db.sql(
		f"""
        SELECT name, seller_profile, price_tier, selling_price, average_rating,
               title, description, brand, product_category, status, is_visible
        FROM `tabListing`
        WHERE name IN ({placeholders})
          AND status = 'Active'
          AND is_visible = 1
          AND selling_price > 0
        """,
		tuple(listing_ids),
		as_dict=True,
	)

	for src in listings:
		try:
			rows = _score_all(src, settings)
		except Exception as exc:
			frappe.log_error(
				title="chunk listing score failed",
				message=f"listing={src['name']}: {exc}",
			)
			continue
		if rows:
			_insert_rows_to(rows, swap.SHADOW_TABLE)

	frappe.db.commit()
	clear_attribute_cache()


def finalize_rebuild(rebuild_id: str, snapshot_time: str) -> dict[str, Any]:
	"""Called once after the last chunk finishes. Swaps shadow→PROD if
	every chunk succeeded, otherwise aborts and leaves PROD untouched.

	Always cleans up Redis tracker keys before returning.
	"""
	cache = frappe.cache()
	completed = int(cache.get(_rk(rebuild_id, "completed")) or 0)
	failed = int(cache.get(_rk(rebuild_id, "failed")) or 0)
	total = int(cache.get(_rk(rebuild_id, "total")) or 0)

	if failed > 0:
		swap.cleanup_shadow()
		frappe.log_error(
			title="rebuild aborted",
			message=(f"rebuild_id={rebuild_id} total_chunks={total} completed={completed} failed={failed}"),
		)
		_redis_cleanup(rebuild_id)
		return {"status": "aborted", "rebuild_id": rebuild_id}

	# Pre-swap orphan purge: listings that were deleted/deactivated DURING
	# the rebuild window may have left rows in shadow that point at no-longer
	# active listings. Drop those before the swap so PROD never serves them.
	purged = _purge_shadow_orphans()

	shadow_rows = swap.shadow_row_count()
	swap.swap_tables()
	catched_up = _catch_up_modified_after(snapshot_time)

	frappe.logger("related-products").info(
		f"rebuild finalized: rebuild_id={rebuild_id} "
		f"completed_chunks={completed} shadow_rows={shadow_rows} "
		f"orphans_purged={purged} catch_up_listings={catched_up}"
	)
	_redis_cleanup(rebuild_id)
	return {
		"status": "swapped",
		"rebuild_id": rebuild_id,
		"rows_swapped": shadow_rows,
		"orphans_purged": purged,
		"catch_up_listings": catched_up,
	}


# ─── Listing lifecycle hooks (registered in hooks.py) ───────────────────


def cleanup_cache_on_listing_remove(doc, method=None) -> None:
	"""Listing.on_trash hook: drop every PROD cache row referencing this
	listing (as either source or target).
	"""
	name = doc.name
	frappe.db.sql(
		f"DELETE FROM `{swap.PROD_TABLE}` WHERE source_listing = %s OR target_listing = %s",
		(name, name),
	)


def cleanup_cache_if_deactivated(doc, method=None) -> None:
	"""Listing.on_update hook: if the listing went to Inactive or
	is_visible=0, remove it from the cache so storefront stops suggesting
	it. Reactivation is picked up by `schedule_recompute_on_listing_update`
	on the same on_update fire.
	"""
	status = (getattr(doc, "status", "") or "").lower()
	is_visible = int(getattr(doc, "is_visible", 0) or 0)
	if status != "active" or is_visible != 1:
		cleanup_cache_on_listing_remove(doc)


def schedule_recompute_on_listing_update(doc, method=None) -> None:
	"""Listing.on_update / after_insert hook: enqueue async recompute of
	the listing's related cache rows.

	Idempotent — multiple successive saves enqueue multiple jobs, each
	one DELETE+INSERTs only the source listing's rows so the last one
	wins. Skips when the listing isn't active+visible (cleanup hook on
	the same event handles that case).
	"""
	name = getattr(doc, "name", None)
	if not name:
		return
	status = (getattr(doc, "status", "") or "").lower()
	is_visible = int(getattr(doc, "is_visible", 0) or 0)
	if status != "active" or is_visible != 1:
		return
	frappe.enqueue(
		"tradehub_core.recommendations.engine.compute_for_listing",
		queue="short",
		timeout=120,
		listing_id=name,
		enqueue_after_commit=True,
		job_name=f"recompute_listing_{name}",
	)


# ─── internals ──────────────────────────────────────────────────────────


def _load_source(listing_id: str) -> dict[str, Any] | None:
	return frappe.db.get_value(
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


def _score_all(source: dict[str, Any], settings: dict[str, Any]) -> list[ScoreRow]:
	max_results = int(settings["max_results_per_tab"])
	min_score = float(settings["min_score_threshold"])

	rows: list[ScoreRow] = []
	rows.extend(similar.score_for_listing(source, settings["similar"], max_results, min_score))
	rows.extend(substitute.score_for_listing(source, settings["substitute"], max_results, min_score))
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


def _replace_in_prod(source_id: str, rows: list[ScoreRow]) -> None:
	_clear_source_in(source_id, swap.PROD_TABLE)
	if rows:
		_insert_rows_to(rows, swap.PROD_TABLE)
	frappe.db.commit()


def _clear_source_in(source_id: str, table_name: str) -> None:
	frappe.db.sql(
		f"DELETE FROM `{table_name}` WHERE source_listing = %s",
		(source_id,),
	)


def _insert_rows_to(rows: list[ScoreRow], table_name: str) -> None:
	"""Batch insert with a single multi-row INSERT for throughput.

	`table_name` parameterises PROD vs SHADOW so the per-listing replace
	(PROD) and the chunked rebuild (SHADOW) share the same write path.
	"""
	if not rows:
		return
	now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

	by_group: dict[tuple[str, str], int] = {}
	values: list[list[Any]] = []
	for r in rows:
		key = (r.source_listing, r.relation_type)
		by_group[key] = by_group.get(key, 0) + 1
		display_order = by_group[key]
		values.append(
			[
				frappe.generate_hash(length=10),  # name
				now,
				now,  # creation, modified
				"Administrator",  # owner
				"Administrator",  # modified_by
				r.source_listing,
				r.target_listing,
				r.relation_type,
				r.base_score,
				0.0,  # ctr_boost (Faz 2 placeholder)
				r.base_score,  # final_score
				display_order,
				now,  # computed_at
			]
		)

	placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"] * len(values))
	flat: list = [v for row in values for v in row]
	frappe.db.sql(
		f"""
        INSERT INTO `{table_name}`
        (name, creation, modified, owner, modified_by,
         source_listing, target_listing, relation_type,
         base_score, ctr_boost, final_score, display_order, computed_at)
        VALUES {placeholders}
        """,
		flat,
	)


def _catch_up_modified_after(snapshot_time: str) -> int:
	"""Re-enqueue compute_for_listing for listings that changed during the
	rebuild window — ensures their fresh state ends up in PROD even though
	the swapped shadow was built from a pre-modification snapshot.
	"""
	rows = frappe.db.sql(
		"""
        SELECT name FROM `tabListing`
        WHERE modified > %s
          AND status = 'Active' AND is_visible = 1
        """,
		(snapshot_time,),
		as_list=True,
	)
	for (listing_id,) in rows:
		frappe.enqueue(
			"tradehub_core.recommendations.engine.compute_for_listing",
			queue="short",
			timeout=120,
			listing_id=listing_id,
		)
	return len(rows)


def _iter_active_listing_ids(batch_size: int = LISTING_STREAM_BATCH) -> Iterator[str]:
	"""Yield active listing IDs in keyset-paginated batches.

	Keyset pagination (`name > last_seen`) avoids the O(N²) scan that an
	OFFSET-based approach would incur on a 100K+ listing table. Memory
	is bounded to one batch at a time regardless of total table size.
	"""
	last_name = ""
	while True:
		rows = frappe.db.sql(
			"""
            SELECT name FROM `tabListing`
            WHERE status = 'Active' AND is_visible = 1 AND selling_price > 0
              AND name > %s
            ORDER BY name
            LIMIT %s
            """,
			(last_name, batch_size),
			as_list=True,
		)
		if not rows:
			return
		for (name,) in rows:
			yield name
			last_name = name
		if len(rows) < batch_size:
			return


def _chunkify(iterable: Iterable[str], size: int) -> Iterator[list[str]]:
	"""Chunk a (possibly streaming) iterable into lists of `size`."""
	iterator = iter(iterable)
	while True:
		chunk = list(itertools.islice(iterator, size))
		if not chunk:
			return
		yield chunk


def _purge_shadow_orphans() -> int:
	"""Remove shadow rows whose source or target listing is no longer
	active. Called immediately before swap_tables so the orphan rows
	never reach PROD.
	"""
	if not swap.shadow_exists():
		return 0
	frappe.db.sql(
		f"""
        DELETE rlc FROM `{swap.SHADOW_TABLE}` rlc
        LEFT JOIN `tabListing` l ON l.name = rlc.source_listing
        WHERE l.name IS NULL OR l.status != 'Active' OR l.is_visible != 1
        """
	)
	src = frappe.db.sql("SELECT ROW_COUNT()")[0][0] or 0

	frappe.db.sql(
		f"""
        DELETE rlc FROM `{swap.SHADOW_TABLE}` rlc
        LEFT JOIN `tabListing` l ON l.name = rlc.target_listing
        WHERE l.name IS NULL OR l.status != 'Active' OR l.is_visible != 1
        """
	)
	tgt = frappe.db.sql("SELECT ROW_COUNT()")[0][0] or 0
	return int(src) + int(tgt)


def _rk(rebuild_id: str, suffix: str) -> str:
	"""Redis key with explicit db_name prefix so multi-tenant deployments
	don't collide on shared Redis instances.
	"""
	db_prefix = getattr(frappe.local, "conf", None)
	db_name = (db_prefix and getattr(db_prefix, "db_name", None)) or "default"
	return f"{db_name}|{REBUILD_KEY_PREFIX}:{rebuild_id}:{suffix}"


def _redis_cleanup(rebuild_id: str) -> None:
	cache = frappe.cache()
	for suffix in ("total", "completed", "failed", "finalized"):
		try:
			cache.delete(_rk(rebuild_id, suffix))
		except Exception:
			pass
