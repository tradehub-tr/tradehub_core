# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

"""SEO içerik kuralları birim testleri — saf fonksiyonlar (frappe bağımsız)."""

import unittest

from tradehub_core.utils.seo_content import (
	DESC_MIN_CHARS,
	TITLE_MIN_CHARS,
	check_description,
	check_title,
	contains_emoji,
	visible_text_length,
)

_GOOD_TITLE = "Piknik Seti 4 Parça Plastik Servis ve Saklama Kabı Açık Hava İçin"
_GOOD_DESC = "Dayanıklı plastikten üretilmiş, mutfakta saklama için ideal, uzun ömürlü ürün. " * 3


class TestSeoContent(unittest.TestCase):
	def test_emoji_turkce_harf_yanlis_eslesmez(self):
		self.assertFalse(contains_emoji("Çelik Öğütücü Şişe Ürün İğne Ğ"))
		self.assertFalse(contains_emoji("Marka® Ürün™ ©2026"))

	def test_emoji_yakalanir(self):
		self.assertTrue(contains_emoji("Süper ürün 🔥"))
		self.assertTrue(contains_emoji("Yıldız ⭐ set"))
		self.assertTrue(contains_emoji("Bayrak 🇹🇷"))

	def test_visible_text_length_html_saymaz(self):
		self.assertEqual(visible_text_length("<p>abc</p>"), 3)
		self.assertEqual(visible_text_length("<b>ab</b>&nbsp;<i>cd</i>"), 5)

	def test_title_kisa_reddedilir(self):
		ok, msg = check_title("Kısa Ad")
		self.assertFalse(ok)
		self.assertIn(str(TITLE_MIN_CHARS), msg)

	def test_title_bos_reddedilir(self):
		ok, msg = check_title("   ")
		self.assertFalse(ok)

	def test_title_emoji_reddedilir(self):
		ok, msg = check_title(_GOOD_TITLE + " 🔥")
		self.assertFalse(ok)
		self.assertIn("emoji", msg.lower())

	def test_title_iyi_gecer(self):
		ok, msg = check_title(_GOOD_TITLE)
		self.assertTrue(ok, msg)

	def test_desc_kisa_reddedilir(self):
		ok, msg = check_description("<p>Çok kısa.</p>")
		self.assertFalse(ok)
		self.assertIn(str(DESC_MIN_CHARS), msg)

	def test_desc_emoji_reddedilir(self):
		ok, msg = check_description(_GOOD_DESC + " 🔥")
		self.assertFalse(ok)
		self.assertIn("emoji", msg.lower())

	def test_desc_iyi_gecer(self):
		ok, msg = check_description("<p>" + _GOOD_DESC + "</p>")
		self.assertTrue(ok, msg)


if __name__ == "__main__":
	unittest.main()
