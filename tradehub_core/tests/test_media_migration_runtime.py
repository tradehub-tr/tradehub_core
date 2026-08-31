"""MOGEM-570 — kalıcı, onay kapılı medya migration runtime testleri."""

from __future__ import annotations

import io
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin
from tradehub_core.media import migration_runtime as runtime
from tradehub_core.media.pipeline.migration.backfill import stamp_plan

# Tarama kancası bu modülde nötrleniyor: `hold_until_clean` açıkken dosya
# insert anında public ağaçtan çıkarılıyor ve diskten okuyan testler
# `FileNotFoundError` alıyor. Gerekçe `tests/av_notr.py` başlığında.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401


class MediaMigrationRuntimeTests(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.previous_user = frappe.session.user
		frappe.set_user("Administrator")
		self.addCleanup(lambda: frappe.set_user(self.previous_user))
		self.run_keys: list[str] = []
		self.file_names: list[str] = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for run_key in reversed(self.run_keys):
			if frappe.db.exists("Media Migration Run", run_key):
				frappe.delete_doc("Media Migration Run", run_key, ignore_permissions=True, force=True)
		for file_name in reversed(self.file_names):
			if frappe.db.exists("File", file_name):
				frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDown()

	def _file(self, tag: str = "a"):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"mogem570-{tag}-{frappe.generate_hash(length=8)}.txt",
				"is_private": 0,
				"content": (f"MOGEM-570 {tag} " * 100).encode(),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.file_names.append(doc.name)
		return doc

	def _image_file(self, tag: str = "rehearsal"):
		"""Gerçek runner'ın küçülteceği, deterministik ve izole bir JPEG üret."""
		from PIL import Image

		image = Image.effect_noise((2800, 1800), 96).convert("RGB")
		buffer = io.BytesIO()
		image.save(buffer, "JPEG", quality=100, subsampling=0)
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"mogem617-{tag}-{frappe.generate_hash(length=8)}.jpg",
				"is_private": 0,
				"content": buffer.getvalue(),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.file_names.append(doc.name)
		return doc

	def _plan(self, *files: frappe._dict) -> dict:
		return stamp_plan(
			{
				"source": "test_media_migration_runtime",
				"records": [
					{
						"file_name": doc.name,
						"file_url": doc.file_url,
						"file_size": int(doc.file_size or 0),
						"class": "A_otomatik",
						"slots": ["listing_main"],
					}
					for doc in files
				],
			}
		)

	def _preflight(self, plan: dict, batch_size: int = 1) -> dict:
		return {
			"ok": True,
			"batch_size": batch_size,
			"plan_digest": plan["plan_digest"],
			"errors": [],
			"warnings": [],
		}

	def _start_dry(self, plan: dict, batch_size: int = 1) -> str:
		with (
			mock.patch.object(runtime, "preflight", return_value=self._preflight(plan, batch_size)),
			mock.patch.object(runtime, "claim_active", return_value=True),
			mock.patch.object(runtime, "_enqueue_batch"),
		):
			result = runtime.start(plan, dry_run=True, batch_size=batch_size)
		frappe.db.commit()
		self.run_keys.append(result["run_key"])
		return result["run_key"]

	def test_schema_and_checkpoint_unique_index_exist(self):
		self.assertTrue(frappe.db.table_exists("Media Migration Run"))
		self.assertTrue(frappe.db.table_exists("Media Migration Batch"))
		indexes = {row[2] for row in frappe.db.sql("SHOW INDEX FROM `tabMedia Migration Batch`")}
		self.assertIn("uniq_media_migration_batch", indexes)

	def test_mutating_and_preflight_endpoints_require_system_manager(self):
		frappe.set_user("Guest")
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				media_admin.preflight_media_migration({})
		finally:
			frappe.flags.in_test = True
			frappe.set_user("Administrator")

	def test_archive_path_guard_allows_double_dot_filename_but_blocks_parent_segment(self):
		self.assertEqual(runtime.archive.relative_path_for("/files/foto..jpg"), "public/foto..jpg")
		with self.assertRaises(frappe.ValidationError):
			runtime.archive.relative_path_for("/files/../secret.jpg")

	def test_preflight_checks_real_file_disk_scope_and_capacity(self):
		file_doc = self._file("preflight")
		plan = self._plan(file_doc)
		queue = {
			"bulk_queue": "media-image-bulk",
			"bulk_depth": 0,
			"live_queue": "media-image-live",
			"live_depth": 0,
			"bulk_workers": ["worker-test"],
		}
		with mock.patch.object(runtime, "_queue_health", return_value=queue):
			result = runtime.preflight(plan, batch_size=1)
		self.assertTrue(result["ok"], result["errors"])
		self.assertEqual(result["a_files"], 1)
		self.assertGreater(result["archive_bytes_required"], 0)
		self.assertGreater(result["disk_free_bytes"], result["archive_bytes_required"])

	def test_each_batch_persists_checkpoint_and_enqueues_only_the_next(self):
		first = self._file("one")
		second = self._file("two")
		plan = self._plan(first, second)
		run_key = self._start_dry(plan, batch_size=1)

		progress = {
			"state": "completed",
			"processed": 1,
			"optimized": 1,
			"skipped": 0,
			"errors": 0,
			"original_bytes": 1000,
			"new_bytes": 500,
			"skip_reasons": {},
			"optimized_files": [first.name],
			"skipped_files": [],
			"error_files": [],
		}
		with (
			mock.patch.object(runtime, "refresh_active", return_value=True),
			mock.patch.object(runtime, "_live_depth", return_value=0),
			mock.patch.object(runtime.runner, "run_batch", return_value=progress) as run_batch,
			mock.patch.object(runtime, "_enqueue_batch") as enqueue,
		):
			runtime.execute_batch(run_key, 1)

		run_batch.assert_called_once()
		self.assertEqual(run_batch.call_args.kwargs["collect_files"], 1)
		enqueue.assert_called_once_with(run_key, 2)
		state = runtime.status(run_key)
		self.assertEqual(state["status"], "queued")
		self.assertEqual(state["next_batch_index"], 2)
		self.assertEqual(state["processed"], 1)
		self.assertEqual(state["batches"][0]["status"], "completed")
		self.assertEqual(state["batches"][1]["status"], "queued")

	def test_runner_collects_exact_changed_skipped_and_error_identities_on_demand(self):
		outcomes = [
			{"status": "optimized", "original_bytes": 100, "new_bytes": 50},
			{"status": "skipped", "reason": "already_small", "original_bytes": 20, "new_bytes": 20},
			RuntimeError("broken"),
		]
		with (
			mock.patch.object(runtime.runner, "_process_one", side_effect=outcomes),
			mock.patch.object(runtime.runner, "_write_progress"),
			mock.patch.object(runtime.runner.jobs, "record_terminal"),
			mock.patch.object(runtime.runner.audit, "log_media_batch"),
			mock.patch.object(frappe, "log_error"),
		):
			result = runtime.runner.run_batch(
				["changed", "skipped", "errored"], job_key="collect-test", dry_run=1, collect_files=1
			)
		self.assertEqual(result["optimized_files"], ["changed"])
		self.assertEqual(result["skipped_files"], ["skipped"])
		self.assertEqual(result["error_files"], ["errored"])
		self.assertEqual(result["processed"], 3)

	def test_final_dry_batch_is_automatically_integrity_validated(self):
		file_doc = self._file("validate")
		plan = self._plan(file_doc)
		run_key = self._start_dry(plan)
		progress = {
			"state": "completed",
			"processed": 1,
			"optimized": 1,
			"skipped": 0,
			"errors": 0,
			"original_bytes": int(file_doc.file_size or 0),
			"new_bytes": max(1, int(file_doc.file_size or 0) // 2),
			"skip_reasons": {},
			"optimized_files": [file_doc.name],
			"skipped_files": [],
			"error_files": [],
		}
		with (
			mock.patch.object(runtime, "refresh_active", return_value=True),
			mock.patch.object(runtime, "release_active", return_value=True),
			mock.patch.object(runtime, "_live_depth", return_value=0),
			mock.patch.object(runtime.runner, "run_batch", return_value=progress),
		):
			runtime.execute_batch(run_key, 1)

		state = runtime.status(run_key)
		self.assertEqual(state["status"], "validated")
		self.assertTrue(state["validation"]["ok"])
		self.assertEqual(state["validation"]["checked_files"], 1)
		self.assertEqual(state["validation"]["changed_files"], 0)

	def test_wet_run_requires_validated_same_digest_dry_run(self):
		file_doc = self._file("approval")
		plan = self._plan(file_doc)
		dry_key = self._start_dry(plan)
		frappe.db.set_value("Media Migration Run", dry_key, "status", "validated")
		frappe.db.commit()

		with (
			mock.patch.object(runtime, "preflight", return_value=self._preflight(plan)),
			mock.patch.object(runtime, "claim_active", return_value=True),
			mock.patch.object(runtime, "_enqueue_batch"),
		):
			wet = runtime.start(plan, dry_run=False, batch_size=1, approved_dry_run=dry_key)
		frappe.db.commit()
		self.run_keys.append(wet["run_key"])
		wet_doc = frappe.get_doc("Media Migration Run", wet["run_key"])
		self.assertEqual(wet_doc.approved_dry_run, dry_key)
		self.assertEqual(wet_doc.plan_digest, plan["plan_digest"])
		self.assertTrue(runtime.archive_purge_hold()["held"])
		purge = runtime.archive.purge_expired(retention_days=0, trigger="test")
		self.assertTrue(purge["held"])
		self.assertEqual(purge["deleted"], 0)

		tampered = self._plan(file_doc)
		tampered["source"] = "changed-after-signature"
		with self.assertRaises(frappe.ValidationError):
			runtime.start(tampered, dry_run=False, approved_dry_run=dry_key)

	def test_stop_resume_and_exact_reverse_rollback_use_persisted_identity(self):
		file_doc = self._file("rollback")
		plan = self._plan(file_doc)
		dry_key = self._start_dry(plan)
		frappe.db.set_value("Media Migration Run", dry_key, "status", "validated")
		frappe.db.commit()
		with (
			mock.patch.object(runtime, "preflight", return_value=self._preflight(plan)),
			mock.patch.object(runtime, "claim_active", return_value=True),
			mock.patch.object(runtime, "_enqueue_batch"),
		):
			wet = runtime.start(plan, dry_run=False, batch_size=1, approved_dry_run=dry_key)
		wet_key = wet["run_key"]
		self.run_keys.append(wet_key)
		self.assertEqual(runtime.request_stop(wet_key)["status"], "stopping")
		frappe.db.set_value("Media Migration Run", wet_key, "status", "stopped")
		with (
			mock.patch.object(runtime, "claim_active", return_value=True),
			mock.patch.object(runtime, "_enqueue_batch") as resume_enqueue,
		):
			self.assertEqual(runtime.resume(wet_key)["status"], "queued")
		resume_enqueue.assert_called_once_with(wet_key, 1, after_commit=True)
		wet_doc = frappe.get_doc("Media Migration Run", wet_key)
		batch = wet_doc.batches[0]
		frappe.db.set_value(
			"Media Migration Batch",
			batch.name,
			{
				"status": "completed",
				"processed": 1,
				"optimized": 1,
				"changed_files_json": frappe.as_json([file_doc.name]),
			},
		)
		frappe.db.set_value(
			"Media Migration Run",
			wet_key,
			{"status": "completed", "processed": 1, "optimized": 1, "next_batch_index": 2},
		)
		frappe.db.commit()

		with (
			mock.patch.object(runtime, "claim_active", return_value=True),
			mock.patch.object(runtime, "_enqueue_rollback") as enqueue,
		):
			runtime.start_rollback(wet_key)
		enqueue.assert_called_once_with(wet_key, 1, after_commit=True)

		rollback_progress = {
			"state": "completed",
			"processed": 1,
			"optimized": 1,
			"skipped": 0,
			"errors": 0,
			"restored_files": [file_doc.name],
			"error_files": [],
		}
		with (
			mock.patch.object(runtime, "refresh_active", return_value=True),
			mock.patch.object(runtime, "release_active", return_value=True),
			mock.patch.object(
				runtime, "_rollback_validation", return_value={"ok": True, "checked_files": 1, "errors": []}
			),
			mock.patch.object(runtime.runner, "restore_batch", return_value=rollback_progress) as restore,
		):
			runtime.execute_rollback_batch(wet_key, 1)
		restore.assert_called_once()
		self.assertEqual(restore.call_args.args[0], [file_doc.name])
		self.assertEqual(runtime.status(wet_key)["status"], "rolled_back")
		self.assertFalse(runtime.archive_purge_hold()["held"])

	def test_controlled_real_file_dry_wet_validate_and_exact_rollback_rehearsal(self):
		"""T-143/T-144: gerçek disk+DB üzerinde küçük ve geri alınan tatbikat."""
		file_doc = self._image_file()
		plan = self._plan(file_doc)
		original = file_doc.get_content()

		with mock.patch.object(runtime, "_enqueue_batch"):
			dry = runtime.start(plan, dry_run=True, batch_size=1)
		frappe.db.commit()
		self.run_keys.append(dry["run_key"])
		with (
			mock.patch.object(runtime, "_live_depth", return_value=0),
			mock.patch.object(runtime, "_enqueue_batch"),
		):
			runtime.execute_batch(dry["run_key"], 1)
		dry_status = runtime.status(dry["run_key"])
		self.assertEqual(dry_status["status"], "validated")
		self.assertEqual(dry_status["errors"], 0)
		self.assertEqual(dry_status["optimized"], 1)
		self.assertEqual(frappe.get_doc("File", file_doc.name).get_content(), original)

		with mock.patch.object(runtime, "_enqueue_batch"):
			wet = runtime.start(
				plan,
				dry_run=False,
				batch_size=1,
				approved_dry_run=dry["run_key"],
			)
		frappe.db.commit()
		self.run_keys.append(wet["run_key"])
		with (
			mock.patch.object(runtime, "_live_depth", return_value=0),
			mock.patch.object(runtime, "_enqueue_batch"),
		):
			runtime.execute_batch(wet["run_key"], 1)
		wet_status = runtime.status(wet["run_key"])
		self.assertEqual(wet_status["status"], "validated")
		self.assertEqual(wet_status["errors"], 0)
		self.assertEqual(wet_status["optimized"], 1)
		optimized_doc = frappe.get_doc("File", file_doc.name)
		self.assertLess(len(optimized_doc.get_content()), len(original))
		self.assertTrue(optimized_doc.th_optimized_at)

		with mock.patch.object(runtime, "_enqueue_rollback"):
			runtime.start_rollback(wet["run_key"])
		frappe.db.commit()
		with mock.patch.object(runtime, "_enqueue_rollback"):
			rollback = runtime.execute_rollback_batch(wet["run_key"], 1)
		self.assertEqual(rollback["status"], "rolled_back")
		restored = frappe.get_doc("File", file_doc.name)
		self.assertEqual(restored.get_content(), original)
		self.assertFalse(restored.th_optimized_at)
		self.assertEqual(int(restored.th_original_size or 0), 0)
