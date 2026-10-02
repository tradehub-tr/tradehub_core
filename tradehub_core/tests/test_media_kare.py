"""Ürün görseli kare dönüşümü — saf fonksiyonlar (spec 2026-09-29 §1)."""

import io

from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.media import kare


def _img(w, h, mode="RGB", color=(200, 30, 30), fmt="JPEG", **save):
	im = Image.new(mode, (w, h), color)
	buf = io.BytesIO()
	im.save(buf, fmt, **save)
	return buf.getvalue()


def _ac(b):
	return Image.open(io.BytesIO(b))


class TestKareBoyutu(FrappeTestCase):
	def test_ornek_tablo(self):
		self.assertEqual(kare.kare_boyutu(3068, 2547), 2000)
		self.assertEqual(kare.kare_boyutu(800, 1000), 1000)
		self.assertEqual(kare.kare_boyutu(600, 500), 1000)
		self.assertEqual(kare.kare_boyutu(1500, 900), 1500)
		self.assertEqual(kare.kare_boyutu(2000, 2000), None)
		self.assertEqual(kare.kare_boyutu(1200, 1200), None)
		self.assertEqual(kare.kare_boyutu(1000, 1000), None)
		self.assertEqual(kare.kare_boyutu(800, 800), 1000)
		self.assertEqual(kare.kare_boyutu(2500, 2500), 2000)

	def test_gecersiz(self):
		self.assertIsNone(kare.kare_boyutu(0, 100))


class TestKareyeCevir(FrappeTestCase):
	def test_buyuk_yatay_2000_kare(self):
		out, s = kare.kareye_cevir(_img(3068, 2547))
		im = _ac(out)
		self.assertEqual((s, im.format, im.size), (2000, "WEBP", (2000, 2000)))
		# Üst kenar dolgu: beyaz; merkez: ürün rengi.
		self.assertEqual(im.convert("RGB").getpixel((1000, 5)), (255, 255, 255))
		r, g, b = im.convert("RGB").getpixel((1000, 1000))
		self.assertTrue(r > 150 and g < 90)

	def test_kucuk_buyutulmez_1000_tuval(self):
		out, s = kare.kareye_cevir(_img(600, 500))
		im = _ac(out).convert("RGB")
		self.assertEqual((s, im.size), (1000, (1000, 1000)))
		# Görsel 600 px genişlikte kalır: x=150 beyaz, x=250 kırmızı.
		self.assertEqual(im.getpixel((150, 500)), (255, 255, 255))
		self.assertTrue(im.getpixel((250, 500))[0] > 150)

	def test_dikey_800x1000(self):
		out, s = kare.kareye_cevir(_img(800, 1000))
		im = _ac(out).convert("RGB")
		self.assertEqual(im.size, (1000, 1000))
		self.assertEqual(im.getpixel((50, 500)), (255, 255, 255))

	def test_seffaf_png_beyaz(self):
		out, _s = kare.kareye_cevir(_img(1200, 600, "RGBA", (0, 0, 0, 0), "PNG"))
		im = _ac(out)
		self.assertNotIn("A", im.mode)
		self.assertEqual(im.convert("RGB").getpixel((600, 600)), (255, 255, 255))

	def test_cmyk_jpeg(self):
		out, s = kare.kareye_cevir(_img(1200, 900, "CMYK", (0, 0, 0, 0)))
		self.assertEqual(_ac(out).size, (1200, 1200))

	def test_exif_dondurme(self):
		im = Image.new("RGB", (1600, 1000), (10, 200, 10))
		exif = im.getexif()
		exif[0x0112] = 6  # 90° döndür → 1000x1600
		buf = io.BytesIO()
		im.save(buf, "JPEG", exif=exif)
		out, s = kare.kareye_cevir(buf.getvalue())
		self.assertEqual(s, 1600)
		# Döndürülmüş görsel dikey: sol kenar beyaz dolgu.
		self.assertEqual(_ac(out).convert("RGB").getpixel((5, 800)), (255, 255, 255))

	def test_zaten_kare_webp_atlar(self):
		with self.assertRaises(kare.Atla) as c:
			kare.kareye_cevir(_img(1200, 1200, fmt="WEBP"))
		self.assertEqual(c.exception.reason, "already_square")

	def test_kare_jpeg_ayni_olcude_webp_olur(self):
		"""2026-09-30: kare + aralıkta ama WebP olmayan görsel yalnız biçim değiştirir."""
		out, s = kare.kareye_cevir(_img(1200, 1200))
		self.assertEqual(s, 1200)
		with _ac(out) as im:
			self.assertEqual((im.format, im.size), ("WEBP", (1200, 1200)))
			# Dolgu yok: köşe de ortayla aynı renk (JPEG/WebP kaybı ±4 tolerans).
			orta, kose = im.convert("RGB").getpixel((600, 600)), im.convert("RGB").getpixel((5, 5))
			self.assertTrue(all(abs(a - b) <= 4 for a, b in zip(orta, kose, strict=True)), (orta, kose))

	def test_kare_png_alfa_beyaza_duzlenir(self):
		out, s = kare.kareye_cevir(_img(1500, 1500, mode="RGBA", color=(0, 0, 0, 0), fmt="PNG"))
		self.assertEqual(s, 1500)
		self.assertEqual(_ac(out).convert("RGB").getpixel((10, 10)), (255, 255, 255))

	def test_animasyonlu_gif_atlar(self):
		frames = [Image.new("P", (1200, 800), i) for i in range(2)]
		buf = io.BytesIO()
		frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:])
		with self.assertRaises(kare.Atla) as c:
			kare.kareye_cevir(buf.getvalue())
		self.assertEqual(c.exception.reason, "animated")

	def test_bozuk_icerik(self):
		with self.assertRaises(kare.Atla) as c:
			kare.kareye_cevir(b"not an image")
		self.assertEqual(c.exception.reason, "unreadable")

	def test_cok_buyuk_gorsel_decompression_bomb(self):
		"""DecompressionBombError yakalama — MAX_IMAGE_PIXELS aşıldığında."""
		from unittest import mock

		# MAX_IMAGE_PIXELS < 1200*1200 olduğunda Image.load() raise eder
		with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 1000):
			with self.assertRaises(kare.Atla) as c:
				kare.kareye_cevir(_img(1200, 1200))
			self.assertEqual(c.exception.reason, "too_large")
