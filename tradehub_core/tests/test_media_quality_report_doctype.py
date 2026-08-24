"""T-066 — Media Quality Report gerçek DocType kalıcılık testleri."""

from __future__ import annotations

import hashlib

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media.pipeline.image import report as image_report


class MediaQualityReportDoctypeTests(FrappeTestCase):
	def _asset(self) -> str:
		content_hash = hashlib.sha256(frappe.generate_hash().encode()).hexdigest()
		doc = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": "product.image",
				"media_type": "image",
				"state": "ready",
				"content_sha256": content_hash,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Media Asset", doc.name, ignore_permissions=True, force=True)
		return doc.name

	def _asset_report(self, asset: str) -> dict:
		return {
			"schema_version": image_report.REPORT_SCHEMA_VERSION,
			"engine": {"id": "image", "version": "pillow-test"},
			"asset": {"id": asset, "version": None, "bytes": 1_000},
			"slot": "product.image",
			"savings": {
				"original_bytes": 1_000,
				"optimized_bytes": 400,
				"saved_bytes": 600,
				"saving_ratio": 0.6,
			},
			"totals": {"bytes": 400, "elapsed_ms": 25.0},
			"quality": {
				"ssim_mean": 0.98,
				"ssim_min": 0.97,
				"by_profile": [{"profile": "w640", "ssim": 0.98}],
			},
			"decisions": [{"code": "encoded", "profile": "w640"}],
			"warnings": [],
			"verdict": "ok",
			"summary_tr": "Görseliniz optimize edildi.",
		}

	def test_asset_report_persists_json_and_derived_savings(self) -> None:
		asset = self._asset()

		doc = image_report.persist_report(self._asset_report(asset))
		self.addCleanup(frappe.delete_doc, "Media Quality Report", doc.name, force=True)

		self.assertEqual(doc.report_type, "asset")
		self.assertEqual(doc.asset, asset)
		self.assertEqual((doc.input_bytes, doc.output_bytes, doc.saved_bytes), (1_000, 400, 600))
		self.assertAlmostEqual(doc.saving_ratio, 0.6)
		self.assertIn('"profile": "w640"', doc.ssim_by_profile)
		self.assertIn(f'"id": "{asset}"', doc.report_json)

	def test_monthly_report_persists_platform_fields(self) -> None:
		asset = self._asset()
		monthly = image_report.build_monthly_report(
			[self._asset_report(asset)],
			period_start="2099-02-01",
			period_end="2099-02-28",
			failure_count=1,
			total_job_count=4,
		)

		doc = image_report.persist_report(monthly)
		self.addCleanup(frappe.delete_doc, "Media Quality Report", doc.name, force=True)

		self.assertEqual(doc.report_type, "monthly")
		self.assertEqual(doc.period_key, "2099-02")
		self.assertIsNone(doc.asset)
		self.assertEqual(doc.processed_assets, 1)
		self.assertEqual(doc.total_job_count, 4)
		self.assertEqual(doc.failure_count, 1)
		self.assertEqual(doc.failure_rate, 0.25)
		self.assertEqual(len(frappe.parse_json(doc.worst_assets)), 1)
		self.assertIn("Aylık Medya Kalite Raporu", doc.markdown)

	def test_monthly_failure_rate_is_derived_from_terminal_jobs(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Media Quality Report",
				"report_type": "monthly",
				"period_start": "2099-03-01",
				"period_end": "2099-03-31",
				"total_job_count": 10,
				"failure_count": 3,
				# Kalıcı controller bu güvenilmez girdiyi yeniden türetmelidir.
				"failure_rate": 0.99,
			}
		)

		doc.validate()

		self.assertEqual(doc.failure_rate, 0.3)

	def test_monthly_rejects_more_failures_than_terminal_jobs(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Media Quality Report",
				"report_type": "monthly",
				"period_start": "2099-03-01",
				"period_end": "2099-03-31",
				"total_job_count": 2,
				"failure_count": 3,
			}
		)

		with self.assertRaises(frappe.ValidationError):
			doc.validate()


if __name__ == "__main__":
	import unittest

	unittest.main(verbosity=2)
