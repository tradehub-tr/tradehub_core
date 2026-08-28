"""Canlı File → RQ → S3 ayna köprüsü regresyonları.

Bu dosya adaptör sözleşmesini tekrar etmez. Şu eksik halkayı sınar:
Frappe ``File.after_insert`` gerçekten commit-sonrası tekilleştirilmiş iş
üretiyor mu ve dotted-path worker yerel baytı gerçek MinIO'ya taşıyor mu?

    env/bin/python -m unittest tradehub_core.tests.test_media_mirror_runtime -v

MinIO yoksa yalnız gerçek servis testi atlanır; birim testleri koşar.

Kapsanan gereksinimler: FR-105, FR-106, FR-107, NFR-041, NFR-044, NFR-050.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from unittest.mock import MagicMock, patch

import frappe

from tradehub_core.media import mirror_runtime as runtime
from tradehub_core.media.pipeline.fakes.storage import InMemoryStorage
from tradehub_core.media.pipeline.storage import MODE_LOCAL, MODE_MIRROR, StoragePlan
from tradehub_core.media.pipeline.storage.local import LocalDiskStorage
from tradehub_core.media.pipeline.storage.mirror import (
	OP_PUT,
	FrappeEnqueueMirrorQueue,
	MirrorTask,
	inline_mirror,
)
from tradehub_core.media.pipeline.storage.s3 import S3Storage
from tradehub_core.tests.test_storage_adapters_minio import (
	MINIO_OK,
	MINIO_SKIP,
	minio_config,
	purge_prefix,
)


class FakeSettings(dict):
	"""Frappe Single DocType'inin testte gereken dar yüzeyi."""

	def storage_mapping(self) -> dict:
		return dict(self)


def settings(mode: str = MODE_MIRROR, **overrides) -> FakeSettings:
	values = {
		"storage_mode": mode,
		"s3_enabled": 1 if mode == MODE_MIRROR else 0,
		"s3_upload_originals": 1,
		"s3_upload_renditions": 1,
	}
	values.update(overrides)
	return FakeSettings(values)


class MediaMirrorQueueTests(unittest.TestCase):
	def test_local_mode_kuyruk_uretmez(self) -> None:
		with patch.object(runtime, "_storage_doc", return_value=settings(MODE_LOCAL)):
			result = runtime.enqueue_file_url("/files/ab/ab1234.jpg")
		self.assertEqual(result, {"queued": False, "reason": "storage_mode_not_mirror"})

	def test_upload_bayragi_kapaliysa_kuyruk_uretmez(self) -> None:
		with patch.object(
			runtime,
			"_storage_doc",
			return_value=settings(s3_upload_originals=0),
		):
			result = runtime.enqueue_file_url("/files/ab/ab1234.jpg")
		self.assertEqual(result, {"queued": False, "reason": "s3_upload_originals_disabled"})

	def test_shardsiz_ve_dis_url_reddedilir(self) -> None:
		with patch.object(runtime, "_storage_doc", return_value=settings()):
			for url in ("/files/eski.jpg", "https://cdn.example/foto.jpg", "/files/../x.jpg"):
				with self.subTest(url=url):
					self.assertEqual(
						runtime.enqueue_file_url(url),
						{"queued": False, "reason": "unsupported_file_url"},
					)

	def test_frappe_kuyrugu_commit_sonrasi_ve_tekillestirilmis(self) -> None:
		ref = runtime._ref_from_payload("/files/ab/ab1234.jpg")
		with patch.object(frappe, "enqueue") as enqueue:
			queued = FrappeEnqueueMirrorQueue("tradehub_core.api.media_mirror.run_mirror_task").submit(
				MirrorTask(op=OP_PUT, ref=ref)
			)
		self.assertTrue(queued)
		kwargs = enqueue.call_args.kwargs
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertTrue(kwargs["deduplicate"])
		self.assertTrue(kwargs["job_id"].startswith("media-mirror::"))
		self.assertEqual(kwargs["url"], ref.url)

	def test_payload_url_ile_oynanirsa_worker_reddeder(self) -> None:
		with self.assertRaisesRegex(ValueError, "shard"):
			runtime._ref_from_payload(
				"/files/ab/ab1234.jpg",
				scope="public",
				shard="cd",
				name="ab1234.jpg",
			)

	def test_worker_basarili_gorevi_kapatir(self) -> None:
		primary = InMemoryStorage()
		secondary = InMemoryStorage()
		ref = primary.put(b"runtime-worker", ".jpg").ref
		adapter = inline_mirror(primary, secondary)
		plan = StoragePlan(
			adapter=adapter,
			mode=MODE_MIRROR,
			requested_mode=MODE_MIRROR,
		)
		with (
			patch.object(runtime, "_storage_doc", return_value=settings()),
			patch.object(runtime, "_build_runtime_plan", return_value=plan),
		):
			result = runtime.run_mirror_task(**MirrorTask(op=OP_PUT, ref=ref).to_dict())
		self.assertTrue(result["ok"])
		self.assertTrue(secondary.exists(ref))

	def test_hook_kuyruk_hatasinda_file_yuklemesini_dusurmez(self) -> None:
		doc = MagicMock(is_folder=0, file_url="/files/ab/ab1234.jpg")
		with (
			patch.object(runtime, "enqueue_file_url", side_effect=RuntimeError("redis")),
			patch.object(runtime, "_safe_log") as log,
		):
			runtime.maybe_mirror_on_insert(doc)
		log.assert_called_once()

	def test_file_silme_ikincile_delete_gorevi_birakir(self) -> None:
		queue = MagicMock()
		queue.submit.return_value = True
		with (
			patch.object(runtime, "_storage_doc", return_value=settings()),
			patch.object(runtime, "FrappeEnqueueMirrorQueue", return_value=queue),
		):
			runtime.maybe_mirror_on_trash(
				MagicMock(is_folder=0, file_url="/files/ab/ab1234.jpg")
			)
		task = queue.submit.call_args.args[0]
		self.assertEqual(task.op, "delete")
		self.assertEqual(task.ref.url, "/files/ab/ab1234.jpg")


@unittest.skipUnless(MINIO_OK, MINIO_SKIP)
class MediaMirrorMinioTests(unittest.TestCase):
	def setUp(self) -> None:  # noqa: N802
		self.site_path = tempfile.mkdtemp(prefix="media-mirror-runtime-")
		self.prefix = f"t051/runtime/{uuid.uuid4().hex[:10]}"

	def tearDown(self) -> None:  # noqa: N802
		purge_prefix(self.prefix)
		shutil.rmtree(self.site_path, ignore_errors=True)

	def test_worker_yerel_bayti_gercek_minioya_yazar(self) -> None:
		local = LocalDiskStorage(
			f"{self.site_path}/public/files",
			f"{self.site_path}/private/files",
			fsync=False,
		)
		ref = local.put(b"live-file-to-minio", ".jpg").ref
		conf = minio_config(self.prefix)
		ayar = settings(
			s3_bucket=conf.bucket,
			s3_region=conf.region,
			s3_endpoint_url=conf.endpoint_url,
			s3_prefix=conf.prefix,
			s3_access_key_id=conf.access_key_id,
			s3_secret_access_key=conf.secret_access_key,
			s3_path_style=1,
		)
		with (
			patch.object(runtime, "_storage_doc", return_value=ayar),
			patch.object(frappe, "get_site_path", return_value=self.site_path),
		):
			result = runtime.run_mirror_task(**MirrorTask(op=OP_PUT, ref=ref).to_dict())

		self.assertTrue(result["ok"])
		self.assertTrue(S3Storage(conf).exists(ref), "beklenen ObjectRef MinIO'da yok")


if __name__ == "__main__":
	unittest.main(verbosity=2)
