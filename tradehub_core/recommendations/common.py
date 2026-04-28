"""Shared primitives for the 4 Related Products scorers.

Concentrates anything that's used by ≥2 of similar/substitute/complementary/
accessory so the individual scorers stay readable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import frappe

# Axes that are variant-selector axes, not genuine similarity signals.
# Excluded from attribute cosine similarity (otherwise every red XL vs
# blue XL comparison tanks the score).
VARIANT_AXES = {"color", "renk", "size", "beden", "boyut"}


@dataclass
class ScoreRow:
	source_listing: str
	target_listing: str
	relation_type: str
	base_score: float


# ─── Candidate pool helpers ──────────────────────────────────────────────

# How many days of order history to consider for co-purchase lift.
COPURCHASE_WINDOW_DAYS = 90

# How many days of view history to consider for co-view.
COVIEW_WINDOW_DAYS = 30

# Hard cap on candidate pool size per scorer — guards against runaway
# comparisons in very large categories. Picked above typical category
# size; tune if batch starts timing out.
MAX_CANDIDATES = 200


def fetch_candidate_listings_same_category(source_id: str, category: str | None) -> list[dict[str, Any]]:
	if not category:
		return []
	return frappe.db.sql(
		"""
        SELECT name, seller_profile, price_tier, selling_price, average_rating,
               title, description, brand, product_category
        FROM `tabListing`
        WHERE product_category = %s
          AND status = 'Active'
          AND is_visible = 1
          AND name != %s
          AND selling_price > 0
        ORDER BY order_count DESC, average_rating DESC
        LIMIT %s
        """,
		(category, source_id, MAX_CANDIDATES),
		as_dict=True,
	)


def fetch_all_active_listings(batch_size: int = 5000) -> list[dict[str, Any]]:
	return frappe.db.sql(
		f"""
        SELECT name, seller_profile, price_tier, selling_price, average_rating,
               title, description, brand, product_category
        FROM `tabListing`
        WHERE status = 'Active'
          AND is_visible = 1
          AND selling_price > 0
        LIMIT {int(batch_size)}
        """,
		as_dict=True,
	)


# ─── Attribute vector helpers ────────────────────────────────────────────

_ATTR_CACHE: dict[str, dict[str, str]] = {}


def clear_attribute_cache() -> None:
	_ATTR_CACHE.clear()


def load_listing_attribute_vector(listing_id: str) -> dict[str, str]:
	"""Return {attribute_name_lower: value_lower} for a listing, cached for the batch run."""
	if listing_id in _ATTR_CACHE:
		return _ATTR_CACHE[listing_id]

	rows = frappe.db.sql(
		"""
        SELECT attribute, attribute_value
        FROM `tabListing Attribute Value`
        WHERE parent = %s
        """,
		(listing_id,),
		as_dict=True,
	)
	vec: dict[str, str] = {}
	for r in rows:
		name = (r.get("attribute") or "").strip().lower()
		val = (r.get("attribute_value") or "").strip().lower()
		if not name or not val:
			continue
		if name in VARIANT_AXES:
			continue
		vec[name] = val
	_ATTR_CACHE[listing_id] = vec
	return vec


def attribute_similarity(a: dict[str, str], b: dict[str, str]) -> float:
	"""Jaccard-style similarity over (key, value) pairs — simpler than
	cosine over one-hot and behaves well when attribute sets are small.

	Returns a float in [0, 1].
	"""
	if not a or not b:
		return 0.0
	a_pairs = {f"{k}={v}" for k, v in a.items()}
	b_pairs = {f"{k}={v}" for k, v in b.items()}
	intersection = a_pairs & b_pairs
	union = a_pairs | b_pairs
	if not union:
		return 0.0
	return len(intersection) / len(union)


# ─── Scalar signal helpers ──────────────────────────────────────────────


def price_tier_match(source_tier: str | None, cand_tier: str | None) -> float:
	"""1.0 if same Q-bucket, 0.5 if adjacent, else 0.0."""
	if not source_tier or not cand_tier:
		return 0.0
	order = ["Q1", "Q2", "Q3", "Q4"]
	try:
		ai = order.index(source_tier)
		bi = order.index(cand_tier)
	except ValueError:
		return 0.0
	diff = abs(ai - bi)
	if diff == 0:
		return 1.0
	if diff == 1:
		return 0.5
	return 0.0


def rating_proximity(a: float, b: float) -> float:
	"""1.0 if ratings within 0.2, scales to 0 at delta=1.5."""
	if a <= 0 or b <= 0:
		return 0.5  # one of them unrated — neutral
	delta = abs(a - b)
	if delta >= 1.5:
		return 0.0
	return max(0.0, 1.0 - (delta / 1.5))


def price_proximity(a: float, b: float) -> float:
	"""1.0 if identical, 0 if ratio > 2×. Smooth linear in between."""
	if a <= 0 or b <= 0:
		return 0.0
	hi = max(a, b)
	lo = min(a, b)
	ratio = lo / hi  # 0..1
	# ratio >= 0.8 → very close; ratio <= 0.5 → far apart
	if ratio >= 0.8:
		return 1.0
	if ratio <= 0.5:
		return 0.0
	return (ratio - 0.5) / 0.3


# ─── Vector math (used by embeddings fallback) ──────────────────────────


def cosine(a: list[float], b: list[float]) -> float:
	"""Dense cosine — kept for legacy callers and unit comparison."""
	if not a or not b or len(a) != len(b):
		return 0.0
	dot = sum(x * y for x, y in zip(a, b, strict=False))
	na = math.sqrt(sum(x * x for x in a))
	nb = math.sqrt(sum(y * y for y in b))
	if na == 0 or nb == 0:
		return 0.0
	return dot / (na * nb)


def sparse_cosine(a: dict[str, float], b: dict[str, float]) -> float:
	"""Cosine for sparse vectors stored as {key: weight}.

	O(min(|a|, |b|)) over the intersection — vocab-size independent.
	Computes a true cosine (no pre-normalisation assumption) so callers
	can safely mix L2-normalised embeddings with raw weight maps.
	"""
	if not a or not b:
		return 0.0
	if len(a) > len(b):
		a, b = b, a
	dot = 0.0
	for k, weight in a.items():
		other = b.get(k)
		if other is not None:
			dot += weight * other
	if dot == 0.0:
		return 0.0
	norm_a = math.sqrt(sum(w * w for w in a.values()))
	norm_b = math.sqrt(sum(w * w for w in b.values()))
	if norm_a == 0 or norm_b == 0:
		return 0.0
	return dot / (norm_a * norm_b)
