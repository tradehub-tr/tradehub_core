"""T-034 queue topology and deployment-projection closure gates."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradehub_core.media.pipeline.core import queues
from tradehub_core.media.pipeline.observability import metrics

ROOT = Path(__file__).resolve().parents[2]
DOCTYPE_SPEC = ROOT / "tradehub_core/media/pipeline/doctype_specs/media_processing_job.json"
DOCTYPE_INSTALLED = ROOT / "tradehub_core/tradehub_core/doctype/media_processing_job/media_processing_job.json"
DEPLOY = ROOT / "deploy/media-workers.compose.yml"
BRIDGE = ROOT / "tradehub_core/media/pipeline_bridge.py"
WORKSPACE_COMPOSE = ROOT.parent / "docker/docker-compose.yml"


def _select_options(path: Path, fieldname: str) -> tuple[str, ...]:
	data = json.loads(path.read_text(encoding="utf-8"))
	field = next(field for field in data["fields"] if field["fieldname"] == fieldname)
	return tuple(line for line in str(field["options"]).splitlines() if line)


class QueueTopologyTest(unittest.TestCase):
	def test_bes_ayrik_kuyruk_ve_degiskenler(self):
		self.assertEqual(
			queues.QUEUE_NAMES,
			(
				"media-image-live",
				"media-image-bulk",
				"media-video",
				"media-ai",
				"media-maint",
			),
		)
		self.assertEqual(queues.validate_topology(), ())
		self.assertLess(queues.VIDEO.timeout_seconds, 2700)
		self.assertNotEqual(queues.IMAGE_LIVE.name, queues.IMAGE_BULK.name)

	def test_her_is_tipi_bir_kuyruga_bagli(self):
		self.assertEqual(set(queues.JOB_QUEUE.values()), set(queues.QUEUE_NAMES))
		self.assertEqual(queues.for_job("rendition").name, queues.IMAGE_LIVE.name)
		self.assertEqual(queues.for_job("rendition", bulk=True).name, queues.IMAGE_BULK.name)
		self.assertEqual(queues.for_job("transcode").name, queues.VIDEO.name)
		with self.assertRaises(ValueError):
			queues.for_job("unknown")

	def test_doctype_projeksiyonlari_kodla_ayni(self):
		for path in (DOCTYPE_SPEC, DOCTYPE_INSTALLED):
			with self.subTest(path=path):
				self.assertEqual(_select_options(path, "queue"), queues.QUEUE_NAMES)
				statuses = _select_options(path, "status")
				self.assertIn("dead", statuses)
				fields = json.loads(path.read_text(encoding="utf-8"))["fields"]
				names = {field["fieldname"] for field in fields}
				self.assertTrue({"attempt", "duration_ms", "peak_memory_mb", "error_code"} <= names)

	def test_frappe_koprusu_genel_long_kuyruguna_dusmez(self):
		text = BRIDGE.read_text(encoding="utf-8")
		self.assertIn("from tradehub_core.media.pipeline.core import queues as media_queues", text)
		self.assertNotIn('RQ_QUEUE: str = "long"', text)
		self.assertIn("QUEUE_TIMEOUT_LIVE_SECONDS", text)

	def test_repo_deploy_projeksiyonunda_her_kuyrugun_workeri_var(self):
		text = DEPLOY.read_text(encoding="utf-8")
		for spec in queues.QUEUE_SPECS:
			with self.subTest(queue=spec.name):
				self.assertIn(f"queue-{spec.name}:", text)
				if spec is queues.IMAGE_BULK:
					self.assertIn("tradehub_core.media.bulk_worker", text)
				else:
					self.assertIn(f'"--queue", "{spec.name}"', text)
				self.assertIn(f"{spec.name}: {{timeout: {spec.timeout_seconds}", text)

	def test_workspace_compose_varsa_ayni_topolojiyi_tasir(self):
		if not WORKSPACE_COMPOSE.exists():
			self.skipTest("Workspace Docker deposu bu checkout'ta yok")
		text = WORKSPACE_COMPOSE.read_text(encoding="utf-8")
		for spec in queues.QUEUE_SPECS:
			with self.subTest(queue=spec.name):
				self.assertIn(f"queue-{spec.name}:", text)
				if spec is queues.IMAGE_BULK:
					self.assertIn("tradehub_core.media.bulk_worker", text)
				else:
					self.assertIn(f'"--queue", "{spec.name}"', text)

	def test_prometheus_kuyruk_metrikleri_tanimli(self):
		names = {metric.ad for metric in metrics.REGISTRY.metrikler()}
		self.assertIn("media_queue_depth", names)
		self.assertIn("media_queue_jobs", names)


if __name__ == "__main__":
	unittest.main()
