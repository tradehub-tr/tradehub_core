"""Similar (Benzer) product scorer.

Content-based filtering:

    score = w_category   × category_match
          + w_attribute  × attribute_cosine_similarity
          + w_price_tier × price_tier_match
          + w_rating     × rating_proximity

Weights come from `Related Products Settings`. Only candidates within the
same leaf category are considered — keeps the candidate pool small enough
to run inside the nightly batch without needing a separate similarity index.
"""

from __future__ import annotations

from typing import Any

from .common import (
	ScoreRow,
	attribute_similarity,
	fetch_candidate_listings_same_category,
	load_listing_attribute_vector,
	price_tier_match,
	rating_proximity,
)


def score_for_listing(
	source: dict[str, Any], weights: dict[str, float], max_results: int, min_score: float
) -> list[ScoreRow]:
	"""Return top-N Similar candidates for a source listing.

	`source` must contain at minimum: name, product_category, price_tier,
	selling_price, average_rating. Attribute vector is loaded internally.
	"""
	candidates = fetch_candidate_listings_same_category(source["name"], source.get("product_category"))
	if not candidates:
		return []

	source_attrs = load_listing_attribute_vector(source["name"])
	source_tier = source.get("price_tier") or "Q2"
	source_rating = float(source.get("average_rating") or 0.0)

	rows: list[ScoreRow] = []
	for cand in candidates:
		cand_attrs = load_listing_attribute_vector(cand["name"])

		# 1) Same leaf category → always 1.0 here (candidate pool is
		# pre-filtered by category). Kept as a multiplier so future pool
		# widening doesn't break scoring.
		s_category = 1.0

		# 2) Attribute cosine similarity (excluding highly-variant axes
		# like Color/Size which are handled by variants, not similarity).
		s_attr = attribute_similarity(source_attrs, cand_attrs)

		# 3) Price tier match (Q1..Q4)
		s_price = price_tier_match(source_tier, cand.get("price_tier"))

		# 4) Rating proximity (|Δrating| < 0.5 → high score)
		s_rating = rating_proximity(source_rating, float(cand.get("average_rating") or 0.0))

		final = (
			weights["category"] * s_category
			+ weights["attribute"] * s_attr
			+ weights["price_tier"] * s_price
			+ weights["rating"] * s_rating
		)

		if final >= min_score:
			rows.append(
				ScoreRow(
					source_listing=source["name"],
					target_listing=cand["name"],
					relation_type="Similar",
					base_score=final,
				)
			)

	rows.sort(key=lambda r: r.base_score, reverse=True)
	return rows[:max_results]
