"""Unit tests for 3-layer resolver — Profile → Regex → Semantic kaskadı.

Patch path'leri resolver modülünün **kullandığı** import noktalarına işaret
ediyor (tanımlandığı modüle değil) — bu Python mock best practice.
"""

import unittest
from unittest.mock import patch


class TestResolverLayers(unittest.TestCase):
	def test_layer1_profile_hit_short_circuits(self):
		"""Profile match olunca regex ve semantic çağrılmaz — %100 confidence."""
		with (
			patch("tradehub_core.bulk_import.ingestion.resolver.profile_store.lookup_profile") as mock_lookup,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.profile_store.increment_hit_count"
			) as mock_hit,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.regex_lib.resolve_column_mapping"
			) as mock_regex,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.semantic.resolve_header_semantic"
			) as mock_semantic,
		):
			mock_lookup.return_value = {
				"profile_name": "PROFILE-001",
				"mapping": {"sku": "SKU", "title": "Ürün Adı"},
				"normalizer_overrides": {},
			}

			from tradehub_core.bulk_import.ingestion.resolver import resolve_columns

			result = resolve_columns(
				headers=["SKU", "Ürün Adı"],
				seller_profile="SELLER-001",
			)

			# Profile yolu seçildi
			self.assertEqual(result["profile_used"], "PROFILE-001")
			self.assertEqual(result["overall_score"], 1.0)
			self.assertEqual(result["sources"]["sku"], "profile")
			# Regex ve semantic çağrılmadı
			mock_regex.assert_not_called()
			mock_semantic.assert_not_called()
			mock_hit.assert_called_once_with("PROFILE-001")

	def test_layer2_regex_fallback(self):
		"""Profile yok → regex devreye girer."""
		with (
			patch("tradehub_core.bulk_import.ingestion.resolver.profile_store.lookup_profile") as mock_lookup,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.regex_lib.resolve_column_mapping"
			) as mock_regex,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.semantic.resolve_header_semantic"
			) as mock_semantic,
		):
			mock_lookup.return_value = None
			mock_regex.return_value = {"sku": "Stok Kodu", "title": "Ürün Adı"}
			mock_semantic.return_value = (None, 0.0)

			from tradehub_core.bulk_import.ingestion.resolver import resolve_columns

			result = resolve_columns(
				headers=["Stok Kodu", "Ürün Adı"],
				seller_profile="SELLER-001",
			)

			self.assertIsNone(result["profile_used"])
			self.assertEqual(result["sources"]["sku"], "regex")
			self.assertEqual(result["sources"]["title"], "regex")
			self.assertEqual(result["confidence"]["sku"], 0.9)

	def test_layer3_semantic_fills_gaps(self):
		"""Regex bazı header'ları çözemezse semantic devreye girer."""
		with (
			patch("tradehub_core.bulk_import.ingestion.resolver.profile_store.lookup_profile") as mock_lookup,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.regex_lib.resolve_column_mapping"
			) as mock_regex,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.semantic.resolve_header_semantic"
			) as mock_semantic,
		):
			mock_lookup.return_value = None
			mock_regex.return_value = {"sku": "Stok Kodu"}

			def semantic_side(header):
				if header == "Marka":
					return ("brand", 0.85)
				return (None, 0.0)

			mock_semantic.side_effect = semantic_side

			from tradehub_core.bulk_import.ingestion.resolver import resolve_columns

			result = resolve_columns(
				headers=["Stok Kodu", "Marka"],
				seller_profile="SELLER-001",
			)

			self.assertEqual(result["mapping"].get("sku"), "Stok Kodu")
			self.assertEqual(result["mapping"].get("brand"), "Marka")
			self.assertEqual(result["sources"]["sku"], "regex")
			self.assertEqual(result["sources"]["brand"], "semantic")
			self.assertEqual(result["confidence"]["brand"], 0.85)

	def test_unmapped_headers_reported(self):
		"""Çözülemeyen header'lar unmapped listesinde."""
		with (
			patch("tradehub_core.bulk_import.ingestion.resolver.profile_store.lookup_profile") as mock_lookup,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.regex_lib.resolve_column_mapping"
			) as mock_regex,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.semantic.resolve_header_semantic"
			) as mock_semantic,
		):
			mock_lookup.return_value = None
			mock_regex.return_value = {}
			mock_semantic.return_value = (None, 0.3)

			from tradehub_core.bulk_import.ingestion.resolver import resolve_columns

			result = resolve_columns(
				headers=["RandomHeader1", "RandomHeader2"],
				seller_profile="SELLER-001",
			)

			self.assertEqual(len(result["unmapped"]), 2)
			self.assertEqual(result["overall_score"], 0.0)

	def test_overall_score_aggregation(self):
		"""Confidence ortalaması doğru hesaplanıyor mu."""
		with (
			patch("tradehub_core.bulk_import.ingestion.resolver.profile_store.lookup_profile") as mock_lookup,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.regex_lib.resolve_column_mapping"
			) as mock_regex,
			patch(
				"tradehub_core.bulk_import.ingestion.resolver.semantic.resolve_header_semantic"
			) as mock_semantic,
		):
			mock_lookup.return_value = None
			mock_regex.return_value = {"sku": "SKU"}  # 0.9
			mock_semantic.return_value = ("brand", 0.8)

			from tradehub_core.bulk_import.ingestion.resolver import resolve_columns

			result = resolve_columns(
				headers=["SKU", "Marka"],
				seller_profile="SELLER-001",
			)

			# (0.9 + 0.8) / 2 = 0.85
			self.assertAlmostEqual(result["overall_score"], 0.85, places=2)


class TestConfidenceReport(unittest.TestCase):
	def test_build_confidence_report(self):
		from tradehub_core.bulk_import.ingestion.confidence import build_confidence_report

		resolve_result = {
			"mapping": {"sku": "SKU", "brand": "Marka"},
			"sources": {"sku": "regex", "brand": "semantic"},
			"confidence": {"sku": 0.9, "brand": 0.6},
			"unmapped": ["Unknown Col"],
			"profile_used": None,
			"overall_score": 0.75,
		}
		report = build_confidence_report(resolve_result, total_rows=100)
		self.assertEqual(report["by_source"]["regex"], 1)
		self.assertEqual(report["by_source"]["semantic"], 1)
		self.assertEqual(report["total_mapped"], 2)
		self.assertEqual(report["total_unmapped"], 1)
		self.assertEqual(report["total_rows"], 100)
		self.assertIn("brand", report["low_confidence_fields"])  # 0.6 < 0.75
		self.assertNotIn("sku", report["low_confidence_fields"])
		self.assertTrue(report["needs_manual_intervention"])

	def test_no_intervention_needed(self):
		from tradehub_core.bulk_import.ingestion.confidence import build_confidence_report

		resolve_result = {
			"mapping": {"sku": "SKU"},
			"sources": {"sku": "profile"},
			"confidence": {"sku": 1.0},
			"unmapped": [],
			"profile_used": "PROFILE-001",
			"overall_score": 1.0,
		}
		report = build_confidence_report(resolve_result, total_rows=100)
		self.assertFalse(report["needs_manual_intervention"])
		self.assertEqual(report["by_source"]["profile"], 1)


if __name__ == "__main__":
	unittest.main()
