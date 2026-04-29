"""
Phone canonicalization unit tests.

`tradehub_core/utils/phone.py` Frappe runtime'a bağımlı değildir; doğrudan
``unittest`` ile çalışır:

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_phone_canonicalize
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.utils.phone import (  # noqa: E402
	canonicalize_phone,
	is_valid_tr_phone,
	split_e164,
)


class TestCanonicalizeMobileTR(unittest.TestCase):
	"""Tüm yaygın TR mobil formatları aynı E.164 string'ine çıkmalı."""

	expected = "+905326542137"

	def test_e164_input_passthrough(self):
		self.assertEqual(canonicalize_phone("+905326542137"), self.expected)

	def test_with_country_code_no_plus(self):
		self.assertEqual(canonicalize_phone("905326542137"), self.expected)

	def test_with_trunk_zero(self):
		self.assertEqual(canonicalize_phone("05326542137"), self.expected)

	def test_bare_subscriber(self):
		self.assertEqual(canonicalize_phone("5326542137"), self.expected)

	def test_with_spaces(self):
		self.assertEqual(canonicalize_phone("+90 532 654 21 37"), self.expected)

	def test_with_dashes(self):
		self.assertEqual(canonicalize_phone("0532-654-21-37"), self.expected)

	def test_with_parentheses(self):
		self.assertEqual(canonicalize_phone("(0532) 654 2137"), self.expected)

	def test_mixed_separators(self):
		self.assertEqual(canonicalize_phone("+90-(532) 654.21.37"), self.expected)

	def test_leading_trailing_whitespace(self):
		self.assertEqual(canonicalize_phone("  +90 532 654 21 37  "), self.expected)


class TestCanonicalizeLandlineTR(unittest.TestCase):
	"""Sabit hat (alan kodu 2/3/4) da TR olarak kabul edilmeli."""

	def test_istanbul_212(self):
		self.assertEqual(canonicalize_phone("0212 555 12 34"), "+902125551234")

	def test_ankara_312_with_country_code(self):
		self.assertEqual(canonicalize_phone("+90 312 444 11 22"), "+903124441122")

	def test_izmir_232_bare(self):
		self.assertEqual(canonicalize_phone("2324567890"), "+902324567890")


class TestRejectInvalid(unittest.TestCase):
	"""Geçersiz girişler ``None`` döndürmeli."""

	def test_none(self):
		self.assertIsNone(canonicalize_phone(None))

	def test_empty(self):
		self.assertIsNone(canonicalize_phone(""))

	def test_whitespace_only(self):
		self.assertIsNone(canonicalize_phone("   "))

	def test_letters_only(self):
		self.assertIsNone(canonicalize_phone("abc-def-ghij"))

	def test_too_short(self):
		self.assertIsNone(canonicalize_phone("12345"))

	def test_too_long_for_tr(self):
		# 14 digits and not international
		self.assertIsNone(canonicalize_phone("12345678901234"))

	def test_subscriber_starts_with_invalid_digit(self):
		# starts with 1 — not mobile (5) nor landline (2-4)
		self.assertIsNone(canonicalize_phone("1234567890"))

	def test_subscriber_starts_with_six_or_more(self):
		# starts with 6 — outside TR mobile/landline range
		self.assertIsNone(canonicalize_phone("6234567890"))


class TestInternational(unittest.TestCase):
	"""``+`` ile ve TR-dışı ülke kodu ile gelen E.164 numaraları korunmalı."""

	def test_us_number(self):
		self.assertEqual(canonicalize_phone("+14155551234"), "+14155551234")

	def test_uk_number(self):
		self.assertEqual(canonicalize_phone("+442071234567"), "+442071234567")

	def test_intl_with_spaces(self):
		self.assertEqual(canonicalize_phone("+1 415 555 1234"), "+14155551234")

	def test_intl_too_short(self):
		# 7 digits is borderline; we set min 8
		self.assertIsNone(canonicalize_phone("+1234567"))


class TestIsValidTRPhone(unittest.TestCase):
	"""``is_valid_tr_phone`` yalnızca ``+90...`` çıkışına yeşil ışık yakar."""

	def test_tr_mobile_true(self):
		self.assertTrue(is_valid_tr_phone("0532 654 21 37"))

	def test_tr_landline_true(self):
		self.assertTrue(is_valid_tr_phone("0212 555 12 34"))

	def test_intl_false(self):
		# Geçerli E.164 ama TR değil → is_valid_tr_phone False döner
		self.assertFalse(is_valid_tr_phone("+14155551234"))

	def test_garbage_false(self):
		self.assertFalse(is_valid_tr_phone("abc"))

	def test_empty_false(self):
		self.assertFalse(is_valid_tr_phone(""))


class TestEqualityViaCanonicalization(unittest.TestCase):
	"""Aynı kişinin farklı formatlarda yazılmış numaraları eşit olmalı."""

	def test_all_tr_forms_equal(self):
		forms = [
			"+905326542137",
			"905326542137",
			"05326542137",
			"5326542137",
			"+90 532 654 21 37",
			"0532-654-21-37",
			"(0532) 654 2137",
			"+90 (532) 654.21.37",
		]
		canonicals = {canonicalize_phone(f) for f in forms}
		self.assertEqual(len(canonicals), 1)
		self.assertEqual(canonicals.pop(), "+905326542137")


class TestSplitE164(unittest.TestCase):
	"""``Addresses`` DocType'ının prefix+local ihtiyacını destekleyen split."""

	def test_tr_split(self):
		self.assertEqual(split_e164("+905326542137"), ("+90", "5326542137"))

	def test_us_split(self):
		self.assertEqual(split_e164("+14155551234"), ("+1", "4155551234"))

	def test_uk_split(self):
		self.assertEqual(split_e164("+442071234567"), ("+44", "2071234567"))

	def test_empty(self):
		self.assertEqual(split_e164(""), (None, None))

	def test_none(self):
		self.assertEqual(split_e164(None), (None, None))


class TestNoUnderscoreShadowing(unittest.TestCase):
	"""Statik guard — `_, x = split_e164(...)` pattern'i fonksiyon içindeki
	`from frappe import _` import'unu shadow'lar ve sonraki ``_("...")`` i18n
	çağrılarını ``UnboundLocalError`` ile patlatır. Hata adres ekleme akışını
	tamamen kırdığı için bir daha düşmemek üzere statik olarak doğruluyoruz.
	"""

	def _read(self, relpath):
		path = _APP_ROOT / relpath
		return path.read_text()

	def test_buyer_save_address_no_underscore_shadow(self):
		src = self._read("tradehub_core/api/buyer.py")
		self.assertNotIn("_, ", src.replace("__, ", ""))  # tolerate "__, " (double underscore)
		self.assertNotIn("_phone_local = split_e164", src)

	def test_seller_addresses_save_address_no_underscore_shadow(self):
		src = self._read("tradehub_core/api/seller_addresses.py")
		self.assertNotIn("_, ", src.replace("__, ", ""))
		self.assertNotIn("_phone_local = split_e164", src)


if __name__ == "__main__":
	unittest.main()
