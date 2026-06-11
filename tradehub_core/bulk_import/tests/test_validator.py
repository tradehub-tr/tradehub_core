"""bulk_import.validator unit testleri — standalone (Frappe DB gerektirmez)."""

import unittest

from tradehub_core.bulk_import import validator


class TestValidateSku(unittest.TestCase):
	def test_valid_sku(self):
		ok, msg = validator.validate_sku("ABC-001")
		self.assertTrue(ok)
		self.assertIsNone(msg)

	def test_valid_sku_with_underscore_and_dot(self):
		ok, _msg = validator.validate_sku("ST_2024.001")
		self.assertTrue(ok)

	def test_empty_sku(self):
		ok, msg = validator.validate_sku("")
		self.assertFalse(ok)
		self.assertIn("boş", msg.lower())

	def test_whitespace_only_sku(self):
		ok, _msg = validator.validate_sku("   ")
		self.assertFalse(ok)

	def test_invalid_chars(self):
		ok, _msg = validator.validate_sku("ABC@001")
		self.assertFalse(ok)

	def test_too_long(self):
		ok, _msg = validator.validate_sku("A" * 60)
		self.assertFalse(ok)

	def test_starts_with_alphanumeric(self):
		ok, _msg = validator.validate_sku("-INVALID")
		self.assertFalse(ok)


class TestValidatePrice(unittest.TestCase):
	def test_positive_int(self):
		ok, _msg = validator.validate_price(100)
		self.assertTrue(ok)

	def test_positive_float(self):
		ok, _msg = validator.validate_price(1234.56)
		self.assertTrue(ok)

	def test_negative(self):
		ok, msg = validator.validate_price(-10)
		self.assertFalse(ok)
		self.assertIn("negatif", msg.lower())

	def test_zero(self):
		ok, _msg = validator.validate_price(0)
		self.assertTrue(ok)  # 0 fiyat sınır kontrolü policy — burada kabul

	def test_invalid_string(self):
		ok, _msg = validator.validate_price("abc")
		self.assertFalse(ok)

	def test_empty(self):
		ok, _msg = validator.validate_price("")
		self.assertFalse(ok)

	def test_overflow(self):
		ok, _msg = validator.validate_price(20_000_000)
		self.assertFalse(ok)


class TestValidateStock(unittest.TestCase):
	def test_positive(self):
		ok, _msg = validator.validate_stock(150)
		self.assertTrue(ok)

	def test_zero(self):
		ok, _msg = validator.validate_stock(0)
		self.assertTrue(ok)

	def test_negative(self):
		ok, _msg = validator.validate_stock(-5)
		self.assertFalse(ok)

	def test_empty_allowed(self):
		ok, _msg = validator.validate_stock("")
		self.assertTrue(ok)


class TestValidateTitle(unittest.TestCase):
	def test_valid(self):
		ok, _msg = validator.validate_title("Solvent Grade A 20L")
		self.assertTrue(ok)

	def test_empty(self):
		ok, _msg = validator.validate_title("")
		self.assertFalse(ok)

	def test_too_long(self):
		ok, _msg = validator.validate_title("x" * 251)
		self.assertFalse(ok)


class TestValidateMapping(unittest.TestCase):
	def test_complete_mapping_ok(self):
		mapping = {"sku": "Stok Kodu", "title": "Ürün Adı", "base_price": "Fiyat"}
		self.assertEqual(validator.validate_mapping(mapping), [])

	def test_missing_price_reported(self):
		# Fiyat sütunu eşleşmemiş — ham MandatoryError yerine anlaşılır mesaj
		mapping = {"sku": "Stok Kodu", "title": "Ürün Adı"}
		errors = validator.validate_mapping(mapping)
		self.assertEqual(len(errors), 1)
		self.assertIn("Fiyat", errors[0])

	def test_multiple_missing_listed(self):
		errors = validator.validate_mapping({"title": "Ürün Adı"})
		self.assertEqual(len(errors), 1)
		self.assertIn("Fiyat", errors[0])
		self.assertIn("Stok Kodu", errors[0])


class TestValidateRow(unittest.TestCase):
	def test_valid_row(self):
		row = {"Stok Kodu": "ABC-001", "Ürün Adı": "Solvent", "Fiyat": "100"}
		mapping = {"sku": "Stok Kodu", "title": "Ürün Adı", "base_price": "Fiyat"}
		errors = validator.validate_row(row, mapping)
		self.assertEqual(errors, [])

	def test_invalid_row_multi_error(self):
		row = {"Stok Kodu": "", "Ürün Adı": "", "Fiyat": "-5"}
		mapping = {"sku": "Stok Kodu", "title": "Ürün Adı", "base_price": "Fiyat"}
		errors = validator.validate_row(row, mapping)
		self.assertEqual(len(errors), 3)


if __name__ == "__main__":
	unittest.main()
