"""Adaptive ingestion normalizer testleri — registry + price + qty + date + bool + currency + sku."""

import unittest
from datetime import datetime

from tradehub_core.bulk_import.ingestion import normalizers
from tradehub_core.bulk_import.ingestion.normalizers import bool_ as bool_mod
from tradehub_core.bulk_import.ingestion.normalizers import currency as currency_mod
from tradehub_core.bulk_import.ingestion.normalizers import date as date_mod
from tradehub_core.bulk_import.ingestion.normalizers import price as price_mod
from tradehub_core.bulk_import.ingestion.normalizers import qty as qty_mod
from tradehub_core.bulk_import.ingestion.normalizers import sku as sku_mod


class TestRegistry(unittest.TestCase):
	def test_registered_names(self):
		names = normalizers.get_registered_names()
		self.assertIn("price", names)
		self.assertIn("qty", names)
		self.assertIn("date", names)
		self.assertIn("bool", names)
		self.assertIn("currency", names)
		self.assertIn("sku", names)

	def test_normalize_dispatch(self):
		self.assertEqual(normalizers.normalize("price", "100"), 100.0)
		self.assertEqual(normalizers.normalize("bool", "evet"), True)

	def test_unknown_normalizer_returns_value_as_is(self):
		self.assertEqual(normalizers.normalize("nope", "abc"), "abc")


class TestPriceNormalizer(unittest.TestCase):
	def test_turkish_decimal_comma(self):
		self.assertEqual(price_mod.parse_price("1.234,56 TL"), 1234.56)

	def test_english_format(self):
		self.assertEqual(price_mod.parse_price("$1,234.56"), 1234.56)

	def test_simple_int(self):
		self.assertEqual(price_mod.parse_price("1234"), 1234.0)

	def test_simple_float(self):
		self.assertEqual(price_mod.parse_price("1234.56"), 1234.56)

	def test_negative(self):
		val = price_mod.parse_price("-100")
		self.assertLess(val, 0)

	def test_invalid(self):
		self.assertIsNone(price_mod.parse_price("abc"))

	def test_none(self):
		self.assertIsNone(price_mod.parse_price(None))

	def test_empty(self):
		self.assertIsNone(price_mod.parse_price(""))

	def test_int_passthrough(self):
		self.assertEqual(price_mod.parse_price(100), 100.0)

	def test_lira_symbol(self):
		self.assertEqual(price_mod.parse_price("₺1.250,50"), 1250.50)


class TestQtyNormalizer(unittest.TestCase):
	def test_simple(self):
		self.assertEqual(qty_mod.parse_qty("100"), 100)

	def test_k_suffix(self):
		self.assertEqual(qty_mod.parse_qty("1k"), 1000)

	def test_adet_suffix(self):
		self.assertEqual(qty_mod.parse_qty("100 adet"), 100)

	def test_invalid(self):
		self.assertIsNone(qty_mod.parse_qty("abc"))

	def test_int_passthrough(self):
		self.assertEqual(qty_mod.parse_qty(50), 50)


class TestDateNormalizer(unittest.TestCase):
	def test_tr_dot_format(self):
		self.assertEqual(date_mod.parse_date("15.03.2025"), datetime(2025, 3, 15))

	def test_iso(self):
		self.assertEqual(date_mod.parse_date("2025-03-15"), datetime(2025, 3, 15))

	def test_slash_format(self):
		self.assertEqual(date_mod.parse_date("15/03/2025"), datetime(2025, 3, 15))

	def test_invalid(self):
		self.assertIsNone(date_mod.parse_date("hayır bu tarih değil"))

	def test_empty(self):
		self.assertIsNone(date_mod.parse_date(""))


class TestBoolNormalizer(unittest.TestCase):
	def test_evet(self):
		self.assertTrue(bool_mod.parse_bool("evet"))

	def test_hayir(self):
		self.assertFalse(bool_mod.parse_bool("hayır"))

	def test_one_zero(self):
		self.assertTrue(bool_mod.parse_bool("1"))
		self.assertFalse(bool_mod.parse_bool("0"))

	def test_yes_no(self):
		self.assertTrue(bool_mod.parse_bool("yes"))
		self.assertFalse(bool_mod.parse_bool("no"))

	def test_unknown(self):
		self.assertIsNone(bool_mod.parse_bool("maybe"))


class TestCurrencyNormalizer(unittest.TestCase):
	def test_tl(self):
		self.assertEqual(currency_mod.parse_currency("TL"), "TRY")

	def test_lira_symbol(self):
		self.assertEqual(currency_mod.parse_currency("₺"), "TRY")

	def test_dollar(self):
		self.assertEqual(currency_mod.parse_currency("$"), "USD")

	def test_eur(self):
		self.assertEqual(currency_mod.parse_currency("€"), "EUR")

	def test_unknown(self):
		self.assertIsNone(currency_mod.parse_currency("BTC"))


class TestSkuNormalizer(unittest.TestCase):
	def test_trim(self):
		self.assertEqual(sku_mod.normalize_sku("  abc-001  "), "abc-001")

	def test_multiple_spaces(self):
		self.assertEqual(sku_mod.normalize_sku("abc  001"), "abc 001")

	def test_empty(self):
		self.assertIsNone(sku_mod.normalize_sku(""))


if __name__ == "__main__":
	unittest.main()
