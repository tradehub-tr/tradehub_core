"""Complementary (Tamamlayıcı) product scorer.

Behavioural signals:

    score = w_copurchase × normalized_lift
          + w_coview     × coview_ratio
          + w_embedding  × category_embedding_similarity  (cold-start fallback)

Lift = P(B | A) / P(B). Values ≥ 1.5 are considered meaningful. We pull the
top-N co-purchase peers in the computed order and lean on embedding
similarity only when the behavioural tail is empty (fresh platform).
"""

from __future__ import annotations

from typing import Any

import frappe

from . import embeddings
from .common import (
	COPURCHASE_WINDOW_DAYS,
	COVIEW_WINDOW_DAYS,
	ScoreRow,
)


def score_for_listing(
	source: dict[str, Any],
	weights: dict[str, float],
	max_results: int,
	min_score: float,
	lift_threshold: float,
	embedding_cosine_threshold: float,
) -> list[ScoreRow]:
	source_id = source["name"]
	source_category = source.get("product_category")

	# 1) Co-purchase lift over the past N days
	lift_rows = _copurchase_candidates(source_id, lift_threshold)
	# 2) Co-view within session
	coview_rows = _coview_candidates(source_id)

	coview_map = {r["listing"]: float(r["ratio"]) for r in coview_rows}
	seen: set[str] = set()
	rows: list[ScoreRow] = []

	for r in lift_rows:
		target = r["listing"]
		if target == source_id or target in seen:
			continue
		seen.add(target)
		# Normalise lift into 0..1: lift=threshold → 0.5, lift=10 → 1.0.
		lift = float(r["lift"])
		normalised = min(1.0, lift / 10.0) if lift >= lift_threshold else 0.0
		coview = coview_map.get(target, 0.0)
		emb = _embedding_similarity(source_category, _category_of(target), embedding_cosine_threshold)

		final = weights["copurchase"] * normalised + weights["coview"] * coview + weights["embedding"] * emb
		if final >= min_score:
			rows.append(
				ScoreRow(
					source_listing=source_id,
					target_listing=target,
					relation_type="Complementary",
					base_score=final,
				)
			)

	# 3) Cold-start fallback: if we have < max_results from lift, fill
	# the rest with embedding-similar category neighbours.
	if len(rows) < max_results:
		rows.extend(
			_embedding_fallback_rows(
				source_id,
				source_category,
				seen,
				weights,
				embedding_cosine_threshold,
				min_score,
				max_results - len(rows),
			)
		)

	rows.sort(key=lambda r: r.base_score, reverse=True)
	return rows[:max_results]


# ─── SQL helpers ─────────────────────────────────────────────────────────


def _copurchase_candidates(source_id: str, lift_threshold: float) -> list[dict[str, Any]]:
	"""Compute co-purchase lift between source_id and every other listing.

	lift = P(A ∩ B) / (P(A) * P(B))

	Done inline in SQL — no Order Item rescans per candidate. We restrict
	to orders in the recent window so stale baskets don't dominate.
	"""
	rows = frappe.db.sql(
		"""
        WITH window_orders AS (
            SELECT DISTINCT oi.parent AS order_id, oi.listing
            FROM `tabOrder Item` oi
            INNER JOIN `tabOrder` o ON o.name = oi.parent
            WHERE o.creation >= DATE_SUB(NOW(), INTERVAL %(days)s DAY)
              AND oi.listing IS NOT NULL
              AND oi.listing != ''
        ),
        total AS (
            SELECT COUNT(DISTINCT order_id) AS n FROM window_orders
        ),
        a_orders AS (
            SELECT DISTINCT order_id FROM window_orders WHERE listing = %(source)s
        ),
        b_counts AS (
            SELECT wo.listing, COUNT(DISTINCT wo.order_id) AS b_n
            FROM window_orders wo
            GROUP BY wo.listing
        ),
        ab_counts AS (
            SELECT wo.listing, COUNT(DISTINCT wo.order_id) AS ab_n
            FROM window_orders wo
            INNER JOIN a_orders ao ON ao.order_id = wo.order_id
            WHERE wo.listing != %(source)s
            GROUP BY wo.listing
        )
        SELECT ab.listing AS listing,
               ab.ab_n AS ab_n,
               bc.b_n AS b_n,
               (SELECT COUNT(DISTINCT order_id) FROM a_orders) AS a_n,
               (SELECT n FROM total) AS total_n
        FROM ab_counts ab
        INNER JOIN b_counts bc ON bc.listing = ab.listing
        WHERE ab.ab_n >= 2
        """,
		{"source": source_id, "days": COPURCHASE_WINDOW_DAYS},
		as_dict=True,
	)

	out: list[dict[str, Any]] = []
	for r in rows:
		ab_n = int(r["ab_n"])
		b_n = int(r["b_n"])
		a_n = int(r["a_n"] or 0)
		total_n = int(r["total_n"] or 0)
		if a_n == 0 or b_n == 0 or total_n == 0:
			continue
		# lift = (ab_n / total_n) / ((a_n / total_n) * (b_n / total_n))
		#      = ab_n * total_n / (a_n * b_n)
		lift = (ab_n * total_n) / (a_n * b_n)
		if lift < lift_threshold:
			continue
		out.append({"listing": r["listing"], "lift": lift})
	out.sort(key=lambda x: x["lift"], reverse=True)
	return out[:50]  # cap for downstream scoring


def _coview_candidates(source_id: str) -> list[dict[str, Any]]:
	"""Within the last N days, which listings co-occur with source in the
	same user's browsing history? Ratio = co_views / total_source_views.
	"""
	rows = frappe.db.sql(
		"""
        WITH source_viewers AS (
            SELECT DISTINCT `user` AS user_name
            FROM `tabUser Product View`
            WHERE listing = %(source)s
              AND creation >= DATE_SUB(NOW(), INTERVAL %(days)s DAY)
        ),
        peer_views AS (
            SELECT upv.listing, COUNT(DISTINCT upv.`user`) AS peers
            FROM `tabUser Product View` upv
            INNER JOIN source_viewers sv ON sv.user_name = upv.`user`
            WHERE upv.listing != %(source)s
              AND upv.creation >= DATE_SUB(NOW(), INTERVAL %(days)s DAY)
            GROUP BY upv.listing
        )
        SELECT listing, peers FROM peer_views
        WHERE peers >= 2
        ORDER BY peers DESC
        LIMIT 50
        """,
		{"source": source_id, "days": COVIEW_WINDOW_DAYS},
		as_dict=True,
	)

	if not rows:
		return []
	total = max(int(rows[0]["peers"]), 1)
	return [{"listing": r["listing"], "ratio": min(1.0, int(r["peers"]) / total)} for r in rows]


def _category_of(listing_id: str) -> str | None:
	return frappe.db.get_value("Listing", listing_id, "product_category")


def _embedding_similarity(source_cat: str | None, cand_cat: str | None, threshold: float) -> float:
	if not source_cat or not cand_cat or source_cat == cand_cat:
		return 0.0
	sim = embeddings.category_similarity(source_cat, cand_cat)
	if sim < threshold:
		return 0.0
	# Stretch the threshold..1 range back to 0..1 so a threshold match
	# contributes something meaningful to the final score.
	span = max(1e-6, 1.0 - threshold)
	return max(0.0, min(1.0, (sim - threshold) / span))


def _embedding_fallback_rows(
	source_id: str,
	source_category: str | None,
	seen: set[str],
	weights: dict[str, float],
	threshold: float,
	min_score: float,
	need: int,
) -> list[ScoreRow]:
	if not source_category or need <= 0:
		return []

	related_cats = embeddings.neighbour_categories(source_category, top_k=5, threshold=threshold)
	if not related_cats:
		return []

	rows: list[ScoreRow] = []
	for cat, cat_sim in related_cats:
		candidates = frappe.db.sql(
			"""
            SELECT name FROM `tabListing`
            WHERE product_category = %s
              AND status = 'Active'
              AND is_visible = 1
              AND name != %s
            ORDER BY order_count DESC, average_rating DESC
            LIMIT 5
            """,
			(cat, source_id),
			as_dict=True,
		)
		for c in candidates:
			if c["name"] in seen:
				continue
			# Only the embedding signal fires in the fallback path.
			# Mapping back the already-stretched similarity keeps the score
			# comparable with the behavioural rows above.
			span = max(1e-6, 1.0 - threshold)
			stretched = max(0.0, min(1.0, (cat_sim - threshold) / span))
			final = weights["embedding"] * stretched
			if final < min_score:
				continue
			seen.add(c["name"])
			rows.append(
				ScoreRow(
					source_listing=source_id,
					target_listing=c["name"],
					relation_type="Complementary",
					base_score=final,
				)
			)
			if len(rows) >= need:
				return rows
	return rows
