"""T-066 gerçek RUM tabanlı aylık LCP etkisi testleri."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from tradehub_core.media.pipeline.image import lcp_impact, report


def _row(value: float, profile: str, **overrides):
	row = {
		"metric": "LCP",
		"value": value,
		"sample_rate": 1.0,
		"route": "/urun/:slug",
		"lcp_region": "product_detail/main_image",
		"device_class": "phone",
		"viewport_bucket": 390,
		"dpr": 2.0,
		"connection": "4g",
		"lcp_profile": profile,
	}
	row.update(overrides)
	return row


class LcpImpactAAA(unittest.TestCase):
	def test_same_cohort_reports_positive_improvement(self) -> None:
		# Arrange — original ortalama 2000 ms, optimize ortalama 1300 ms.
		rows = [
			_row(2200, "original"),
			_row(1800, "original"),
			_row(1400, "w1280"),
			_row(1200, "w1280"),
		]

		# Act
		measured = lcp_impact.measure_lcp_impact(rows)

		# Assert
		self.assertEqual(measured.average_impact_ms, 700.0)
		self.assertEqual(measured.comparable_cohorts, 1)
		self.assertEqual(measured.comparable_samples, 4)
		self.assertEqual(measured.direction, "positive_is_faster")

	def test_sample_rate_and_comparable_population_weight_cohorts(self) -> None:
		# Arrange — ilk kohort +1000 ms ve tahmini 10 çift; ikinci kohort
		# -100 ms ve tahmini 1 çift: (1000*10 - 100) / 11 = 900 ms.
		rows = [
			_row(2500, "original", sample_rate=0.1),
			_row(1500, "w640", sample_rate=0.1),
			_row(1000, "original", connection="3g"),
			_row(1100, "w640", connection="3g"),
		]

		# Act
		measured = lcp_impact.measure_lcp_impact(rows)

		# Assert
		self.assertEqual(measured.average_impact_ms, 900.0)
		self.assertEqual(measured.estimated_comparable_population, 11.0)

	def test_unmatched_and_unknown_profiles_are_not_fabricated(self) -> None:
		rows = [
			_row(2000, "original", device_class="phone"),
			_row(1300, "w1280", device_class="desktop"),
			_row(1700, "unknown", device_class="phone"),
		]

		measured = lcp_impact.measure_lcp_impact(rows)

		self.assertIsNone(measured.average_impact_ms)
		self.assertEqual(measured.comparable_cohorts, 0)
		self.assertEqual(measured.comparable_samples, 0)

	def test_invalid_persisted_sample_fails_closed(self) -> None:
		with self.assertRaises(lcp_impact.LcpImpactError):
			lcp_impact.measure_lcp_impact([_row(1000, "original", sample_rate=0)])

	def test_month_filter_is_half_open(self) -> None:
		filters = lcp_impact.monthly_lcp_filters(date(2026, 7, 1), date(2026, 7, 31))

		self.assertIn(["creation", ">=", "2026-07-01 00:00:00"], filters)
		self.assertIn(["creation", "<", "2026-08-01 00:00:00"], filters)

	def test_monthly_report_uses_rum_measurement(self) -> None:
		measurement = lcp_impact.measure_lcp_impact(
			[_row(1800, "original"), _row(1200, "w768")]
		)

		monthly = report.build_monthly_report(
			[],
			period_start="2026-07-01",
			period_end="2026-07-31",
			total_job_count=0,
			lcp_measurement=measurement,
		)

		self.assertEqual(monthly["average_lcp_impact_ms"], 600.0)
		self.assertEqual(monthly["lcp_measured_samples"], 2)
		self.assertEqual(monthly["lcp_comparable_cohorts"], 1)
		self.assertIn("pozitif = daha hızlı", monthly["markdown"])

	def test_production_scheduler_reads_month_rum_rows(self) -> None:
		calls: list[tuple[date, date]] = []
		inserted: list[dict] = []

		def fetch_lcp_rows(start: date, end: date):
			calls.append((start, end))
			return [_row(2100, "original"), _row(1400, "w1280")]

		with TemporaryDirectory() as directory:
			result = report.run_previous_month_report(
				as_of="2026-08-23",
				fetch_rows=lambda _start, _end: (),
				fetch_failure_count=lambda _start, _end: 0,
				fetch_total_job_count=lambda _start, _end: 0,
				fetch_lcp_rows=fetch_lcp_rows,
				find_existing=lambda _key: None,
				insert=lambda payload: inserted.append(payload) or payload,
				markdown_path=Path(directory) / "2026-07.md",
			)

		self.assertEqual(calls, [(date(2026, 7, 1), date(2026, 7, 31))])
		self.assertEqual(result["average_lcp_impact_ms"], 700.0)
		self.assertEqual(result["lcp_measured_samples"], 2)
		self.assertEqual(inserted[0]["average_lcp_impact_ms"], 700.0)


if __name__ == "__main__":
	unittest.main()
