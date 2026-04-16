"""Category embedding provider — used as the cold-start fallback in the
Complementary scorer.

V2 (sparse): vectors are stored as JSON dicts `{ngram: weight}` with
L2-normalised TF-IDF weights pre-applied. Cosine reduces to a sparse
dot product over the intersection of ngrams — vocab-size independent
and constant in storage regardless of corpus growth.

Why character n-grams and not word vectors?
  Category names are short and often single-word ("Kazak", "Pantolon").
  Character n-grams pick up morphological neighbours ("Kazak"↔"Kazaklar")
  without needing Turkish stemming.

Storage: each Category Embedding row stores `vector` as JSON dict.
Legacy dense list format is auto-detected during deserialize and treated
as empty (forces re-embed on next build_all → migration patch handles
the wipe explicitly).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from typing import Any

import frappe

from .common import sparse_cosine

MODEL_VERSION = "tfidf-sparse-v2"
NGRAM_MIN = 3
NGRAM_MAX = 4
MIN_TEXT_LENGTH = 3  # Skip degenerate categories (1-2 char names produce zero vectors)
PERSIST_BATCH_SIZE = 500

_VECTOR_CACHE: dict[str, dict[str, float]] = {}


def clear_cache() -> None:
	_VECTOR_CACHE.clear()


# ─── Public API ──────────────────────────────────────────────────────────


def build_all() -> dict[str, Any]:
	"""Embed every active Product Category and persist into Category Embedding.

	Pipeline:
	  1. Cleanup orphan embeddings (categories no longer active or deleted)
	  2. Build global IDF from active category texts that pass length filter
	  3. Compute sparse TF-IDF vector per category, L2-normalise, persist
	  4. Trigger Category Neighbour Cache rebuild (Phase 2)

	Idempotent — re-running overwrites stored vectors.
	"""
	rows = frappe.db.sql(
		"SELECT name, category_name FROM `tabProduct Category` WHERE is_active = 1",
		as_dict=True,
	)

	active_names = [r["name"] for r in rows]
	orphans_deleted = _delete_orphan_embeddings(active_names)

	if not rows:
		return {"embedded": 0, "skipped": 0, "orphans_deleted": orphans_deleted}

	# Filter candidates by minimum text length to avoid zero-vector pollution
	candidates: list[tuple[str, str]] = []
	skipped_short = 0
	for r in rows:
		text = ((r.get("category_name") or r["name"]) or "").strip().lower()
		if len(text) < MIN_TEXT_LENGTH:
			skipped_short += 1
			continue
		candidates.append((r["name"], text))

	if not candidates:
		return {
			"embedded": 0,
			"skipped": skipped_short,
			"orphans_deleted": orphans_deleted,
		}

	idf = _compute_idf([text for _, text in candidates])
	now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

	embedded = 0
	for category_name, text in candidates:
		vec = _vectorize_sparse(text, idf)
		if not vec:
			skipped_short += 1
			continue
		_persist(category_name, vec, now)
		embedded += 1

	frappe.db.commit()
	clear_cache()

	# Trigger Neighbour Cache rebuild (Phase 2 — pre-computed neighbour pairs)
	neighbours_built = _trigger_neighbour_cache_rebuild(candidates, idf)

	return {
		"embedded": embedded,
		"skipped": skipped_short,
		"orphans_deleted": orphans_deleted,
		"neighbours_built": neighbours_built,
		"model_version": MODEL_VERSION,
	}


def category_similarity(cat_a: str, cat_b: str) -> float:
	"""Cosine similarity between two category embeddings. 0 if either is
	missing a vector or vectors are incompatible.
	"""
	if cat_a == cat_b:
		return 1.0
	v1 = _load_vector(cat_a)
	v2 = _load_vector(cat_b)
	if not v1 or not v2:
		return 0.0
	return sparse_cosine(v1, v2)


def neighbour_categories(category: str, top_k: int = 5, threshold: float = 0.6) -> list[tuple[str, float]]:
	"""Return [(category, similarity), …] for the top_k most similar
	categories (excluding `category` itself) whose similarity ≥ threshold.

	Hot path: reads pre-computed Category Neighbour Cache (O(log N) indexed
	lookup). Falls back to full scan only if the cache table doesn't exist
	(pre-Phase-2 deployment) or returns no rows for the given category.
	"""
	cached = _load_from_neighbour_cache(category, top_k, threshold)
	if cached is not None:
		return cached

	# Legacy fallback — only triggers if Phase 2 not deployed yet
	source_vec = _load_vector(category)
	if not source_vec:
		return []

	rows = frappe.db.sql(
		"SELECT category, `vector` FROM `tabCategory Embedding` WHERE category != %s",
		(category,),
		as_dict=True,
	)
	sims: list[tuple[str, float]] = []
	for r in rows:
		vec = _deserialize(r["vector"])
		if not vec:
			continue
		sim = sparse_cosine(source_vec, vec)
		if sim >= threshold:
			sims.append((r["category"], sim))
	sims.sort(key=lambda x: x[1], reverse=True)
	return sims[:top_k]


def _load_from_neighbour_cache(category: str, top_k: int, threshold: float) -> list[tuple[str, float]] | None:
	"""Return cached neighbours or None if the cache table isn't deployed."""
	if not frappe.db.table_exists("Category Neighbour Cache"):
		return None
	rows = frappe.db.sql(
		"""
        SELECT neighbour_category, similarity
        FROM `tabCategory Neighbour Cache`
        WHERE category = %s AND similarity >= %s
        ORDER BY similarity DESC
        LIMIT %s
        """,
		(category, threshold, top_k),
		as_dict=True,
	)
	return [(r["neighbour_category"], float(r["similarity"])) for r in rows]


def _trigger_neighbour_cache_rebuild(candidates: list[tuple[str, str]], idf: dict[str, float]) -> int:
	"""Best-effort rebuild of Category Neighbour Cache. Returns 0 if Phase 2
	module isn't deployed yet so that build_all stays standalone-runnable.
	"""
	try:
		from . import neighbour_cache
	except ImportError:
		return 0
	return neighbour_cache.rebuild_all(candidates=candidates, idf=idf)


# ─── Internals: TF-IDF over char n-grams (sparse) ────────────────────────


def _ngrams(text: str) -> list[str]:
	text = " " + text.strip() + " "
	out: list[str] = []
	for n in range(NGRAM_MIN, NGRAM_MAX + 1):
		if len(text) < n:
			continue
		for i in range(len(text) - n + 1):
			out.append(text[i : i + n])
	return out


def _compute_idf(texts: list[str]) -> dict[str, float]:
	"""Build IDF lookup from a corpus. Returns {ngram: idf_weight}."""
	df: Counter[str] = Counter()
	for t in texts:
		grams = set(_ngrams(t))
		for g in grams:
			df[g] += 1
	n_docs = max(len(texts), 1)
	return {g: math.log((1 + n_docs) / (1 + c)) + 1 for g, c in df.items()}


def _vectorize_sparse(text: str, idf: dict[str, float]) -> dict[str, float]:
	"""Return L2-normalised sparse TF-IDF vector as `{ngram: weight}`.

	Returns empty dict if text has no usable ngrams.
	"""
	grams = _ngrams(text)
	if not grams:
		return {}
	tf: Counter[str] = Counter(grams)
	raw: dict[str, float] = {}
	for g, c in tf.items():
		weight = idf.get(g)
		if weight is None:
			continue
		raw[g] = c * weight
	if not raw:
		return {}
	norm = math.sqrt(sum(v * v for v in raw.values()))
	if norm == 0:
		return {}
	return {g: v / norm for g, v in raw.items()}


def _persist(category_name: str, vec: dict[str, float], computed_at: str) -> None:
	"""Upsert into Category Embedding using raw SQL for tight loops.

	NB: `vector` is a reserved keyword in MariaDB ≥ 11.7 (native VECTOR
	type), so the column reference must be backtick-escaped in raw SQL.
	"""
	serialized = json.dumps(vec, separators=(",", ":"))
	if frappe.db.exists("Category Embedding", category_name):
		frappe.db.sql(
			"""
            UPDATE `tabCategory Embedding`
            SET `vector` = %s, model_version = %s, computed_at = %s, modified = NOW()
            WHERE name = %s
            """,
			(serialized, MODEL_VERSION, computed_at, category_name),
		)
	else:
		doc = frappe.new_doc("Category Embedding")
		doc.category = category_name
		doc.vector = serialized
		doc.model_version = MODEL_VERSION
		doc.computed_at = computed_at
		doc.insert(ignore_permissions=True)


def _delete_orphan_embeddings(active_names: list[str]) -> int:
	"""Delete Category Embedding rows whose category is no longer active.

	Batched delete to keep transactions short on large category counts.
	"""
	if not active_names:
		n = frappe.db.count("Category Embedding")
		if n:
			frappe.db.sql("DELETE FROM `tabCategory Embedding`")
		return n

	existing = frappe.db.sql_list("SELECT category FROM `tabCategory Embedding`")
	active_set = set(active_names)
	orphans = [name for name in existing if name not in active_set]
	if not orphans:
		return 0

	for i in range(0, len(orphans), PERSIST_BATCH_SIZE):
		batch = orphans[i : i + PERSIST_BATCH_SIZE]
		placeholders = ",".join(["%s"] * len(batch))
		frappe.db.sql(
			f"DELETE FROM `tabCategory Embedding` WHERE name IN ({placeholders})",
			tuple(batch),
		)
	return len(orphans)


def _load_vector(category: str) -> dict[str, float]:
	"""Read the persisted vector via raw SQL with backtick-escaped column.

	Frappe's get_value would also work in current versions, but the
	explicit backtick guards against MariaDB ≥ 11.7 reserving `vector`
	for the native VECTOR data type (would silently break ORM lookups).
	"""
	if category in _VECTOR_CACHE:
		return _VECTOR_CACHE[category]
	rows = frappe.db.sql(
		"SELECT `vector` FROM `tabCategory Embedding` WHERE name = %s LIMIT 1",
		(category,),
	)
	raw = rows[0][0] if rows else None
	vec = _deserialize(raw)
	_VECTOR_CACHE[category] = vec
	return vec


def _deserialize(raw: Any) -> dict[str, float]:
	"""Deserialize stored vector. Handles new sparse dict format. Legacy
	dense list format returns empty dict — forces re-embed on next
	build_all (migration patch wipes them anyway).
	"""
	if not raw:
		return {}
	try:
		out = json.loads(raw)
	except (TypeError, ValueError):
		return {}
	if isinstance(out, dict):
		return {str(k): float(v) for k, v in out.items()}
	return {}


# ─── Accessory category auto-flag (used by scheduler) ───────────────────

ACCESSORY_KEYWORDS = (
	"aksesuar",
	"yedek",
	"aparat",
	"kılıf",
	"kilif",
	"kablo",
	"stand",
	"askı",
	"aski",
	"tutucu",
	"adaptör",
	"adaptor",
	"şarj",
	"sarj",
)


def autoflag_accessory_categories() -> dict[str, int]:
	"""Set Product Category.is_accessory_category based on name heuristics.

	Idempotent: only writes when computed flag differs from stored value.
	"""
	rows = frappe.db.sql(
		"""
        SELECT name, LOWER(COALESCE(category_name, '')) AS category_name,
               LOWER(COALESCE(description, '')) AS description,
               COALESCE(is_accessory_category, 0) AS is_accessory_category
        FROM `tabProduct Category`
        WHERE is_active = 1
        """,
		as_dict=True,
	)
	changed = 0
	for r in rows:
		haystack = f"{r.category_name} {r.description}"
		is_accessory = any(k in haystack for k in ACCESSORY_KEYWORDS)
		want = 1 if is_accessory else 0
		if int(r.is_accessory_category or 0) != want:
			frappe.db.set_value(
				"Product Category", r["name"], "is_accessory_category", want, update_modified=False
			)
			changed += 1
	frappe.db.commit()
	return {"scanned": len(rows), "flag_changes": changed}
