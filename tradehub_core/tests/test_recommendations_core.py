"""Pure-Python unit tests for the Related Products engine internals.

Covers the sparse-vector pipeline (Phase 1), the chunking + keyset stream
helpers (Phase 5), and the legacy-format deserialization compatibility
contract. Frappe runtime is stubbed at module import time so tests run
with plain `python -m unittest` — no bench shell needed.

Run:
    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_recommendations_core
"""

from __future__ import annotations

import math
import sys
import types
import unittest
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────
# Path + frappe stub — must run BEFORE any tradehub_core.recommendations
# import, since those modules do `import frappe` at module load time.
# ──────────────────────────────────────────────────────────────────────────
_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


def _install_frappe_stub() -> None:
	"""Provide a minimal `frappe` module so the recommendations package
	can be imported and its pure-Python helpers exercised in isolation.
	"""
	if "frappe" in sys.modules:
		return
	frappe_stub = types.ModuleType("frappe")

	def _noop(*_a, **_k):
		return None

	class _DBStub:
		def sql(self, *_a, **_k):
			return []

		def sql_list(self, *_a, **_k):
			return []

		def get_value(self, *_a, **_k):
			return None

		def exists(self, *_a, **_k):
			return False

		def count(self, *_a, **_k):
			return 0

		def commit(self):
			pass

		def table_exists(self, _name):
			return False

		def delete(self, *_a, **_k):
			return None

		def set_value(self, *_a, **_k):
			return None

		def get_table_columns(self, *_a, **_k):
			return []

	frappe_stub.db = _DBStub()
	frappe_stub.cache = lambda: types.SimpleNamespace(
		get_value=_noop,
		set_value=_noop,
		delete_key=_noop,
		get=_noop,
		set=_noop,
		incr=_noop,
		delete=_noop,
		expire=_noop,
	)
	frappe_stub.generate_hash = lambda length=10: "x" * length
	frappe_stub.log_error = _noop
	frappe_stub.logger = lambda _name=None: types.SimpleNamespace(
		info=_noop,
		warning=_noop,
		error=_noop,
		debug=_noop,
	)
	frappe_stub.enqueue = _noop
	frappe_stub.new_doc = _noop
	frappe_stub.get_doc = _noop
	frappe_stub.get_single = _noop
	frappe_stub.local = types.SimpleNamespace(
		cache={},
		conf=types.SimpleNamespace(db_name="testdb"),
	)
	frappe_stub.conf = types.SimpleNamespace(db_name="testdb")
	sys.modules["frappe"] = frappe_stub

	# frappe.model.document.Document — referenced by some doctype controllers
	frappe_model = types.ModuleType("frappe.model")
	frappe_model_doc = types.ModuleType("frappe.model.document")

	class _Document:
		pass

	frappe_model_doc.Document = _Document
	sys.modules["frappe.model"] = frappe_model
	sys.modules["frappe.model.document"] = frappe_model_doc


_install_frappe_stub()


from tradehub_core.recommendations import embeddings  # noqa: E402
from tradehub_core.recommendations import engine as engine_mod  # noqa: E402
from tradehub_core.recommendations.common import cosine, sparse_cosine  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Sparse vs Dense Cosine Equivalence
# ──────────────────────────────────────────────────────────────────────────
class TestSparseCosine(unittest.TestCase):
	"""sparse_cosine must match dense cosine on the same logical vector."""

	def test_identical_vectors_yield_one(self):
		v = {"a": 0.6, "b": 0.8}  # norm = 1
		self.assertAlmostEqual(sparse_cosine(v, v), 1.0, places=6)

	def test_orthogonal_vectors_yield_zero(self):
		a = {"a": 1.0}
		b = {"b": 1.0}
		self.assertEqual(sparse_cosine(a, b), 0.0)

	def test_partial_overlap_matches_dense(self):
		# Build dense + sparse representations of the same vectors
		keys = ["a", "b", "c", "d"]
		dense_a = [1.0, 2.0, 0.0, 3.0]
		dense_b = [0.0, 2.0, 1.0, 4.0]
		sparse_a = {k: v for k, v in zip(keys, dense_a, strict=False) if v != 0}
		sparse_b = {k: v for k, v in zip(keys, dense_b, strict=False) if v != 0}

		self.assertAlmostEqual(
			sparse_cosine(sparse_a, sparse_b),
			cosine(dense_a, dense_b),
			places=6,
		)

	def test_empty_vector_yields_zero(self):
		self.assertEqual(sparse_cosine({}, {"a": 1.0}), 0.0)
		self.assertEqual(sparse_cosine({"a": 1.0}, {}), 0.0)
		self.assertEqual(sparse_cosine({}, {}), 0.0)

	def test_handles_argument_swap_for_efficiency(self):
		# The implementation iterates the smaller dict; result must be invariant.
		big = {chr(c): float(c) for c in range(ord("a"), ord("z") + 1)}
		small = {"a": 1.0, "z": 2.0}
		self.assertAlmostEqual(
			sparse_cosine(big, small),
			sparse_cosine(small, big),
			places=6,
		)


# ──────────────────────────────────────────────────────────────────────────
# N-gram + IDF + Vectorize Pipeline
# ──────────────────────────────────────────────────────────────────────────
class TestNgramPipeline(unittest.TestCase):
	def test_ngrams_includes_word_boundaries(self):
		# _ngrams pads with spaces so prefix/suffix grams capture edges.
		grams = embeddings._ngrams("ab")
		# text becomes " ab ", length 4 → 3-grams: " ab", "ab "; 4-grams: " ab "
		self.assertIn(" ab", grams)
		self.assertIn("ab ", grams)
		self.assertIn(" ab ", grams)

	def test_ngrams_empty_text_returns_empty(self):
		# text becomes "  " (just two spaces), length 2 < NGRAM_MIN=3
		self.assertEqual(embeddings._ngrams(""), [])

	def test_ngrams_short_text_under_min(self):
		# "a" → " a ", length 3 → only 3-gram " a "
		grams = embeddings._ngrams("a")
		self.assertEqual(grams, [" a "])

	def test_compute_idf_basic_properties(self):
		texts = ["pantolon", "kazak", "ceket", "pantolon"]
		idf = embeddings._compute_idf(texts)
		# Every ngram should map to a positive IDF weight
		self.assertTrue(all(v > 0 for v in idf.values()))
		# Common ngrams across multiple docs get LOWER weight than rare ones
		# (idf formula: log((1+N)/(1+df)) + 1, monotonically decreasing in df)
		common = embeddings._ngrams("pantolon")  # appears 2x
		rare = embeddings._ngrams("kazak")  # appears 1x
		common_weight = idf.get(common[0]) if common else None
		rare_weight = idf.get(rare[0]) if rare else None
		if common_weight and rare_weight and common[0] != rare[0]:
			self.assertLessEqual(common_weight, rare_weight)

	def test_vectorize_sparse_is_l2_normalised(self):
		idf = embeddings._compute_idf(["pantolon", "kazak"])
		vec = embeddings._vectorize_sparse("pantolon", idf)
		norm = math.sqrt(sum(v * v for v in vec.values()))
		self.assertAlmostEqual(norm, 1.0, places=6)

	def test_vectorize_unknown_text_yields_empty(self):
		# Vocab doesn't contain ngrams for "xyz", so vector is empty
		idf = embeddings._compute_idf(["pantolon"])
		vec = embeddings._vectorize_sparse("xyz", idf)
		# "xyz" → " xyz " → 3-grams: " xy", "xyz", "yz "; 4-grams: " xyz", "xyz "
		# None overlap with "pantolon" ngrams → empty vector expected
		self.assertEqual(vec, {})

	def test_vectorize_self_similarity_is_one(self):
		idf = embeddings._compute_idf(["kazak", "ceket"])
		vec_a = embeddings._vectorize_sparse("kazak", idf)
		vec_b = embeddings._vectorize_sparse("kazak", idf)
		self.assertAlmostEqual(sparse_cosine(vec_a, vec_b), 1.0, places=6)


# ──────────────────────────────────────────────────────────────────────────
# Deserialize Legacy + Sparse Format
# ──────────────────────────────────────────────────────────────────────────
class TestDeserialize(unittest.TestCase):
	def test_sparse_dict_roundtrip(self):
		import json

		original = {"abc": 0.5, "def": 0.866}
		raw = json.dumps(original)
		result = embeddings._deserialize(raw)
		self.assertEqual(result, original)

	def test_legacy_dense_list_returns_empty(self):
		# Old format was a JSON list of floats. New code treats as unsupported.
		raw = "[0.0, 0.123, 0.456, 0.0]"
		self.assertEqual(embeddings._deserialize(raw), {})

	def test_malformed_json_returns_empty(self):
		self.assertEqual(embeddings._deserialize("{not json}"), {})
		self.assertEqual(embeddings._deserialize(""), {})
		self.assertEqual(embeddings._deserialize(None), {})

	def test_string_keys_and_float_values_normalised(self):
		# Mixed types should be coerced to str/float
		import json

		raw = json.dumps({"abc": 1, "def": "0.5"})
		result = embeddings._deserialize(raw)
		self.assertEqual(result, {"abc": 1.0, "def": 0.5})


# ──────────────────────────────────────────────────────────────────────────
# Chunkify (Phase 5 — generator-aware)
# ──────────────────────────────────────────────────────────────────────────
class TestChunkify(unittest.TestCase):
	def test_chunkify_list(self):
		chunks = list(engine_mod._chunkify(["a", "b", "c", "d", "e"], 2))
		self.assertEqual(chunks, [["a", "b"], ["c", "d"], ["e"]])

	def test_chunkify_empty(self):
		self.assertEqual(list(engine_mod._chunkify([], 10)), [])

	def test_chunkify_consumes_generator(self):
		def gen():
			for i in range(7):
				yield f"x{i}"

		chunks = list(engine_mod._chunkify(gen(), 3))
		self.assertEqual(len(chunks), 3)
		self.assertEqual([len(c) for c in chunks], [3, 3, 1])
		self.assertEqual(chunks[0], ["x0", "x1", "x2"])

	def test_chunkify_size_larger_than_input(self):
		chunks = list(engine_mod._chunkify(["a"], 100))
		self.assertEqual(chunks, [["a"]])


# ──────────────────────────────────────────────────────────────────────────
# Redis key prefix isolation (multi-tenant safety)
# ──────────────────────────────────────────────────────────────────────────
class TestRedisKeyPrefix(unittest.TestCase):
	def test_prefix_includes_db_name(self):
		key = engine_mod._rk("abc123", "completed")
		# Stub sets db_name="testdb"; key should be "testdb|...:abc123:completed"
		self.assertTrue(key.startswith("testdb|"))
		self.assertIn(":abc123:completed", key)

	def test_different_rebuilds_get_isolated_keys(self):
		a = engine_mod._rk("rebuild1", "completed")
		b = engine_mod._rk("rebuild2", "completed")
		self.assertNotEqual(a, b)


# ──────────────────────────────────────────────────────────────────────────
# Swap module — naming + table constant invariants
# ──────────────────────────────────────────────────────────────────────────
class TestSwapConstants(unittest.TestCase):
	def test_table_names_share_prod_prefix(self):
		from tradehub_core.recommendations import swap

		self.assertTrue(swap.SHADOW_TABLE.startswith(swap.PROD_TABLE))
		self.assertTrue(swap.ARCHIVE_TABLE.startswith(swap.PROD_TABLE))
		self.assertTrue(swap.SHADOW_TABLE.endswith("_shadow"))
		self.assertTrue(swap.ARCHIVE_TABLE.endswith("_archive"))

	def test_prod_table_matches_doctype_convention(self):
		from tradehub_core.recommendations import swap

		# Frappe table convention: tab + DocType (with spaces preserved)
		self.assertEqual(swap.PROD_TABLE, "tabRelated Listing Cache")


# ──────────────────────────────────────────────────────────────────────────
# Cleanup hook safety — must not raise on null/empty inputs
# ──────────────────────────────────────────────────────────────────────────
class TestCleanupSafety(unittest.TestCase):
	def test_on_product_category_trash_handles_none(self):
		from tradehub_core.recommendations import cleanup

		# Should silently no-op rather than raise on null doc
		cleanup.on_product_category_trash(None)

	def test_on_product_category_trash_handles_doc_without_name(self):
		from tradehub_core.recommendations import cleanup

		cleanup.on_product_category_trash(types.SimpleNamespace())


# ──────────────────────────────────────────────────────────────────────────
# Engine tunables — sanity bounds for production safety
# ──────────────────────────────────────────────────────────────────────────
class TestEngineTunables(unittest.TestCase):
	def test_chunk_size_in_sane_range(self):
		# Too small → queue thrashing; too large → memory + RQ timeout
		self.assertGreaterEqual(engine_mod.CHUNK_SIZE, 100)
		self.assertLessEqual(engine_mod.CHUNK_SIZE, 10000)

	def test_chunk_timeout_exceeds_dispatch_timeout(self):
		# Each chunk must have at least as much budget as the dispatcher
		self.assertGreaterEqual(engine_mod.CHUNK_TIMEOUT, engine_mod.DISPATCH_TIMEOUT)

	def test_redis_ttl_outlives_chunk_timeout(self):
		# Tracker keys must survive longer than the slowest chunk
		self.assertGreater(engine_mod.REBUILD_TTL_SECONDS, engine_mod.CHUNK_TIMEOUT)

	def test_max_chunk_retries_at_least_two(self):
		# Phase 5 hardening contract — at least one retry on transient failure
		self.assertGreaterEqual(engine_mod.MAX_CHUNK_RETRIES, 2)


if __name__ == "__main__":
	unittest.main()
