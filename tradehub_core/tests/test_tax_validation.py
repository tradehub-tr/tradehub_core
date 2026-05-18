"""
TR VKN/TCKN doğrulama unit testleri.

`tradehub_core/utils/tax_validation.py` Frappe runtime'a bağımlı değildir;
doğrudan ``unittest`` ile çalışır:

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_tax_validation
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.utils.tax_validation import (  # noqa: E402
	is_valid_tax_id,
	is_valid_tckn,
	is_valid_vkn,
)


class TestVKN(unittest.TestCase):
	"""VKN (10 hane) Maliye checksum algoritması."""

	def test_algorithmic_valid_sample(self):
		# Algoritmamızın doğru kabul ettiği örnek: 1234567890 (her digit'in checksum'u
		# uygun pattern oluşturuyor — gerçek Maliye VKN'si değil ama checksum valid).
		self.assertTrue(is_valid_vkn("1234567890"))

	def test_invalid_random_10digit(self):
		# Çoğu rastgele 10 hane invalid olmalı
		self.assertFalse(is_valid_vkn("9876543210"))
		self.assertFalse(is_valid_vkn("0290028000"))

	def test_all_same_digits(self):
		# Tüm aynı rakam — non-zero — checksum bypass yok
		self.assertFalse(is_valid_vkn("1111111111"))
		self.assertFalse(is_valid_vkn("9999999999"))

	def test_empty_and_none(self):
		self.assertFalse(is_valid_vkn(""))
		self.assertFalse(is_valid_vkn(None))

	def test_short_length(self):
		# 9 hane geçersiz
		self.assertFalse(is_valid_vkn("123456789"))
		# 5 hane geçersiz
		self.assertFalse(is_valid_vkn("12345"))

	def test_long_length(self):
		# 11 hane VKN değil (TCKN olabilir)
		self.assertFalse(is_valid_vkn("12345678901"))

	def test_non_numeric_stripped(self):
		# Boşluk + tire aynı algoritmik valid VKN — regex ile temizleniyor
		self.assertTrue(is_valid_vkn("123-4567 890"))
		# Tamamen alfa
		self.assertFalse(is_valid_vkn("ABCDEFGHIJ"))


class TestTCKN(unittest.TestCase):
	"""TCKN (11 hane) NVI checksum algoritması."""

	def test_invalid_starts_with_zero(self):
		# TCKN 0 ile başlayamaz
		self.assertFalse(is_valid_tckn("01234567890"))

	def test_all_same_digits(self):
		self.assertFalse(is_valid_tckn("11111111111"))

	def test_wrong_length(self):
		# 10 hane
		self.assertFalse(is_valid_tckn("1234567890"))
		# 12 hane
		self.assertFalse(is_valid_tckn("123456789012"))

	def test_empty(self):
		self.assertFalse(is_valid_tckn(""))
		self.assertFalse(is_valid_tckn(None))


class TestDispatcher(unittest.TestCase):
	"""is_valid_tax_id dispatcher — 10 hane VKN, 11 hane TCKN."""

	def test_dispatcher_routes_vkn(self):
		# Algoritmik valid VKN dispatcher üzerinden valid
		self.assertTrue(is_valid_tax_id("1234567890"))

	def test_dispatcher_routes_tckn(self):
		# 11 hane TCKN yolu — geçersiz örnek (0 ile başlıyor)
		self.assertFalse(is_valid_tax_id("01234567890"))

	def test_other_lengths_false(self):
		self.assertFalse(is_valid_tax_id("12345"))
		self.assertFalse(is_valid_tax_id("123456789"))  # 9
		self.assertFalse(is_valid_tax_id("123456789012"))  # 12

	def test_empty_inputs(self):
		self.assertFalse(is_valid_tax_id(""))
		self.assertFalse(is_valid_tax_id(None))
		self.assertFalse(is_valid_tax_id("   "))


if __name__ == "__main__":
	unittest.main()
