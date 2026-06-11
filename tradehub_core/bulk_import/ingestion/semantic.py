"""TF-IDF semantic resolver — short-text header similarity."""

import hashlib
import re

import frappe
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from tradehub_core.bulk_import.ingestion.canonical_fields import build_corpus

SEMANTIC_CACHE_TTL = 24 * 3600  # 24 saat per-header
CONFIDENCE_THRESHOLD = 0.75

_vectorizer: TfidfVectorizer | None = None
_field_vectors = None
_field_labels: list[str] | None = None

# Türkçe karakterleri ASCII'ye indir — canonical alias'lar ASCII ("birim fiyat")
# olduğundan, başlıklar fold edilmezse "BİRİM FİYAT" str.lower() ile "bi̇rim"
# (combining dot) üretir ve char n-gram'lar uyuşmaz → düşük benzerlik. resolver
# tarafıyla aynı fold tablosu (bkz. resolver._TR_FOLD).
_TR_FOLD = str.maketrans(
	{
		"ı": "i",
		"İ": "i",
		"ş": "s",
		"Ş": "s",
		"ğ": "g",
		"Ğ": "g",
		"ü": "u",
		"Ü": "u",
		"ö": "o",
		"Ö": "o",
		"ç": "c",
		"Ç": "c",
	}
)


def _ensure_vectorizer() -> None:
	"""Lazy init TF-IDF — corpus fit'i sadece 1 kez."""
	global _vectorizer, _field_vectors, _field_labels
	if _vectorizer is not None:
		return
	corpus = build_corpus()
	_field_labels = [field for field, _syn in corpus]
	texts = [_normalize(syn) for _field, syn in corpus]
	_vectorizer = TfidfVectorizer(
		analyzer="char_wb",
		ngram_range=(2, 4),
		lowercase=True,
		sublinear_tf=True,
	)
	_field_vectors = _vectorizer.fit_transform(texts)


def _normalize(text: str) -> str:
	"""Türkçe-fold + lowercase, strip, collapse whitespace, remove non-word chars."""
	text = (text or "").translate(_TR_FOLD).lower().strip()
	text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
	text = re.sub(r"\s+", " ", text)
	return text


def resolve_header_semantic(header: str) -> tuple[str | None, float]:
	"""Header'ı canonical field'a TF-IDF cosine similarity ile eşle.

	Returns: (field_name | None, confidence_score)
	"""
	if not header or not header.strip():
		return None, 0.0

	# Cache lookup
	cache_key = _cache_key(header)
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		return cached.get("field"), cached.get("score", 0.0)

	_ensure_vectorizer()

	query = _normalize(header)
	query_vec = _vectorizer.transform([query])
	sims = cosine_similarity(query_vec, _field_vectors).flatten()

	# Aggregate by field: max similarity per field
	field_scores: dict[str, float] = {}
	for i, sim in enumerate(sims):
		field = _field_labels[i]
		if sim > field_scores.get(field, 0.0):
			field_scores[field] = float(sim)

	# En iyi eşleşme
	if not field_scores:
		result: tuple[str | None, float] = (None, 0.0)
	else:
		best_field = max(field_scores, key=field_scores.get)
		best_score = field_scores[best_field]
		result = (best_field, best_score) if best_score >= CONFIDENCE_THRESHOLD else (None, best_score)

	# Cache write
	frappe.cache.set_value(
		cache_key,
		{"field": result[0], "score": result[1]},
		expires_in_sec=SEMANTIC_CACHE_TTL,
	)
	return result


def _cache_key(header: str) -> str:
	h = hashlib.sha1(_normalize(header).encode("utf-8")).hexdigest()[:16]
	return f"semantic_header:{h}"


def clear_semantic_cache() -> None:
	"""Test/debug için cache temizle."""
	try:
		frappe.cache.delete_keys("semantic_header:*")
	except Exception:
		# Cache temizleme kritik değil — log gerekmiyor
		pass
