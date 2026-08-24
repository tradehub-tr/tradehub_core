"""T-063 literal performans bütçesi: 2400×2400 master, 34 rendition, tek çekirdek."""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from tradehub_core.media.pipeline.image import render as R

FIXTURE = Path(__file__).parent / "fixtures" / "media" / "images" / "ok_product_1x1_2400.jpg"


@unittest.skipUnless(FIXTURE.is_file(), "2400×2400 fixture yok")
class OtuzDortRenditionButcesi(unittest.TestCase):
	def test_34_rendition_12_saniyenin_altinda(self):
		kaynak = FIXTURE.read_bytes()
		profiller = tuple(
			R.RenditionProfile(
				slot_key="product.image",
				name=f"perf-{i:02d}",
				# 17 AYRI tuval × 2 format: encode cache'e yaslanan boş-doğru
				# ölçüm değil, 34 gerçek çıktı.
				width=(i + 1) * 96,
				formats=("webp", "jpeg"),
				fit="contain",
				encoder_quality=(("jpeg", 82), ("webp", 80)),
			)
			for i in range(17)
		)

		baslangic = time.perf_counter()
		sonuclar = R.render_ladder(
			kaynak,
			"product.image",
			profiles=profiller,
			per_format=True,
		)
		sure = time.perf_counter() - baslangic

		self.assertEqual(len(sonuclar), 34)
		self.assertEqual(len({(r.width, r.format) for r in sonuclar}), 34)
		self.assertGreaterEqual(sum(r.encodes for r in sonuclar), 34)
		self.assertTrue(all(not r.passthrough for r in sonuclar))
		self.assertTrue(all(r.size_bytes < len(kaynak) for r in sonuclar))
		self.assertLess(sure, 12.0, f"34 rendition {sure:.3f} sn sürdü")
		self.assertTrue(all(r.encodes <= R.DEFAULT_MAX_ENCODES for r in sonuclar))
		self.assertTrue(all(not r.ssim_target or r.ssim >= r.ssim_target for r in sonuclar))


if __name__ == "__main__":
	unittest.main(verbosity=2)
