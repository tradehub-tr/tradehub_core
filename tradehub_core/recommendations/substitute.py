"""Substitute (İkame) product scorer.

Like Similar, but weights *different seller* candidates — the buyer's
intent here is "show me an alternative supplier for roughly the same item".

    score = w_same_category    × category_match
          + w_different_seller × seller_differs
          + w_attribute        × attribute_similarity
          + w_price_proximity  × price_proximity
"""

from __future__ import annotations

from typing import Any

from .common import (
	ScoreRow,
	attribute_similarity,
	fetch_candidate_listings_same_category,
	load_listing_attribute_vector,
	price_proximity,
)


def score_for_listing(
	source: dict[str, Any], weights: dict[str, float], max_results: int, min_score: float
) -> list[ScoreRow]:
	candidates = fetch_candidate_listings_same_category(source["name"], source.get("product_category"))
	if not candidates:
		return []

	source_attrs = load_listing_attribute_vector(source["name"])
	source_seller = source.get("seller_profile")
	source_price = float(source.get("selling_price") or 0)

	rows: list[ScoreRow] = []
	for cand in candidates:
		cand_attrs = load_listing_attribute_vector(cand["name"])

		s_same_cat = 1.0  # pre-filtered by category
		s_diff_seller = 1.0 if cand.get("seller_profile") != source_seller else 0.0
		s_attr = attribute_similarity(source_attrs, cand_attrs)
		s_price = price_proximity(source_price, float(cand.get("selling_price") or 0))

		final = (
			weights["same_category"] * s_same_cat
			+ weights["different_seller"] * s_diff_seller
			+ weights["attribute"] * s_attr
			+ weights["price_proximity"] * s_price
		)

		if final >= min_score:
			rows.append(
				ScoreRow(
					source_listing=source["name"],
					target_listing=cand["name"],
					relation_type="Substitute",
					base_score=final,
				)
			)

	rows.sort(key=lambda r: r.base_score, reverse=True)
	return rows[:max_results]
