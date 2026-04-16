"""Category Neighbour Cache builder.

Pre-computes (category, similar_category, similarity) tuples consumed by
the Complementary cold-start fallback. Replaces the per-listing
`neighbour_categories` full scan (O(C × V) per call) with a single
indexed SQL lookup at scoring time.

Build strategy: an inverted index over n-grams keeps the candidate pool
per category to roughly O(avg_shared_ngrams × avg_categories_per_ngram)
rather than O(C). For the typical Turkish category corpus this is one to
two orders of magnitude smaller than the naive full-scan variant.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import frappe

from . import embeddings
from .common import sparse_cosine

# How many neighbours to keep per category. Higher = better recall + bigger
# cache; 10 covers the Complementary scorer's top_k=5 with a 2× safety
# margin so the runtime threshold can be tightened without rebuilds.
DEFAULT_TOP_K_PER_CATEGORY = 10
DEFAULT_THRESHOLD = 0.6
INSERT_BATCH_SIZE = 500


def rebuild_all(
	candidates: list[tuple[str, str]] | None = None,
	idf: dict[str, float] | None = None,
	top_k: int = DEFAULT_TOP_K_PER_CATEGORY,
	threshold: float = DEFAULT_THRESHOLD,
) -> int:
	"""Rebuild the entire Category Neighbour Cache table from scratch.

	If `candidates` and `idf` are provided (the build_all tail-call path)
	the work skips the bootstrap query. Otherwise the corpus is read
	from Product Category — slower but useful for ad-hoc rebuilds via
	`bench --site <s> execute tradehub_core.recommendations.neighbour_cache.rebuild_all`.

	Returns: number of (cat, neighbour) edges written.
	"""
	if not frappe.db.table_exists("Category Neighbour Cache"):
		return 0

	if candidates is None or idf is None:
		candidates, idf = _bootstrap_corpus()

	if not candidates:
		frappe.db.sql("TRUNCATE TABLE `tabCategory Neighbour Cache`")
		frappe.db.commit()
		return 0

	# Vectorise each category once
	vectors: dict[str, dict[str, float]] = {}
	for cat, text in candidates:
		vec = embeddings._vectorize_sparse(text, idf)
		if vec:
			vectors[cat] = vec

	# Inverted index: ngram → set of categories carrying it.
	# Lets us reduce candidate pool from O(C) to O(avg shared ngrams).
	inverted: dict[str, set[str]] = {}
	for cat, vec in vectors.items():
		for ngram in vec.keys():
			bucket = inverted.get(ngram)
			if bucket is None:
				inverted[ngram] = {cat}
			else:
				bucket.add(cat)

	# Atomic-ish replacement: TRUNCATE then bulk insert.
	# Read path tolerates an empty table briefly (falls back to legacy
	# full-scan in embeddings.neighbour_categories).
	frappe.db.sql("TRUNCATE TABLE `tabCategory Neighbour Cache`")
	now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

	pending: list[tuple[str, str, float, str]] = []
	total_written = 0

	for cat, vec in vectors.items():
		candidate_set: set[str] = set()
		for ngram in vec.keys():
			bucket = inverted.get(ngram)
			if bucket:
				candidate_set.update(bucket)
		candidate_set.discard(cat)
		if not candidate_set:
			continue

		scored: list[tuple[str, float]] = []
		for other in candidate_set:
			other_vec = vectors.get(other)
			if not other_vec:
				continue
			sim = sparse_cosine(vec, other_vec)
			if sim >= threshold:
				scored.append((other, sim))

		if not scored:
			continue
		scored.sort(key=lambda x: x[1], reverse=True)
		for other, sim in scored[:top_k]:
			pending.append((cat, other, sim, now))

		if len(pending) >= INSERT_BATCH_SIZE:
			_flush(pending)
			total_written += len(pending)
			pending.clear()

	if pending:
		_flush(pending)
		total_written += len(pending)

	frappe.db.commit()
	return total_written


def _bootstrap_corpus() -> tuple[list[tuple[str, str]], dict[str, float]]:
	"""Recompute candidates+idf from Product Category. Used when rebuild_all
	runs outside the build_all pipeline (manual console invocations).
	"""
	rows = frappe.db.sql(
		"SELECT name, category_name FROM `tabProduct Category` WHERE is_active = 1",
		as_dict=True,
	)
	candidates: list[tuple[str, str]] = []
	for r in rows:
		text = ((r.get("category_name") or r["name"]) or "").strip().lower()
		if len(text) < embeddings.MIN_TEXT_LENGTH:
			continue
		candidates.append((r["name"], text))
	idf = embeddings._compute_idf([text for _, text in candidates])
	return candidates, idf


def _flush(rows: Iterable[tuple[str, str, float, str]]) -> None:
	"""Bulk insert into Category Neighbour Cache. `name` is hash-generated."""
	rows_list = list(rows)
	if not rows_list:
		return
	values: list[list] = []
	for cat, neighbour, sim, computed_at in rows_list:
		values.append(
			[
				frappe.generate_hash(length=10),  # name
				computed_at,
				computed_at,  # creation, modified
				"Administrator",  # owner
				"Administrator",  # modified_by
				cat,
				neighbour,
				float(sim),
				computed_at,
			]
		)
	placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s,%s)"] * len(values))
	flat: list = [v for row in values for v in row]
	frappe.db.sql(
		f"""
        INSERT INTO `tabCategory Neighbour Cache`
        (name, creation, modified, owner, modified_by,
         category, neighbour_category, similarity, computed_at)
        VALUES {placeholders}
        """,
		flat,
	)


def invalidate_for_category(category: str) -> int:
	"""Drop all cache rows touching `category` (as either side of the edge).

	Called by the Product Category on_trash hook so a deleted category
	leaves no stale recommendations behind. Returns rows deleted.
	"""
	if not frappe.db.table_exists("Category Neighbour Cache"):
		return 0
	before = frappe.db.count(
		"Category Neighbour Cache",
		filters={"category": category},
	) + frappe.db.count(
		"Category Neighbour Cache",
		filters={"neighbour_category": category},
	)
	if not before:
		return 0
	frappe.db.sql(
		"DELETE FROM `tabCategory Neighbour Cache` WHERE category = %s OR neighbour_category = %s",
		(category, category),
	)
	return before
