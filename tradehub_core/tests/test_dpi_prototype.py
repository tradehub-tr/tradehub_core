"""T-012 DPI prototipi kabul testleri."""

from __future__ import annotations

import io
import unittest

from tradehub_core.media.pipeline.image.dpi import (
	DpiError,
	NATIVE_DPI_FORMATS,
	SUPPORTED_FORMATS,
	pixel_cap_size,
	rewrite_dpi,
)


def source(fmt: str, *, size: tuple[int, int] = (96, 64), dpi: int = 300) -> bytes:
	from PIL import Image

	image = Image.new("RGB", size)
	pixels = image.load()
	for y in range(size[1]):
		for x in range(size[0]):
			pixels[x, y] = ((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256)
	out = io.BytesIO()
	kwargs = {"dpi": (dpi, dpi)} if fmt in NATIVE_DPI_FORMATS else {}
	if fmt == "JPEG":
		kwargs["quality"] = 92
	image.save(out, fmt, **kwargs)
	return out.getvalue()


class DpiPrototypeTest(unittest.TestCase):
	def test_bes_bicimde_dpi_round_trip_ve_piksel_koruma(self):
		for fmt in SUPPORTED_FORMATS:
			with self.subTest(fmt=fmt):
				try:
					result = rewrite_dpi(source(fmt), dpi=72, fmt=fmt)
				except DpiError as exc:
					if fmt == "AVIF" and "encoder" in str(exc).lower():
						self.skipTest(f"Pillow AVIF encoder yok: {exc}")
					raise
				self.assertEqual((result.width, result.height), (96, 64))
				self.assertTrue(result.pixels_preserved)
				self.assertAlmostEqual(result.dpi[0], 72, delta=0.1)
				self.assertAlmostEqual(result.dpi[1], 72, delta=0.1)
				self.assertEqual(result.storage, "native" if fmt in NATIVE_DPI_FORMATS else "exif")

	def test_3000_kare_dpi_degisiminden_dolayi_720_olmaz(self):
		self.assertEqual(
			pixel_cap_size(3000, 3000, max_long_edge=3000, max_megapixels=9, min_long_edge=2000),
			(3000, 3000),
		)

	def test_piksel_tavani_dpi_degerinden_bagimsizdir(self):
		# İşlev DPI parametresi dahi almaz; yalnız gerçek piksel bütçesi karar verir.
		self.assertEqual(
			pixel_cap_size(3000, 3000, max_long_edge=2400, max_megapixels=8, min_long_edge=2000),
			(2400, 2400),
		)

	def test_minimum_2000_upscale_yaptirmaz(self):
		self.assertEqual(
			pixel_cap_size(1200, 900, max_long_edge=2400, max_megapixels=8, min_long_edge=2000),
			(1200, 900),
		)

	def test_gecersiz_dpi_reddedilir(self):
		with self.assertRaises(DpiError):
			rewrite_dpi(source("PNG"), dpi=0)


if __name__ == "__main__":
	unittest.main()
