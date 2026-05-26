"""
Address API validator unit tests.

Bu test dosyası `_address_validators.py` modülünü doğrular ve `buyer.py` /
`seller_addresses.py` modüllerinin race-safe `_ensure_one_default()` ile
beklenen şekilde donatıldığını statik olarak garantiler.

Frappe runtime'a ihtiyaç duymaz — `unittest` ile doğrudan çalışır. Çalıştırma:

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_address_validators
"""

import json
import re
import sys
import unittest
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Path setup — tradehub_core paketini import edebilmek için PYTHONPATH'a ekle.
# Bench yapısı: apps/tradehub_core/tradehub_core/...
# ──────────────────────────────────────────────────────────────────────────────
_APP_ROOT = Path(__file__).resolve().parents[2]  # apps/tradehub_core/
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.api._address_validators import (  # noqa: E402
	ADDRESS_FIELD_LIMITS,
	ALLOWED_COUNTRY_CODES,
	AddressValidationError,
	parse_address_payload,
	validate_country_code,
	validate_field_lengths,
	validate_postal_code,
)


class TestParseAddressPayload(unittest.TestCase):
	"""parse_address_payload — JSON parse + tip güvenliği."""

	def test_dict_passthrough(self):
		payload = {"title": "Ev", "city": "İstanbul"}
		self.assertEqual(parse_address_payload(payload), payload)

	def test_valid_json_string(self):
		payload = json.dumps({"title": "Ev", "city": "İstanbul"})
		result = parse_address_payload(payload)
		self.assertEqual(result["title"], "Ev")
		self.assertEqual(result["city"], "İstanbul")

	def test_empty_dict_is_valid(self):
		# Boş dict geçerli — required field kontrolü çağıran tarafta yapılır
		self.assertEqual(parse_address_payload({}), {})
		self.assertEqual(parse_address_payload("{}"), {})

	def test_unicode_in_json_string(self):
		payload = '{"city": "Şanlıurfa", "state": "İstanbul"}'
		result = parse_address_payload(payload)
		self.assertEqual(result["city"], "Şanlıurfa")
		self.assertEqual(result["state"], "İstanbul")

	def test_malformed_json_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload("{not valid json}")

	def test_truncated_json_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload('{"title": "Ev"')

	def test_empty_string_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload("")

	def test_json_array_rejected(self):
		# JSON parse başarılı ama dict değil → reddet
		with self.assertRaises(AddressValidationError):
			parse_address_payload("[1, 2, 3]")

	def test_json_string_literal_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload('"just a string"')

	def test_json_number_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload("42")

	def test_json_null_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload("null")

	def test_json_boolean_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload("true")

	def test_none_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload(None)

	def test_int_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload(42)

	def test_list_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload([{"title": "Ev"}])

	def test_bytes_rejected(self):
		with self.assertRaises(AddressValidationError):
			parse_address_payload(b'{"title": "Ev"}')

	def test_error_message_is_user_safe(self):
		"""Hata mesajı kullanıcıya gösterilebilir olmalı — Python detayı sızdırmamalı."""
		try:
			parse_address_payload("{not valid")
		except AddressValidationError as e:
			msg = str(e)
			self.assertNotIn("JSONDecodeError", msg)
			self.assertNotIn("Expecting", msg)
			self.assertNotIn("Traceback", msg)
			self.assertEqual(msg, "Geçersiz istek formatı")


class TestValidateCountryCode(unittest.TestCase):
	"""validate_country_code — whitelist tabanlı ülke kodu doğrulaması."""

	def test_tr_is_allowed(self):
		validate_country_code("TR")  # raise etmemeli

	def test_us_is_allowed(self):
		validate_country_code("US")

	def test_all_30_codes_pass(self):
		for code in ALLOWED_COUNTRY_CODES:
			validate_country_code(code)

	def test_unknown_code_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_country_code("XX")

	def test_lowercase_rejected(self):
		# Dropdown her zaman uppercase yollar; lowercase = manipülasyon
		with self.assertRaises(AddressValidationError):
			validate_country_code("tr")

	def test_empty_string_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_country_code("")

	def test_none_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_country_code(None)

	def test_int_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_country_code(90)

	def test_long_garbage_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_country_code("TURKEY" * 100)

	def test_sql_injection_attempt_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_country_code("TR'; DROP TABLE users;--")

	def test_html_injection_attempt_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_country_code("<script>")


class TestAllowedCountryCodes(unittest.TestCase):
	"""Whitelist'in temel beklentileri karşıladığını doğrular."""

	def test_is_frozenset(self):
		# Mutasyon olmasın diye frozenset olmalı
		self.assertIsInstance(ALLOWED_COUNTRY_CODES, frozenset)

	def test_count_matches_frontend(self):
		# Frontend `mockCheckout.ts` `countries` listesi 30 ülke içerir;
		# bu sayı değişirse iki tarafı birden güncelleyin.
		self.assertEqual(len(ALLOWED_COUNTRY_CODES), 30)

	def test_tr_present(self):
		# Türkiye-odaklı marketplace; TR mutlaka olmalı
		self.assertIn("TR", ALLOWED_COUNTRY_CODES)

	def test_all_codes_are_iso_alpha2(self):
		# ISO 3166-1 alpha-2: tam 2 büyük harf
		for code in ALLOWED_COUNTRY_CODES:
			self.assertRegex(code, r"^[A-Z]{2}$", f"{code} ISO alpha-2 değil")


class TestValidatePostalCode(unittest.TestCase):
	"""validate_postal_code — TR sıkı, diğer ülkeler gevşek, boş izinli."""

	# ── TR ─────────────────────────────────────────────────────────────────
	def test_tr_valid_5_digits(self):
		validate_postal_code("34394", "TR")
		validate_postal_code("06800", "TR")
		validate_postal_code("01000", "TR")

	def test_tr_4_digits_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code("3439", "TR")

	def test_tr_6_digits_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code("343940", "TR")

	def test_tr_letters_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code("3439A", "TR")

	def test_tr_with_space_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code("34 394", "TR")

	def test_tr_error_mentions_5_digits(self):
		try:
			validate_postal_code("123", "TR")
		except AddressValidationError as e:
			self.assertIn("5", str(e))

	# ── Boş / None — her ülkede izinli (alan zorunlu değil) ────────────────
	def test_empty_string_allowed_tr(self):
		validate_postal_code("", "TR")

	def test_empty_string_allowed_us(self):
		validate_postal_code("", "US")

	def test_none_allowed(self):
		validate_postal_code(None, "TR")

	def test_whitespace_only_allowed(self):
		validate_postal_code("   ", "TR")

	# ── Diğer ülkeler — gevşek format ──────────────────────────────────────
	def test_us_valid(self):
		validate_postal_code("90210", "US")
		validate_postal_code("12345-6789", "US")

	def test_uk_valid(self):
		validate_postal_code("SW1A 1AA", "GB")

	def test_canada_valid(self):
		validate_postal_code("K1A 0B1", "CA")

	def test_international_too_long_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code("ABCDEFGHIJKLM12345", "DE")

	def test_international_too_short_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code("X", "DE")

	def test_international_special_chars_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code("12@34", "DE")

	# ── Tip güvenliği ──────────────────────────────────────────────────────
	def test_int_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code(34394, "TR")

	def test_list_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_postal_code(["34394"], "TR")


class TestValidateFieldLengths(unittest.TestCase):
	"""validate_field_lengths — Frappe field length sınırlarını backend'de yakalar."""

	def _good_payload(self):
		"""Tüm alanları sınır içinde olan baseline payload."""
		return {
			"title": "Ev",
			"contact_name": "Ali Veli",
			"company": "Acme Ltd.",
			"phone_prefix": "+90",
			"phone": "5551234567",
			"country": "TR",
			"state": "İstanbul",
			"city": "Şişli",
			"street": "Gülbahar Mh. No:12",
			"apartment": "Daire 7",
			"postal_code": "34394",
			"note": "Kapı zili çalışmıyor",
		}

	def test_baseline_passes(self):
		validate_field_lengths(self._good_payload())

	def test_empty_dict_passes(self):
		validate_field_lengths({})

	def test_extra_fields_ignored(self):
		# Bilinmeyen alan validator'ı bozmaz — sessizce atlar
		payload = self._good_payload()
		payload["unknown_field"] = "x" * 99999
		validate_field_lengths(payload)

	def test_non_dict_rejected(self):
		with self.assertRaises(AddressValidationError):
			validate_field_lengths("not a dict")
		with self.assertRaises(AddressValidationError):
			validate_field_lengths(None)
		with self.assertRaises(AddressValidationError):
			validate_field_lengths([1, 2, 3])

	def test_title_140_boundary(self):
		payload = self._good_payload()
		payload["title"] = "A" * 140  # tam sınır → izinli
		validate_field_lengths(payload)
		payload["title"] = "A" * 141  # 1 fazla → reddet
		with self.assertRaises(AddressValidationError) as ctx:
			validate_field_lengths(payload)
		self.assertIn("Adres Başlığı", str(ctx.exception))
		self.assertIn("140", str(ctx.exception))

	def test_company_overflow_rejected(self):
		payload = self._good_payload()
		payload["company"] = "X" * 5000
		with self.assertRaises(AddressValidationError) as ctx:
			validate_field_lengths(payload)
		self.assertIn("Şirket Adı", str(ctx.exception))

	def test_street_1000_boundary(self):
		payload = self._good_payload()
		payload["street"] = "S" * 1000  # tam sınır → izinli
		validate_field_lengths(payload)
		payload["street"] = "S" * 1001  # 1 fazla → reddet
		with self.assertRaises(AddressValidationError) as ctx:
			validate_field_lengths(payload)
		self.assertIn("Adres Satırı", str(ctx.exception))

	def test_note_1000_boundary(self):
		payload = self._good_payload()
		payload["note"] = "N" * 1001
		with self.assertRaises(AddressValidationError):
			validate_field_lengths(payload)

	def test_giant_payload_attack(self):
		"""10MB payload — backend'de yakalanmalı, DB'ye kadar gitmemeli."""
		payload = self._good_payload()
		payload["street"] = "X" * (10 * 1024 * 1024)
		with self.assertRaises(AddressValidationError):
			validate_field_lengths(payload)

	def test_unicode_characters_count_correctly(self):
		# Türkçe diakritikler 1 karakter sayılmalı (Python str len semantiği)
		payload = self._good_payload()
		payload["title"] = "Şğüöçİı" * 20  # 140 karakter, tam sınır
		self.assertEqual(len(payload["title"]), 140)
		validate_field_lengths(payload)
		payload["title"] = "Şğüöçİı" * 21  # 147, sınır üstü
		with self.assertRaises(AddressValidationError):
			validate_field_lengths(payload)

	def test_strip_applied_before_length_check(self):
		# Baş/son boşluklar sayılmamalı — final stored değer önemli
		payload = self._good_payload()
		payload["title"] = "   " + ("A" * 140) + "   "
		validate_field_lengths(payload)  # 140 + boşluk → strip sonrası 140 → OK

	def test_int_value_ignored(self):
		# bool/int gibi tipler validator'ı bozmaz; Frappe doc.save yakalar
		payload = self._good_payload()
		payload["title"] = 12345  # int — sessizce atlanır
		validate_field_lengths(payload)

	def test_none_value_ignored(self):
		payload = self._good_payload()
		payload["note"] = None
		validate_field_lengths(payload)


class TestAddressFieldLimits(unittest.TestCase):
	"""ADDRESS_FIELD_LIMITS sabitinin doctype JSON ile tutarlı olduğunu doğrular."""

	def test_all_limits_have_label_and_max(self):
		for _field, value in ADDRESS_FIELD_LIMITS.items():
			self.assertIsInstance(value, tuple)
			self.assertEqual(len(value), 2)
			label, max_len = value
			self.assertIsInstance(label, str)
			self.assertGreater(len(label), 0)
			self.assertIsInstance(max_len, int)
			self.assertGreater(max_len, 0)

	def test_doctype_data_fields_at_140(self):
		"""Frappe Data fieldtype default 140 char — sabitlerimiz uyumlu olmalı."""
		data_fields = {
			"title",
			"contact_name",
			"company",
			"state",
			"city",
			"apartment",
		}
		for field in data_fields:
			label, max_len = ADDRESS_FIELD_LIMITS[field]
			self.assertEqual(
				max_len,
				140,
				f"{field} Data fieldtype, 140 olmalı (gerçek: {max_len})",
			)

	def test_doctype_small_text_fields_at_1000(self):
		"""Small Text alanlar — application limit 1000."""
		for field in ("street", "note"):
			label, max_len = ADDRESS_FIELD_LIMITS[field]
			self.assertEqual(max_len, 1000, f"{field} Small Text, 1000 olmalı")

	def test_country_limit_is_2(self):
		# ISO alpha-2 → kesin 2 karakter
		_, max_len = ADDRESS_FIELD_LIMITS["country"]
		self.assertEqual(max_len, 2)

	def test_no_unknown_field_in_limits(self):
		"""Limits map'inde olmayan alan eklenmediğinden emin ol — drift kontrolü."""
		expected_fields = {
			"title",
			"contact_name",
			"company",
			"phone_prefix",
			"phone",
			"country",
			"state",
			"city",
			"street",
			"apartment",
			"postal_code",
			"note",
		}
		self.assertEqual(set(ADDRESS_FIELD_LIMITS.keys()), expected_fields)


class TestLockHelper(unittest.TestCase):
	"""
	_lock_user_addresses / _lock_seller_addresses — tüm mutation endpoint'lerinin
	paylaştığı ortak row lock helper'ı. Bu helper'ın varlığı ve doğruluğu
	aşağıdaki iki bug'ın fix'i için kritiktir:

	1) MAX_ADDRESSES count+insert race (count'tan önce lock → atomik)
	2) save_address vs save/delete/set_default deadlock (aynı lock order)

	Helper statically tested; runtime'da Frappe DB gerektiren kısım
	entegrasyon testi değil — yalnız kaynak kod statik kontrol.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} bulunamadı: {module_path}")
		return m.group(0)

	# ── buyer: _lock_user_addresses ───────────────────────────────────────
	def test_buyer_lock_helper_exists(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_lock_user_addresses")
		self.assertTrue(len(src) > 0)

	def test_buyer_lock_helper_uses_for_update(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_lock_user_addresses")
		self.assertIn("FOR UPDATE", src, "_lock_user_addresses row-level lock almalı")
		self.assertIn("frappe.db.sql", src, "_lock_user_addresses raw SQL kullanmalı")

	def test_buyer_lock_helper_scoped_to_user_and_kind(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_lock_user_addresses")
		# Lock sadece bu kullanıcının Buyer satırlarına olmalı —
		# tüm tabloyu kilitlemek production'da catastrophic olur
		self.assertIn("user = %(user)s", src)
		self.assertIn("kind = 'Buyer'", src)

	def test_buyer_lock_helper_selects_modified_column(self):
		"""Self-heal tie-break için modified kolonu çekilmeli."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_lock_user_addresses")
		self.assertRegex(src, r"SELECT\s+name,\s*is_default,\s*modified")

	def test_buyer_lock_helper_returns_rows(self):
		"""Helper return etmeli — _ensure_one_default ve set_default_address kullanır."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_lock_user_addresses")
		self.assertIn("return frappe.db.sql", src)
		self.assertIn("as_dict=True", src)

	def test_buyer_lock_helper_stable_order(self):
		"""ORDER BY creation ASC — fallback "en eski default yap" deterministic olsun."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_lock_user_addresses")
		self.assertIn("ORDER BY creation ASC", src)

	# ── seller: _lock_seller_addresses ────────────────────────────────────
	def test_seller_lock_helper_exists(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_lock_seller_addresses")
		self.assertTrue(len(src) > 0)

	def test_seller_lock_helper_uses_for_update(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_lock_seller_addresses")
		self.assertIn("FOR UPDATE", src)
		self.assertIn("frappe.db.sql", src)

	def test_seller_lock_helper_scoped_to_seller_and_kind(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_lock_seller_addresses")
		self.assertIn("seller = %(seller)s", src)
		self.assertIn("kind = 'Seller'", src)

	def test_seller_lock_helper_selects_modified_column(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_lock_seller_addresses")
		self.assertRegex(src, r"SELECT\s+name,\s*is_default,\s*modified")

	def test_seller_lock_helper_returns_rows(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_lock_seller_addresses")
		self.assertIn("return frappe.db.sql", src)
		self.assertIn("as_dict=True", src)

	def test_seller_lock_helper_stable_order(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_lock_seller_addresses")
		self.assertIn("ORDER BY creation ASC", src)


class TestEnsureOneDefaultIsRaceSafe(unittest.TestCase):
	"""
	`_ensure_one_default()` artık `_lock_user_addresses` / `_lock_seller_addresses`
	helper'ını çağırarak lock alıyor. Lock semantiği TestLockHelper'da kontrol
	ediliyor; bu sınıf delegation + self-heal semantiğini doğrular.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} bulunamadı: {module_path}")
		return m.group(0)

	def test_buyer_ensure_one_default_uses_lock_helper(self):
		"""Lock ortak helper'a delege edilmeli — drift önlemi."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertIn(
			"_lock_user_addresses(user)",
			src,
			"_ensure_one_default lock helper'ını çağırmalı",
		)

	def test_seller_ensure_one_default_uses_lock_helper(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertIn("_lock_seller_addresses(seller_name)", src)

	def test_buyer_ensure_one_default_no_inline_sql(self):
		"""Lock helper'a taşındıktan sonra _ensure_one_default inline SQL tutmamalı."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertNotIn(
			"FOR UPDATE",
			src,
			"_ensure_one_default FOR UPDATE'i helper'a taşımadan kaldırmamış (drift)",
		)

	def test_seller_ensure_one_default_no_inline_sql(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertNotIn("FOR UPDATE", src)

	def test_buyer_ensure_one_default_returns_string(self):
		"""save_address atomik default_id okuyabilmek için return etmeli."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertIn('return ""', src)
		self.assertRegex(src, r"return\s+\w+\.name|return\s+keep\.name")

	def test_seller_ensure_one_default_returns_string(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertIn('return ""', src)
		self.assertRegex(src, r"return\s+\w+\.name|return\s+keep\.name")

	def test_buyer_ensure_one_default_self_heals_multiple(self):
		"""Multi-default broken state'i temizleme mantığı kaynakta olmalı."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertIn("defaults", src)
		self.assertIn('"is_default", 0', src)

	def test_seller_ensure_one_default_self_heals_multiple(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertIn("defaults", src)
		self.assertIn('"is_default", 0', src)

	def test_buyer_self_heal_picks_newest_modified(self):
		"""
		Self-heal semantik garantisi: çoklu default'ta 'en son modified olanı
		koru'. Semantik yanlışlıkla geri alınırsa CI yakalar.
		"""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertRegex(
			src,
			r"max\(defaults,\s*key=lambda\s+r:\s*\(r\.modified",
			"buyer._ensure_one_default 'max(defaults, key=r.modified)' pattern'ini kullanmalı",
		)

	def test_seller_self_heal_picks_newest_modified(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "_ensure_one_default")
		self.assertRegex(
			src,
			r"max\(defaults,\s*key=lambda\s+r:\s*\(r\.modified",
			"seller._ensure_one_default 'max(defaults, key=r.modified)' pattern'ini kullanmalı",
		)


class TestEnsureOneDefaultRuntimeSemantic(unittest.TestCase):
	"""
	_ensure_one_default'un saf Python mantığını simüle ederek davranışsal
	garantileri runtime'da doğrular. Bu test Frappe bağımlılığı olmadan
	çalışır — "multi-default ise en son modified kazanır" semantiği kaynak
	kodda grep edilmekten öte gerçek veriyle sınanır.

	Simülasyon: _ensure_one_default'un kritik karar mantığı pure fonksiyon
	olarak yeniden ifade edilmiştir. Kaynak koddaki algoritma değişirse bu
	testler güncellenmeli (drift'i yakalamak için statik testler de var).
	"""

	def _pick_keep(self, rows):
		"""
		Kaynak kodun karar mantığını birebir aynalar:
		- no rows → ""
		- single default → default'un name'i
		- multiple defaults → max(modified, name)
		- zero defaults → oldest by creation
		"""
		if not rows:
			return ""
		defaults = [r for r in rows if r["is_default"]]
		if len(defaults) == 1:
			return defaults[0]["name"]
		if len(defaults) > 1:
			keep = max(defaults, key=lambda r: (r["modified"], r["name"]))
			return keep["name"]
		# sorted by creation asc in source → caller passes in that order
		return rows[0]["name"]

	def test_empty_list_returns_empty_string(self):
		self.assertEqual(self._pick_keep([]), "")

	def test_single_default_returns_its_name(self):
		rows = [
			{"name": "A1", "is_default": 1, "modified": "2026-01-01", "creation": "2026-01-01"},
			{"name": "A2", "is_default": 0, "modified": "2026-01-02", "creation": "2026-01-02"},
		]
		self.assertEqual(self._pick_keep(rows), "A1")

	def test_multi_default_picks_newest_modified(self):
		"""Kullanıcı son kaydedilen adresi default yaptıysa o kazanmalı."""
		rows = [
			# creation asc: eski → yeni
			{"name": "A1", "is_default": 1, "modified": "2026-01-01 10:00:00", "creation": "2026-01-01"},
			{"name": "A2", "is_default": 1, "modified": "2026-04-10 15:30:00", "creation": "2026-04-10"},
		]
		# Eski davranış "en eski"yi korurdu (A1); yeni davranış A2 döndürmeli
		self.assertEqual(self._pick_keep(rows), "A2")

	def test_multi_default_older_modified_loses(self):
		"""Creation sırası önemli değil — modified önemli."""
		rows = [
			{
				"name": "NEW_CREATED_FIRST",
				"is_default": 1,
				"modified": "2020-01-01",
				"creation": "2020-01-01",
			},
			{
				"name": "OLD_CREATED_LATER_EDITED_TODAY",
				"is_default": 1,
				"modified": "2026-04-10",
				"creation": "2026-02-01",
			},
		]
		self.assertEqual(self._pick_keep(rows), "OLD_CREATED_LATER_EDITED_TODAY")

	def test_multi_default_tie_break_by_name(self):
		"""Modified tamamen aynıysa name deterministic tie-breaker olmalı."""
		rows = [
			{"name": "A1", "is_default": 1, "modified": "2026-04-10", "creation": "2026-01-01"},
			{"name": "A2", "is_default": 1, "modified": "2026-04-10", "creation": "2026-01-02"},
		]
		# Aynı modified → max(name) = "A2"
		self.assertEqual(self._pick_keep(rows), "A2")

	def test_three_defaults_newest_wins(self):
		rows = [
			{"name": "A1", "is_default": 1, "modified": "2025-01-01", "creation": "2025-01-01"},
			{"name": "A2", "is_default": 0, "modified": "2025-06-01", "creation": "2025-06-01"},
			{"name": "A3", "is_default": 1, "modified": "2026-03-01", "creation": "2026-01-15"},
			{"name": "A4", "is_default": 1, "modified": "2026-04-10", "creation": "2026-02-01"},
		]
		self.assertEqual(self._pick_keep(rows), "A4")

	def test_no_defaults_falls_back_to_oldest(self):
		"""
		Hiç default yoksa kaynaktaki SELECT sırası (creation ASC) gereği
		locked[0] en eski olur — test de öyle geçirir.
		"""
		rows = [
			{"name": "OLDEST", "is_default": 0, "modified": "2026-04-10", "creation": "2020-01-01"},
			{"name": "MIDDLE", "is_default": 0, "modified": "2026-04-09", "creation": "2021-01-01"},
			{"name": "NEWEST", "is_default": 0, "modified": "2026-04-08", "creation": "2026-04-01"},
		]
		self.assertEqual(self._pick_keep(rows), "OLDEST")


class TestSetDefaultAddressIsRaceSafe(unittest.TestCase):
	"""
	set_default_address artık `_lock_user_addresses` / `_lock_seller_addresses`
	helper'ına delege ederek lock alıyor olmalı. Lock'un FOR UPDATE / scope
	kontrolleri TestLockHelper'da yapılır; burada delegation + per-row flip
	semantiği test edilir.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} bulunamadı: {module_path}")
		return m.group(0)

	def test_buyer_set_default_uses_lock_helper(self):
		"""Lock ortak helper'a delege edilmeli — drift önlemi."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertIn(
			"_lock_user_addresses(user)",
			src,
			"set_default_address lock helper'ını çağırmalı",
		)

	def test_seller_set_default_uses_lock_helper(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertIn("_lock_seller_addresses(seller_name)", src)

	def test_buyer_set_default_no_inline_sql(self):
		"""Lock helper'a taşındıktan sonra set_default_address inline SQL tutmamalı.
		Docstring'deki referansları yakalamamak için `frappe.db.sql` çağrısının
		varlığını kontrol ediyoruz."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertNotIn(
			"frappe.db.sql",
			src,
			"set_default_address inline raw SQL içeriyor (helper'a taşınmalı)",
		)

	def test_seller_set_default_no_inline_sql(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertNotIn("frappe.db.sql", src)

	def test_buyer_set_default_no_bulk_dict_filter(self):
		"""
		Eski race-prone pattern: `set_value("Addresses", {"user": ..., "kind": ...}, "is_default", 0)`
		Frappe'nin dict filter davranışı tek satır garanti etmediğinden kaldırılmalı.
		"""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertNotIn(
			'{"user": user, "kind": "Buyer"}, "is_default", 0',
			src,
			"set_default_address hâlâ bulk dict filter kullanıyor (race-prone)",
		)

	def test_seller_set_default_no_bulk_dict_filter(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertNotIn(
			'{"seller": seller_name, "kind": "Seller"}, "is_default", 0',
			src,
			"set_default_address hâlâ bulk dict filter kullanıyor (race-prone)",
		)

	def test_buyer_set_default_per_row_flip(self):
		"""Per-row atomik flip pattern'i — lock altında dolaşıp gerekli satırları
		set_value ile günceller."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertIn("for row in locked", src)
		self.assertIn('frappe.db.set_value("Addresses"', src)

	def test_seller_set_default_per_row_flip(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertIn("for row in locked", src)
		self.assertIn('frappe.db.set_value("Addresses"', src)

	def test_buyer_set_default_returns_default_id(self):
		"""Frontend tutarlılığı için response'ta default_id olmalı."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertIn('"default_id"', src)

	def test_seller_set_default_returns_default_id(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertIn('"default_id"', src)

	def test_buyer_set_default_handles_race_deleted(self):
		"""Lock altında target bulunamazsa DoesNotExistError fırlatmalı (arada silinme)."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertIn("target_found", src)
		self.assertIn("DoesNotExistError", src)

	def test_seller_set_default_handles_race_deleted(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertIn("target_found", src)
		self.assertIn("DoesNotExistError", src)


class TestDeleteAddressUnconditionalHeal(unittest.TestCase):
	"""
	delete_address her iki tarafta da `_ensure_one_default`'ı koşulsuz
	çağırmalı — self-heal fırsatını kaçırmamak için (audit #7 drift fix).
	Buyer tarafındaki eski `was_default` conditional branch kaldırılmış olmalı.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} bulunamadı: {module_path}")
		return m.group(0)

	def test_buyer_delete_unconditionally_heals(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "delete_address")
		self.assertIn("_ensure_one_default(user)", src)
		self.assertNotIn(
			"was_default",
			src,
			"buyer.delete_address hâlâ was_default koşullu dallanması içeriyor",
		)
		self.assertNotIn(
			"if was_default",
			src,
			"buyer.delete_address self-heal koşulu temizlenmemiş",
		)

	def test_seller_delete_unconditionally_heals(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "delete_address")
		self.assertIn("_ensure_one_default(seller_name)", src)
		self.assertNotIn("was_default", src)


class TestSaveAddressNoPreSaveCleanup(unittest.TestCase):
	"""
	save_address artık pre-save ile `set_value(..., "is_default", 0)` yapmamalı.
	_ensure_one_default lock altında "son modified kazanır" semantiğiyle
	çoklu-default invariant'ını garanti ediyor. Pre-save cleanup bloğu
	hem gereksiz hem de dict filter çoklu-row davranışı Frappe versiyonları
	arasında garanti olmadığı için kırılgan.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m)
		return m.group(0)

	def test_buyer_save_no_presave_exclude_self_cleanup(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		# Eski pre-save cleanup bloğu işareti: "name != doc.name" filter
		self.assertNotIn(
			'"name": ("!=", doc.name)',
			src,
			"buyer.save_address hâlâ pre-save exclude-self cleanup içeriyor",
		)

	def test_seller_save_no_presave_exclude_self_cleanup(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertNotIn(
			'"name": ("!=", doc.name)',
			src,
			"seller.save_address hâlâ pre-save exclude-self cleanup içeriyor",
		)

	def test_buyer_save_no_presave_bulk_cleanup(self):
		"""Yeni doc path'indeki bulk cleanup da kaldırılmış olmalı."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		# Pre-save cleanup bloğundaki if/elif branch'i tamamen silinmiş olmalı
		self.assertNotIn("elif doc.is_default and not doc.name", src)
		self.assertNotIn("if doc.is_default and doc.name", src)

	def test_seller_save_no_presave_bulk_cleanup(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertNotIn("elif doc.is_default and not doc.name", src)
		self.assertNotIn("if doc.is_default and doc.name", src)

	def test_buyer_save_still_calls_ensure_one_default(self):
		"""Cleanup kaldırıldı ama invariant hâlâ _ensure_one_default ile garanti."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("_ensure_one_default(user)", src)

	def test_seller_save_still_calls_ensure_one_default(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("_ensure_one_default(seller_name)", src)


class TestSaveAddressAtomicDefaultRead(unittest.TestCase):
	"""
	save_address artık `_ensure_one_default()` return değerini kullanıyor —
	ayrı bir SELECT yapmıyor. Race-free atomic read pattern'ini static
	olarak doğrularız (audit #6).
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		# whitelist decorator'lı fonksiyonlar için: önce 'def func' bul
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} bulunamadı: {module_path}")
		return m.group(0)

	def test_buyer_save_address_uses_return_value(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		# Atomic okuma — _ensure_one_default'un return'ünü değişkene atayıp
		# ayrı SELECT yapmıyor olmalı
		self.assertIn("current_default_id = _ensure_one_default(user)", src)
		# Eski pattern artık olmamalı: ayrı bir get_value ile is_default=1 sorgusu
		self.assertNotIn(
			'{"user": user, "kind": "Buyer", "is_default": 1}',
			src,
			"save_address hâlâ ayrı default_id SELECT'i kullanıyor (race-prone)",
		)

	def test_seller_save_address_uses_return_value(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("current_default_id = _ensure_one_default(seller_name)", src)
		self.assertNotIn(
			'{"seller": seller_name, "kind": "Seller", "is_default": 1}',
			src,
			"save_address hâlâ ayrı default_id SELECT'i kullanıyor (race-prone)",
		)

	def test_buyer_save_address_calls_field_length_validator(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("validate_field_lengths(data)", src)

	def test_seller_save_address_calls_field_length_validator(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("validate_field_lengths(data)", src)

	def test_buyer_save_address_calls_postal_code_validator(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("validate_postal_code(postal_code_in, country_in)", src)

	def test_seller_save_address_calls_postal_code_validator(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("validate_postal_code(postal_code_in, country_in)", src)


class TestSaveAddressLocksBeforeCount(unittest.TestCase):
	"""
	save_address MAX_ADDRESSES kontrolünden ÖNCE `_lock_user_addresses` /
	`_lock_seller_addresses` çağırmalı. Aksi halde count+insert race tetiklenir:
	iki eşzamanlı request aynı sayıyı görüp limiti bypass eder.

	Refactor sonrası `frappe.db.count` çağrısı yerine `len(locked)` kullanılıyor;
	test pozisyonu MAX_ADDRESSES sabit referansına göre kontrol ediyor (lock
	çağrısı MAX_ADDRESSES kontrolünden önce gelmeli).
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} bulunamadı: {module_path}")
		return m.group(0)

	def test_buyer_save_locks_before_max_check(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		lock_pos = src.find("_lock_user_addresses(user)")
		max_pos = src.find(">= MAX_ADDRESSES")
		self.assertNotEqual(lock_pos, -1, "save_address lock helper'ını çağırmıyor")
		self.assertNotEqual(max_pos, -1, "save_address MAX_ADDRESSES kontrolü yok")
		self.assertLess(
			lock_pos,
			max_pos,
			"save_address lock'tan ÖNCE MAX_ADDRESSES kontrol ediyor — race açık",
		)

	def test_seller_save_locks_before_max_check(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		lock_pos = src.find("_lock_seller_addresses(seller_name)")
		max_pos = src.find(">= MAX_ADDRESSES")
		self.assertNotEqual(lock_pos, -1)
		self.assertNotEqual(max_pos, -1)
		self.assertLess(
			lock_pos,
			max_pos,
			"seller.save_address lock'tan ÖNCE MAX_ADDRESSES kontrol ediyor",
		)

	def test_buyer_save_uses_len_locked_not_count(self):
		"""Refactor: ekstra `frappe.db.count` query'sini kaldırıp `len(locked)`
		kullanıyoruz — locked zaten lock altında alındığı için race-free."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		self.assertNotIn(
			"frappe.db.count",
			src,
			"save_address hâlâ ayrı frappe.db.count yapıyor (gereksiz ve race-prone)",
		)
		self.assertIn("len(locked)", src)

	def test_seller_save_uses_len_locked_not_count(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertNotIn("frappe.db.count", src)
		self.assertIn("len(locked)", src)


class TestDeleteAddressReturnsDefaultId(unittest.TestCase):
	"""
	delete_address response'ta silme sonrası aktif olan default_id'yi döndürmeli.
	Frontend tutarlılığı için save_address ve set_default_address ile aynı API
	şeklini kullanır — frontend ayrı get_addresses fetch'i atmak zorunda kalmaz.

	Ayrıca delete'ten önce lock helper çağrılmalı (concurrent save/delete
	deadlock'u önlemek için aynı lock order'ı paylaşılır).
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} bulunamadı: {module_path}")
		return m.group(0)

	def test_buyer_delete_returns_default_id(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "delete_address")
		self.assertIn('"default_id"', src)
		self.assertIn("new_default_id", src)

	def test_seller_delete_returns_default_id(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "delete_address")
		self.assertIn('"default_id"', src)
		self.assertIn("new_default_id", src)

	def test_buyer_delete_locks_before_delete(self):
		"""Lock delete'ten önce alınmalı — concurrent save_address/delete deadlock fix.
		Daha spesifik substring (`frappe.delete_doc("Addresses"`) kullanılıyor —
		docstring'lerdeki referanslar yanılgıya yol açmasın."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "delete_address")
		lock_pos = src.find("_lock_user_addresses(user)")
		delete_pos = src.find('frappe.delete_doc("Addresses"')
		self.assertNotEqual(lock_pos, -1, "delete_address lock helper'ını çağırmıyor")
		self.assertNotEqual(delete_pos, -1)
		self.assertLess(
			lock_pos,
			delete_pos,
			"delete_address delete'ten önce lock almıyor — concurrent deadlock riski",
		)

	def test_seller_delete_locks_before_delete(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "delete_address")
		lock_pos = src.find("_lock_seller_addresses(seller_name)")
		delete_pos = src.find('frappe.delete_doc("Addresses"')
		self.assertNotEqual(lock_pos, -1)
		self.assertNotEqual(delete_pos, -1)
		self.assertLess(lock_pos, delete_pos)


class TestDeleteAddressLockBeforeOwnerCheck(unittest.TestCase):
	"""
	Audit fix #1 (TOCTOU race): delete_address lock'u owner check'ten önce
	almalı. Aksi halde:
	  TX1 owner check passed → TX2 lock + delete + commit → TX1 lock alır
	  ama row gitmiş → frappe.delete_doc DoesNotExistError fırlatır → 500.

	Refactor sonrası `_check_address_owner` çağrısı tamamen kaldırıldı;
	owner check locked rows üzerinde `any(row.name == address_id ...)` ile
	yapılıyor. Bu test her iki garantiyi statically doğrular.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} bulunamadı: {module_path}")
		return m.group(0)

	# ── delete_address ────────────────────────────────────────────────────
	def test_buyer_delete_no_owner_check_helper(self):
		"""Owner check artık locked rows üzerinde yapılıyor; ayrı helper çağrısı yok."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "delete_address")
		self.assertNotIn(
			"_check_address_owner(address_id, user)",
			src,
			"delete_address hâlâ lock-suz _check_address_owner çağırıyor (TOCTOU)",
		)

	def test_seller_delete_no_owner_check_helper(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "delete_address")
		self.assertNotIn(
			"_check_address_owner(address_id, seller_name)",
			src,
			"seller.delete_address hâlâ lock-suz _check_address_owner çağırıyor (TOCTOU)",
		)

	def test_buyer_delete_existence_check_under_lock(self):
		"""locked üzerinde any(row.name == address_id) ile existence kontrol edilmeli."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "delete_address")
		self.assertRegex(
			src,
			r"any\(row\.name\s*==\s*address_id\s+for\s+row\s+in\s+locked\)",
			"delete_address locked rows üzerinde existence check yapmıyor",
		)
		self.assertIn("DoesNotExistError", src)

	def test_seller_delete_existence_check_under_lock(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "delete_address")
		self.assertRegex(
			src,
			r"any\(row\.name\s*==\s*address_id\s+for\s+row\s+in\s+locked\)",
		)
		self.assertIn("DoesNotExistError", src)

	def test_buyer_delete_lock_first_then_check(self):
		"""Pozisyon: lock helper çağrısı existence check'ten önce gelmeli."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "delete_address")
		lock_pos = src.find("locked = _lock_user_addresses(user)")
		check_pos = src.find("any(row.name == address_id")
		self.assertNotEqual(lock_pos, -1)
		self.assertNotEqual(check_pos, -1)
		self.assertLess(lock_pos, check_pos)

	def test_seller_delete_lock_first_then_check(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "delete_address")
		lock_pos = src.find("locked = _lock_seller_addresses(seller_name)")
		check_pos = src.find("any(row.name == address_id")
		self.assertNotEqual(lock_pos, -1)
		self.assertNotEqual(check_pos, -1)
		self.assertLess(lock_pos, check_pos)


class TestSetDefaultLockBeforeOwnerCheck(unittest.TestCase):
	"""
	Audit fix #2: set_default_address da delete_address ile aynı pattern'i
	kullanmalı — owner check locked rows üzerinde, ayrı _check_address_owner
	çağrısı yok. target_found döngüsü zaten existence check görevi görüyor.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m)
		return m.group(0)

	def test_buyer_set_default_no_owner_check_helper(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertNotIn(
			"_check_address_owner(address_id, user)",
			src,
			"set_default_address hâlâ lock-suz _check_address_owner çağırıyor",
		)

	def test_seller_set_default_no_owner_check_helper(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "set_default_address")
		self.assertNotIn(
			"_check_address_owner(address_id, seller_name)",
			src,
		)

	def test_buyer_set_default_lock_first(self):
		"""Lock işlevin başında — _require_login'den hemen sonra gelmeli."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "set_default_address")
		login_pos = src.find("_require_login()")
		lock_pos = src.find("_lock_user_addresses(user)")
		target_pos = src.find("target_found = False")
		self.assertLess(login_pos, lock_pos)
		self.assertLess(lock_pos, target_pos)

	def test_seller_set_default_lock_first(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "set_default_address")
		resolve_pos = src.find("_resolve_seller_profile(user)")
		lock_pos = src.find("_lock_seller_addresses(seller_name)")
		target_pos = src.find("target_found = False")
		self.assertLess(resolve_pos, lock_pos)
		self.assertLess(lock_pos, target_pos)


class TestSaveAddressNoReloadRace(unittest.TestCase):
	"""
	Audit fix #3: save_address artık `doc.reload()` çağırmıyor. Reload commit
	sonrası lock-suz çalıştığından concurrent silme race window'u taşıyordu —
	başka bir tab/tx commit'imizden hemen sonra delete ederse reload
	`DoesNotExistError` fırlatabilirdi.

	Çözüm: `doc.is_default`'u atomik `current_default_id`'den türet
	(`doc.is_default = (current_default_id == doc.name)`). Bu, _ensure_one_default
	fallback path'inin (zero-default → en eski default yap) in-memory doc'u
	güncellememesi sorununu da elimine eder. Reload tamamen gereksiz.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m)
		return m.group(0)

	def test_buyer_save_no_reload_call(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		self.assertNotIn(
			"doc.reload()",
			src,
			"save_address hâlâ doc.reload() çağırıyor — commit sonrası race window'u",
		)

	def test_seller_save_no_reload_call(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertNotIn("doc.reload()", src)

	def test_buyer_save_derives_is_default_from_current_default_id(self):
		"""Reload yerine `doc.is_default = current_default_id == doc.name`
		ile in-memory doc senkronize edilmeli."""
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("doc.is_default = current_default_id == doc.name", src)

	def test_seller_save_derives_is_default_from_current_default_id(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertIn("doc.is_default = current_default_id == doc.name", src)


class TestSaveAddressLockedAsOwnerCheck(unittest.TestCase):
	"""
	save_address UPDATE path'inde de `_check_address_owner` kaldırıldı —
	locked rows üzerinde existence check yapılıyor. Bu hem ekstra SELECT'i
	tasarruf eder hem de buyer/seller arasında ortak owner-check pattern'i
	sağlar.
	"""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m)
		return m.group(0)

	def test_buyer_save_no_owner_check_helper(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		self.assertNotIn(
			"_check_address_owner(address_id, user)",
			src,
			"save_address hâlâ ayrı _check_address_owner SELECT'i yapıyor",
		)

	def test_seller_save_no_owner_check_helper(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertNotIn(
			"_check_address_owner(address_id, seller_name)",
			src,
		)

	def test_buyer_save_existence_check_under_lock(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "buyer.py"
		src = self._read_function_source(path, "save_address")
		self.assertRegex(
			src,
			r"any\(row\.name\s*==\s*address_id\s+for\s+row\s+in\s+locked\)",
		)

	def test_seller_save_existence_check_under_lock(self):
		path = _APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py"
		src = self._read_function_source(path, "save_address")
		self.assertRegex(
			src,
			r"any\(row\.name\s*==\s*address_id\s+for\s+row\s+in\s+locked\)",
		)


class TestBuyerSellerSyncOnValidators(unittest.TestCase):
	"""
	buyer.py ve seller_addresses.py'nin aynı validator pipeline'ını kullandığını
	doğrular — drift'i CI'da yakalar (audit'teki #8 maddesi).
	"""

	def setUp(self):
		self.buyer_src = (_APP_ROOT / "tradehub_core" / "api" / "buyer.py").read_text(encoding="utf-8")
		self.seller_src = (_APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py").read_text(
			encoding="utf-8"
		)

	def test_both_import_validators(self):
		for label, src in [("buyer", self.buyer_src), ("seller", self.seller_src)]:
			with self.subTest(module=label):
				self.assertIn("from tradehub_core.api._address_validators import", src)
				self.assertIn("parse_address_payload", src)
				self.assertIn("validate_country_code", src)
				self.assertIn("validate_field_lengths", src)
				self.assertIn("validate_postal_code", src)
				self.assertIn("AddressValidationError", src)

	def test_neither_uses_raw_json_loads(self):
		# Ham `json.loads(address_json)` artık olmamalı — parse_address_payload
		# tüm JSON girdilerini güvenli şekilde sarmalıyor.
		for label, src in [("buyer", self.buyer_src), ("seller", self.seller_src)]:
			with self.subTest(module=label):
				self.assertNotIn(
					"json.loads(address_json)",
					src,
					f"{label}.py hâlâ raw json.loads kullanıyor",
				)

	def test_both_validate_country(self):
		# country alanı her iki tarafta da validate_country_code'tan geçmeli
		for label, src in [("buyer", self.buyer_src), ("seller", self.seller_src)]:
			with self.subTest(module=label):
				self.assertIn("validate_country_code(country_in)", src)


# ═══════════════════════════════════════════════════════════════════════════════
# E2E / Cross-layer Testleri — 2026-05-26 düzeltme doğrulaması
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuyerPurposeValidation(unittest.TestCase):
	"""buyer.py: Buyer kullanıcı sadece Delivery veya Billing gönderebilir."""

	def setUp(self):
		self.src = (_APP_ROOT / "tradehub_core" / "api" / "buyer.py").read_text(encoding="utf-8")

	def test_buyer_rejects_pickup_purpose(self):
		"""Buyer purpose='Pickup' sessiz fallback yerine hata fırlatmalı."""
		self.assertIn('BUYER_ALLOWED_PURPOSES = ("Delivery", "Billing")', self.src)
		self.assertNotIn(
			'purpose = "Delivery"  # Silent fallback',
			self.src,
			"Sessiz purpose fallback hâlâ mevcut — kaldırılmalıydı",
		)

	def test_buyer_purpose_throws_on_invalid(self):
		"""Geçersiz purpose'ta frappe.throw çağrılmalı."""
		# save_address fonksiyonu içinde purpose kontrolü throw içermeli
		self.assertIn("Geçersiz adres amacı", self.src)

	def test_buyer_address_type_throws_on_invalid(self):
		"""Geçersiz address_type'ta frappe.throw çağrılmalı."""
		self.assertIn("Geçersiz adres tipi", self.src)

	def test_no_silent_fallback_for_purpose(self):
		"""purpose invalid iken sessizce 'Delivery' atanmamalı."""
		# Eski pattern: `if purpose not in ...: purpose = "Delivery"`
		# Yeni pattern: `if purpose not in ...: frappe.throw(...)`
		pattern = re.compile(r'if\s+purpose\s+not\s+in.*:\s*\n\s*purpose\s*=')
		self.assertIsNone(
			pattern.search(self.src),
			"Sessiz purpose fallback pattern hâlâ mevcut",
		)

	def test_no_silent_fallback_for_address_type(self):
		"""address_type invalid iken sessizce 'Individual' atanmamalı."""
		pattern = re.compile(r'if\s+address_type\s+not\s+in.*:\s*\n\s*address_type\s*=')
		self.assertIsNone(
			pattern.search(self.src),
			"Sessiz address_type fallback pattern hâlâ mevcut",
		)


class TestPhonePrefixConsistency(unittest.TestCase):
	"""buyer.py ve seller_addresses.py: Telefon prefix-numara tutarlılık kontrolü."""

	def setUp(self):
		self.buyer_src = (_APP_ROOT / "tradehub_core" / "api" / "buyer.py").read_text(encoding="utf-8")
		self.seller_src = (_APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py").read_text(
			encoding="utf-8"
		)

	def test_buyer_has_prefix_consistency_check(self):
		"""buyer.py non-TR phone path'inde prefix tutarlılık kontrolü olmalı."""
		self.assertIn("prefix_digits = phone_prefix_in.lstrip", self.buyer_src)
		self.assertIn("intl_digits.startswith(prefix_digits)", self.buyer_src)

	def test_seller_has_prefix_consistency_check(self):
		"""seller_addresses.py non-TR phone path'inde prefix tutarlılık kontrolü olmalı."""
		self.assertIn("prefix_digits = phone_prefix_in.lstrip", self.seller_src)
		self.assertIn("intl_digits.startswith(prefix_digits)", self.seller_src)

	def test_buyer_strips_prefix_from_phone(self):
		"""Buyer: numara prefix ile başlıyorsa local kısmı saklanmalı."""
		self.assertIn('phone_to_save = intl_digits[len(prefix_digits):]', self.buyer_src)

	def test_seller_strips_prefix_from_phone(self):
		"""Seller: numara prefix ile başlıyorsa local kısmı saklanmalı."""
		self.assertIn('phone_to_save = intl_digits[len(prefix_digits):]', self.seller_src)


class TestIgnorePermissionsJustification(unittest.TestCase):
	"""ignore_permissions=True kullanımları gerekçe yorumu içermeli."""

	def _read_function_source(self, module_path: Path, func_name: str) -> str:
		text = module_path.read_text(encoding="utf-8")
		pattern = re.compile(
			rf"^def {re.escape(func_name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(text)
		self.assertIsNotNone(m, f"{func_name} not found in {module_path}")
		return m.group(0)

	def test_buyer_save_has_justification(self):
		src = self._read_function_source(
			_APP_ROOT / "tradehub_core" / "api" / "buyer.py", "save_address"
		)
		# Her ignore_permissions satırından önce yorum olmalı
		lines = src.split("\n")
		for i, line in enumerate(lines):
			if "ignore_permissions=True" in line:
				# Önceki satır(lar)da yorum olmalı
				prev_lines = "\n".join(lines[max(0, i - 2) : i])
				self.assertIn(
					"#",
					prev_lines,
					f"ignore_permissions yorumsuz: satır {i}: {line.strip()}",
				)

	def test_buyer_delete_has_justification(self):
		src = self._read_function_source(
			_APP_ROOT / "tradehub_core" / "api" / "buyer.py", "delete_address"
		)
		lines = src.split("\n")
		for i, line in enumerate(lines):
			if "ignore_permissions=True" in line:
				prev_lines = "\n".join(lines[max(0, i - 2) : i])
				self.assertIn("#", prev_lines)

	def test_seller_save_has_justification(self):
		src = self._read_function_source(
			_APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py", "save_address"
		)
		lines = src.split("\n")
		for i, line in enumerate(lines):
			if "ignore_permissions=True" in line:
				prev_lines = "\n".join(lines[max(0, i - 2) : i])
				self.assertIn("#", prev_lines)

	def test_seller_delete_has_justification(self):
		src = self._read_function_source(
			_APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py", "delete_address"
		)
		lines = src.split("\n")
		for i, line in enumerate(lines):
			if "ignore_permissions=True" in line:
				prev_lines = "\n".join(lines[max(0, i - 2) : i])
				self.assertIn("#", prev_lines)


class TestStorefrontCheckoutCompanyOptional(unittest.TestCase):
	"""Storefront checkout: company alanı opsiyonel olmalı."""

	_CHECKOUT_PATH = (
		Path(__file__).resolve().parents[3] / "tradehubfront" / "src" / "alpine" / "checkout.ts"
	)

	@unittest.skipUnless(
		_CHECKOUT_PATH.exists(),
		"tradehubfront/src/alpine/checkout.ts mevcut değil",
	)
	def test_company_not_in_validate_required_fields(self):
		src = self._CHECKOUT_PATH.read_text(encoding="utf-8")
		# validateAddAddressForm içindeki requiredFields'da "company" olmamalı
		pattern = re.compile(
			r'validateAddAddressForm\(\).*?requiredFields.*?\[([^\]]+)\]',
			re.DOTALL,
		)
		m = pattern.search(src)
		self.assertIsNotNone(m, "validateAddAddressForm requiredFields bulunamadı")
		fields_str = m.group(1)
		self.assertNotIn('"company"', fields_str)

	@unittest.skipUnless(
		_CHECKOUT_PATH.exists(),
		"tradehubfront/src/alpine/checkout.ts mevcut değil",
	)
	def test_company_not_in_handlesubmit_required_fields(self):
		src = self._CHECKOUT_PATH.read_text(encoding="utf-8")
		# handleSubmit içindeki requiredFields'da "company" olmamalı
		pattern = re.compile(
			r'handleSubmit\(\).*?requiredFields\s*=\s*\[([^\]]+)\]',
			re.DOTALL,
		)
		m = pattern.search(src)
		self.assertIsNotNone(m, "handleSubmit requiredFields bulunamadı")
		fields_str = m.group(1)
		self.assertNotIn('"company"', fields_str)


class TestStorefrontNoAlertCalls(unittest.TestCase):
	"""Storefront checkout: alert() yerine showToast kullanılmalı."""

	_CHECKOUT_PATH = (
		Path(__file__).resolve().parents[3] / "tradehubfront" / "src" / "alpine" / "checkout.ts"
	)

	@unittest.skipUnless(
		_CHECKOUT_PATH.exists(),
		"tradehubfront/src/alpine/checkout.ts mevcut değil",
	)
	def test_no_alert_calls(self):
		src = self._CHECKOUT_PATH.read_text(encoding="utf-8")
		# `alert(` çağrısı olmamalı — window.alert da dahil
		alert_pattern = re.compile(r'\balert\s*\(')
		matches = alert_pattern.findall(src)
		self.assertEqual(
			len(matches),
			0,
			f"checkout.ts'de {len(matches)} adet alert() çağrısı kaldı",
		)

	@unittest.skipUnless(
		_CHECKOUT_PATH.exists(),
		"tradehubfront/src/alpine/checkout.ts mevcut değil",
	)
	def test_showtoast_imported(self):
		src = self._CHECKOUT_PATH.read_text(encoding="utf-8")
		self.assertIn("import { showToast }", src)

	@unittest.skipUnless(
		_CHECKOUT_PATH.exists(),
		"tradehubfront/src/alpine/checkout.ts mevcut değil",
	)
	def test_showtoast_used_for_errors(self):
		src = self._CHECKOUT_PATH.read_text(encoding="utf-8")
		# Hata durumlarında showToast error tipiyle kullanılmalı
		self.assertIn('showToast({ message: msg, type: "error" })', src)


class TestStorefrontAddressBookFields(unittest.TestCase):
	"""Storefront address book: form alanları backend ile uyumlu olmalı."""

	_ADDRESSES_PATH = (
		Path(__file__).resolve().parents[3] / "tradehubfront" / "src" / "alpine" / "addresses.ts"
	)

	@unittest.skipUnless(
		_ADDRESSES_PATH.exists(),
		"tradehubfront/src/alpine/addresses.ts mevcut değil",
	)
	def test_default_purpose_is_delivery(self):
		src = self._ADDRESSES_PATH.read_text(encoding="utf-8")
		self.assertIn('purpose: "Delivery"', src)

	@unittest.skipUnless(
		_ADDRESSES_PATH.exists(),
		"tradehubfront/src/alpine/addresses.ts mevcut değil",
	)
	def test_no_pickup_purpose_in_buyer_storefront(self):
		"""Buyer storefront hiçbir yerde purpose='Pickup' atamamalı."""
		src = self._ADDRESSES_PATH.read_text(encoding="utf-8")
		self.assertNotIn('purpose: "Pickup"', src)
		self.assertNotIn("purpose: 'Pickup'", src)


class TestBackendBuyerSellerFieldSymmetry(unittest.TestCase):
	"""buyer.py ve seller_addresses.py aynı doc_to_dict alanlarını dönmeli."""

	def setUp(self):
		self.buyer_src = (_APP_ROOT / "tradehub_core" / "api" / "buyer.py").read_text(encoding="utf-8")
		self.seller_src = (_APP_ROOT / "tradehub_core" / "api" / "seller_addresses.py").read_text(
			encoding="utf-8"
		)

	def _extract_doc_to_dict_fields(self, src: str) -> set:
		"""_doc_to_dict fonksiyonundaki return dict key'lerini çıkart."""
		pattern = re.compile(
			r"def _doc_to_dict\(.*?return\s*\{(.*?)\}",
			re.DOTALL,
		)
		m = pattern.search(src)
		self.assertIsNotNone(m)
		# Key'leri çıkar: "field_name": ...
		keys = re.findall(r'"(\w+)"\s*:', m.group(1))
		return set(keys)

	def test_buyer_seller_return_same_fields(self):
		buyer_fields = self._extract_doc_to_dict_fields(self.buyer_src)
		seller_fields = self._extract_doc_to_dict_fields(self.seller_src)
		self.assertEqual(
			buyer_fields,
			seller_fields,
			f"Buyer/Seller _doc_to_dict alan farkı: "
			f"buyer_extra={buyer_fields - seller_fields}, "
			f"seller_extra={seller_fields - buyer_fields}",
		)

	def test_required_api_fields_present(self):
		"""API response'ta olması gereken kritik alanlar."""
		expected_fields = {
			"id", "title", "contact_name", "company", "phone_prefix", "phone",
			"country", "state", "city", "street", "apartment", "postal_code",
			"note", "is_default", "purpose", "address_type", "tax_no", "tax_office",
		}
		buyer_fields = self._extract_doc_to_dict_fields(self.buyer_src)
		missing = expected_fields - buyer_fields
		self.assertEqual(
			missing,
			set(),
			f"API response'ta eksik alanlar: {missing}",
		)


class TestCartServiceTypeAlignment(unittest.TestCase):
	"""cartService.ts BuyerAddressData tipi backend ile uyumlu olmalı."""

	_CART_SERVICE_PATH = (
		Path(__file__).resolve().parents[3] / "tradehubfront" / "src" / "services" / "cartService.ts"
	)

	@unittest.skipUnless(
		_CART_SERVICE_PATH.exists(),
		"tradehubfront/src/services/cartService.ts mevcut değil",
	)
	def test_buyer_address_data_has_required_fields(self):
		src = self._CART_SERVICE_PATH.read_text(encoding="utf-8")
		# BuyerAddressData type'ında backend'in döndüğü tüm alanlar olmalı
		required = [
			"id", "title", "contact_name", "company", "phone_prefix", "phone",
			"country", "state", "city", "street", "apartment", "postal_code",
			"note", "is_default", "purpose", "address_type", "tax_no", "tax_office",
		]
		for field in required:
			self.assertIn(
				field,
				src,
				f"cartService.ts BuyerAddressData'da '{field}' alanı eksik",
			)


class TestAdminPanelAddressFieldSync(unittest.TestCase):
	"""Admin panel SellerAddressesPanel.vue: backend ile alan senkronizasyonu."""

	_PANEL_PATH = (
		Path(__file__).resolve().parents[3]
		/ "admin-panel"
		/ "frontend"
		/ "src"
		/ "components"
		/ "seller"
		/ "SellerAddressesPanel.vue"
	)

	@unittest.skipUnless(
		_PANEL_PATH.exists(),
		"admin-panel SellerAddressesPanel.vue mevcut değil",
	)
	def test_panel_calls_correct_api(self):
		src = self._PANEL_PATH.read_text(encoding="utf-8")
		self.assertIn("tradehub_core.api.seller_addresses.get_addresses", src)
		self.assertIn("tradehub_core.api.seller_addresses.save_address", src)
		self.assertIn("tradehub_core.api.seller_addresses.delete_address", src)
		self.assertIn("tradehub_core.api.seller_addresses.set_default_address", src)

	@unittest.skipUnless(
		_PANEL_PATH.exists(),
		"admin-panel SellerAddressesPanel.vue mevcut değil",
	)
	def test_panel_has_phone_validation(self):
		src = self._PANEL_PATH.read_text(encoding="utf-8")
		# Türk telefon regex'i frontend'de de olmalı
		self.assertRegex(src, r"\(\\\+90\|0\)")


class TestAddressDocTypeSchemaIntegrity(unittest.TestCase):
	"""DocType JSON schema: purpose, address_type, tax alanları mevcut olmalı."""

	_SCHEMA_PATH = (
		_APP_ROOT
		/ "tradehub_core"
		/ "tradehub_core"
		/ "doctype"
		/ "addresses"
		/ "addresses.json"
	)

	@unittest.skipUnless(
		_SCHEMA_PATH.exists(),
		"addresses.json mevcut değil",
	)
	def test_schema_has_purpose_field(self):
		import json as _json
		schema = _json.loads(self._SCHEMA_PATH.read_text(encoding="utf-8"))
		field_names = [f["fieldname"] for f in schema.get("fields", [])]
		self.assertIn("purpose", field_names)

	@unittest.skipUnless(
		_SCHEMA_PATH.exists(),
		"addresses.json mevcut değil",
	)
	def test_schema_has_address_type_field(self):
		import json as _json
		schema = _json.loads(self._SCHEMA_PATH.read_text(encoding="utf-8"))
		field_names = [f["fieldname"] for f in schema.get("fields", [])]
		self.assertIn("address_type", field_names)

	@unittest.skipUnless(
		_SCHEMA_PATH.exists(),
		"addresses.json mevcut değil",
	)
	def test_schema_has_tax_fields(self):
		import json as _json
		schema = _json.loads(self._SCHEMA_PATH.read_text(encoding="utf-8"))
		field_names = [f["fieldname"] for f in schema.get("fields", [])]
		self.assertIn("tax_no", field_names)
		self.assertIn("tax_office", field_names)

	@unittest.skipUnless(
		_SCHEMA_PATH.exists(),
		"addresses.json mevcut değil",
	)
	def test_purpose_options_match_backend(self):
		"""DocType purpose seçenekleri buyer+seller allowed_purposes'ı kapsamalı."""
		import json as _json
		schema = _json.loads(self._SCHEMA_PATH.read_text(encoding="utf-8"))
		purpose_field = next(
			(f for f in schema["fields"] if f["fieldname"] == "purpose"), None
		)
		self.assertIsNotNone(purpose_field)
		options = set(purpose_field.get("options", "").split("\n"))
		# Buyer: Delivery, Billing — Seller: Pickup
		self.assertIn("Delivery", options)
		self.assertIn("Billing", options)
		self.assertIn("Pickup", options)


if __name__ == "__main__":
	unittest.main()
