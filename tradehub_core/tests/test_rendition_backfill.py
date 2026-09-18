"""Eski görsellerin yayın sonrası taranması, checkpoint ve sınırlı retry."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import Mock, patch

import frappe

from tradehub_core.media import pipeline_bridge
from tradehub_core.media import rendition_backfill as backfill
from tradehub_core.patches import v15_9_58_enable_media_and_backfill as activation


class RenditionBackfillTests(unittest.TestCase):
	def setUp(self):
		self.state = backfill._new_state()
		self.names = ["file-a", "file-b", "file-c"]
		self.fake = Mock()
		self.fake.cache.lock.return_value.acquire.return_value = True
		self.fake.get_traceback.return_value = "test error"
		self.process = Mock(return_value=("generated", ""))
		self.enqueue = Mock()
		self.saved = []
		patches = (
			patch.object(backfill, "frappe", self.fake),
			patch.object(backfill, "get_redis_conn", return_value=self.fake.cache),
			patch.object(backfill, "status", side_effect=lambda: copy.deepcopy(self.state)),
			patch.object(backfill, "_save", side_effect=self._save),
			patch.object(backfill, "_candidates", side_effect=self._candidates),
			patch.object(backfill, "_process_file", self.process),
			patch.object(backfill, "enqueue_pending", self.enqueue),
			patch.object(backfill.pipeline_flags, "is_enabled", return_value=True),
			patch.object(backfill.pipeline_flags, "clear_cache"),
		)
		for item in patches:
			item.start()
			self.addCleanup(item.stop)

	def _save(self, state):
		self.state = copy.deepcopy(state)
		self.saved.append(copy.deepcopy(state))

	def _candidates(self, cursor, limit):
		return [name for name in self.names if name > cursor][:limit]

	def test_batch_limit_continues_without_reprocessing_checkpoint(self):
		with patch.object(backfill, "BATCH_SIZE", 2):
			first = backfill.run_batch()
		self.assertEqual((first["scanned"], first["cursor"]), (2, "file-b"))
		self.enqueue.assert_called_once()

		last = backfill.run_batch()
		self.assertEqual(last["status"], "completed")
		self.assertEqual(last["generated"], 3)
		self.assertEqual([c.args[0] for c in self.process.call_args_list], self.names)

	def test_failed_file_retries_then_allows_following_files(self):
		self.process.side_effect = lambda name: (
			("failed", "decode") if name == "file-a" else ("generated", "")
		)
		for attempt in range(1, backfill.MAX_ATTEMPTS):
			result = backfill.run_batch()
			self.assertEqual(result["attempts"], attempt)
			self.assertEqual(result["cursor"], "")
		result = backfill.run_batch()
		self.assertEqual(result["status"], "completed_with_errors")
		self.assertEqual((result["failed"], result["generated"]), (1, 2))
		self.assertEqual(self.process.call_count, backfill.MAX_ATTEMPTS + 2)

	def test_interrupted_worker_does_not_retry_one_file_forever(self):
		self.state.update(current_file="file-a", attempts=backfill.MAX_ATTEMPTS)
		result = backfill.run_batch()
		self.assertEqual(result["failed"], 1)
		self.assertEqual(result["error_examples"][0]["reason"], "worker_interrupted")
		self.assertEqual([c.args[0] for c in self.process.call_args_list], ["file-b", "file-c"])

	def test_attempt_is_durable_before_processing(self):
		def check_checkpoint(name):
			self.assertEqual(self.saved[-1]["current_file"], name)
			self.assertEqual(self.saved[-1]["attempts"], 1)
			return "generated", ""

		self.process.side_effect = check_checkpoint
		backfill.run_batch()

	def test_existing_outputs_and_excluded_files_have_separate_counts(self):
		self.process.side_effect = [("already_ready", ""), ("skipped", "out_of_scope"), ("generated", "")]
		result = backfill.run_batch()
		self.assertEqual((result["already_ready"], result["skipped"], result["generated"]), (1, 1, 1))
		self.assertEqual(result["skip_reasons"], {"out_of_scope": 1})

	def test_disabled_pipeline_keeps_checkpoint_for_resume(self):
		with patch.object(backfill.pipeline_flags, "is_enabled", return_value=False):
			result = backfill.run_batch()
		self.assertEqual(result["status"], "paused")
		self.assertEqual(result["cursor"], "")
		self.process.assert_not_called()
		self.assertEqual(backfill.run_batch()["status"], "completed")

	def test_second_worker_does_not_process_the_same_batch(self):
		self.fake.cache.lock.return_value.acquire.return_value = False
		self.assertEqual(backfill.run_batch()["status"], "busy")
		self.process.assert_not_called()

	def test_job_lock_is_separate_from_frappe_cache(self):
		queue_redis = Mock()
		queue_redis.lock.return_value.acquire.return_value = False
		with patch.object(backfill, "get_redis_conn", return_value=queue_redis):
			backfill.run_batch()
		queue_redis.lock.assert_called_once()
		self.fake.cache.lock.assert_not_called()

	def test_completed_migration_does_not_restart_scan(self):
		self.state["status"] = "completed"
		self.assertEqual(backfill.run_batch()["status"], "completed")
		self.process.assert_not_called()

	def test_slow_batch_yields_after_current_file(self):
		with patch.object(backfill.time, "monotonic", side_effect=[0, backfill.BATCH_SECONDS + 1]):
			result = backfill.run_batch()
		self.assertEqual(result["scanned"], 1)
		self.assertEqual(result["cursor"], "file-a")
		self.enqueue.assert_called_once()

	def test_processing_exception_keeps_durable_retry_checkpoint(self):
		self.process.side_effect = RuntimeError("decoder unavailable")
		result = backfill.run_batch()
		self.assertEqual(result["cursor"], "")
		self.assertEqual(result["attempts"], 1)
		self.fake.db.rollback.assert_called_once()
		self.enqueue.assert_called_once()


class LibraryImageScopeTests(unittest.TestCase):
	def _file(self, **overrides):
		doc = frappe._dict(
			name="library-photo",
			file_name="photo.jpg",
			file_url="/files/photo.jpg",
			is_private=0,
			is_folder=0,
			attached_to_doctype=None,
			attached_to_field=None,
			content_hash=None,
		)
		doc.update(overrides)
		return doc

	def test_unattached_library_image_is_included_without_crop(self):
		with (
			patch.object(pipeline_bridge, "_slot_from_reference", return_value=None),
			patch("tradehub_core.media.access_level._is_protected_pii", return_value=False),
		):
			self.assertEqual(pipeline_bridge._resolve_scope(self._file()), "library.image")

	def test_sensitive_unattached_document_is_not_treated_as_library_photo(self):
		with (
			patch.object(pipeline_bridge, "_slot_from_reference", return_value=None),
			patch("tradehub_core.media.access_level._is_protected_pii", return_value=True),
		):
			self.assertIsNone(pipeline_bridge._resolve_scope(self._file()))

	def test_private_image_and_known_sensitive_attachment_stay_excluded(self):
		self.assertIsNone(pipeline_bridge._resolve_scope(self._file(is_private=1)))
		self.assertIsNone(pipeline_bridge._resolve_scope(self._file(attached_to_doctype="KYB Verification")))

	def test_other_public_image_attachment_gets_uncropped_library_derivatives(self):
		with patch("tradehub_core.media.access_level._is_protected_pii", return_value=False):
			self.assertEqual(
				pipeline_bridge._resolve_scope(self._file(attached_to_doctype="Product Category")),
				"library.image",
			)


class ExistingSiteActivationTests(unittest.TestCase):
	def test_upgrade_enables_existing_disabled_flags_and_all_scopes(self):
		settings = Mock(
			media_pipeline_enabled=0, rendition_on_upload=0, manifest_api_enabled=0, active_slots=""
		)
		with (
			patch.object(activation, "frappe") as fake,
			patch.object(activation, "seed_settings"),
			patch.object(activation.pipeline_flags, "clear_cache"),
		):
			fake.get_doc.return_value = settings
			activation.execute()
		self.assertEqual(settings.media_pipeline_enabled, 1)
		self.assertEqual(settings.rendition_on_upload, 1)
		self.assertEqual(settings.manifest_api_enabled, 1)
		self.assertEqual(settings.active_slots, "*")
		self.assertEqual(settings.rollout_percent, 100)
		settings.save.assert_called_once_with(ignore_permissions=True)


class HistoricalFileManifestTests(unittest.TestCase):
	def test_same_public_content_at_two_urls_resolves_for_both_files(self):
		from tradehub_core.api import media_manifest

		files = [
			{"name": "a", "file_url": "/files/a.jpg", "content_hash": "same", "is_private": 0},
			{"name": "b", "file_url": "/files/b.jpg", "content_hash": "same", "is_private": 0},
		]
		with patch.object(media_manifest.frappe, "get_all", side_effect=[files, files]):
			bridge = media_manifest._mukerrer_dosya_koprusu(files)
		self.assertEqual(set(bridge["/files/a.jpg"]), {"a", "b"})
		self.assertEqual(set(bridge["/files/b.jpg"]), {"a", "b"})
		owned_asset = {"name": "owned", "source_file": "a", "active_version": "v1"}
		with (
			patch.object(media_manifest.frappe, "get_list", return_value=[owned_asset]) as permitted,
			patch.object(media_manifest.frappe, "get_all") as unfiltered,
		):
			assets = media_manifest._dosya_varliklari(bridge)
		self.assertEqual(assets["/files/a.jpg"], [owned_asset])
		self.assertEqual(assets["/files/b.jpg"], [owned_asset])
		permitted.assert_called_once()
		unfiltered.assert_not_called()

	def test_private_file_does_not_expand_by_content_hash(self):
		from tradehub_core.api import media_manifest

		files = [
			{"name": "private", "file_url": "/private/files/a.jpg", "content_hash": "same", "is_private": 1}
		]
		with patch.object(media_manifest.frappe, "get_all", return_value=files) as query:
			media_manifest._mukerrer_dosya_koprusu(files)
		query.assert_called_once()


class AvifBackfillReadinessTests(unittest.TestCase):
	def _ready(self, rows, *, exists=True):
		with (
			patch.object(backfill.frappe.db, "sql", return_value=rows),
			patch.object(backfill.ownership, "store_of", return_value="seller-a"),
			patch(
				"tradehub_core.media.pipeline.image.render.load_slot_policy", return_value={"profiles": []}
			),
			patch.object(backfill.os.path, "isfile", return_value=exists),
		):
			return backfill._ready(frappe._dict(owner="owner"), "source", "product.image")

	def test_old_mixed_version_is_regenerated(self):
		self.assertFalse(
			self._ready(
				[("/files/a.avif", "avif", '{"profiles": []}'), ("/files/a.webp", "webp", '{"profiles": []}')]
			)
		)

	def test_old_avif_policy_is_regenerated(self):
		self.assertFalse(self._ready([("/files/a.avif", "avif", '{"profiles": ["old"]}')]))

	def test_only_current_complete_avif_outputs_are_skipped(self):
		rows = [("/files/a.avif", "avif", '{"profiles": []}')]
		self.assertTrue(self._ready(rows))
		self.assertFalse(self._ready(rows, exists=False))
		self.assertFalse(self._ready([]))


class AvifManifestTests(unittest.TestCase):
	def test_variant_images_join_the_gallery_without_duplicates_or_private_urls(self):
		from tradehub_core.api import media_manifest as api

		gallery = [{"parent": "listing", "image": "/files/main.jpg", "alt_text": "main"}]
		variants = [
			{
				"parent": "listing",
				"variant_image": "/files/red.jpg",
				"variant_gallery": '["/files/main.jpg", "/files/detail.jpg", "/private/files/secret.jpg"]',
			}
		]
		with patch.object(api.frappe, "get_all", side_effect=[gallery, variants]) as query:
			images = api._ilan_gorselleri([{"name": "listing", "primary_image": "/files/main.jpg"}])
		self.assertEqual(
			[i["file_url"] for i in images["listing"]],
			["/files/main.jpg", "/files/red.jpg", "/files/detail.jpg"],
		)
		self.assertEqual(query.call_count, 2)
		self.assertEqual(
			query.call_args.kwargs["filters"], {"parent": ["in", ["listing"]], "parenttype": "Listing"}
		)

	def test_native_avif_srcset_uses_actual_width(self):
		from tradehub_core.api import media_manifest as api

		manifest = api._render_manifest(
			"product.image",
			"/files/small.jpg",
			[
				{
					"profile": "w96",
					"format": "avif",
					"width": 64,
					"height": 64,
					"file_url": "/files/small-64.avif",
				}
			],
			alt="small",
			is_lcp=False,
		)
		self.assertIsNotNone(manifest)
		self.assertEqual([s["type"] for s in manifest["sources"]], ["image/avif"])
		self.assertEqual(manifest["sources"][0]["srcset"], "/files/small-64.avif 64w")
		self.assertEqual(manifest["src"], "/files/small-64.avif")
