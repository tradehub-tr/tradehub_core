"""Category embedding provider — used as the cold-start fallback in the
Complementary scorer.

MVP ships with a pure-Python TF-IDF over character n-grams. No external
model download, no network call. If/when a proper transformer model is
bundled, swap the implementation of `_embed_text()` and bump the stored
`model_version`. Downstream consumers read similarity via
`category_similarity(a, b)` and don't care which model produced the vector.

Why character n-grams and not word vectors?
  Category names are short and often single-word ("Kazak", "Pantolon").
  Character n-grams pick up morphological neighbours ("Kazak"↔"Kazaklar")
  without needing Turkish stemming. Good enough until an upgrade path.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from typing import Any

import frappe

from .common import cosine


MODEL_VERSION = "tfidf-charngram-v1"
NGRAM_MIN = 3
NGRAM_MAX = 4

_VECTOR_CACHE: dict[str, list[float]] = {}
_FEATURE_VOCAB: dict[str, int] | None = None


def clear_cache() -> None:
    global _FEATURE_VOCAB
    _VECTOR_CACHE.clear()
    _FEATURE_VOCAB = None


# ─── Public API ──────────────────────────────────────────────────────────

def build_all() -> dict[str, Any]:
    """Embed every Product Category and persist into Category Embedding.

    Called manually from setup, and weekly from the scheduler.
    Idempotent — re-running just overwrites stored vectors.
    """
    names = frappe.db.sql(
        "SELECT name, category_name FROM `tabProduct Category` WHERE is_active = 1",
        as_dict=True,
    )
    if not names:
        return {"embedded": 0}

    vocab = _build_global_vocab([row["category_name"] or row["name"] for row in names])
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    embedded = 0
    for row in names:
        text = (row["category_name"] or row["name"]).lower()
        vec = _vectorize(text, vocab)
        _persist(row["name"], vec, now)
        embedded += 1
    frappe.db.commit()
    clear_cache()
    return {"embedded": embedded, "model_version": MODEL_VERSION}


def category_similarity(cat_a: str, cat_b: str) -> float:
    """Cosine similarity between two category embeddings. 0 if either is
    missing a vector.
    """
    if cat_a == cat_b:
        return 1.0
    v1 = _load_vector(cat_a)
    v2 = _load_vector(cat_b)
    if not v1 or not v2:
        return 0.0
    return cosine(v1, v2)


def neighbour_categories(category: str, top_k: int = 5, threshold: float = 0.6) -> list[tuple[str, float]]:
    """Return [(category, similarity), …] for the top_k most similar
    categories (excluding `category` itself) whose similarity ≥ threshold.

    This is what the Complementary fallback uses: "no co-purchase data for
    this listing — what categories is its category semantically close to?"
    """
    source_vec = _load_vector(category)
    if not source_vec:
        return []

    rows = frappe.db.sql(
        "SELECT category, vector FROM `tabCategory Embedding`",
        as_dict=True,
    )
    sims: list[tuple[str, float]] = []
    for r in rows:
        if r["category"] == category:
            continue
        vec = _deserialize(r["vector"])
        if not vec:
            continue
        sim = cosine(source_vec, vec)
        if sim >= threshold:
            sims.append((r["category"], sim))
    sims.sort(key=lambda x: x[1], reverse=True)
    return sims[:top_k]


# ─── Internals: TF-IDF-lite over char n-grams ───────────────────────────

def _ngrams(text: str) -> list[str]:
    text = " " + text.strip() + " "
    out: list[str] = []
    for n in range(NGRAM_MIN, NGRAM_MAX + 1):
        if len(text) < n:
            continue
        for i in range(len(text) - n + 1):
            out.append(text[i : i + n])
    return out


def _build_global_vocab(texts: list[str]) -> dict[str, int]:
    df: Counter[str] = Counter()
    for t in texts:
        grams = set(_ngrams(t.lower()))
        for g in grams:
            df[g] += 1
    vocab = {g: i for i, g in enumerate(sorted(df.keys()))}
    # stash IDF for later vectorize call — flat dict, minor waste ok
    global _FEATURE_VOCAB
    _FEATURE_VOCAB = vocab
    _FEATURE_VOCAB_IDF.clear()
    n_docs = max(len(texts), 1)
    for g, c in df.items():
        _FEATURE_VOCAB_IDF[g] = math.log((1 + n_docs) / (1 + c)) + 1
    return vocab


_FEATURE_VOCAB_IDF: dict[str, float] = {}


def _vectorize(text: str, vocab: dict[str, int]) -> list[float]:
    grams = _ngrams(text.lower())
    if not grams:
        return []
    tf: Counter[str] = Counter(grams)
    vec = [0.0] * len(vocab)
    for g, c in tf.items():
        idx = vocab.get(g)
        if idx is None:
            continue
        idf = _FEATURE_VOCAB_IDF.get(g, 1.0)
        vec[idx] = c * idf
    # L2 normalise
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _persist(category_name: str, vec: list[float], computed_at: str) -> None:
    """Upsert into Category Embedding. Uses raw SQL to avoid the Document
    overhead for a tight loop over ~hundreds of categories.
    """
    serialized = json.dumps(vec)
    exists = frappe.db.exists("Category Embedding", category_name)
    if exists:
        frappe.db.sql(
            """
            UPDATE `tabCategory Embedding`
            SET vector = %s, model_version = %s, computed_at = %s, modified = NOW()
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


def _load_vector(category: str) -> list[float]:
    if category in _VECTOR_CACHE:
        return _VECTOR_CACHE[category]
    raw = frappe.db.get_value("Category Embedding", category, "vector")
    vec = _deserialize(raw)
    _VECTOR_CACHE[category] = vec
    return vec


def _deserialize(raw: Any) -> list[float]:
    if not raw:
        return []
    try:
        out = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(out, list):
        return []
    return [float(x) for x in out]


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

    Scans the category's name and description for any accessory keyword.
    Idempotent: only writes when the computed flag differs from the stored
    value, which keeps `modified` stable for categories we didn't touch.
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
