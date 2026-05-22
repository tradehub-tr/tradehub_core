"""image_matcher standalone testleri — SKU regex + folder/filename detection."""

import os
import tempfile
import unittest
import zipfile

from tradehub_core.bulk_import import image_matcher


class TestSkuFilenameRegex(unittest.TestCase):
	def test_simple_sku(self):
		m = image_matcher.SKU_FILENAME_RE.match("ABC-001.jpg")
		self.assertIsNotNone(m)
		self.assertEqual(m.group("sku"), "ABC-001")

	def test_sku_with_index(self):
		m = image_matcher.SKU_FILENAME_RE.match("ABC-001_2.jpg")
		self.assertEqual(m.group("sku"), "ABC-001")
		self.assertEqual(m.group("idx"), "2")

	def test_sku_with_named_suffix(self):
		m = image_matcher.SKU_FILENAME_RE.match("ABC-001_main.png")
		self.assertEqual(m.group("sku"), "ABC-001")

	def test_invalid_extension_rejected(self):
		m = image_matcher.SKU_FILENAME_RE.match("ABC-001.txt")
		self.assertIsNone(m)


class TestBuildImageIndex(unittest.TestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp()
		self.zip_path = os.path.join(self.tmpdir, "images.zip")

	def tearDown(self):
		import shutil

		shutil.rmtree(self.tmpdir, ignore_errors=True)

	def _create_zip(self, entries):
		"""entries: {arcname: bytes}"""
		with zipfile.ZipFile(self.zip_path, "w") as z:
			for name, data in entries.items():
				z.writestr(name, data)

	# Real File doctype gerektirdiği için bunları Frappe context'inde test etmek lazım.
	# Burada sadece SKU detection regex testleri yapıyoruz; build_image_index için
	# integration test test_bulk_import.py'da yapılacak.


if __name__ == "__main__":
	unittest.main()
