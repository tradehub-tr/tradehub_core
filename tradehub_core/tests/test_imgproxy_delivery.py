"""T-018 imgproxy imza ve boyut allowlist testleri."""

from __future__ import annotations

import base64
import hashlib
import hmac
import unittest

from tradehub_core.media.pipeline.delivery.imgproxy import (
	IMGPROXY_WIDTHS,
	ImgproxyConfig,
	ImgproxyError,
	ImgproxyUrlBuilder,
)

KEY = "00" * 32
SALT = "11" * 32


class ImgproxyDeliveryTest(unittest.TestCase):
	def setUp(self):
		self.config = ImgproxyConfig("https://images.example.test", KEY, SALT)
		self.builder = ImgproxyUrlBuilder(self.config)

	def test_bes_boyutlu_merdiven(self):
		ladder = self.builder.ladder("https://origin.example.test/files/a b.jpg")
		self.assertEqual(tuple(item.width for item in ladder), IMGPROXY_WIDTHS)
		self.assertEqual(len({item.url for item in ladder}), 5)

	def test_imza_resmi_algoritmayla_ayni(self):
		item = self.builder.build("https://origin.example.test/a.jpg", width=384, output_format="avif")
		digest = hmac.new(bytes.fromhex(KEY), bytes.fromhex(SALT) + item.path.encode(), hashlib.sha256).digest()
		expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
		self.assertEqual(item.signature, expected)
		self.assertIn(f"/{expected}/rs:fit:384:0:0/", item.url)

	def test_allowlist_disi_reddedilir(self):
		with self.assertRaises(ImgproxyError):
			self.builder.build("https://origin.example.test/a.jpg", width=385)

	def test_http_ve_kullanici_bilgili_kaynak_reddedilir(self):
		with self.assertRaises(ImgproxyError):
			self.builder.build("file:///etc/passwd", width=96)
		with self.assertRaises(ImgproxyError):
			self.builder.build("https://user:pass@example.test/a", width=96)

	def test_sirlar_repr_ve_url_icinde_yok(self):
		item = self.builder.build("https://origin.example.test/a.jpg", width=96)
		self.assertNotIn(KEY, repr(self.config))
		self.assertNotIn(SALT, repr(self.config))
		self.assertNotIn(KEY, item.url)
		self.assertNotIn(SALT, item.url)

	def test_hex_olmayan_sir_reddedilir_ama_deger_hatada_yoktur(self):
		secret = "bu-bir-hex-degil"
		with self.assertRaises(ImgproxyError) as ctx:
			ImgproxyConfig("https://images.example.test", secret, SALT)
		self.assertNotIn(secret, str(ctx.exception))


if __name__ == "__main__":
	unittest.main()
