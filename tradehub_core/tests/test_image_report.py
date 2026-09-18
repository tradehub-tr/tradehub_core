"""T-066 kalite raporu, kalıcılık, aylık özet ve metrik AAA testleri."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tradehub_core.media.pipeline.image import render as render_mod
from tradehub_core.media.pipeline.image import report as report_mod
from tradehub_core.media.pipeline.image.normalize import NormalizeResult
from tradehub_core.media.pipeline.observability import metrics

ROOT = Path(__file__).resolve().parents[2]


def _source() -> bytes:
	from PIL import Image

	buffer = io.BytesIO()
	Image.new("RGB", (32, 32), (40, 80, 120)).save(buffer, "PNG", dpi=(300, 300))
	return buffer.getvalue()


def _result(source: bytes, *, output_bytes: int = 32, ssim: float = 0.97):
	profile = render_mod.RenditionProfile(
		slot_key="product.image",
		name="w32",
		width=32,
		formats=("webp",),
		encoder_quality=(("webp", 80),),
	)
	geometry = render_mod.GeometryPlan(
		source_size=(32, 32),
		crop_box=(0, 0, 32, 32),
		inner_size=(32, 32),
		canvas_size=(32, 32),
		paste_at=(0, 0),
		scale=1.0,
		upscale_blocked=False,
		crop_method="center",
		padded=False,
	)
	attempt = render_mod.FormatAttempt(
		format="webp",
		quality=80,
		out_bytes=output_bytes,
		ssim=ssim,
		encodes=1,
		elapsed_ms=12.5,
		accepted=True,
	)
	return render_mod.RenditionResult(
		slot_key="product.image",
		profile=profile,
		format="webp",
		content=b"x" * output_bytes,
		width=32,
		height=32,
		quality=80,
		ssim=ssim,
		ssim_target=0.95,
		content_class="photo",
		geometry=geometry,
		encodes=1,
		elapsed_ms=12.5,
		source_bytes=len(source),
		attempts=(attempt,),
		notes=(render_mod.NOTE_NO_DOWNSCALE,),
		ssim_backend="pure",
	)


def _asset_report(index: int, *, lcp_ms: float | None = None) -> dict:
	input_bytes = 2_000_000 + index * 10_000
	output_bytes = 500_000 + index * 1_000
	report = {
		"schema_version": report_mod.REPORT_SCHEMA_VERSION,
		"engine": {"id": "test", "version": "1"},
		"asset": {"id": f"ASSET-{index:02d}", "sha256": f"{index:064x}", "bytes": input_bytes},
		"slot": "product.image" if index % 2 == 0 else "brand.logo",
		"savings": {
			"original_bytes": input_bytes,
			"optimized_bytes": output_bytes,
			"saved_bytes": input_bytes - output_bytes,
			"saving_ratio": (input_bytes - output_bytes) / input_bytes,
		},
		"totals": {"bytes": output_bytes, "elapsed_ms": 100 + index},
		"quality": {"ssim_min": 0.99 - index / 1000},
		"verdict": "ok",
	}
	if lcp_ms is not None:
		report["impact"] = {"lcp_ms": lcp_ms, "measured": True}
	return report


class AssetReportAAA(unittest.TestCase):
	def setUp(self) -> None:
		self.source = _source()

	def test_exif_rational_dpi_is_persistable(self) -> None:
		from PIL import Image, TiffImagePlugin

		exif = Image.Exif()
		exif[282] = TiffImagePlugin.IFDRational(300, 1)
		exif[283] = TiffImagePlugin.IFDRational(300, 1)
		exif[296] = 2
		for fmt in ("JPEG", "TIFF"):
			with self.subTest(format=fmt):
				buffer = io.BytesIO()
				Image.new("RGB", (32, 32), (40, 80, 120)).save(buffer, fmt, exif=exif)
				source = buffer.getvalue()
				report = report_mod.build_report(
					source, [_result(source)], slot_key="product.image", asset_id="ASSET-EXIF"
				)

				payload = report_mod.persist_report(report, insert=lambda row: row)

				self.assertEqual(json.loads(payload["report_json"])["asset"]["dpi"], [300.0, 300.0])
				self.assertTrue(report["asset"]["readable"])

	def test_bytes_ssim_and_decisions_are_persistable(self) -> None:
		# Arrange
		result = _result(self.source)

		# Act
		report = report_mod.build_report(
			self.source,
			[result],
			slot_key="product.image",
			asset_id="ASSET-1",
			version_id="VERSION-1",
			extra={"normalized": {"width": 32, "height": 32, "dpi": [72, 72]}},
		)
		payload = report_mod.doctype_payload(report)

		# Assert
		self.assertEqual(report["savings"]["original_bytes"], len(self.source))
		self.assertEqual(report["savings"]["optimized_bytes"], result.size_bytes)
		self.assertEqual(report["quality"]["by_profile"][0]["ssim"], 0.97)
		self.assertEqual(report["decisions"][0]["action"], "encoded")
		self.assertIn(render_mod.NOTE_NO_DOWNSCALE, report["decisions"][0]["reason_codes"])
		self.assertEqual(payload["asset"], "ASSET-1")
		self.assertEqual(json.loads(payload["ssim_by_profile"])[0]["profile"], "w32")
		self.assertEqual(json.loads(payload["decisions"])[0]["selected_format"], "webp")

	def test_seller_summary_explains_dpi_without_claiming_pixel_loss(self) -> None:
		# Arrange
		report = {
			"asset": {"width": 3000, "height": 3000, "dpi": [300, 300], "bytes": 12_400_000},
			"processing": {"normalized": {"width": 2400, "height": 2400, "dpi": [72, 72]}},
			"savings": {
				"original_bytes": 12_400_000,
				"optimized_bytes": 1_100_000,
				"saving_ratio": 11.3 / 12.4,
			},
			"renditions": [],
		}

		# Act
		summary = report_mod.seller_summary_tr(report)

		# Assert
		self.assertIn("3000×3000 → 2400×2400", summary)
		self.assertIn("300→72 dpi", summary)
		self.assertIn("piksel çözünürlüğü korundu", summary)
		self.assertIn("12,4 MB → 1,1 MB", summary)
		self.assertIn("tasarruf", summary)

	def test_negative_saving_is_not_fabricated_as_a_gain(self) -> None:
		# Arrange
		result = _result(self.source, output_bytes=len(self.source) + 100)

		# Act
		report = report_mod.build_report(self.source, [result], slot_key="product.image")

		# Assert
		self.assertLess(report["savings"]["saved_bytes"], 0)
		self.assertFalse(report["savings"]["has_saving"])
		self.assertIn("ek depolama", report["summary_tr"])

	def test_normalize_result_extra_remains_json_persistable(self) -> None:
		# Arrange
		normalized = NormalizeResult(
			ok=True,
			content=b"master-bytes",
			fmt="JPEG",
			width=32,
			height=32,
			dpi=(72.0, 72.0),
		)

		# Act
		report = report_mod.build_report(
			self.source,
			[_result(self.source)],
			slot_key="product.image",
			extra={"normalized": normalized},
		)
		serialized = json.dumps(report)

		# Assert
		self.assertIn('"width": 32', serialized)
		self.assertEqual(report["processing"]["normalized"]["bytes"], len(normalized.content))
		self.assertEqual(report["extra"]["normalized"]["size_bytes"], len(normalized.content))


class MonthlyReportAAA(unittest.TestCase):
	def test_monthly_totals_lcp_slots_and_worst_20(self) -> None:
		# Arrange
		reports = [_asset_report(i, lcp_ms=float(i) if i < 5 else None) for i in range(25)]

		# Act
		monthly = report_mod.build_monthly_report(
			reports,
			period_start="2026-07-01",
			period_end="2026-07-31",
			failure_count=2,
			total_job_count=40,
		)

		# Assert
		self.assertEqual(monthly["processed_assets"], 25)
		self.assertEqual(monthly["total_job_count"], 40)
		self.assertEqual(monthly["failure_rate"], 0.05)
		self.assertEqual(monthly["lcp_measured_assets"], 5)
		self.assertEqual(monthly["average_lcp_impact_ms"], 2.0)
		self.assertEqual(len(monthly["worst_20"]), 20)
		self.assertEqual(sum(row["assets"] for row in monthly["slot_distribution"].values()), 25)
		self.assertAlmostEqual(monthly["saved_gb"], monthly["saved_bytes"] / 1_000_000_000, places=6)
		self.assertIn("En kötü 20 asset", monthly["markdown"])

	def test_monthly_persists_doctype_and_markdown_from_same_payload(self) -> None:
		# Arrange
		inserted: list[dict] = []
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "2026-07.md"

			# Act
			monthly, doc, written = report_mod.persist_monthly_report(
				[_asset_report(1)],
				period_start="2026-07-01",
				period_end="2026-07-31",
				markdown_path=path,
				total_job_count=1,
				insert=lambda payload: inserted.append(payload) or payload,
			)

			# Assert
			self.assertEqual(doc["report_type"], "monthly")
			self.assertEqual(inserted[0]["saved_bytes"], monthly["saved_bytes"])
			self.assertEqual(written.read_text(encoding="utf-8"), monthly["markdown"])

	def test_inverted_period_and_invalid_job_counts_are_rejected(self) -> None:
		with self.assertRaises(ValueError):
			report_mod.build_monthly_report(
				[], period_start="2026-08-02", period_end="2026-08-01", total_job_count=0
			)
		with self.assertRaises(ValueError):
			report_mod.build_monthly_report(
				[],
				period_start="2026-08-01",
				period_end="2026-08-31",
				failure_count=-1,
				total_job_count=0,
			)
		with self.assertRaises(ValueError):
			report_mod.build_monthly_report(
				[], period_start="2026-08-01", period_end="2026-08-31", total_job_count=-1
			)
		with self.assertRaises(ValueError):
			report_mod.build_monthly_report(
				[],
				period_start="2026-08-01",
				period_end="2026-08-31",
				failure_count=2,
				total_job_count=1,
			)

	def test_failure_rate_uses_total_jobs_not_deduplicated_asset_reports(self) -> None:
		# Arrange — bir asset raporu, aynı dönemde on ayrı terminal image işi.
		reports = [_asset_report(1)]

		# Act
		monthly = report_mod.build_monthly_report(
			reports,
			period_start="2026-07-01",
			period_end="2026-07-31",
			failure_count=3,
			total_job_count=10,
		)

		# Assert — eski `3 / (1 + 3) == .75` hesabı geri gelmemeli.
		self.assertEqual(monthly["processed_assets"], 1)
		self.assertEqual(monthly["total_job_count"], 10)
		self.assertEqual(monthly["failure_rate"], 0.3)

	def test_previous_month_scheduler_reads_persisted_assets_once(self) -> None:
		# Arrange
		state: dict[str, str] = {}
		fetch_calls: list[tuple] = []
		failure_calls: list[tuple] = []
		total_calls: list[tuple] = []
		inserted: list[dict] = []

		def fetch_rows(start, end):
			fetch_calls.append((start, end))
			return [{"name": "MQR-ASSET-1", "report_json": json.dumps(_asset_report(1))}]

		def find_existing(period_key):
			return state.get(period_key)

		def fetch_failure_count(start, end):
			failure_calls.append((start, end))
			return 2

		def fetch_total_job_count(start, end):
			total_calls.append((start, end))
			return 8

		def insert(payload):
			document = dict(payload, name="MQR-MONTH-2025-12")
			inserted.append(document)
			state[payload["period_key"]] = document["name"]
			return document

		with tempfile.TemporaryDirectory() as directory:
			markdown = Path(directory) / "2025-12.md"

			# Act
			first = report_mod.run_previous_month_report(
				as_of="2026-01-22",
				fetch_rows=fetch_rows,
				fetch_failure_count=fetch_failure_count,
				fetch_total_job_count=fetch_total_job_count,
				find_existing=find_existing,
				insert=insert,
				markdown_path=markdown,
			)
			second = report_mod.run_previous_month_report(
				as_of="2026-01-22",
				fetch_rows=fetch_rows,
				fetch_failure_count=fetch_failure_count,
				fetch_total_job_count=fetch_total_job_count,
				find_existing=find_existing,
				insert=insert,
				markdown_path=markdown,
			)

			# Assert
			self.assertEqual(first["status"], "created")
			self.assertEqual(second["status"], "existing")
			self.assertEqual(first["period_key"], "2025-12")
			self.assertEqual(fetch_calls, [(date(2025, 12, 1), date(2025, 12, 31))])
			self.assertEqual(failure_calls, [(date(2025, 12, 1), date(2025, 12, 31))])
			self.assertEqual(total_calls, [(date(2025, 12, 1), date(2025, 12, 31))])
			self.assertEqual(len(inserted), 1)
			self.assertEqual(inserted[0]["report_type"], "monthly")
			self.assertEqual(inserted[0]["failure_count"], 2)
			self.assertEqual(inserted[0]["failure_rate"], 0.25)
			self.assertEqual(first["failed_jobs"], 2)
			self.assertEqual(first["total_jobs"], 8)
			self.assertTrue(markdown.is_file())

		hooks = (ROOT / "tradehub_core" / "hooks.py").read_text(encoding="utf-8")
		self.assertIn("report.run_previous_month_report", hooks)

	def test_job_queries_are_half_open_and_only_count_terminal_image_jobs(self) -> None:
		# Arrange
		start, end = date(2026, 7, 1), date(2026, 7, 31)

		# Act
		failure_filters = report_mod.monthly_failure_filters(start, end)
		total_filters = report_mod.monthly_total_job_filters(start, end)

		# Assert
		self.assertEqual(
			failure_filters,
			[
				["job_type", "in", ["normalize", "rendition"]],
				["status", "in", ["failed", "dead"]],
				["finished_at", ">=", "2026-07-01 00:00:00"],
				["finished_at", "<", "2026-08-01 00:00:00"],
			],
		)
		self.assertEqual(
			total_filters,
			[
				["job_type", "in", ["normalize", "rendition"]],
				["status", "in", ["success", "failed", "dead"]],
				["finished_at", ">=", "2026-07-01 00:00:00"],
				["finished_at", "<", "2026-08-01 00:00:00"],
			],
		)

	def test_monthly_scheduler_deduplicates_asset_version_by_latest_creation(self) -> None:
		# Arrange
		older = _asset_report(1)
		older["asset"]["version"] = "VERSION-1"
		newer = json.loads(json.dumps(older))
		newer["savings"]["optimized_bytes"] = 250_000
		newer["savings"]["saved_bytes"] = newer["savings"]["original_bytes"] - 250_000
		newer["totals"]["bytes"] = 250_000
		inserted: list[dict] = []
		rows = [
			{"name": "MQR-NEW", "creation": "2026-07-20 12:00:00", "report_json": newer},
			{"name": "MQR-OLD", "creation": "2026-07-02 12:00:00", "report_json": older},
		]

		with tempfile.TemporaryDirectory() as directory:
			# Act
			result = report_mod.run_previous_month_report(
				as_of="2026-08-22",
				fetch_rows=lambda _start, _end: rows,
				fetch_failure_count=lambda _start, _end: 3,
				fetch_total_job_count=lambda _start, _end: 10,
				find_existing=lambda _key: None,
				insert=lambda payload: inserted.append(payload) or payload,
				markdown_path=Path(directory) / "2026-07.md",
			)

		# Assert
		self.assertEqual(result["asset_reports"], 1)
		self.assertEqual(result["failed_jobs"], 3)
		self.assertEqual(inserted[0]["processed_assets"], 1)
		self.assertEqual(inserted[0]["output_bytes"], 250_000)
		self.assertEqual(inserted[0]["failure_count"], 3)
		self.assertEqual(inserted[0]["total_job_count"], 10)
		self.assertEqual(inserted[0]["failure_rate"], 0.3)

	def test_monthly_scheduler_does_not_invent_zero_when_failures_are_unmeasured(self) -> None:
		# Arrange
		inserted: list[dict] = []
		with tempfile.TemporaryDirectory() as directory:
			# Act / Assert
			with self.assertRaisesRegex(RuntimeError, "ölçülemedi"):
				report_mod.run_previous_month_report(
					as_of="2026-08-22",
					fetch_rows=lambda _start, _end: [],
					fetch_failure_count=lambda _start, _end: None,
					fetch_total_job_count=lambda _start, _end: 0,
					find_existing=lambda _key: None,
					insert=lambda payload: inserted.append(payload) or payload,
					markdown_path=Path(directory) / "2026-07.md",
				)
		self.assertEqual(inserted, [])

	def test_monthly_scheduler_does_not_invent_total_job_count(self) -> None:
		# Arrange
		inserted: list[dict] = []
		with tempfile.TemporaryDirectory() as directory:
			# Act / Assert
			with self.assertRaisesRegex(RuntimeError, "toplam.*ölçülemedi"):
				report_mod.run_previous_month_report(
					as_of="2026-08-22",
					fetch_rows=lambda _start, _end: [],
					fetch_failure_count=lambda _start, _end: 0,
					fetch_total_job_count=lambda _start, _end: None,
					find_existing=lambda _key: None,
					insert=lambda payload: inserted.append(payload) or payload,
					markdown_path=Path(directory) / "2026-07.md",
				)
		self.assertEqual(inserted, [])

	def test_monthly_scheduler_treats_unique_insert_race_as_existing(self) -> None:
		# Arrange
		state: dict[str, str] = {}

		def lose_insert_race(payload):
			state[payload["period_key"]] = "MQR-MONTH-WINNER"
			raise RuntimeError("duplicate period_key")

		with tempfile.TemporaryDirectory() as directory:
			# Act
			result = report_mod.run_previous_month_report(
				as_of="2026-08-22",
				fetch_rows=lambda _start, _end: [],
				fetch_failure_count=lambda _start, _end: 0,
				fetch_total_job_count=lambda _start, _end: 0,
				find_existing=lambda key: state.get(key),
				insert=lose_insert_race,
				markdown_path=Path(directory) / "2026-07.md",
			)

		# Assert
		self.assertEqual(result["status"], "existing")
		self.assertEqual(result["name"], "MQR-MONTH-WINNER")


class PrometheusAAA(unittest.TestCase):
	def setUp(self) -> None:
		metrics.REGISTRY.temizle()
		self.addCleanup(metrics.REGISTRY.temizle)

	def test_four_t066_metrics_are_registered_and_recorded(self) -> None:
		# Arrange
		report = _asset_report(1)

		# Act
		report_mod.record_report_metrics(report)
		report_mod.record_job_failure(reason="decode_failed", duration_s=0.25)
		text = metrics.render()

		# Assert
		for name in (
			"media_processed_total",
			"media_bytes_saved_total",
			"media_job_duration_seconds",
			"media_job_failures_total",
		):
			self.assertIn(name, text)
		self.assertEqual(metrics.MEDIA_PROCESSED_TOTAL.deger(slot="brand.logo", outcome="ok"), 1.0)
		self.assertEqual(
			metrics.MEDIA_JOB_FAILURES_TOTAL.deger(job="image_render", reason="decode_failed"), 1.0
		)
		self.assertEqual(
			metrics.MEDIA_JOB_DURATION_SECONDS.ozet(job="image_render", outcome="failed")["count"],
			1.0,
		)


class SchemaAAA(unittest.TestCase):
	def test_installed_doctype_contains_asset_and_monthly_fields(self) -> None:
		# Arrange
		path = (
			ROOT
			/ "tradehub_core"
			/ "tradehub_core"
			/ "doctype"
			/ "media_quality_report"
			/ "media_quality_report.json"
		)

		# Act
		schema = json.loads(path.read_text(encoding="utf-8"))
		fields = {field["fieldname"]: field for field in schema["fields"]}

		# Assert
		for name in (
			"input_bytes",
			"output_bytes",
			"saved_bytes",
			"ssim_by_profile",
			"decisions",
			"period_start",
			"total_job_count",
			"saved_gb",
			"average_lcp_impact_ms",
			"worst_assets",
			"markdown",
			"period_key",
			"vmaf",
		):
			self.assertIn(name, fields)
		self.assertEqual(fields["ssim_by_profile"]["fieldtype"], "JSON")
		self.assertEqual(fields["period_key"]["unique"], 1)
		patches = (ROOT / "tradehub_core" / "patches.txt").read_text(encoding="utf-8")
		self.assertIn("v15_9_41_media_quality_report", patches)


class PermissionAAA(unittest.TestCase):
	def test_hooks_and_docperm_use_asset_ownership_instead_of_worker_owner(self) -> None:
		# Arrange / Act
		from tradehub_core import hooks

		path = (
			ROOT
			/ "tradehub_core"
			/ "tradehub_core"
			/ "doctype"
			/ "media_quality_report"
			/ "media_quality_report.json"
		)
		schema = json.loads(path.read_text(encoding="utf-8"))
		seller_rows = [
			row for row in schema["permissions"] if row["role"] in {"Seller", "Marketplace Seller"}
		]

		# Assert
		self.assertIn("Media Quality Report", hooks.permission_query_conditions)
		self.assertIn("Media Quality Report", hooks.has_permission)
		self.assertEqual(len(seller_rows), 2)
		self.assertTrue(all(not row.get("if_owner") for row in seller_rows))


if __name__ == "__main__":
	unittest.main(verbosity=2)
