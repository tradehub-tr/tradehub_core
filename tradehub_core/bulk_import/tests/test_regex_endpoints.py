"""regex_lib whitelist endpoint testleri — test_pattern + get_canonical_fields."""

import unittest

try:
	from frappe.tests.utils import FrappeTestCase

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False

if HAS_FRAPPE:
	from tradehub_core.bulk_import import regex_lib


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestRegexLibEndpoints(FrappeTestCase):
	def test_pattern_match_basic(self):
		res = regex_lib.test_pattern(
			regex=r"\bfi(y|i)at\b",
			sample="Birim Fiyat",
			flags="IGNORECASE,UNICODE",
		)
		self.assertTrue(res["matched"])
		self.assertIsNone(res["error"])
		# Match metni "fiyat" parçası olmalı
		self.assertIn(res["match_text"].lower(), {"fiyat", "fiiat"})

	def test_pattern_no_match(self):
		res = regex_lib.test_pattern(
			regex=r"^\d{4}-\d{2}-\d{2}$",
			sample="abc",
			flags="",
		)
		self.assertFalse(res["matched"])
		self.assertIsNone(res["match_text"])
		self.assertIsNone(res["error"])

	def test_pattern_empty_regex(self):
		res = regex_lib.test_pattern(regex="", sample="x", flags="IGNORECASE")
		self.assertFalse(res["matched"])
		self.assertIn("boş", res["error"].lower())

	def test_pattern_empty_sample(self):
		res = regex_lib.test_pattern(regex=r"\d+", sample="", flags="")
		self.assertFalse(res["matched"])
		self.assertIn("örne", res["error"].lower())

	def test_pattern_catastrophic_blocked(self):
		# SafeRegex catastrophic backtracking pattern'ini reddetmeli
		res = regex_lib.test_pattern(
			regex=r"(a+)+",
			sample="aaaaaa",
			flags="",
		)
		self.assertFalse(res["matched"])
		self.assertIsNotNone(res["error"])

	def test_pattern_invalid_regex(self):
		# Yarım kalan grup — re.error
		res = regex_lib.test_pattern(regex=r"(abc", sample="abc", flags="")
		self.assertFalse(res["matched"])
		self.assertIsNotNone(res["error"])

	def test_get_canonical_fields(self):
		fields = regex_lib.get_canonical_fields()
		self.assertIsInstance(fields, list)
		self.assertGreater(len(fields), 0)
		# Listing alanlarından en az birinin varlığı
		self.assertTrue(any(isinstance(f, str) for f in fields))


if __name__ == "__main__":
	unittest.main()
