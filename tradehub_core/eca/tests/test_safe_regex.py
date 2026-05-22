"""SafeRegex koruma testleri — length + catastrophic + timeout."""

import unittest

from tradehub_core.eca.safe_regex import MAX_PATTERN_LENGTH, RegexError, SafeRegex


class TestSafeRegex(unittest.TestCase):
	def test_normal_pattern_search(self):
		m = SafeRegex.search(r"\bfiyat\b", "birim fiyat tl", SafeRegex.IGNORECASE)
		self.assertIsNotNone(m)

	def test_no_match(self):
		m = SafeRegex.search(r"foo", "bar")
		self.assertIsNone(m)

	def test_length_limit(self):
		long_pattern = "a" * (MAX_PATTERN_LENGTH + 1)
		with self.assertRaises(RegexError):
			SafeRegex.search(long_pattern, "test")

	def test_catastrophic_nested_quantifier(self):
		with self.assertRaises(RegexError):
			SafeRegex.search(r"(a+)+", "aaaaaab")

	def test_catastrophic_alternation_quantifier(self):
		with self.assertRaises(RegexError):
			SafeRegex.search(r"(a|a)+", "aaa")

	def test_findall(self):
		results = SafeRegex.findall(r"\d+", "a1 b22 c333")
		self.assertEqual(results, ["1", "22", "333"])

	def test_sub(self):
		result = SafeRegex.sub(r"\d+", "X", "abc 123 def")
		self.assertEqual(result, "abc X def")

	def test_invalid_pattern_type(self):
		with self.assertRaises(RegexError):
			SafeRegex.search(123, "test")


if __name__ == "__main__":
	unittest.main()
