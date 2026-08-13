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

	def test_to_webp_boyutu_1920_ile_sinirlar(self):
		buf = io.BytesIO()
		Image.new("RGB", (4000, 3000), "blue").save(buf, "JPEG", quality=95)

		out = engine.to_webp(buf.getvalue(), quality=80)

		with Image.open(io.BytesIO(out)) as im:
			self.assertLessEqual(max(im.size), 1920)
			self.assertEqual(im.format, "WEBP")

	def test_to_webp_zaten_webp_olan_gorseli_de_kabul_eder(self):
		src = io.BytesIO()
		Image.new("RGB", (100, 100), "green").save(src, "WEBP", quality=90)

		out = engine.to_webp(src.getvalue(), quality=80)

		self.assertEqual(out[:4], b"RIFF")
		self.assertEqual(out[8:12], b"WEBP")


if __name__ == "__main__":
	unittest.main()
