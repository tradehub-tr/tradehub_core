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


class TestNormalizeSkuKey(unittest.TestCase):
	def test_case_insensitive(self):
		self.assertEqual(
			image_matcher.normalize_sku_key("ABC-001"),
			image_matcher.normalize_sku_key("abc-001"),
		)

	def test_turkish_fold(self):
		# "İ"/"Ş" gibi karakterler ASCII'ye indirgenir, lookup tutarlı olur
		self.assertEqual(image_matcher.normalize_sku_key("ÜRÜN-İŞ"), "urun-is")

	def test_strip(self):
		self.assertEqual(image_matcher.normalize_sku_key("  X1 "), "x1")


class TestNaturalSort(unittest.TestCase):
	def test_numeric_order_not_lexicographic(self):
		files = ["10.jpg", "2.jpg", "1.jpg", "main.jpg"]
		ordered = sorted(files, key=image_matcher._natural_key)
		# 1,2,10 (leksikografik olsaydı 1,10,2 olurdu)
		self.assertEqual(ordered[:3], ["1.jpg", "2.jpg", "10.jpg"])


class TestLooksLikeImage(unittest.TestCase):
	def test_jpeg_signature(self):
		self.assertTrue(image_matcher._looks_like_image(b"\xff\xd8\xff" + b"\x00" * 20))

	def test_png_signature(self):
		self.assertTrue(image_matcher._looks_like_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20))

	def test_webp_signature(self):
		self.assertTrue(image_matcher._looks_like_image(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8))

	def test_garbage_rejected(self):
		self.assertFalse(image_matcher._looks_like_image(b"this is not an image at all"))

	def test_too_short_rejected(self):
		self.assertFalse(image_matcher._looks_like_image(b"\xff\xd8"))


class TestLeadingCode(unittest.TestCase):
	def test_suffix_stripped(self):
		self.assertEqual(image_matcher._leading_code("325 LOGOSUZ"), "325")

	def test_variant_dash(self):
		self.assertEqual(image_matcher._leading_code("308-1"), "308")

	def test_plain_code_with_letter(self):
		self.assertEqual(image_matcher._leading_code("191G"), "191g")

	def test_no_leading_digit(self):
		self.assertIsNone(image_matcher._leading_code("Kamp1"))


class TestMatchSkuInPath(unittest.TestCase):
	# pass 1/2 ile eşleşen durumlar (regex_lib/frappe'ye düşmez → standalone)
	def test_deep_folder_exact(self):
		p = "FOTO/KATEGORI/307/307-2.jpg"
		self.assertEqual(image_matcher._match_sku_in_path(p, {"307"}, "S1"), "307")

	def test_suffix_folder_token(self):
		p = "FOTO/325 LOGOSUZ/Kamp1.png"
		self.assertEqual(image_matcher._match_sku_in_path(p, {"325"}, "S1"), "325")

	def test_exact_beats_token_when_deeper_category_looks_like_sku(self):
		# Yol: .../308/307 SEHPA/f.jpg — SKU klasörü 308 üstte, altında "307 ..."
		# Tam eşleşme (308) token eşleşmesinden (307) önce gelmeli.
		p = "FOTO/308/307 SEHPA/f.jpg"
		self.assertEqual(image_matcher._match_sku_in_path(p, {"307", "308"}, "S1"), "308")

	def test_top_level_filename_stem(self):
		self.assertEqual(image_matcher._match_sku_in_path("307.jpg", {"307"}, "S1"), "307")


class TestOptimizeImage(unittest.TestCase):
	def _img(self, fmt, size):
		from io import BytesIO

		from PIL import Image

		buf = BytesIO()
		Image.new("RGB", size, (123, 200, 50)).save(buf, fmt)
		return buf.getvalue()

	def test_downscale_preserves_png(self):
		from io import BytesIO

		from PIL import Image

		out = image_matcher.optimize_image(self._img("PNG", (2400, 1800)))
		im = Image.open(BytesIO(out))
		self.assertEqual(im.format, "PNG")  # format korunur
		self.assertLessEqual(max(im.size), image_matcher.MAX_IMAGE_DIM)  # küçültüldü

	def test_downscale_preserves_jpeg(self):
		from io import BytesIO

		from PIL import Image

		out = image_matcher.optimize_image(self._img("JPEG", (3000, 2000)))
		im = Image.open(BytesIO(out))
		self.assertEqual(im.format, "JPEG")
		self.assertLessEqual(max(im.size), image_matcher.MAX_IMAGE_DIM)

	def test_garbage_returns_original(self):
		raw = b"this is not an image"
		self.assertEqual(image_matcher.optimize_image(raw), raw)  # başarısızlık güvenli


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
