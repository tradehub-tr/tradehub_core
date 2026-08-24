"""`engine.to_webp` testleri — sunucu garanti-WebP (TUR-128).

Safari/iOS/Capacitor'da `canvas.toBlob('image/webp')` yok; client bu
ortamlarda JPEG fallback gönderiyor. Bu test motorun her koşulda gerçek
WebP ürettiğini ve boyutu küçülttüğünü doğrular. `engine.py`'da `import
frappe` yok — saf Pillow, site kurmadan test edilebilir.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_engine_webp
"""

from __future__ import annotations

import io
import unittest

from PIL import Image

from tradehub_core.media import engine


class TestToWebp(unittest.TestCase):
	def test_to_webp_kucultur_ve_webp_dondurur(self):
		buf = io.BytesIO()
		Image.new("RGB", (3000, 2000), "red").save(buf, "JPEG", quality=95)

		out = engine.to_webp(buf.getvalue(), quality=80)

		self.assertEqual(out[:4], b"RIFF")
		self.assertEqual(out[8:12], b"WEBP")
		self.assertLess(len(out), buf.tell())  # küçüldü

	def test_to_webp_boyutu_2400_ile_sinirlar(self):
		buf = io.BytesIO()
		Image.new("RGB", (4000, 3000), "blue").save(buf, "JPEG", quality=95)

		out = engine.to_webp(buf.getvalue(), quality=80)

		with Image.open(io.BytesIO(out)) as im:
			self.assertEqual(max(im.size), 2400)
			self.assertEqual(im.format, "WEBP")

	def test_to_webp_cagiranin_tavanini_kullanir(self):
		buf = io.BytesIO()
		Image.new("RGB", (1600, 900), "purple").save(buf, "JPEG", quality=95)

		out = engine.to_webp(buf.getvalue(), quality=80, max_dim=512)

		with Image.open(io.BytesIO(out)) as im:
			self.assertEqual(max(im.size), 512)

	def test_to_webp_zaten_webp_olan_gorseli_de_kabul_eder(self):
		src = io.BytesIO()
		Image.new("RGB", (100, 100), "green").save(src, "WEBP", quality=90)

		out = engine.to_webp(src.getvalue(), quality=80)

		self.assertEqual(out[:4], b"RIFF")
		self.assertEqual(out[8:12], b"WEBP")

	def test_to_webp_seffaf_png_alfa_kanalini_korur(self):
		"""Fix round 1, Bulgu 1: koşulsuz `convert("RGB")` alfayı düşürüyordu —
		şeffaf logo/kesim görseli WebP'ye geçince opaklaşıyordu. WebP alfayı
		doğal destekler; `optimize()`'ın generic WebP dalı da `convert("RGB")`
		YAPMADAN kaydediyor (engine.py ~133) — bu davranışla tutarlı olmalı.
		"""
		src = Image.new("RGBA", (200, 200), (255, 0, 0, 0))  # tamamen şeffaf
		opak = Image.new("RGBA", (100, 200), (0, 255, 0, 255))  # sağ yarı opak
		src.paste(opak, (100, 0))
		buf = io.BytesIO()
		src.save(buf, "PNG")

		out = engine.to_webp(buf.getvalue(), quality=80)

		with Image.open(io.BytesIO(out)) as im:
			self.assertEqual(im.format, "WEBP")
			self.assertIn("A", im.getbands())
			alpha = im.getchannel("A")
			self.assertLess(alpha.getpixel((10, 10)), 50)  # sol: şeffaf kaldı
			self.assertGreater(alpha.getpixel((150, 10)), 200)  # sağ: opak kaldı


if __name__ == "__main__":
	unittest.main()
