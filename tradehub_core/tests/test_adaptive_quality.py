"""T-013 biçim sınırı, encode bütçesi ve kayıpsız karar testleri."""

from __future__ import annotations

import io
import unittest

from tradehub_core.media.pipeline.quality.adaptive import (
	AdaptiveQualityError,
	FORMAT_QUALITY_BOUNDS,
	bounds_for,
	select_quality,
)


def image_bytes(*, alpha: bool = False, graphic: bool = False) -> bytes:
	from PIL import Image

	mode = "RGBA" if alpha else "RGB"
	image = Image.new(mode, (192, 128))
	pixels = image.load()
	for y in range(image.height):
		for x in range(image.width):
			if graphic:
				color = (240, 30, 30) if x < 96 else (30, 30, 240)
			else:
				color = ((x * 13 + y * 3) % 256, (x * 5 + y * 17) % 256, (x * y) % 256)
			pixels[x, y] = (*color, 100 if x < 96 else 255) if alpha else color
	out = io.BytesIO()
	image.save(out, "PNG")
	return out.getvalue()


class AdaptiveQualityTest(unittest.TestCase):
	def test_her_codec_ayri_sinir_tasir(self):
		self.assertEqual(set(FORMAT_QUALITY_BOUNDS), {"jpeg", "webp", "avif"})
		self.assertEqual(len(set(FORMAT_QUALITY_BOUNDS.values())), 3)
		for fmt, (low, high) in FORMAT_QUALITY_BOUNDS.items():
			self.assertLess(low, high, fmt)

	def test_jpg_aliasi(self):
		self.assertEqual(bounds_for("jpg"), bounds_for("jpeg"))

	def test_fotograf_en_faz_dort_encode(self):
		result = select_quality(
			image_bytes(),
			fmt="webp",
			content_class="photo",
			target_ssim=0.90,
		)
		self.assertLessEqual(result.encodes, 4)
		self.assertFalse(result.lossless)
		self.assertGreaterEqual(result.ssim, 0.90)
		self.assertGreaterEqual(result.quality, bounds_for("webp")[0])
		self.assertLessEqual(result.quality, bounds_for("webp")[1])

	def test_alfa_kayipsizdir_ve_jpeg_istegi_pngye_duser(self):
		result = select_quality(image_bytes(alpha=True), fmt="jpeg", content_class="photo")
		self.assertTrue(result.lossless)
		self.assertEqual(result.actual_format, "png")
		self.assertEqual(result.quality, "lossless")
		self.assertEqual(result.encodes, 1)

	def test_grafik_kayipsiz_webp(self):
		result = select_quality(image_bytes(graphic=True), fmt="webp", content_class="graphic")
		self.assertTrue(result.lossless)
		self.assertEqual(result.actual_format, "webp")
		self.assertEqual(result.ssim, 1.0)

	def test_butce_dortten_buyuk_olamaz(self):
		with self.assertRaises(AdaptiveQualityError):
			select_quality(image_bytes(), fmt="webp", max_encodes=5)


if __name__ == "__main__":
	unittest.main()
