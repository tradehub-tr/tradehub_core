"""T-050 streaming storage contract and atomic-failure guards."""

from __future__ import annotations

import os
import tempfile
import tracemalloc
import unittest

from tradehub_core.media.pipeline.delivery.signed import HmacUrlSigner
from tradehub_core.media.pipeline.storage.local import TEMP_PREFIX, LocalDiskStorage
from tradehub_core.media.pipeline.storage.mirror import inline_mirror
from tradehub_core.media.pipeline.storage.s3 import S3Config, S3Storage
from tradehub_core.media.pipeline.storage.tiered import TieredStorage
from tradehub_core.tests.test_storage_adapters import FakeS3Client


class StorageStreamingContractTest(unittest.TestCase):
	CHUNK = b"media-stream-contract\0" * 4096
	COUNT = 129

	def setUp(self) -> None:
		self.tmp = tempfile.TemporaryDirectory(prefix="media-stream-test-")
		self.addCleanup(self.tmp.cleanup)
		self.local = LocalDiskStorage(
			os.path.join(self.tmp.name, "public"),
			os.path.join(self.tmp.name, "private"),
			fsync=False,
			signer=HmacUrlSigner(b"stream-test-signing-key"),
		)
		self.client = FakeS3Client()
		self.s3 = S3Storage(
			S3Config(enabled=True, bucket="stream-test", prefix="stream"),
			client_factory=lambda: self.client,
		)

	def _chunks(self):
		for _ in range(self.COUNT):
			yield self.CHUNK

	def test_dort_mod_ayni_stream_contractini_gecer(self) -> None:
		stores = {
			"local": self.local,
			"s3": self.s3,
			"mirror": inline_mirror(self.local, self.s3),
			"tiered": TieredStorage(self.local, self.s3, age_days=90),
		}
		expected_size = len(self.CHUNK) * self.COUNT
		for name, store in stores.items():
			with self.subTest(mode=name):
				result = store.put_stream(self._chunks(), f".{name}.bin")
				self.assertEqual(result.stat.size_bytes, expected_size)
				self.assertEqual(sum(map(len, store.iter_bytes(result.ref))), expected_size)
				again = store.put_stream(self._chunks(), f".{name}.bin")
				self.assertFalse(again.created)

	def test_stream_peak_memory_girdiden_bagimsizdir(self) -> None:
		tracemalloc.start()
		try:
			result = self.local.put_stream(self._chunks(), ".bin")
			_current, peak = tracemalloc.get_traced_memory()
		finally:
			tracemalloc.stop()
		self.assertGreater(result.stat.size_bytes, 8 * 1024 * 1024)
		self.assertLess(peak, 16 * 1024 * 1024)

	def test_stream_hatasi_gecici_dosya_birakmaz(self) -> None:
		def broken():
			yield self.CHUNK
			raise RuntimeError("injected stream failure")

		with self.assertRaises(RuntimeError):
			self.local.put_stream(broken(), ".bin")
		leftovers = [
			name
			for root, _dirs, files in os.walk(self.tmp.name)
			for name in files
			if name.startswith(TEMP_PREFIX)
		]
		self.assertEqual(leftovers, [])


if __name__ == "__main__":
	unittest.main()
