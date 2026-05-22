"""
og_image pure resize testleri.

Pillow gerektirir ama Frappe runtime'a bağımlı değil; standalone unittest:

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_og_image
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from PIL import Image  # noqa: E402

from tradehub_core.seo.og_image import (  # noqa: E402
	OG_HEIGHT,
	OG_WIDTH,
	_cache_filename_for,
	_produce_resized,
	_resolve_to_disk_path,
	resize_to_og_dimensions,
)


class TestResizeToOgDimensions(unittest.TestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp()

	def tearDown(self):
		for f in os.listdir(self.tmpdir):
			os.remove(os.path.join(self.tmpdir, f))
		os.rmdir(self.tmpdir)

	def _make_image(self, w: int, h: int, color: str = "red") -> str:
		path = os.path.join(self.tmpdir, f"src_{w}x{h}.png")
		Image.new("RGB", (w, h), color=color).save(path)
		return path

	def test_square_image_resized_to_1200x630(self):
		src = self._make_image(2000, 2000)
		out = os.path.join(self.tmpdir, "out.jpg")
		resize_to_og_dimensions(src, out)
		with Image.open(out) as img:
			self.assertEqual(img.size, (OG_WIDTH, OG_HEIGHT))

	def test_wide_image_resized_to_1200x630(self):
		src = self._make_image(3000, 1000)  # 3:1 aspect
		out = os.path.join(self.tmpdir, "out.jpg")
		resize_to_og_dimensions(src, out)
		with Image.open(out) as img:
			self.assertEqual(img.size, (OG_WIDTH, OG_HEIGHT))

	def test_narrow_image_resized_to_1200x630(self):
		src = self._make_image(600, 1200)  # 1:2 portrait
		out = os.path.join(self.tmpdir, "out.jpg")
		resize_to_og_dimensions(src, out)
		with Image.open(out) as img:
			self.assertEqual(img.size, (OG_WIDTH, OG_HEIGHT))

	def test_exact_target_size_unchanged(self):
		src = self._make_image(OG_WIDTH, OG_HEIGHT)
		out = os.path.join(self.tmpdir, "out.jpg")
		resize_to_og_dimensions(src, out)
		with Image.open(out) as img:
			self.assertEqual(img.size, (OG_WIDTH, OG_HEIGHT))


class TestCacheFilename(unittest.TestCase):
	def test_deterministic(self):
		a = _cache_filename_for("/files/x.png")
		b = _cache_filename_for("/files/x.png")
		self.assertEqual(a, b)

	def test_different_inputs_produce_different_files(self):
		a = _cache_filename_for("/files/x.png")
		b = _cache_filename_for("/files/y.png")
		self.assertNotEqual(a, b)

	def test_jpg_extension(self):
		self.assertTrue(_cache_filename_for("anything").endswith(".jpg"))


class TestResolveToDiskPath(unittest.TestCase):
	def test_relative_files_path_resolved_against_root(self):
		root = "/srv/site/public/files"
		result = _resolve_to_disk_path("/files/foo.png", root)
		self.assertEqual(result, "/srv/site/public/files/foo.png")

	def test_empty_returns_empty(self):
		self.assertEqual(_resolve_to_disk_path("", "/any"), "")

	def test_non_files_relative_returns_empty(self):
		# Sadece /files/ prefix'i destekleniyor
		self.assertEqual(_resolve_to_disk_path("uploads/x.png", "/any"), "")


class TestProduceResized(unittest.TestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp()
		self.public = os.path.join(self.tmpdir, "public_files")
		self.cache = os.path.join(self.tmpdir, "cache")
		os.makedirs(self.public, exist_ok=True)

	def tearDown(self):
		import shutil
		shutil.rmtree(self.tmpdir, ignore_errors=True)

	def test_resizes_and_returns_cache_url(self):
		# Source resmi public/files/ altına koy
		src_rel = "/files/source.png"
		src_disk = os.path.join(self.public, "source.png")
		Image.new("RGB", (2000, 1500), color="blue").save(src_disk)

		result = _produce_resized(
			src_rel,
			public_files_root=self.public,
			cache_dir=self.cache,
		)
		self.assertTrue(result.startswith("/files/og_cache/"))
		self.assertTrue(result.endswith(".jpg"))

		# Cache dosyası gerçekten oluşmuş ve doğru boyutta
		cache_file = os.path.join(self.cache, os.path.basename(result))
		self.assertTrue(os.path.exists(cache_file))
		with Image.open(cache_file) as img:
			self.assertEqual(img.size, (OG_WIDTH, OG_HEIGHT))

	def test_second_call_returns_cached_without_rebuild(self):
		src_rel = "/files/source.png"
		src_disk = os.path.join(self.public, "source.png")
		Image.new("RGB", (1500, 1500), color="green").save(src_disk)

		r1 = _produce_resized(src_rel, public_files_root=self.public, cache_dir=self.cache)
		cache_file = os.path.join(self.cache, os.path.basename(r1))
		mtime1 = os.path.getmtime(cache_file)

		# Kısa bir yapay gecikme — mtime farklılığı tespit edilebilsin
		import time
		time.sleep(0.05)

		r2 = _produce_resized(src_rel, public_files_root=self.public, cache_dir=self.cache)
		self.assertEqual(r1, r2)
		mtime2 = os.path.getmtime(cache_file)
		# Dosya yeniden yazılmamış olmalı
		self.assertEqual(mtime1, mtime2)

	def test_missing_source_returns_empty(self):
		result = _produce_resized(
			"/files/nonexistent.png",
			public_files_root=self.public,
			cache_dir=self.cache,
		)
		self.assertEqual(result, "")

	def test_error_callback_invoked_on_corrupt_image(self):
		# Corrupt "image" dosyası
		corrupt_path = os.path.join(self.public, "corrupt.png")
		with open(corrupt_path, "w") as f:
			f.write("not a real png")

		errors = []
		result = _produce_resized(
			"/files/corrupt.png",
			public_files_root=self.public,
			cache_dir=self.cache,
			on_error=errors.append,
		)
		self.assertEqual(result, "")
		self.assertEqual(len(errors), 1)


if __name__ == "__main__":
	unittest.main()
