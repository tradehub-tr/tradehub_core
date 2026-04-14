"""Accessory (Aksesuar) product scorer.

NLP-ish content matching:

    score = w_token              × title_token_match
          + w_price_ratio        × price_ratio_ok
          + w_category_pattern   × accessory_category_flag
          + w_copurchase         × has_copurchase_signal

Token match fires when the candidate's title references the source product
(e.g. "<SourceBrand> için …", "… compatible with <SourceModel>"). Paired
with a price-ratio filter this rules out spare parts (e.g. a replacement
screen at full phone price).
"""
from __future__ import annotations

import re
from typing import Any

import frappe

from .common import ScoreRow


ACCESSORY_TRIGGER_TOKENS = (
    "için",
    "uyumlu",
    "compatible",
    "fits",
    "accessory for",
    "for use with",
)


def score_for_listing(
    source: dict[str, Any],
    weights: dict[str, float],
    max_results: int,
    min_score: float,
    price_ratio_threshold: float,
) -> list[ScoreRow]:
    source_title = (source.get("title") or "").lower().strip()
    source_brand = (source.get("brand") or "").lower().strip()
    source_price = float(source.get("selling_price") or 0)
    source_id = source["name"]

    if not source_title or source_price <= 0:
        return []

    # Build the set of strings that, if found in a candidate title, suggest
    # "this is made for the source product": brand name + leading 2-3 words
    # of the source title.
    anchor_phrases: set[str] = set()
    if source_brand and len(source_brand) >= 3:
        anchor_phrases.add(source_brand)
    source_anchor = _leading_anchor(source_title)
    if source_anchor:
        anchor_phrases.add(source_anchor)

    if not anchor_phrases:
        return []

    # Candidate pool: listings whose title contains any anchor phrase.
    # We keep the SQL simple with an OR chain over LIKE matches.
    where_parts = []
    params: list[Any] = []
    for ph in anchor_phrases:
        where_parts.append("LOWER(title) LIKE %s")
        params.append(f"%{ph}%")
    where_sql = " OR ".join(where_parts)

    candidates = frappe.db.sql(
        f"""
        SELECT l.name, l.title, l.selling_price, l.product_category,
               pc.is_accessory_category
        FROM `tabListing` l
        LEFT JOIN `tabProduct Category` pc ON pc.name = l.product_category
        WHERE l.status = 'Active'
          AND l.is_visible = 1
          AND l.name != %s
          AND l.selling_price > 0
          AND ({where_sql})
        ORDER BY l.order_count DESC
        LIMIT 100
        """,
        tuple([source_id] + params),
        as_dict=True,
    )
    if not candidates:
        return []

    # Pre-pull copurchase signal once (top N accessory-candidate peers).
    copurchase_ids = _copurchase_peer_ids(source_id)

    rows: list[ScoreRow] = []
    for c in candidates:
        cand_title = (c.get("title") or "").lower()

        s_token = _token_match_score(cand_title, anchor_phrases)
        s_price = _price_ratio_score(source_price, float(c.get("selling_price") or 0), price_ratio_threshold)
        s_category = 1.0 if c.get("is_accessory_category") else 0.0
        s_copurchase = 1.0 if c["name"] in copurchase_ids else 0.0

        final = (
            weights["token"] * s_token
            + weights["price_ratio"] * s_price
            + weights["category_pattern"] * s_category
            + weights["copurchase"] * s_copurchase
        )
        if final >= min_score:
            rows.append(
                ScoreRow(
                    source_listing=source_id,
                    target_listing=c["name"],
                    relation_type="Accessory",
                    base_score=final,
                )
            )

    rows.sort(key=lambda r: r.base_score, reverse=True)
    return rows[:max_results]


# ─── helpers ─────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[a-zçğıöşü0-9]+", re.IGNORECASE)


def _leading_anchor(title: str) -> str:
    """First 2-3 content words of the product title, joined with space.

    Meant to capture things like "iPhone 15 Pro", "Bosch Profesyonel",
    "Toyota Corolla" — enough to be specific, short enough to still match
    candidates that mention the base product.
    """
    words = _WORD_RE.findall(title)
    meaningful = [w for w in words if len(w) >= 3]
    if not meaningful:
        return ""
    return " ".join(meaningful[:3]) if len(meaningful) >= 3 else " ".join(meaningful[:2])


def _token_match_score(candidate_title: str, anchor_phrases: set[str]) -> float:
    """1.0 if candidate contains an anchor AND an accessory trigger word,
    0.6 if only anchor, else 0.
    """
    has_anchor = any(ph in candidate_title for ph in anchor_phrases)
    if not has_anchor:
        return 0.0
    for trig in ACCESSORY_TRIGGER_TOKENS:
        if trig in candidate_title:
            return 1.0
    return 0.6


def _price_ratio_score(source_price: float, candidate_price: float, threshold: float) -> float:
    """1.0 when candidate is well below threshold × source, 0 when at/above."""
    if source_price <= 0 or candidate_price <= 0:
        return 0.0
    ratio = candidate_price / source_price
    if ratio <= threshold:
        return 1.0
    if ratio >= threshold * 2:
        return 0.0
    # linear decay between threshold and 2×threshold
    span = threshold
    return max(0.0, 1.0 - (ratio - threshold) / span)


def _copurchase_peer_ids(source_id: str) -> set[str]:
    rows = frappe.db.sql(
        """
        SELECT DISTINCT oi2.listing
        FROM `tabOrder Item` oi1
        INNER JOIN `tabOrder Item` oi2 ON oi1.parent = oi2.parent
        WHERE oi1.listing = %s
          AND oi2.listing != %s
          AND oi2.listing IS NOT NULL
          AND oi2.listing != ''
        LIMIT 100
        """,
        (source_id, source_id),
        as_dict=True,
    )
    return {r["listing"] for r in rows}
