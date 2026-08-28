# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""09-BE A — Entegrasyon logu altyapısı testleri (maskeleme + yazıcı + saklama + izin).

Çalıştırma:
	docker exec istoccom-backend-1 bash -lc "cd /home/frappe/frappe-bench && \\
	  bench --site tradehub.localhost run-tests \\
	  --module tradehub_core.logistics.tests.test_integration_log"

Bloklar:

	TestMasking                    saf fonksiyonlar — Frappe gerektirmez
	TestValueBasedRedaction        birincil savunma: sırrı BİÇİMDEN bağımsız ara
	TestMaskingRegressionTiming    ReDoS regresyonu (düz + XML)
	TestContractSingleSource       constants ↔ DocType JSON ↔ log.py aynı kümede mi
	TestIntegrationLogWriter       gerçek DocType'a yazma, kırpma, hata dayanıklılığı
	TestIntegrationLogDocType      controller: append-only + ikinci maskeleme
	TestIntegrationLogRetention    saklama job'ı (eski silinir, yeni kalır, geride kalma)
	TestIntegrationLogPermissions  satıcıya kapalı olduğunun kanıtı

TASARIM NOTU — neden bu kadar çok "vaka sınıfı":
	Önceki turda dört güvenlik açığı (camelCase, XML/SOAP, TR anahtarlar,
	`error_message`) testlerden KAÇTI çünkü tüm fixture'lar İngilizce, düz JSON
	ve yalnız gövde alanlarıydı. Oysa sistem TR kargo entegrasyonu ve baskın
	protokol SOAP. Aşağıdaki sınıflar o kör noktaları kalıcı olarak kapatır.
"""

from __future__ import annotations

import base64
import json
import time
import unittest
import unittest.mock as mock
import urllib.parse
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tradehub_core.logistics.constants import (
	INTEGRATION_LOG_DIRECTION_ORDER,
	INTEGRATION_LOG_DIRECTIONS,
	INTEGRATION_LOG_OPERATION_ORDER,
	INTEGRATION_LOG_OPERATIONS,
)
from tradehub_core.logistics.integration import log as log_module
from tradehub_core.logistics.integration.log import (
	CONTRACT_VIOLATION_CODE,
	CONTROLLER_MASKED_FIELDS,
	INTEGRATION_LOG_DOCTYPE,
	MASKED_LOG_FIELDS,
	MAX_BODY_BYTES,
	VALID_DIRECTIONS,
	VALID_OPERATIONS,
	write_integration_log,
)
from tradehub_core.logistics.integration.masking import (
	DEFAULT_SENSITIVE_KEYS,
	MASK,
	MIN_NUMERIC_SECRET_LENGTH,
	MIN_SECRET_LENGTH,
	XML_BOUNDARY_UNRESOLVED,
	build_secret_variants,
	is_sensitive_key,
	mask_headers,
	mask_mapping,
	mask_payload,
	mask_value,
	redact_text,
	strip_partial_secret_tail,
)
from tradehub_core.logistics.integration.secrets import collect_secret_values
from tradehub_core.logistics.jobs import integration_log_retention as retention
from tradehub_core.logistics.permissions import (
	carrier_integration_log_has_permission,
	carrier_integration_log_query_conditions,
)

_SECRET = "SUPERSECRETVALUE"


# ---------------------------------------------------------------------------
# Maskeleme — saf, Frappe'siz
# ---------------------------------------------------------------------------


class TestMasking(unittest.TestCase):
	"""Kimlik bilgisi hiçbir girdi biçiminde log'a düşmemeli."""

	def test_mask_value_is_constant(self):
		"""Uzunluk ipucu bile verilmez — her değer aynı sabite iner."""
		self.assertEqual(mask_value("a"), MASK)
		self.assertEqual(mask_value("a" * 500), MASK)

	def test_flat_dict(self):
		masked = mask_payload({"api_key": _SECRET, "carrier": "ARAS"})
		self.assertEqual(masked["api_key"], MASK)
		self.assertEqual(masked["carrier"], "ARAS")

	def test_nested_dict(self):
		masked = mask_payload({"header": {"api_key": _SECRET, "musteri": "istoc"}})
		self.assertEqual(masked["header"]["api_key"], MASK)
		self.assertEqual(masked["header"]["musteri"], "istoc")

	def test_sensitive_container_is_masked_wholesale(self):
		"""`auth` adının kendisi hassas: alt ağacın tamamı tek `***`e iner."""
		self.assertEqual(mask_payload({"auth": {"api_key": _SECRET, "user": "istoc"}})["auth"], MASK)

	def test_dict_inside_list(self):
		masked = mask_payload({"accounts": [{"password": _SECRET}, {"name": "ok"}]})
		self.assertEqual(masked["accounts"][0]["password"], MASK)
		self.assertEqual(masked["accounts"][1]["name"], "ok")

	def test_json_string_is_parsed_and_masked(self):
		raw = json.dumps({"token": _SECRET, "shipment": "SHP-1"})
		masked = mask_payload(raw)
		self.assertIsInstance(masked, str)
		self.assertNotIn(_SECRET, masked)
		self.assertIn("SHP-1", masked)

	def test_non_json_string_uses_regex(self):
		raw = f"grant_type=client_credentials&client_secret={_SECRET}&scope=read"
		masked = mask_payload(raw)
		self.assertNotIn(_SECRET, masked)
		self.assertIn("scope=read", masked)

	def test_non_json_string_with_quoted_pairs(self):
		raw = f'çağrı başarısız: "api_secret": "{_SECRET}", "code": "E42"'
		masked = mask_payload(raw)
		self.assertNotIn(_SECRET, masked)
		self.assertIn("E42", masked)

	def test_plain_text_is_untouched(self):
		self.assertEqual(mask_payload("gönderi oluşturuldu"), "gönderi oluşturuldu")

	def test_bytes_utf8(self):
		masked = mask_payload(json.dumps({"password": _SECRET}).encode("utf-8"))
		self.assertNotIn(_SECRET, masked)

	def test_bytes_binary_becomes_size_summary(self):
		self.assertEqual(mask_payload(b"\xff\xfe\x00\x01binary"), "<binary 10 bytes>")

	def test_none(self):
		self.assertIsNone(mask_payload(None))

	def test_scalars_pass_through(self):
		self.assertEqual(mask_payload(42), 42)
		self.assertIs(mask_payload(True), True)

	def test_unknown_object_becomes_type_name(self):
		"""Tanınmayan nesnenin `repr`'i kimlik bilgisi taşıyabilir — yazılmaz.

		Eski davranış nesneyi olduğu gibi geçiriyor, `log.py` de
		`json.dumps(default=str)` ile `repr`'ini sütuna yazıyordu.
		"""

		class Credentials:
			def __repr__(self) -> str:
				return f"Credentials(api_key={_SECRET})"

		masked = mask_payload({"istek": Credentials()})
		self.assertEqual(masked["istek"], "<Credentials>")
		self.assertNotIn(_SECRET, json.dumps(masked))

	def test_suffix_match_catches_prefixed_keys(self):
		"""`client_secret` gibi ön ekli adlar da yakalanmalı (son-ek kuralı)."""
		masked = mask_mapping(
			{
				"client_secret": _SECRET,
				"bearer_token": _SECRET,
				"user_password": _SECRET,
				# Teşhis için gerekli, sır değil — maskelenmemeli (allowlist)
				"idempotency_key": "IK-1",
				"tracking_number": "TR-9",
				"error_code": "E42",
			}
		)
		self.assertEqual(masked["client_secret"], MASK)
		self.assertEqual(masked["bearer_token"], MASK)
		self.assertEqual(masked["user_password"], MASK)
		self.assertEqual(masked["idempotency_key"], "IK-1")
		self.assertEqual(masked["tracking_number"], "TR-9")
		self.assertEqual(masked["error_code"], "E42")

	def test_allowlist_beats_bare_key_denylist(self):
		"""Çıplak `key`/`kod` denylist'e girdi; teşhis alanları yine de açık kalmalı."""
		self.assertTrue(is_sensitive_key("key"))
		self.assertTrue(is_sensitive_key("kod"))
		self.assertFalse(is_sensitive_key("idempotency_key"))
		self.assertFalse(is_sensitive_key("x-idempotency-key"))
		self.assertFalse(is_sensitive_key("takip_kod"))

	def test_camel_case_keys_are_split(self):
		"""REGRESYON: camelCase adlar TAMAMEN kaçıyordu (ölçüldü)."""
		masked = mask_mapping(
			{
				"clientSecret": _SECRET,
				"accessToken": _SECRET,
				"AccessToken": _SECRET,
				"apiSecret": _SECRET,
				"webhookSecret": _SECRET,
				"xApiKey": _SECRET,
				"musteriSifre": _SECRET,
				"trackingNumber": "TR-9",
			}
		)
		for key in (
			"clientSecret",
			"accessToken",
			"AccessToken",
			"apiSecret",
			"webhookSecret",
			"xApiKey",
			"musteriSifre",
		):
			self.assertEqual(masked[key], MASK, key)
		self.assertEqual(masked["trackingNumber"], "TR-9")

	def test_turkish_keys_are_masked(self):
		"""Sistem TR kargo entegrasyonu; İngilizce-only sözlük hiçbir şey yakalamaz."""
		masked = mask_mapping(
			{
				"sifre": _SECRET,
				"parola": _SECRET,
				"kullanici_adi": _SECRET,
				"kullanici": _SECRET,
				"musteri_kodu": _SECRET,
				"musteri_no": _SECRET,
				"kod": _SECRET,
				"pin": _SECRET,
				"gonderi_no": "GN-1",
			}
		)
		for key in (
			"sifre",
			"parola",
			"kullanici_adi",
			"kullanici",
			"musteri_kodu",
			"musteri_no",
			"kod",
			"pin",
		):
			self.assertEqual(masked[key], MASK, key)
		self.assertEqual(masked["gonderi_no"], "GN-1")

	def test_crypto_and_session_keys_are_masked(self):
		masked = mask_mapping(
			{
				"private_key": _SECRET,
				"certificate": _SECRET,
				"signature": _SECRET,
				"hmac": _SECRET,
				"nonce": _SECRET,
				"session_id": _SECRET,
				"jsessionid": _SECRET,
				"phpsessid": _SECRET,
				"username": _SECRET,
				"credentials": _SECRET,
			}
		)
		for key, value in masked.items():
			self.assertEqual(value, MASK, key)

	def test_xml_soap_element_is_masked(self):
		"""REGRESYON: SOAP TR kargo firmalarının baskın protokolü, hiç yakalanmıyordu."""
		body = (
			"<soap:Envelope><soap:Body><Login>"
			f"<soap:Password>{_SECRET}</soap:Password>"
			f"<Sifre>{_SECRET}</Sifre>"
			f"<KullaniciAdi>{_SECRET}</KullaniciAdi>"
			"<MusteriAdi>İstoç</MusteriAdi>"
			"</Login></soap:Body></soap:Envelope>"
		)
		masked = mask_payload(body)
		self.assertNotIn(_SECRET, masked)
		self.assertIn("İstoç", masked)
		self.assertIn("<soap:Password>***</soap:Password>", masked)
		self.assertIn("<Sifre>***</Sifre>", masked)

	def test_xml_attribute_is_masked(self):
		masked = mask_payload(f"<Login password=\"{_SECRET}\" kullanici='{_SECRET}' sehir='İstanbul'/>")
		self.assertNotIn(_SECRET, masked)
		self.assertIn("İstanbul", masked)

	def test_same_content_masks_identically_across_shapes(self):
		"""REGRESYON: `{'cookie': ...}` dict olarak maskelenmiyordu, metin olarak maskeleniyordu.

		Sözlük yolu `SENSITIVE_KEYS`, metin yolu `SENSITIVE_HEADER_KEYS`
		kullanıyordu. Artık küme seçimi TEK yerde.
		"""
		as_dict = mask_payload({"cookie": _SECRET})
		as_json = mask_payload(json.dumps({"cookie": _SECRET}))
		as_query = mask_payload(f"cookie={_SECRET}")

		self.assertEqual(as_dict["cookie"], MASK)
		self.assertNotIn(_SECRET, as_json)
		self.assertNotIn(_SECRET, as_query)

	def test_key_case_and_separator_variants(self):
		payload = {
			"API_KEY": _SECRET,
			"Api-Key": _SECRET,
			"X-Api-Key": _SECRET,
			"AccessToken": _SECRET,
			"ACCESS_TOKEN": _SECRET,
			"Authorization": _SECRET,
		}
		masked = mask_mapping(payload)
		for key in payload:
			self.assertEqual(masked[key], MASK, key)

	def test_mask_headers(self):
		masked = mask_headers(
			{
				"Authorization": f"Bearer {_SECRET}",
				"Cookie": f"sid={_SECRET}",
				"X-Api-Key": _SECRET,
				"Content-Type": "application/json",
			}
		)
		self.assertEqual(masked["Authorization"], MASK)
		self.assertEqual(masked["Cookie"], MASK)
		self.assertEqual(masked["X-Api-Key"], MASK)
		self.assertEqual(masked["Content-Type"], "application/json")

	def test_mask_headers_none(self):
		self.assertEqual(mask_headers(None), {})

	def test_masking_is_idempotent(self):
		once = mask_payload({"api_key": _SECRET, "nested": {"token": _SECRET}})
		self.assertEqual(once, mask_payload(once))

	def test_input_is_not_mutated(self):
		original = {"api_key": _SECRET}
		mask_payload(original)
		self.assertEqual(original["api_key"], _SECRET)


class TestMaskingSecondAudit(unittest.TestCase):
	"""2. tur güvenlik denetiminin ÖLÇÜLMÜŞ kaçışları — hepsi kalıcı olarak kapalı."""

	def test_cdata_does_not_bypass_masking(self):
		"""KRİTİK: `<![CDATA[` değer grubunu ilk karakterde kırıyordu.

		CDATA, TR kargo SOAP yanıtlarında (Aras/Yurtiçi/MNG) yaygındır ve tam da
		"değer bilinmiyor, tek savunma denylist" senaryosudur: taşıyıcının
		YANITINDA dönen oturum jetonu `secret_values` içinde YOKTUR.
		"""
		self.assertEqual(mask_payload("<Sifre><![CDATA[SESSIONABC999]]></Sifre>"), f"<Sifre>{MASK}</Sifre>")
		self.assertNotIn(_SECRET, mask_payload(f"<Token><![CDATA[{_SECRET}]]></Token>"))

	def test_raw_lt_inside_value_does_not_bypass_masking(self):
		"""Aynı kök neden: değerde geçen çıplak `<` de eşleşmeyi kırıyordu."""
		self.assertNotIn("SECRETXYZ", mask_payload("<Password>a<bSECRETXYZ</Password>"))

	def test_xml_value_longer_than_old_bound_is_masked(self):
		"""KRİTİK FAIL-OPEN: 4096 karakterlik üst sınır aşılınca maskeleme HİÇ uygulanmıyordu.

		JWT / SAML assertion / uzun oturum jetonu 4 KB'ı rahat aşar.
		"""
		blob = "T" * 5000
		self.assertEqual(mask_payload(f"<Token>{blob}</Token>"), f"<Token>{MASK}</Token>")
		self.assertNotIn(blob, mask_payload(f'<a token="{blob}"/>'))
		# Açılış etiketinde 512 baytı aşan öznitelik bloğu eşleşmeyi düşürüyordu.
		self.assertNotIn(_SECRET, mask_payload(f"<Sifre {'z' * 600}>{_SECRET}</Sifre>"))

	def test_turkish_dotted_capital_i_is_normalized(self):
		"""KRİTİK: `'İ'.lower()` == `'i' + U+0307`, `'i'` DEĞİL.

		Noktalı İ TR klavyede VARSAYILANDIR; büyük harfli alan adı (SIFRE,
		KULLANICIADI, MUSTERIKODU) TR kargo XML şemalarında standart kalıptır.
		"""
		for key in ("SIFRE", "ŞİFRE", "Şifre", "MÜŞTERİ_KODU", "MUSTERİKODU", "PAROLA"):
			self.assertTrue(is_sensitive_key(key), key)

	def test_camel_boundary_is_unicode_aware(self):
		"""KRİTİK: `[A-Z]` Python str regex'inde SALT ASCII — `Ş`/`İ`/`Ö` ile eşleşmez."""
		for key in ("musteriŞifre", "musteriSifre", "clientSecret", "HTTPAuth", "xApiKey"):
			self.assertTrue(is_sensitive_key(key), key)

	def test_joined_names_are_derived_automatically(self):
		"""MINOR: `apikey` vardı ama kardeşleri yoktu; artık `_` silinmiş hâl OTOMATİK üretilir."""
		for key in (
			"accesstoken",
			"sessiontoken",
			"sessid",
			"httpauth",
			"apisecret",
			"clientsecret",
			"privatekey",
			"webhooksecret",
			"kullaniciadi",
			"musterikodu",
		):
			self.assertTrue(is_sensitive_key(key), key)

	def test_allowlist_suffix_no_longer_overrides_denylist(self):
		"""KRİTİK REGRESYON: allowlist SON EKİ denylist segmentini geçersiz kılıyordu.

		Bu adlar allowlist eklenmeden ÖNCE maskeleniyordu; `cache_key`/`hata_kod`
		gibi girdiler eklenince sessizce açılmışlardı (altısı da ölçüldü).
		"""
		for key in (
			"password_cache_key",
			"secret_object_key",
			"sifre_hata_kod",
			"token_status_code",
			"auth_error_code",
			"clientSecretCacheKey",
		):
			self.assertTrue(is_sensitive_key(key), key)

	def test_diagnostic_allowlist_still_wins_on_exact_match(self):
		"""Allowlist TAM ad (ve `x-` ön eki sıyrılmış hâli) için hâlâ geçerli."""
		for key in ("idempotency_key", "x-idempotency-key", "tracking_number", "error_code", "takip_kod"):
			self.assertFalse(is_sensitive_key(key), key)

	def test_infrastructure_key_names_are_no_longer_allowlisted(self):
		"""`cache_key`/`routing_key` bir kargo teşhisinde geçmez — yalnız saldırı yüzeyiydi."""
		for key in ("cache_key", "routing_key", "partition_key", "sort_key", "object_key"):
			self.assertTrue(is_sensitive_key(key), key)

	def test_key_colon_value_formats_are_masked(self):
		"""KRİTİK: `anahtar: değer` biçimi için HİÇBİR kalıp yoktu — yedisi de ham sızıyordu."""
		cases = (
			f"Authorization: Basic {_SECRET}",
			f"X-Api-Key: {_SECRET}",
			f"Cookie: SESSID={_SECRET}",
			f"password: {_SECRET}",
			f"-H 'X-Api-Key: {_SECRET}'",
			f"data={{'sifre': '{_SECRET}'}}",
			f"https://user:{_SECRET}@api.kargo.com",
		)
		for raw in cases:
			self.assertNotIn(_SECRET, mask_payload(raw), raw)

	def test_python_repr_traceback_shape_is_masked(self):
		"""`frappe.get_traceback()` / `repr(exc)` TAM OLARAK bu biçimdedir ve `error_message`'a akar."""
		raw = f"HTTPError(url='x', headers={{'Authorization': 'Bearer {_SECRET}'}})"
		self.assertNotIn(_SECRET, mask_payload(raw))

	def test_zero_length_value_produces_no_misleading_mask(self):
		"""MINOR: `password=&b=2` → `password=***&b=2` üretiliyordu.

		Çıktı MASKELENMİŞ GÖRÜNÜYOR ama maskelenmiş bir şey YOKTUR; bu yanıltıcı
		çıktı hiç maskelememekten daha kötüdür.

		10. TURDA VEKTÖR DEĞİŞTİ — GEREKÇE ÖLÇÜLDÜ:
			Test eskiden `'password=\\n<sır>'` girdisini "değer sıfır uzunlukta"
			sayıp DEĞİŞMEDEN geçmesini kilitliyordu. O kilit, `_scan_value`'nun
			ayraç-sonrası boşluk penceresinin `\\r\\n` atlamamasından doğan bir
			FAIL-OPEN'ı doğru davranış sanıyordu: satır sonu değerin BİTTİĞİ
			anlamına gelmez, XML 1.0 `Eq ::= S? '=' S?` gereği `=` etrafında
			MEŞRUDUR ve biçimlendirilmiş SOAP yanıtlarında rutindir. 116/116
			yönlendirilmiş vektör HAM sızıyordu (bkz. `TestSeparatorGapFailsClosed`).

			Testin ASIL İDDİASI DEĞİŞMEDİ: değer GERÇEKTEN boşken yanıltıcı `***`
			yazılmaz. Ölçüt artık boşluk-olmayan bir sonlandırıcının ayraçtan
			HEMEN sonra gelmesidir — yani boşluğun gerçekten "değer yok" demediği
			ölçülebildiğinde.
		"""
		self.assertEqual(mask_payload("password=&b=2"), "password=&b=2")
		self.assertEqual(mask_payload('{"a":1,"sifre":,"takip":"TR-9"}'), '{"a":1,"sifre":,"takip":"TR-9"}')
		self.assertEqual(mask_payload(f"password=\n{_SECRET}"), f"password=\n{MASK}")

	def test_tuple_value_is_masked_whole(self):
		"""`auth=('user','<sır>')` → ilk eleman maskelenip sır kalıyordu."""
		self.assertNotIn(_SECRET, mask_payload(f"auth=('user','{_SECRET}')"))

	def test_mask_headers_accepts_non_mapping_container(self):
		"""MINOR: `requests`'in liste-of-tuple biçiminde AttributeError FIRLIYOR, log satırı düşüyordu."""
		masked = mask_headers([("Authorization", f"Bearer {_SECRET}"), ("Content-Type", "application/json")])
		self.assertEqual(masked["Authorization"], MASK)
		self.assertEqual(masked["Content-Type"], "application/json")

	def test_mask_headers_evaluates_nested_values(self):
		"""İç içe değerli başlık `str()` ile düzleştirilip iç anahtarları görülmüyordu."""
		self.assertEqual(mask_headers({"X-Meta": {"sifre": _SECRET}})["X-Meta"]["sifre"], MASK)

	def test_mask_headers_never_raises_on_garbage(self):
		self.assertEqual(mask_headers(object()), {})

	def test_deeply_nested_json_string_does_not_raise(self):
		"""MAJOR: `json.loads` derin girdide `RecursionError` atıp LOG SATIRINI DÜŞÜRÜYORDU.

		`direction='inbound'` webhook gövdesi SALDIRGAN KONTROLÜNDE: 3 KB'lık iç
		içe JSON POST eden biri o çağrının denetim kaydını engelleyebiliyordu.
		"""
		payload = '{"a":' * 500 + "1" + "}" * 500
		self.assertIsInstance(mask_payload(payload), str)

	def test_deeply_nested_mapping_does_not_raise(self):
		root: dict = {}
		node = root
		for _ in range(400):
			node["a"] = {}
			node = node["a"]
		node["sifre"] = _SECRET

		masked = mask_payload(root)
		self.assertIsInstance(masked, dict)
		self.assertNotIn(_SECRET, json.dumps(masked, ensure_ascii=False))

	def test_bytes_secret_is_redacted(self):
		"""MAJOR: `str(b'SECRET')` == `"b'SECRET'"` — bytes sır SESSİZCE atlanıyordu."""
		self.assertNotIn(_SECRET, redact_text(f"x={_SECRET}", [_SECRET.encode("utf-8")]))
		self.assertNotIn(_SECRET, redact_text(f"x={_SECRET}", [bytearray(_SECRET.encode("utf-8"))]))

	def test_truncation_boundary_leaves_no_secret_prefix(self):
		"""MAJOR: kırpma sırrın ortasına denk gelince ÖN EK ham kalıyordu (ölçüldü: 202 karakter).

		Sınırdaki HER kesme noktası denenir; sırrın 4+ karakterlik hiçbir ön eki
		çıktıda kalmamalı. İki katman birlikte sınanır çünkü iş bölümü budur:
		TAM sırrı `redact_text` siler, YARIM kalanı `strip_partial_secret_tail`.
		"""
		secret = "S" + "k" * 306 + "E"
		variants = build_secret_variants([secret])

		for cut in range(len(secret) + 1):
			truncated = ("A" * 64 + secret)[: 64 + cut]
			guarded = strip_partial_secret_tail(redact_text(truncated, [secret]), variants)
			for length in range(4, len(secret) + 1):
				self.assertNotIn(secret[:length], guarded, f"kesme={cut}, ön ek={length}")


# ---------------------------------------------------------------------------
# Birincil savunma — DEĞER-TABANLI REDAKSİYON
# ---------------------------------------------------------------------------


class TestValueBasedRedaction(unittest.TestCase):
	"""Sır DEĞERİ biliniyorsa biçim tahmini gerekmez — her yerde birebir bulunur."""

	def test_secret_found_in_unknown_format(self):
		"""Anahtar adı tanınmayan bir biçimde bile değer yakalanır."""
		body = f"<ns1:Kimlik>{_SECRET}</ns1:Kimlik>"
		self.assertNotIn(_SECRET, redact_text(body, [_SECRET]))

	def test_secret_found_in_url_encoded_form(self):
		encoded = urllib.parse.quote(_SECRET + "/+=", safe="")
		text = f"POST /auth?p={encoded}"
		self.assertNotIn(encoded, redact_text(text, [_SECRET + "/+="]))

	def test_secret_found_in_base64_form(self):
		encoded = base64.b64encode(_SECRET.encode("utf-8")).decode("ascii")
		text = f"Authorization: Basic {encoded}"
		self.assertNotIn(encoded, redact_text(text, [_SECRET]))

	def test_short_values_are_skipped(self):
		"""`TR` gibi kısa değerler her yerde geçer; birebir arama gövdeyi harap eder."""
		text = "ülke TR, il 34, kargo TR-EXPRESS"
		self.assertEqual(redact_text(text, ["TR", "34"]), text)
		self.assertEqual(build_secret_variants(["TR"]), ())

	def test_longest_secret_replaced_first(self):
		"""Kısa sır uzun sırrın alt dizgisiyse, önce uzun olan değiştirilmeli."""
		short = "ABCDEF"
		long_secret = "ABCDEF123456"
		result = redact_text(f"deger={long_secret}", [short, long_secret])
		self.assertEqual(result, f"deger={MASK}")

	def test_replacement_is_case_sensitive(self):
		"""base64/hex sırlarda harf büyüklüğü ANLAMLIDIR; yanlış eşleşme yapılmaz."""
		self.assertIn("supersecretvalue", redact_text("x=supersecretvalue", [_SECRET]))

	def test_min_secret_length_is_enforced(self):
		self.assertEqual(build_secret_variants(["a" * (MIN_SECRET_LENGTH - 1)]), ())
		self.assertTrue(build_secret_variants(["a" * MIN_SECRET_LENGTH]))

	def test_short_numeric_secrets_do_not_destroy_legitimate_codes(self):
		"""4. tur `int`'i sır türü yaptı; bu YENİ bir çakışma açtı (5. tur).

		6 haneli SAYISAL bir kimlik `MIN_SECRET_LENGTH=6` eşiğini karşılıyor ve
		gövdedeki HER geçişini yok ediyordu — TR taşıyıcılarında müşteri/hesap
		kodu tipik olarak sayısaldır ve `tracking_number` ALLOWLIST'te olmasına
		rağmen o da siliniyordu. Yön güvenliydi ama teşhis kaybı gerçekti.
		"""
		payload = '{"tracking_number":"123456","adet":123456,"tutar":"123456"}'

		masked = mask_payload(payload, secret_values=[123456])

		self.assertIn("123456", masked, "Kısa sayısal sır meşru kodları hâlâ yok ediyor")
		self.assertEqual(build_secret_variants([123456]), ())
		self.assertEqual(build_secret_variants(["123456"]), (), "Eşik TÜRE değil BİÇİME bağlı olmalı")

	def test_long_numeric_secrets_are_still_redacted(self):
		"""Eşik yükseldi, kapanmadı: yeterince uzun sayısal sır redakte edilir."""
		secret = "1" * MIN_NUMERIC_SECRET_LENGTH

		self.assertIn(secret, build_secret_variants([int(secret)]))
		self.assertNotIn(secret, redact_text(f"api_key={secret}", [int(secret)]))

	def test_numeric_threshold_counts_digits_not_characters(self):
		"""`123456.78` 9 KARAKTER ama 8 RAKAM — ayraç eşiği sahte doldurmamalı."""
		self.assertEqual(build_secret_variants(["123456.78"]), ())
		self.assertTrue(build_secret_variants(["1234567890.12"]))

	def test_alphanumeric_secrets_keep_the_short_threshold(self):
		"""Sayısal eşik yalnız SAYISAL biçime uygulanır; `ABC123` 6 karakterle geçer."""
		self.assertEqual(build_secret_variants(["ABC123"]), ("ABC123",))

	def test_decimal_secrets_are_converted_without_scientific_notation(self):
		"""`Decimal` bugün ERROR ile DÜŞÜRÜLÜYORDU — o alan için birincil savunma kapalıydı.

		`str(Decimal('1E+13'))` == `'1E+13'` ve bu biçim gövdede ASLA geçmez;
		`format(raw, 'f')` bilimsel gösterimi açar.
		"""
		self.assertIn("10000000000000", build_secret_variants([Decimal("1E+13")]))
		self.assertIn("1234567890.12", build_secret_variants([Decimal("1234567890.12")]))
		self.assertNotIn(
			"1234567890123",
			redact_text("hesap=1234567890123", [Decimal("1234567890123")]),
		)

	def test_decimal_credential_field_is_collected_not_dropped(self):
		"""`collect_secret_values` `Decimal` alanı için `None` döndürüyordu."""
		self.assertEqual(
			collect_secret_values({"api_key": Decimal("1234567890123")}),
			frozenset({"1234567890123"}),
		)

	def test_redaction_applies_through_mask_payload(self):
		masked = mask_payload({"gorunmez_alan": _SECRET}, secret_values=[_SECRET])
		self.assertEqual(masked["gorunmez_alan"], MASK)

	def test_redaction_applies_to_headers(self):
		masked = mask_headers({"X-Trace": f"id-{_SECRET}"}, secret_values=[_SECRET])
		self.assertNotIn(_SECRET, masked["X-Trace"])


# ---------------------------------------------------------------------------
# ReDoS regresyonu
# ---------------------------------------------------------------------------


class TestMaskingRegressionTiming(unittest.TestCase):
	"""Sınırsız açgözlü kalıp 192 KB'lık gövdede 254 sn sürüyordu — geri gelmesin."""

	LIMIT_SECONDS = 5.0

	def _timed(self, payload) -> float:
		import time

		started = time.monotonic()
		mask_payload(payload)
		return time.monotonic() - started

	def test_large_flat_input(self):
		payload = {"blob": "x" * (64 * 1024 * 3), "querystring": "a=1&" * 20_000}
		self.assertLess(self._timed(payload), self.LIMIT_SECONDS, "Maskeleme geri izlemeye düştü")

	def test_pathological_xml_deeply_nested(self):
		self.assertLess(self._timed("<a>" * 2000 + "z" + "</a>" * 2000), self.LIMIT_SECONDS)

	def test_pathological_xml_unclosed_tag(self):
		self.assertLess(self._timed("<Password>" + "q" * 200_000), self.LIMIT_SECONDS)

	def test_pathological_single_huge_token(self):
		self.assertLess(self._timed("z" * 200_000 + '=1<>"'), self.LIMIT_SECONDS)

	def test_pathological_many_unclosed_tags(self):
		"""`dead_tags` memoizasyonu O(k·n) patlamasını hâlâ kesiyor mu?

		Kapanış araması artık SINIRSIZ; memoizasyon olmasaydı 20 bin kapanmamış
		`<Password>` her biri için metnin sonuna kadar tarardı.
		"""
		self.assertLess(self._timed("<Password>" * 20_000), self.LIMIT_SECONDS)

	def test_pathological_unclosed_tag_with_long_tail(self):
		"""Fail-closed tarama (`_next_tag_boundary`) toplamda DOĞRUSAL kalmalı."""
		self.assertLess(self._timed(("<Password>" + "q" * 1_000) * 200), self.LIMIT_SECONDS)

	def test_pathological_non_ascii_token(self):
		"""Anahtar sınıfı Unicode'a genişledi — geri izleme profili değişmemeli."""
		self.assertLess(self._timed("ş" * 200_000 + "=1"), self.LIMIT_SECONDS)

	def test_pathological_unclosed_value_quote(self):
		"""10. tur: kapanmamış tırnak artık metnin SONUNA kadar maskeleniyor.

		Eski `dead_quotes` kümesi bir O(n²) korumasıydı ve kaldırıldı; yerine
		gelen fail-closed dal `pos`u metnin sonuna atar, yani metin başına EN
		FAZLA BİR kapanışsız-tırnak taraması yapılır. Bu vektörler o iddianın
		ölçümüdür — 500 KB tek değer ve 5000 ayrı kapanmamış anahtar.
		"""
		cases = {
			"single_huge_unclosed_dq": 'sifre="' + "A" * 500_000,
			"single_huge_unclosed_sq": "sifre='" + "A" * 500_000,
			"many_unclosed_quotes": "".join(f'sifre{i}="' for i in range(5_000)) + "A" * 50_000,
			"unclosed_bracket_long_tail": "auth=(" + "A" * 500_000,
			"quote_soup_pairs": 'sifre="x' * 50_000,
		}
		for label, payload in cases.items():
			with self.subTest(case=label):
				self.assertLess(self._timed(payload), self.LIMIT_SECONDS)

	def test_pathological_markup_regions_stay_linear(self):
		"""MARKUP-FARKINDA tarama (5. tur) O(n)'i BOZMAMALI.

		Bölge atlama iki imleçle (`hit`, `region`) yapılıyor ve ikisi de yalnız
		GERİDE KALDIKLARINDA yenileniyor; arama pencereleri ayrık olduğu için
		toplam maliyet doğrusal kalmalı. Bölge başına "metnin sonuna kadar tara"
		davranışı O(k·n) üretirdi.
		"""
		cases = {
			"many_comments": "<Token>" + "<!-- x -->" * 20_000,
			"many_cdata": "<Token>" + "<![CDATA[x]]>" * 20_000,
			"many_pi": "<Token>" + "<?p x?>" * 20_000,
			"fake_closes_in_comments": "<Token>" + "<!-- </Token> -->" * 20_000,
			"unclosed_comment_long_tail": "<Token><!--" + "q" * 200_000,
			"unclosed_cdata_long_tail": "<Token><![CDATA[" + "q" * 200_000,
			"region_openers_only": "<Token>" + "<!--" * 50_000,
			"unclosed_attribute_quotes": "<Token>" + '<a b="' * 50_000,
			"quote_soup_in_tags": "<Token>" + '<a b="x">' * 20_000,
			"nested_regions": "<Token>" + "<!-- <![CDATA[ <?p ?> ]]> -->" * 10_000,
			"comment_then_secret": ("<Sifre><!-- </Root> -->" + "q" * 1_000) * 200,
			# Kapanış araması artık her etiketi `_tag_end` ile geçiyor: sahte
			# kapanış taşıyan 20 bin öznitelik değeri hâlâ doğrusal kalmalı.
			"attr_gt_soup": "<Sifre>" + '<Child a="></Sifre>">' * 20_000,
			"quote_only_soup": "<Token>" + '"' * 200_000,
		}
		for label, payload in cases.items():
			with self.subTest(case=label):
				self.assertLess(self._timed(payload), self.LIMIT_SECONDS)


# ---------------------------------------------------------------------------
# XML tarayıcısı — fail-open regresyonları (3. tur güvenlik denetimi)
# ---------------------------------------------------------------------------


class TestXmlScannerFailClosed(unittest.TestCase):
	"""İndeks tabanlı XML tarayıcısında ölçülmüş İKİ fail-open."""

	def test_earlier_unclosed_tag_does_not_unmask_a_later_one(self):
		"""`dead_tags` memoizasyonu 64 KiB PENCEREYLE birlikte SIR SIZDIRIYORDU.

		Docstring "aynı etiket için sonraki aramalar da kesin başarısız olacak"
		diyordu; bu ancak arama SINIRSIZ olsaydı doğru olurdu. `_find_close_tag`
		`min(len, start + 64 KiB)` penceresi kullanıyordu, yani ileri konumdaki
		aynı etiket ilk aramanın HİÇ GÖRMEDİĞİ metni tarayacaktı.

		Girdi saldırgan kontrolünde olabilir (taşıyıcı yanıtı, `inbound`
		webhook gövdesi) ve tam da denylist'in TEK savunma olduğu senaryo.
		"""
		payload = "<Password>" + "A" * 70_000 + "<Password>REALSECRET123</Password>"

		masked = mask_payload(payload)

		self.assertNotIn("REALSECRET123", masked)

	def test_closing_tag_search_is_not_window_limited(self):
		"""Tek bir elemanın gövdesi 64 KiB'ı aşsa da kapanış BULUNUR."""
		payload = "<Sifre>" + "A" * 70_000 + "REALSECRET123</Sifre>"

		masked = mask_payload(payload)

		self.assertNotIn("REALSECRET123", masked)
		self.assertEqual(masked, f"<Sifre>{MASK}</Sifre>")

	def test_missing_closing_tag_masks_instead_of_passing_through(self):
		"""Kapanış HİÇ yoksa tarayıcı geri kalanı HAM yazıyordu.

		`mask_payload('<Sifre><![CDATA[SESSIONABC999')` GİRDİYLE AYNI dönüyordu.
		Kırpılmış/yarım bir taşıyıcı SOAP yanıtı tam bu sınıfta. "Maskeleyemedim"
		asla "ham yaz" anlamına gelmemeli.

		5. TUR DEĞİŞİKLİĞİ: çıktı artık `'<Sifre>***'` değil FAIL-SAFE ÖZET.
		Kapanmamış bir CDATA bölgesi, tarayıcının "burası eleman içeriği" modelini
		geçersiz kılar (bölgenin içi mi dışı mı bilinmiyor); markup-farkında
		tarayıcı bu durumda sınırı ÇÖZÜLEMEDİ sayar. İki çıktı da sırrı tutuyor,
		yenisi hangi bilginin kaybolduğunu AÇIKÇA söylüyor.
		"""
		masked = mask_payload("<Sifre><![CDATA[SESSIONABC999")

		self.assertNotIn("SESSIONABC999", masked)
		self.assertTrue(masked.startswith(XML_BOUNDARY_UNRESOLVED.split("{", 1)[0]), masked)

	def test_fail_closed_masking_stops_at_the_ancestor_close(self):
		"""Kapanmamış tek bir etiket BÜTÜN gövdeyi silmemeli.

		Aksi hâlde `inbound` webhook gövdesine `<Password>` ekleyen bir saldırgan
		denetim izini tamamen bastırabilirdi — modülün başka yerde açıkça
		kapattığı saldırı. Sınır ATA KAPANIŞINDA durur: `</Root>`'tan sonrası
		ve `<Password>`'dan öncesi teşhis için korunur.

		4. TUR DEĞİŞİKLİĞİ: sınır eskiden "bir sonraki GERÇEK etiket"ti ve
		`<Password>gizli<Takip>TR-123</Takip>` girdisinde `TR-123` korunuyordu.
		O kural, içerik BİR ÇOCUK ETİKETLE BAŞLADIĞINDA hiçbir şey maskelemiyor
		ve sırrı HAM bırakıyordu (bkz. `TestXmlNestedBoundary`). Kapanmamış bir
		`<Password>`'ın çocuğu XML semantiğinde onun İÇERİĞİDİR; maskelenmesi
		doğru olandır.
		"""
		masked = mask_payload("<Root><Takip>TR-123</Takip><Password>gizli</Root><Sonraki>OK</Sonraki>")

		self.assertNotIn("gizli", masked)
		self.assertIn("TR-123", masked, "Hassas etiketten ÖNCEKİ teşhis verisi kayboldu")
		self.assertIn("OK", masked, "Ata kapanışından SONRAKİ denetim izi bastırıldı")
		self.assertEqual(masked, f"<Root><Takip>TR-123</Takip><Password>{MASK}</Root><Sonraki>OK</Sonraki>")

	def test_processing_instructions_are_not_treated_as_tags(self):
		"""`<?xml`, `<!--`, `<![CDATA[` etiket SAYILMAZ; maskeleme onları geçer."""
		masked = mask_payload('<?xml version="1.0"?><!-- not --><Sifre>ABC12345</Sifre>')

		self.assertNotIn("ABC12345", masked)
		self.assertIn("<?xml", masked)


# ---------------------------------------------------------------------------
# XML tarayıcısı — İÇ İÇE SINIR + fail-safe özet (4. tur güvenlik denetimi)
# ---------------------------------------------------------------------------


#: Sınırı çözülemeyen gövdenin özet ön eki — biçim `masking` sözleşmesinden gelir.
_SUMMARY_PREFIX = XML_BOUNDARY_UNRESOLVED.split("{", 1)[0]

#: Bu sınıfta aranan sır — hiçbir çıktıda görünmemeli.
_XML_SECRET = "SESSIONTOKEN_ABC999"


def assert_fail_closed(case: unittest.TestCase, payload: str, secret: str = _XML_SECRET) -> str:
	"""Çözülemeyen bir yapının ARDINDAN hiçbir şey ham kalmadığını doğrular (9. tur).

	8. tura kadar bu iddia "çıktı ÖZET ile başlar"dı. 9. tur fail-safe'i
	YERELLEŞTİRDİ: çözülemeyen `<`ten SONRASI `***` olur, ÖNCESİ (zaten
	anlaşılmış ve maskelenmiş kısım) KORUNUR; özet yalnız korunacak ön ek
	YOKKEN (`lt == 0`, hiç maskelenmiş parça yok) üretilir. İki çıkışın ORTAK
	güvenlik iddiası değişmedi ve tek yerde toplanmıştır:

		* sır çıktıda YOK,
		* çıktı ya ÖZETTİR ya da `***` ile BİTER (yani kuyrukta ham metin yok).

	Ölçülmüş gerekçe `masking._fail_closed` docstring'inde: 64 KiB kırpmasının
	301 kesim noktasında öznitelikli gövdenin 130'u, CDATA'lı gövdenin 154'ü TÜM
	denetim izini siliyordu.
	"""
	masked = mask_payload(payload)
	case.assertNotIn(secret, masked, "HAM jeton kaldı")
	if not masked.startswith(_SUMMARY_PREFIX):
		case.assertTrue(masked.endswith(MASK), masked)
	return masked


class TestXmlNestedBoundary(unittest.TestCase):
	"""Fail-closed sınırı İÇ İÇE yapıda tamamen ATLANIYORDU (ölçüldü).

	3. turda eklenen sınır "bir sonraki GERÇEK etiket"ti. İçerik bir ÇOCUK
	ETİKETLE başladığında sınır hemen `gt + 1`'e düşüyor, maskelenecek aralık
	BOŞ kalıyor ve tarayıcı hiçbir şey yapmadan devam ediyordu:

		'<Sifre><Deger>SESSIONTOKEN_ABC999</Deger>'  → GİRDİYLE AYNI
		'<soap:Body><LoginResult><Sifre><Value>…'    → GİRDİYLE AYNI
		'<Sifre>\\n<Deger>SESSIONTOKEN_ABC999…'       → '<Sifre>***<Deger>…' (YANILTICI)

	İkinci satır TR kargo SOAP zarfının KANONİK biçimi. Üçüncüsü modülün
	`_scan_value` docstring'inde "hiç maskelememekten daha kötü" diye
	YASAKLADIĞI sınıf. Bu yol DEĞER-TABANLI savunmayla kapatılamaz: sızan şey
	taşıyıcının YANITINDA dönen oturum jetonudur, `secret_values` içinde YOKTUR.
	"""

	#: Sınırın atlandığı ölçülmüş girdiler.
	NESTED_CASES = (
		f"<Sifre><Deger>{_XML_SECRET}</Deger>",
		f"<Sifre>\n<Deger>{_XML_SECRET}</Deger>",
		f'<Sifre><Deger v="{_XML_SECRET}"/>',
		f"<Response><Token><Data>{_XML_SECRET}</Data>",
		f"<soap:Body><LoginResult><Sifre><Value>{_XML_SECRET}</Value>",
		# 64 KiB kırpmasının ORTADA kestiği zarf — kırpma maskelemeden ÖNCE.
		f"<soap:Body><LoginResult><Sifre><Value>{_XML_SECRET}",
	)

	def test_nested_child_never_leaves_the_secret_raw(self):
		for payload in self.NESTED_CASES:
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, mask_payload(payload))

	def test_nested_child_is_not_partially_masked(self):
		"""`'<Sifre>***<Deger>SECRET</Deger>'` — maskelenmiş GÖRÜNEN çıktı yasak."""
		for payload in self.NESTED_CASES:
			masked = mask_payload(payload)
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, masked)

	def test_wrapped_in_dict_and_bytes_behaves_identically(self):
		"""Aynı içerik dict/bytes olarak geldiğinde de sızmamalı (tek küme kuralı)."""
		for payload in self.NESTED_CASES:
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, str(mask_payload({"body": payload})))
				self.assertNotIn(_XML_SECRET, str(mask_payload(payload.encode("utf-8"))))
				self.assertNotIn(_XML_SECRET, str(mask_payload([{"a": [payload]}])))

	def test_balanced_children_are_swallowed_not_summarized(self):
		"""Çocuk alt ağaç KAPANMIŞSA sınır metin sonudur; özete inilmez."""
		masked = mask_payload(f"<Sifre><Deger>{_XML_SECRET}</Deger>")

		self.assertEqual(masked, f"<Sifre>{MASK}")

	def test_truncated_body_falls_back_to_a_local_mask(self):
		"""Gövde bir elemanın ORTASINDAN kesilmişse tarayıcının modeli güvenilmez.

		`log.py::MAX_BODY_BYTES` (64 KiB) kırpması maskelemeden ÖNCE yapıldığı
		için gerçek taşıyıcı yanıtları rutin olarak bu hâlde gelir.

		9. TURDA DEĞİŞEN (test GÜNCELLENDİ, güvenlik iddiası AYNI): eylem artık
		gövdenin TAMAMINI silen bir özet değil, çözülemeyen noktadan SONRASINI
		silen YEREL bir maske. Buradaki ön ek (`<soap:Body><LoginResult>`)
		operatörün hangi çağrının kesildiğini görmesini sağlar ve sır yine
		çıktıda YOKTUR — ölçülmüş gerekçe `masking._fail_closed` docstring'inde.
		"""
		payload = f"<soap:Body><LoginResult><Sifre><Value>{_XML_SECRET}"

		self.assertEqual(assert_fail_closed(self, payload), f"<soap:Body><LoginResult>{MASK}")

	def test_summary_keeps_byte_and_field_counts(self):
		"""Özet opak bir `***` DEĞİL — "gövde buradaydı, şu kadardı" der.

		9. TURDA DARALAN KAPSAM: özet artık YALNIZ korunacak ön ek yokken
		üretilir. Bu, `resolved`ın özet yolunda YAPISAL OLARAK 0 olması demektir
		(sayaç ancak `parts`'a bir maske yazılırken artar, `parts` doluysa ön ek
		vardır ve yerelleştirme seçilir) — alan sayısı bu yüzden tamamen
		`_count_sensitive_tags`ten gelir. Testin asıl iddiası DEĞİŞMEDİ: özet
		bayt ve alan sayısını TAŞIR, opak bir `***` değildir.
		"""
		payload = f"<Sifre><Deger>{_XML_SECRET}</Deger><Sifre><X>"
		expected = XML_BOUNDARY_UNRESOLVED.format(len(payload.encode("utf-8")), 2)

		self.assertEqual(mask_payload(payload), expected)

	def test_summary_is_reserved_for_bodies_without_a_preservable_prefix(self):
		"""9. TUR: özet ↔ yerelleştirme AYRIMININ kilidi.

		ÖLÇÜLMÜŞ GEREKÇE (`masking._fail_closed`): `<!DOCTYPE html>` ile başlayan
		bir taşıyıcı/vekil HTML hata sayfasında çözülemeyen `<` metnin TA
		BAŞINDADIR; yerelleştirme orada yalnız `'***'` üretir ve bayt sayısı da
		kaybolur — özetten BİLGİ OLARAK DAHA AZ. Ön ek varsa tersi geçerlidir.
		"""
		no_prefix = "<!DOCTYPE html><html><body>500 Internal Server Error</body></html>"
		self.assertTrue(mask_payload(no_prefix).startswith(_SUMMARY_PREFIX))

		with_prefix = "<Root><Takip>TR-123456</Takip><Durum>Teslim</Durum></Root><!"
		self.assertEqual(
			mask_payload(with_prefix),
			f"<Root><Takip>TR-123456</Takip><Durum>Teslim</Durum></Root>{MASK}",
		)

	def test_closed_wellformed_bodies_are_never_summarized(self):
		"""REGRESYON: teşhis değeri korunmalı — kapalı gövde özete inmemeli."""
		cases = (
			f"<Response><Token><Data>{_XML_SECRET}</Data></Token></Response>",
			f"<Sifre>{_XML_SECRET}</Sifre>",
			f'<?xml version="1.0"?><Root><Takip>TR-9</Takip><Sifre>{_XML_SECRET}</Sifre></Root>',
			"<Root><Takip>TR-9</Takip></Root>",
		)
		for payload in cases:
			masked = mask_payload(payload)
			with self.subTest(payload=payload):
				self.assertNotIn(_SUMMARY_PREFIX, masked, "İyi biçimli gövde özete indirildi")
				self.assertNotIn(_XML_SECRET, masked)
		self.assertEqual(
			mask_payload(cases[0]),
			f"<Response><Token>{MASK}</Token></Response>",
		)

	def test_injected_password_cannot_erase_the_whole_audit_trail(self):
		"""`direction='inbound'` gövdesine `<Password>` ekleyen saldırgan senaryosu."""
		masked = mask_payload("<Bildirim><Durum>TESLIM</Durum><Password>x</Bildirim>")

		self.assertIn("TESLIM", masked)
		self.assertNotIn(_SUMMARY_PREFIX, masked)


class TestXmlMarkupRegions(unittest.TestCase):
	"""XML tarayıcısı MARKUP-KÖRDÜ — dört turda dördüncü kez kenar durumu (5. tur).

	`_find_close_tag` kapanışı ham `str.find` ile arıyordu; yorum (`<!-- -->`),
	CDATA (`<![CDATA[ ]]>`) ve işlem talimatı (`<?p ?>`) İÇİNDEKİ sahte kapanışı
	GERÇEK sanıyordu. Üç girdi de ElementTree ile ayrıştırılabilir ve konformant
	bir ayrıştırıcıya göre jeton `<Token>` elemanının İÇİNDEDİR.

	4. turun fail-safe'i bu yolu KAPSAMIYORDU: özet yalnız "kapanış BULUNAMADI"
	dalında tetikleniyor, tarayıcı ise "sınırı buldum" sanıyordu — bu yüzden
	düzeltme İKİ KATMANLI: (a) markup-farkında ilerleme, (b) kapanmamış bölge →
	özet. Kabul kuralı: ya TAM maskeleme ya ÖZET, ASLA ham jeton.
	"""

	#: Sahte kapanış etiketini bir markup bölgesinin İÇİNDE taşıyan gövdeler.
	FAKE_CLOSE_CASES = (
		f"<R><Token><!-- </Token> -->{_XML_SECRET}</Token></R>",
		f"<R><Token><![CDATA[</Token>]]>{_XML_SECRET}</Token></R>",
		f"<R><Token><?p </Token> ?>{_XML_SECRET}</Token></R>",
		# Yorum içindeki ATA kapanışı derinliği -1 yapıp sınırı ERKEN kapatıyordu.
		f"<Sifre>x<!-- </Root> -->{_XML_SECRET}",
		f"<Sifre>x<![CDATA[</Root>]]>{_XML_SECRET}",
	)

	#: Etiket sonu `>` öznitelik DEĞERİNİN içindeydi (çift ve tek tırnak aynı).
	ATTRIBUTE_GT_CASES = (
		f'<Sifre>x<Child a="/>"></Child>{_XML_SECRET}',
		f"<Sifre>x<Child a='/>'></Child>{_XML_SECRET}",
		f'<Sifre>x<Child a="></Sifre>">{_XML_SECRET}</Child>',
	)

	#: Açılıp KAPANMAYAN markup bölgesi — 64 KiB kırpmasında RUTİN.
	UNCLOSED_REGION_CASES = (
		f"<Sifre><![CDATA[{_XML_SECRET}",
		f"<Sifre><!-- {_XML_SECRET}",
		f"<Sifre><?p {_XML_SECRET}",
		f"<Root><!-- <Sifre>{_XML_SECRET}",
	)

	def _assert_masked_or_summarized(self, payload: str) -> str:
		masked = mask_payload(payload)
		self.assertNotIn(_XML_SECRET, masked, "HAM jeton kaldı")
		return masked

	def test_fake_closing_tag_inside_markup_never_leaks(self):
		for payload in self.FAKE_CLOSE_CASES:
			with self.subTest(payload=payload):
				self._assert_masked_or_summarized(payload)

	def test_fake_closing_tag_produces_full_masking_not_a_summary(self):
		"""Bu vakalarda sınır GERÇEKTEN bilinebilir — teşhis değeri korunmalı."""
		self.assertEqual(mask_payload(self.FAKE_CLOSE_CASES[0]), f"<R><Token>{MASK}</Token></R>")
		self.assertEqual(mask_payload(self.FAKE_CLOSE_CASES[1]), f"<R><Token>{MASK}</Token></R>")
		self.assertEqual(mask_payload(self.FAKE_CLOSE_CASES[2]), f"<R><Token>{MASK}</Token></R>")
		self.assertEqual(mask_payload(self.FAKE_CLOSE_CASES[3]), f"<Sifre>{MASK}")

	def test_attribute_value_gt_is_not_a_tag_end(self):
		"""`text.find('>')` öznitelik değerindeki `>`ı etiket sonu sanıyordu.

		Self-closing kararı da (`text[gt - 1] == '/'`) o YANLIŞ konuma bakıyor ve
		sınırı erken kapatıyordu — ölçülen sızıntı:
		`'<Sifre>x<Child a="/>"></Child>SESSIONTOKEN_ABC999'`
		→ `'<Sifre>***</Child>SESSIONTOKEN_ABC999'`.
		"""
		for payload in self.ATTRIBUTE_GT_CASES:
			with self.subTest(payload=payload):
				self._assert_masked_or_summarized(payload)

	def test_unclosed_markup_region_fails_closed(self):
		"""Bölge kapanmadıysa "burası içerik" iddiası kurulamaz → fail-safe.

		9. TURDA DEĞİŞEN: eylem "gövdenin tamamı özete" değil "çözülemeyen
		noktadan SONRASI `***`". Son vaka (`<Root><!-- <Sifre>…`) bunu gösterir:
		kök eleman ön ek olarak KORUNUR, jeton yine gitmiştir.
		"""
		for payload in self.UNCLOSED_REGION_CASES:
			with self.subTest(payload=payload):
				assert_fail_closed(self, payload)
		self.assertEqual(mask_payload(self.UNCLOSED_REGION_CASES[-1]), f"<Root>{MASK}")

	def test_unclosed_attribute_quote_falls_back_to_a_summary(self):
		"""Ham `break` geri kalan gövdeyi OLDUĞU GİBİ yazıyordu (ölçüldü).

		Burada özet KORUNUR: çözülemeyen `<a b="` metnin ta başındadır, yani
		korunacak ön ek yoktur (9. tur ayrımı).
		"""
		masked = assert_fail_closed(self, f'<a b="><Sifre>{_XML_SECRET}')

		self.assertTrue(masked.startswith(_SUMMARY_PREFIX), masked)

	def test_sensitive_tag_inside_a_closed_region_is_character_data(self):
		"""Yorum/CDATA İÇİNDEKİ `<Sifre>` bir eleman değildir; sayıma da girmez."""
		masked = mask_payload(
			f"<Root><!-- <Sifre>x --><Takip>TR-9</Takip><Sifre>{_XML_SECRET}</Sifre></Root>"
		)

		self.assertNotIn(_XML_SECRET, masked)
		self.assertNotIn(_SUMMARY_PREFIX, masked)
		self.assertIn("TR-9", masked)

	def test_closed_regions_do_not_push_wellformed_bodies_into_a_summary(self):
		"""REGRESYON: markup-farkındalık teşhis değerini DÜŞÜRMEMELİ."""
		cases = (
			f'<?xml version="1.0"?><Root><Sifre>{_XML_SECRET}</Sifre></Root>',
			f"<Root><!-- yorum --><Sifre>{_XML_SECRET}</Sifre></Root>",
			f"<Root><Sifre><![CDATA[{_XML_SECRET}]]></Sifre><Takip>TR-9</Takip></Root>",
			f'<Root><Meta a="1"/><Sifre a="x">{_XML_SECRET}</Sifre></Root>',
			f"<Root><?php echo 1; ?><Sifre>{_XML_SECRET}</Sifre></Root>",
		)
		for payload in cases:
			masked = mask_payload(payload)
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, masked)
				self.assertNotIn(_SUMMARY_PREFIX, masked, "İyi biçimli gövde özete indirildi")

	def test_bytes_and_dict_wrappers_behave_identically(self):
		"""Tek küme kuralı: aynı içerik hangi kapta gelirse gelsin sızmamalı."""
		for payload in self.FAKE_CLOSE_CASES + self.ATTRIBUTE_GT_CASES:
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, str(mask_payload({"body": payload})))
				self.assertNotIn(_XML_SECRET, str(mask_payload(payload.encode("utf-8"))))


class TestXmlMarkupDeclarations(unittest.TestCase):
	"""`<!` BİLDİRİM AİLESİ TAMAMEN GÖRÜNMEZDİ (6. tur — sınıfın ALTINCI kırılması).

	`_MARKUP_REGIONS` yalnız `<!--`, `<![CDATA[` ve `<?` biliyordu. `<!` ile
	başlayan DİĞER HER ŞEY "markup değil" sayılıyor, `_TAG_NAME_RE` `!` ile
	eşleşmediği için üç tarayıcı da `at = lt + 1` ile bildirimin İÇİNE giriyor ve
	orada duran SAHTE kapanışı GERÇEK sanıyordu. `_find_close_tag` POZİTİF sınır
	döndürdüğü için fail-safe özet HİÇ tetiklenmiyor, kapanıştan sonraki GERÇEK
	değer HAM geçiyordu (ölçüldü):

		'<Sifre>x<!ENTITY e "</Sifre>">TOKEN</Sifre>' → '<Sifre>***</Sifre>">TOKEN…'
		'<Sifre><!DOCTYPE d [</Sifre>]>TOKEN</Sifre>' → '<Sifre>***</Sifre>]>TOKEN…'

	KURAL TERSİNE ÇEVRİLDİ: tarayıcı artık "tanıdığım yapıları atla, GERİSİNİ
	İŞLE" demiyor; TANIMADIĞI hiçbir yapıyı işlemiyor ve güvenli yöne (ÖZET)
	gidiyor. Bu bildirimler TR kargo SOAP yanıtlarının GÖVDESİNDE meşru olarak
	bulunmaz, yani fazladan özetin operasyonel maliyeti sıfıra yakındır.
	"""

	#: Denetimin ölçtüğü 8 sızıntı vektörü + iki çıplak ön ek.
	DECLARATION_CASES = (
		f'<Sifre>x<!ENTITY e "</Sifre>">{_XML_SECRET}</Sifre>',
		f"<Sifre><!DOCTYPE d [</Sifre>]>{_XML_SECRET}</Sifre>",
		f'<Sifre>x<!ATTLIST a b "</Sifre>">{_XML_SECRET}</Sifre>',
		f"<Sifre>x<!ELEMENT e (</Sifre>)>{_XML_SECRET}</Sifre>",
		f'<Sifre>x<!NOTATION n SYSTEM "</Sifre>">{_XML_SECRET}</Sifre>',
		f"<Sifre>x<![IGNORE[</Sifre>]]>{_XML_SECRET}</Sifre>",
		f"<Sifre>x<![INCLUDE[</Sifre>]]>{_XML_SECRET}</Sifre>",
		f"<Sifre>x<!q </Sifre> >{_XML_SECRET}</Sifre>",
		f"<Sifre>x<!</Sifre>{_XML_SECRET}</Sifre>",
		f"<Sifre>x<![</Sifre>{_XML_SECRET}</Sifre>",
	)

	def test_declaration_family_never_leaves_the_token_raw(self):
		for payload in self.DECLARATION_CASES:
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, mask_payload(payload))

	def test_declaration_family_falls_back_to_a_summary(self):
		""" "Yapıyı anlamıyorum" → ÖZET. Kısmi/yanıltıcı maske de kabul edilmez."""
		for payload in self.DECLARATION_CASES:
			with self.subTest(payload=payload):
				self.assertTrue(mask_payload(payload).startswith(_SUMMARY_PREFIX), payload)

	def test_declaration_in_wrappers_behaves_identically(self):
		"""Tek küme kuralı: dict/bytes/list kabında da sızmamalı."""
		for payload in self.DECLARATION_CASES:
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, str(mask_payload({"body": payload})))
				self.assertNotIn(_XML_SECRET, str(mask_payload(payload.encode("utf-8"))))
				self.assertNotIn(_XML_SECRET, str(mask_payload([{"a": [payload]}])))

	def test_known_regions_are_still_skipped_not_summarized(self):
		"""REGRESYON: `<!--`, `<![CDATA[`, `<?` TANINAN yapılar — özete İNMEMELİ."""
		cases = (
			f"<R><Token><!-- </Token> -->{_XML_SECRET}</Token></R>",
			f"<R><Token><![CDATA[</Token>]]>{_XML_SECRET}</Token></R>",
			f"<R><Token><?p </Token> ?>{_XML_SECRET}</Token></R>",
			f'<?xml version="1.0"?><Root><Sifre>{_XML_SECRET}</Sifre></Root>',
			f"<Root><!-- yorum --><Sifre>{_XML_SECRET}</Sifre></Root>",
			f"<Root><Sifre><![CDATA[{_XML_SECRET}]]></Sifre><Takip>TR-9</Takip></Root>",
		)
		for payload in cases:
			masked = mask_payload(payload)
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, masked)
				self.assertNotIn(_SUMMARY_PREFIX, masked, "TANINAN yapı özete indirildi")

	def test_declaration_scan_stays_linear(self):
		"""Bildirim ailesi ReDoS bütçesini bozmamalı (tek `startswith`, geri izleme yok)."""
		cases = {
			"many_doctype": "<Token>" + "<!DOCTYPE x>" * 20_000,
			"many_entity": "<Token>" + '<!ENTITY e "x">' * 20_000,
			"bang_openers_only": "<Token>" + "<!" * 100_000,
			"bang_bracket_openers": "<Token>" + "<![" * 60_000,
			"doctype_long_tail": "<Token><!DOCTYPE d [" + "q" * 200_000,
			"attlist_soup": "<Sifre>" + '<!ATTLIST a b "</Sifre>">' * 20_000,
		}
		for label, payload in cases.items():
			started = time.monotonic()
			mask_payload(payload)
			with self.subTest(case=label):
				self.assertLess(time.monotonic() - started, 0.5)


class TestXmlStrayClosingTags(unittest.TestCase):
	"""SINIR DERİNLİĞİ AD-KÖRDÜ (6. tur) — başıboş kapanış maskeyi ERKEN kapatıyordu.

	`_ancestor_boundary` derinlik 0'da gördüğü HERHANGİ bir kapanışı "ATA
	kapanışı" sayıyordu. Ölçülen sızıntı:

		'<R><Sifre></Yanlis>SECRET</R>' → '<R><Sifre>***</Yanlis>SECRET</R>'

	`</Yanlis>` ne `<Sifre>`'nin kapanışıdır ne de bir ata; hoşgörülü bir
	ayrıştırıcı onu YOK SAYAR ve jetonu `<Sifre>`'nin İÇİNDE görür. Denetim
	fuzz'ı bu TEK kök nedenden 2.534 varyant üretti.

	Sınır artık ATA ADINI DOĞRULAR: eşleşmeyen kapanış yok sayılır, en kötü
	ihtimalle maske metnin sonuna kadar uzar (belgelenmiş güvenli yön).
	"""

	STRAY = "SECRET_XYZ12345"

	def test_stray_closing_tag_does_not_end_the_mask(self):
		self.assertEqual(mask_payload(f"<R><Sifre></Yanlis>{self.STRAY}</R>"), f"<R><Sifre>{MASK}</R>")

	def test_stray_closing_tag_without_ancestor_close(self):
		self.assertEqual(mask_payload(f"<R><Sifre></Yanlis>{self.STRAY}"), f"<R><Sifre>{MASK}")

	def test_multiple_stray_closings_stay_masked(self):
		masked = mask_payload(f"<R><Sifre></A></B></C>{self.STRAY}</R>")

		self.assertNotIn(self.STRAY, masked)
		self.assertEqual(masked, f"<R><Sifre>{MASK}</R>")

	def test_real_ancestor_close_still_ends_the_mask(self):
		"""REGRESYON: kapanmamış `<Password>` bütün denetim izini SİLEMEZ."""
		masked = mask_payload("<Root><Takip>TR-123</Takip><Password>gizli</Root><Sonraki>OK</Sonraki>")

		self.assertEqual(masked, f"<Root><Takip>TR-123</Takip><Password>{MASK}</Root><Sonraki>OK</Sonraki>")

	def test_stray_closings_stay_linear(self):
		"""Yığın eşleşmesi O(1) üyelik + amortize O(n) pop — 50 bin başıboş kapanış."""
		started = time.monotonic()
		mask_payload("<R><Sifre>" + "</Yanlis>" * 50_000)

		self.assertLess(time.monotonic() - started, 0.5)


class TestXmlColonTagNames(unittest.TestCase):
	"""XML 1.0 `NameStartChar` `:`i AÇIKÇA içerir; `<:Sifre>` etiket SAYILMIYORDU.

	`ns:Sifre` zaten çalışıyordu (orada `:` ad ORTASINDA). Ad BAŞINDAKİ `:`
	`[^\\W\\d]` sınıfına takılmıyordu ve `'<R><:Sifre>TOKEN</:Sifre></R>'`
	DEĞİŞMEDEN geçiyordu (ölçüldü).

	RAKAM KASTEN DIŞARIDA: XML'de ad rakamla başlayamaz; `<2Sifre>` geçersiz
	XML'dir ve etiket SAYILMAMASI bilinçli kabul edilmiştir (sınıfa rakam
	girerse `<!`/`<?` ayrımı da bulanır).
	"""

	def test_leading_colon_is_a_valid_name_start(self):
		self.assertEqual(
			mask_payload(f"<R><:Sifre>{_XML_SECRET}</:Sifre></R>"), f"<R><:Sifre>{MASK}</:Sifre></R>"
		)

	def test_realistic_spellings_still_masked(self):
		"""REGRESYON: gerçekçi yazımların tamamı korunmalı."""
		for tag in ("ns:Sifre", "a:b:Sifre", "Sifre-2", "_Sifre", "ŞİFRE", "soap:Password"):
			with self.subTest(tag=tag):
				masked = mask_payload(f"<R><{tag}>{_XML_SECRET}</{tag}></R>")
				self.assertNotIn(_XML_SECRET, masked)

	def test_digit_leading_name_is_not_a_tag(self):
		"""Rakamla başlayan ad etiket SAYILMAZ — ve 7. turdan sonra FAIL-CLOSED.

		6. tura kadar bu girdi HAM geçiyordu ("etiket değil, karakter verisi").
		7. turda ölçüldü ki İKİNCİL katman (`_mask_delimited_pairs`) da onu
		yakalamıyor: gövdede `=`/`:` ayracı yok, `_PAIR_KEY_RE` hiç eşleşmiyor.
		Yani koruma YALNIZ değer-tabanlı birincil katmandan geliyordu.

		9. TURDA DEĞİŞEN yalnız EYLEMİN KAPSAMI: gövdenin tamamı özete inmek
		yerine çözülemeyen `<2Sifre`ten SONRASI `***` olur, kök eleman ön ek
		olarak korunur. Değer yine ham GEÇMEZ; bu hâlâ bir maskeleme değil
		TEŞHİS KAYBIDIR ve sınıfın gerçek çözümü çağıranın `secret_values`
		geçmesidir.
		"""
		masked = assert_fail_closed(self, "<R><2Sifre>ABC12345</2Sifre></R>", secret="ABC12345")

		self.assertEqual(masked, f"<R>{MASK}")


class TestXmlSameNameDescendant(unittest.TestCase):
	"""KAPANIŞ EŞLEŞTİRME KATMANI DERİNLİK SAYMIYORDU (7. tur — ölçülmüş sızıntı).

	Altı tur boyunca yalnız yapı TANIMA katmanı (`_markup_region_end`, `_tag_end`)
	sertleştirildi; kapanış EŞLEŞTİRME katmanı HİÇ SINANMADI. `_find_close_tag`
	`str.startswith(needle)` ile İLK eşleşen kapanışı kabul ediyor, AYNI ADLI bir
	TORUN açılışını sıradan etiket gibi atlıyordu:

		'<LoginResponse><Kod><Kod>01</Kod>SESSIONTOKEN_ABC999</Kod></LoginResponse>'
			→ '<LoginResponse><Kod>***</Kod>SESSIONTOKEN_ABC999</Kod></LoginResponse>'
		'<R><Sifre>a<Deger><Sifre>b</Sifre></Deger>SESSIONTOKEN_ABC999</Sifre></R>'
			→ '<R><Sifre>***</Sifre></Deger>SESSIONTOKEN_ABC999</Sifre></R>'

	EN AĞIR YANI: girdi İYİ BİÇİMLİ (ElementTree ile doğrulandı), bölge
	çözülüyor, `_tag_end` belirsizlik bildirmiyor ve `_find_close_tag` POZİTİF
	sınır döndürüyor — `XML_BOUNDARY_UNRESOLVED` fail-safe'i HİÇ tetiklenmiyor.
	"Ya doğru işle ya özete in" ilkesinin ÜÇÜNCÜ, belgelenmemiş çıkışıydı:
	"yanlış anladım ama anladığımı sandım".

	Tehdit modeli modülün kendi gerekçesi: taşıyıcının YANITINDA dönen oturum
	jetonu `secret_values` içinde YOKTUR, yani birincil katman bu vakada tanım
	gereği kapalıdır ve kırılan katman TEK savunmadır.

	Ölçüm: `DEFAULT_SENSITIVE_KEYS`'teki 63 adın 63'ünde ve torun derinliği
	1/2/3'ün üçünde de ham sızıntı (189/189); aynı adlı torunu OLMAYAN 320
	negatif kontrolde 0 sızıntı. Önkoşul TEK: aynı adlı torun.
	"""

	#: Torun derinlikleri — 1/2/3 üçü de ölçüldü, üçü de sızıyordu.
	DEPTHS = (1, 2, 3)

	@staticmethod
	def _nested(tag: str, depth: int) -> str:
		"""`<Root><tag>` + `depth` kez AYNI ADLI torun + sır + kapanışlar."""
		inner = "x"
		for _ in range(depth):
			inner = f"<{tag}>{inner}</{tag}>"
		return f"<Root><{tag}>{inner}{_XML_SECRET}</{tag}></Root>"

	def test_every_sensitive_name_at_every_depth(self):
		"""189 vektör (63 ad × 3 derinlik) — hepsi ham sızdırıyordu."""
		for tag in sorted(DEFAULT_SENSITIVE_KEYS):
			for depth in self.DEPTHS:
				payload = self._nested(tag, depth)
				with self.subTest(tag=tag, depth=depth):
					self.assertNotIn(_XML_SECRET, mask_payload(payload))

	def test_every_sensitive_name_masks_the_whole_subtree(self):
		"""Sızmamak YETMEZ: sınır ELEMANIN kapanışı olmalı, torunun değil."""
		for tag in sorted(DEFAULT_SENSITIVE_KEYS):
			for depth in self.DEPTHS:
				with self.subTest(tag=tag, depth=depth):
					self.assertEqual(
						mask_payload(self._nested(tag, depth)),
						f"<Root><{tag}>{MASK}</{tag}></Root>",
					)

	def test_wellformed_input_is_never_summarized(self):
		"""İyi biçimli gövde ÖZETE inmemeli — düzeltme teşhis değerini korumalı."""
		for tag in sorted(DEFAULT_SENSITIVE_KEYS):
			for depth in self.DEPTHS:
				with self.subTest(tag=tag, depth=depth):
					self.assertNotIn(_SUMMARY_PREFIX, mask_payload(self._nested(tag, depth)))

	def test_measured_leak_vectors(self):
		"""Denetimin BİREBİR ölçtüğü iki vektör (ikisi de iyi biçimli XML)."""
		cases = {
			f"<LoginResponse><Kod><Kod>01</Kod>{_XML_SECRET}</Kod></LoginResponse>": (
				f"<LoginResponse><Kod>{MASK}</Kod></LoginResponse>"
			),
			f"<R><Sifre>a<Deger><Sifre>b</Sifre></Deger>{_XML_SECRET}</Sifre></R>": (
				f"<R><Sifre>{MASK}</Sifre></R>"
			),
		}
		for payload, expected in cases.items():
			with self.subTest(payload=payload):
				self.assertEqual(mask_payload(payload), expected)

	def test_self_closing_same_name_does_not_open_depth(self):
		"""`<Sifre/>` bir TORUN AÇMAZ — sayaç artarsa sınır kaybolur, gövde özete iner."""
		self.assertEqual(
			mask_payload(f"<R><Sifre><Sifre/>{_XML_SECRET}</Sifre></R>"),
			f"<R><Sifre>{MASK}</Sifre></R>",
		)

	def test_same_name_descendant_with_attributes(self):
		"""Öznitelikli torun açılışı da SAYILMALI (`<Kod a="x">`)."""
		self.assertEqual(
			mask_payload(f'<R><Kod><Kod a="x">1</Kod>{_XML_SECRET}</Kod></R>'),
			f"<R><Kod>{MASK}</Kod></R>",
		)

	def test_same_name_inside_markup_regions_is_not_a_descendant(self):
		"""Yorum/CDATA içindeki `<Kod>` eleman DEĞİL — sayacı bozmamalı."""
		cases = (
			f"<R><Kod><!-- <Kod> --><Kod>1</Kod>{_XML_SECRET}</Kod></R>",
			f"<R><Kod><![CDATA[<Kod>]]><Kod>1</Kod>{_XML_SECRET}</Kod></R>",
		)
		for payload in cases:
			with self.subTest(payload=payload):
				self.assertEqual(mask_payload(payload), f"<R><Kod>{MASK}</Kod></R>")

	def test_sibling_after_close_is_a_separate_element(self):
		"""REGRESYON: kapanıştan SONRAKİ aynı adlı KARDEŞ ayrı elemandır."""
		self.assertEqual(
			mask_payload(f"<R><Kod>a</Kod><Kod>{_XML_SECRET}</Kod></R>"),
			f"<R><Kod>{MASK}</Kod><Kod>{MASK}</Kod></R>",
		)

	def test_negative_controls_stay_unchanged(self):
		"""Aynı adlı torunu OLMAYAN 320 kontrol — davranış DEĞİŞMEMELİ."""
		siblings = ("Deger", "Bilgi", "Ic", "Nested", "Alt")
		checked = 0
		for tag in sorted(DEFAULT_SENSITIVE_KEYS):
			for sibling in siblings:
				payload = f"<Root><{tag}>a<{sibling}>b</{sibling}>{_XML_SECRET}</{tag}></Root>"
				checked += 1
				with self.subTest(tag=tag, sibling=sibling):
					self.assertEqual(mask_payload(payload), f"<Root><{tag}>{MASK}</{tag}></Root>")
		extra = (
			f"<R><Sifre>a<Deger>b</Deger>{_XML_SECRET}</Sifre></R>",
			f"<R><Sifre><Deger><Ic>x</Ic></Deger>{_XML_SECRET}</Sifre></R>",
			f'<R><Sifre attr="v">a<Deger/>{_XML_SECRET}</Sifre></R>',
			f"<R><Sifre>a<!-- c --><Deger>b</Deger>{_XML_SECRET}</Sifre></R>",
			f"<R><Sifre>a<![CDATA[b]]>{_XML_SECRET}</Sifre></R>",
		)
		for payload in extra:
			checked += 1
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, mask_payload(payload))
				self.assertNotIn(_SUMMARY_PREFIX, mask_payload(payload))
		self.assertEqual(checked, 320, "Negatif kontrol kümesi küçülmüş")

	def test_resolved_counter_is_not_inflated(self):
		"""`resolved` sayacı YANLIŞ artıyordu — özetteki "K hassas alan" şişiyordu.

		Torunun kapanışında biten maske, elemanın KALAN içeriğini yeniden
		tarattırıyor ve oradaki aynı adlı kardeşleri AYRI birer "çözülmüş alan"
		gibi sayıyordu. Ölçülen: aynı gövde için 2 yerine 1 (doğru) alan.

		9. TURDA ÖLÇÜM ARACI DEĞİŞTİ (iddia AYNI): özet artık YALNIZ korunacak
		ön ek yokken üretildiği için, özete inildiğinde `resolved` yapısal olarak
		0'dır ve sayaç özet metninden OKUNAMAZ. Aynı iddia doğrudan çıktı
		üzerinden kilitlenir: aynı adlı torunlarıyla birlikte TEK bir alan
		(`<Kod>…</Kod>` → tek `***`) ve ön ek korunur.
		"""
		payload = f"<R><Kod><Kod>a</Kod><Kod>b</Kod>{_XML_SECRET}</Kod></R><!"

		self.assertEqual(assert_fail_closed(self, payload), f"<R><Kod>{MASK}</Kod></R>{MASK}")

	def test_positive_boundary_claim_is_true(self):
		"""BEYAZ KUTU: `_find_close_tag` POZİTİF döndüğü HER yolda İDDİA DOĞRU MU.

		Altı turdur yalnız TANIMA katmanı sınandı; "sınırı buldum" iddiasının
		kendisi hiç doğrulanmadı. Beklenen konum girdinin KURULUŞUNDAN gelir
		(bağımsız oracle), tarayıcıdan değil.
		"""
		from tradehub_core.logistics.integration.masking import _find_close_tag

		shapes = {
			"plain": "x",
			"same_name_depth_1": "<Kod>1</Kod>",
			"same_name_depth_3": "<Kod><Kod><Kod>1</Kod></Kod></Kod>",
			"same_name_self_closing": "<Kod/>",
			"same_name_with_attrs": '<Kod a="1">2</Kod>',
			"same_name_in_comment": "<!-- <Kod> -->",
			"same_name_in_cdata": "<![CDATA[</Kod>]]>",
			"same_name_in_attribute": '<Child a="</Kod>"/>',
			"other_children": "<Deger>1</Deger><Bilgi/>",
			"close_with_whitespace_gap": "<Kod>1</Kod\n>",
		}
		for label, body in shapes.items():
			prefix = "<Root><Kod>"
			content = f"{body}{_XML_SECRET}"
			text = f"{prefix}{content}</Kod></Root>"
			expected_start = len(prefix) + len(content)
			with self.subTest(shape=label):
				bounds, _spent = _find_close_tag(text, len(prefix), "Kod", len(text) * 16)
				self.assertIsNotNone(bounds, "Sınır bulunamadı")
				self.assertEqual(bounds, (expected_start, expected_start + len("</Kod>")))
				self.assertTrue(text.startswith("</Kod>", bounds[0]))

	def test_unbalanced_same_name_falls_back_instead_of_claiming(self):
		"""Torun KAPANMAMIŞSA "buldum" DENMEZ — fail-safe/özet yoluna düşülür."""
		payload = f"<Root><Kod><Kod>{_XML_SECRET}</Kod></Root>"
		masked = mask_payload(payload)

		self.assertNotIn(_XML_SECRET, masked)
		self.assertEqual(masked, f"<Root><Kod>{MASK}</Root>")

	def test_deep_same_name_nesting_stays_linear(self):
		"""Derinlik sayacı `at` monotonluğunu bozmaz — ReDoS profili değişmemeli."""
		started = time.monotonic()
		mask_payload("<Sifre>" * 20_000 + "q" + "</Sifre>" * 20_000)

		self.assertLess(time.monotonic() - started, 5.0)


class TestXmlUnrecognizedLessThan(unittest.TestCase):
	"""TANINMAYAN `<` DİZİLERİ — "tanımadığını işleme" ilkesinin son cebi (7. tur).

	`_TAG_NAME_RE` eşleşmediğinde üç tarayıcı da TEK KARAKTER ilerleyip DEVAM
	ediyordu, yani "anlamadığım diziyi yok say". Ölçülen sızıntı:

		'<Sifre>x</</Sifre>SESSIONTOKEN_ABC999</Sifre>'
			→ '<Sifre>***</Sifre>SESSIONTOKEN_ABC999</Sifre>'

	Aynı davranış `<>`, `</>`, `<//>`, `< ` için de üretildi (5 vektör).

	ŞİDDET MINOR ve GEREKÇESİ AÇIK: girdi hiçbir XML ayrıştırıcısı tarafından
	kabul edilmiyor (ElementTree: "not well-formed"), yani konformant bir taşıyıcı
	yanıtı böyle gelemez; sızıntı ancak HTML5 tokenizer semantiği varsayılırsa
	gerçektir (orada `</` + harf-olmayan bir BOGUS COMMENT'tir ve `>`a kadar
	yutulur, böylece jeton elemanın İÇİNDE kalır). Saldırganın bozuk XML
	üretebilmesi gerekir (`direction='inbound'`).

	KARAR TEK YERDE (`_looks_like_tag` → `_markup_region_end`): 5. turun dersi
	aynı sınıfın üç çağrı yerinde ayrı ayrı ele alınmasıydı ve bir sonraki yapı
	yine bir çağrı yerinde unutulmuştu.
	"""

	VECTORS = (
		f"<Sifre>x</</Sifre>{_XML_SECRET}</Sifre>",
		f"<Sifre>x<></Sifre>{_XML_SECRET}</Sifre>",
		f"<Sifre>x</></Sifre>{_XML_SECRET}</Sifre>",
		f"<Sifre>x<//></Sifre>{_XML_SECRET}</Sifre>",
		f"<Sifre>x< </Sifre>{_XML_SECRET}</Sifre>",
	)

	def test_measured_vectors_no_longer_leak(self):
		for payload in self.VECTORS:
			with self.subTest(payload=payload):
				assert_fail_closed(self, payload)

	def test_bare_trailing_less_than_is_unresolved(self):
		"""Metnin sonundaki çıplak `<` de "yapıyı anlamıyorum" demektir.

		9. TUR: bu "anlamıyorum" artık SONDA kaldığı yerde kalır — ondan
		öncesindeki tüm teşhis (takip numarası) korunur. Eski davranış aynı tek
		baytı gerekçe gösterip 32 karakterlik gövdenin TAMAMINI siliyordu.
		"""
		masked = assert_fail_closed(self, "<Root><Takip>TR-9</Takip></Root><")

		self.assertEqual(masked, f"<Root><Takip>TR-9</Takip></Root>{MASK}")

	def test_wellformed_bodies_are_untouched(self):
		"""REGRESYON: geçerli adlı etiketler bu yola HİÇ girmemeli."""
		cases = (
			"<Root><Takip>TR-9</Takip></Root>",
			'<?xml version="1.0"?><R><ns:Takip>TR-9</ns:Takip></R>',
			"<R><:Takip>TR-9</:Takip></R>",
			"<R><Takip a='x'>TR-9</Takip><Bos/></R>",
		)
		for payload in cases:
			with self.subTest(payload=payload):
				self.assertEqual(mask_payload(payload), payload)

	def test_unrecognized_sequences_stay_linear(self):
		"""Fail-safe kaçış yolu da doğrusal olmalı — özet üretmek maliyet olmasın."""
		for label, payload in (
			("many_bogus_closes", "<Sifre>" + "</<" * 50_000),
			("many_empty_tags", "<Sifre>" + "<>" * 50_000),
			("many_spaces", "<Sifre>" + "< " * 50_000),
		):
			started = time.monotonic()
			mask_payload(payload)
			with self.subTest(case=label):
				self.assertLess(time.monotonic() - started, 5.0)


class TestXmlMarkupCriterion(unittest.TestCase):
	"""ÖZETE İNME ÖLÇÜTÜ: "BU METİN MARKUP MI?" — 8. tur (Paket M).

	7. tur "tanınmayan `<` dizisi → fail-safe ÖZET" kuralını doğru yere koydu ama
	`_mask_xml_elements`'in dört fail-safe dalı metinde HASSAS BİR ŞEY OLUP
	OLMADIĞINA bakmadan özete iniyordu. `_mask_text` `error_message`,
	`request_body` ve `response_body` alanlarının HEPSİNE uygulanır ve bunların
	çoğu XML DEĞİL, düz metindir. Sonuç (ölçüldü):

		'a < b'                  → '<XML gövdesi, 5 bayt, 0 hassas alan …>'
		'timeout <2 sn> asildi'  → '<XML gövdesi, 21 bayt, 0 hassas alan …>'
		'error: 5 < 10 gecti'    → '<XML gövdesi, 19 bayt, 0 hassas alan …>'

	Özetin KENDİSİ "0 hassas alan" diyor, yani mekanizma hiçbir şey saklamadığını
	İLAN EDEREK tüm teşhisi yok ediyordu.

	ARA ÇÖZÜM VE ONUN FAIL-OPEN'I: bu aşırı-düzeltme önce metnin BAŞINA bakan bir
	GİRİŞ KAPISIYLA (`_looks_like_xml_body`) giderilmişti — baştaki boşluk/BOM
	atlandıktan sonra `<` + geçerli ad / `?` / `!` yoksa XML tarayıcısı HİÇ
	koşmuyordu. Kapı aşırı-düzeltmeyi gerçekten kapattı ama GERÇEK SIZINTI
	üretti: `LEAK_PREFIXES`'teki 11 önekin 11'i de sırrı HAM döndürüyordu.
	Değer-tabanlı birincil katman bu sınıfta YARDIM EDEMEZ — taşıyıcının
	YANITINDA gelen oturum jetonunun değerini sistem önceden BİLMEZ, etiket
	tabanlı maskeleme o sınıfın TEK savunmasıdır.

	KÖK NEDEN — İKİ AYRI SORU TEK KARARA BAĞLANMIŞTI:
		1. "Bu metin MARKUP mı?"           → ölçütün cevaplaması gereken soru
		2. "Markup'ı AYRIŞTIRABİLDİM Mİ?"  → fail-safe özetin sorusu
	Metnin BAŞINA bakmak 1. soruyu KONUM üzerinden cevaplıyordu; oysa soru
	İÇERİKLE ilgilidir. Baştaki tek bir karakter (bir NBSP, bir `HTTP 500:`
	öneki) markup'ı markup olmaktan çıkarmaz.

	BUGÜNKÜ ÖLÇÜT: giriş kapısı YOK, tarayıcı HER metinde koşar; özete inen dört
	dal ise metnin TAMAMINDA yapı-kör tarama yapar (`_contains_markup_construct`).
	Markup benzeri TEK BİR yapı bile yoksa özet üretilmez.
	"""

	#: Kapının SIZDIRDIĞI 11 önek. Hepsi `<Sifre>…</Sifre>` gövdesinin ÖNÜNE
	#: eklenir; hiçbiri gövdeyi markup olmaktan çıkarmaz.
	LEAK_PREFIXES = (
		("nbsp_u00a0", "\xa0"),
		("line_separator_u2028", "\u2028"),
		("paragraph_separator_u2029", "\u2029"),
		("ideographic_space_u3000", "\u3000"),
		("next_line_u0085", "\x85"),
		("zero_width_space_u200b", "\u200b"),
		("null_u0000", "\x00"),
		# UTF-8 BOM latin1 olarak çözüldüğünde ortaya çıkan mojibake — TR kargo
		# yığınlarında yanlış `encoding` başlığıyla RUTİN.
		("mojibake_bom", "ï»¿"),
		("http_status", "HTTP 500: "),
		("soap_fault_text", "Sunucu hatasi: "),
		("single_quote_wrap", "'"),
	)

	#: Markup benzeri TEK BİR yapı içermeyen metinler — özet YOK, metin AYNEN.
	PLAIN_TEXT_VECTORS = (
		"a < b",
		"timeout <2 sn> asildi",
		"error: 5 < 10 gecti",
		"ConnectionError: <Response [500]>",
		"deger <bos> geldi",
		"1 < 2 < 3",
		"metin sonunda <",
		"<",
		"a<",
		"< tek",
		"  a < b",
		"\ufeffa < b",
		"<2Sifre> rakamla baslayan ad",
		"</ ile baslayan ama ad yok",
		"< bosluk ile baslayan",
	)

	def test_plain_text_with_less_than_is_not_summarized(self):
		"""ÖLÇÜLMÜŞ AŞIRI-DÜZELTME: markup içermeyen metin DEĞİŞMEDEN geçmeli."""
		for payload in self.PLAIN_TEXT_VECTORS:
			with self.subTest(payload=payload):
				self.assertEqual(mask_payload(payload), payload)

	def test_plain_text_never_summarizes(self):
		"""Fail-safe özet markup İÇERMEYEN metinde TETİKLENMEMELİ — sınır vakaları dahil."""
		for payload in self.PLAIN_TEXT_VECTORS:
			with self.subTest(payload=payload):
				self.assertNotIn(_SUMMARY_PREFIX, mask_payload(payload))

	def test_leading_noise_does_not_disable_tag_masking(self):
		"""ÖLÇÜLMÜŞ FAIL-OPEN (11/11): baştaki gürültü sırrı HAM bırakıyordu.

		Konum tabanlı giriş kapısı bu öneklerin HİÇBİRİNİ tanımıyordu ve XML
		tarayıcısını hiç çalıştırmıyordu; `<Sifre>` gövdesi log'a olduğu gibi
		düşüyordu. Etiket maskelemesi bu sınıfın TEK savunmasıdır.
		"""
		for label, prefix in self.LEAK_PREFIXES:
			payload = f"{prefix}<Sifre>{_XML_SECRET}</Sifre>"
			with self.subTest(prefix=label):
				masked = mask_payload(payload)

				self.assertNotIn(_XML_SECRET, masked)
				self.assertEqual(masked, f"{prefix}<Sifre>{MASK}</Sifre>")

	def test_leading_noise_with_namespaced_tag(self):
		"""SOAP fault metni + ad alanlı etiket — ölçülen 11. vektör."""
		masked = mask_payload(f"Sunucu hatasi: <soap:Sifre>{_XML_SECRET}</soap:Sifre>")

		self.assertNotIn(_XML_SECRET, masked)
		self.assertEqual(masked, f"Sunucu hatasi: <soap:Sifre>{MASK}</soap:Sifre>")

	def test_single_quote_wrapper_is_masked_on_both_sides(self):
		"""`repr()` ile log'a düşmüş gövde: sarmalayıcı tırnak markup'ı bozmaz."""
		self.assertEqual(
			mask_payload(f"'<Sifre>{_XML_SECRET}</Sifre>'"),
			f"'<Sifre>{MASK}</Sifre>'",
		)

	def test_markup_bodies_are_masked_with_and_without_leading_whitespace(self):
		"""REGRESYON: boşluk/BOM önekleri de (UTF-8 BOM'lu SOAP) aynı sonucu verir."""
		for prefix in ("", "   ", "\n\t", "\ufeff", "\ufeff  ", "  \ufeff\n"):
			payload = f"{prefix}<Sifre>{_XML_SECRET}</Sifre>"
			with self.subTest(prefix=repr(prefix)):
				self.assertEqual(mask_payload(payload), f"{prefix}<Sifre>{MASK}</Sifre>")

	def test_markup_prologue_bodies_are_masked(self):
		"""`<?` ve `<!` ile başlayan gövdeler eskisi gibi işlenir."""
		self.assertEqual(
			mask_payload(f'<?xml version="1.0"?><R><Sifre>{_XML_SECRET}</Sifre></R>'),
			f'<?xml version="1.0"?><R><Sifre>{MASK}</Sifre></R>',
		)
		self.assertEqual(
			mask_payload(f"<!-- yorum --><R><Sifre>{_XML_SECRET}</Sifre></R>"),
			f"<!-- yorum --><R><Sifre>{MASK}</Sifre></R>",
		)

	def test_unparsable_prefix_plus_real_tag_still_fails_closed(self):
		"""YENİ ÖLÇÜTÜN CAN DAMARI: ilk `< b` çözülemiyor AMA metinde `<Sifre>` VAR.

		Konum tabanlı kapı burada KAPALIYDI (metin `a` ile başlıyor) ve sır HAM
		dönüyordu. İçerik tabanlı ölçüt metnin TAMAMINA baktığı için markup'ı
		görür ve fail-safe devreye girer.

		9. TURDA DEĞİŞEN yalnız fail-safe'in EYLEMİ: özet yerine çözülemeyen
		`<`ten sonrasının yerel maskesi (`'a ***'`). Ölçütün kendisi ve sızıntı
		iddiası AYNEN korunur.
		"""
		masked = assert_fail_closed(self, f"a < b <Sifre>{_XML_SECRET}</Sifre>")

		self.assertEqual(masked, f"a {MASK}")

	def test_declaration_family_still_summarizes(self):
		"""`<!` bildirim ailesinin TAMAMI fail-safe yoluna girer (6./7. tur korunur).

		Bu vakaların hepsinde çözülemeyen dizi ya metnin başındadır ya da ondan
		önce maskelenmiş bir parça yoktur; 9. turun ayrımına göre eylem yine
		ÖZETTİR (bkz. `test_summary_is_reserved_for_bodies_without_a_preservable_prefix`).
		"""
		cases = {
			"doctype": "<!DOCTYPE d [",
			"entity": f'<Sifre>x<!ENTITY e "</Sifre>">{_XML_SECRET}</Sifre>',
			"attlist": f"<!ATTLIST a b CDATA #REQUIRED><Sifre>{_XML_SECRET}</Sifre>",
			"element": f"<!ELEMENT a (b)><Sifre>{_XML_SECRET}</Sifre>",
			"notation": f"<!NOTATION n SYSTEM 'x'><Sifre>{_XML_SECRET}</Sifre>",
			"ignore": f"<![IGNORE[x]]><Sifre>{_XML_SECRET}</Sifre>",
			"include": f"<![INCLUDE[x]]><Sifre>{_XML_SECRET}</Sifre>",
			"bare_bang_name": f"<Sifre>x<!q</Sifre>{_XML_SECRET}</Sifre>",
			"bare_bang": f"<Sifre>x<!</Sifre>{_XML_SECRET}</Sifre>",
			"bare_bang_bracket": f"<Sifre>x<![</Sifre>{_XML_SECRET}</Sifre>",
		}
		for label, payload in cases.items():
			with self.subTest(case=label):
				masked = mask_payload(payload)

				self.assertNotIn(_XML_SECRET, masked)
				self.assertTrue(masked.startswith(_SUMMARY_PREFIX), masked)

	def test_unresolved_structures_inside_markup_still_fail_closed(self):
		"""Kapanmamış tırnak / başıboş kapanış / bogus `<` — mevcut davranış AYNEN.

		9. TUR: son vaka (`trailing_bare_lt`) artık ÖZET değil YEREL maske
		üretir, çünkü çözülemeyen `<` metnin SONUNDADIR ve önündeki gövde
		tamamen anlaşılmıştır. Kalan sekiz vakada çözülemeyen dizi metnin ta
		başındadır (korunacak ön ek yok) ve özet AYNEN korunur.
		"""
		cases = {
			"unclosed_attribute_quote": f'<a b="><Sifre>{_XML_SECRET}',
			"stray_bogus_close": f"<Sifre>x</</Sifre>{_XML_SECRET}</Sifre>",
			"empty_tag": f"<Sifre>x<>{_XML_SECRET}</Sifre>",
			"empty_close": f"<Sifre>x</>{_XML_SECRET}</Sifre>",
			"double_slash": f"<Sifre>x<//>{_XML_SECRET}</Sifre>",
			"lt_space": f"<Sifre>x< {_XML_SECRET}</Sifre>",
			"nested_unclosed": f"<Sifre><Deger>{_XML_SECRET}",
			"unclosed_cdata": f"<Sifre><![CDATA[{_XML_SECRET}",
		}
		for label, payload in cases.items():
			with self.subTest(case=label):
				masked = assert_fail_closed(self, payload)

				self.assertTrue(masked.startswith(_SUMMARY_PREFIX), masked)

		self.assertEqual(
			assert_fail_closed(self, "<Root><Takip>TR-9</Takip></Root><"),
			f"<Root><Takip>TR-9</Takip></Root>{MASK}",
		)

	def test_secondary_layers_still_mask_delimited_pairs(self):
		"""KRİTİK: özet ÜRETİLMEDİĞİNDE İKİNCİL katman çalışmaya DEVAM etmeli."""
		self.assertEqual(mask_payload("x < y, sifre=SECRETVALUE123"), f"x < y, sifre={MASK}")
		self.assertEqual(mask_payload(f"Authorization: Bearer {_SECRET}"), f"Authorization: {MASK}")
		self.assertEqual(mask_payload(f"sifre={_SECRET}"), f"sifre={MASK}")
		self.assertEqual(
			mask_payload("hata: deger < esik, api_key: ABCDEF123456"), f"hata: deger < esik, api_key: {MASK}"
		)

	def test_secondary_layers_still_redact_by_value(self):
		"""Değer-tabanlı BİRİNCİL katman markup olmayan metinde de çalışmalı."""
		masked = mask_payload(f"5 < 10 iken cagri {_SECRET} ile dustu", secret_values=[_SECRET])

		self.assertNotIn(_SECRET, masked)
		self.assertIn("5 < 10", masked)
		self.assertEqual(redact_text(f"a < b {_SECRET}", [_SECRET]), f"a < b {MASK}")

	def test_secondary_layers_still_mask_url_userinfo(self):
		"""URL userinfo katmanı da özet dışında — düz metinde çalışmaya devam eder."""
		masked = mask_payload(f"5 < 10: https://istoc:{_SECRET}@kargo.example/api")

		self.assertNotIn(_SECRET, masked)
		self.assertIn("5 < 10", masked)

	def test_criterion_applies_inside_wrappers_identically(self):
		"""TEK KÜME KURALI: dict/list/bytes kabında da aynı sonuç."""
		payload = "error: 5 < 10 gecti"

		self.assertEqual(mask_payload({"error_message": payload})["error_message"], payload)
		self.assertEqual(mask_payload([payload]), [payload])
		self.assertEqual(mask_payload(payload.encode("utf-8")), payload)

	def test_leak_vectors_apply_inside_wrappers_identically(self):
		"""Sızıntı sınıfı kaplarda da kapalı olmalı — yazıcı gövdeleri dict'tir."""
		payload = f"HTTP 500: <Sifre>{_XML_SECRET}</Sifre>"
		expected = f"HTTP 500: <Sifre>{MASK}</Sifre>"

		self.assertEqual(mask_payload({"error_message": payload})["error_message"], expected)
		self.assertEqual(mask_payload([payload]), [expected])
		self.assertEqual(mask_payload(payload.encode("utf-8")), expected)

	def test_malformed_name_tags_are_a_documented_limit(self):
		"""BİLİNEN SINIR: bozuk adlı hassas etiket, TEK BAŞINA bir gövdede ham geçer.

		Bu bir gözden kaçma değil, ÖLÇÜLMÜŞ bir takas — gerekçesi
		`_contains_markup_construct` docstring'inde. Test sınırın YERİNİ kilitler:
		biri ölçütü genişletirse burası, daralttığında ise aşağıdaki koruma
		iddiaları düşer ve karar yeniden tartışılır.
		"""
		# (a) SINIR: gövdede tek bir GEÇERLİ etiket yok → ham geçer.
		for name in ("2Sifre", "-Sifre", ".Sifre", " Sifre"):
			body = f"<{name}>{_XML_SECRET}</{name}>"
			self.assertEqual(mask_payload(body), body, name)

		# (b) KORUMA: kök eleman geçerliyse (gerçek yanıtlarda HER ZAMAN öyle)
		#     ölçüt markup görür ve fail-safe devreye girer — sızıntı YOK.
		#
		#     9. TURDA GÜNCELLENDİ: iddia eskiden "özete iner"di. Fail-safe'in
		#     EYLEMİ değişti (yerelleştirme; ölçülmüş gerekçe
		#     `masking._fail_closed`), SINIRIN YERİ değişmedi — burada kök `<R>`
		#     korunacak bir ön ek olduğu için özet yerine yerel maske seçilir.
		#     Testin işlevi aynı: ölçüt daraltılırsa `assert_fail_closed` düşer.
		masked = assert_fail_closed(self, f"<R><2Sifre>{_XML_SECRET}</2Sifre></R>")
		self.assertEqual(masked, f"<R>{MASK}")

		# (c) AYRIŞMA YOK: XML'in İZİN VERDİĞİ ad şekilleri (canlı SOAP) maskelenir.
		for name in ("ns2:Sifre", "Api-Sifre", "api.sifre", "Sifre2", "_Sifre"):
			self.assertEqual(
				mask_payload(f"<{name}>{_XML_SECRET}</{name}>"),
				f"<{name}>{MASK}</{name}>",
				name,
			)

		# (d) SINIRI KAPATMANIN BEDELİ: `<` sonrası hassas ad arayan bir kural bu
		#     düz metin hata mesajını özete indirirdi. Teşhis KORUNUYOR.
		self.assertEqual(mask_payload("deger < 5 sifre kadar"), "deger < 5 sifre kadar")

	def test_xml_regressions_survive_the_new_criterion(self):
		"""REGRESYON KİLİDİ: 5.-7. turların düzeltmeleri AYNEN kalır."""
		self.assertEqual(
			mask_payload(f"<LoginResponse><Kod><Kod>01</Kod>{_XML_SECRET}</Kod></LoginResponse>"),
			f"<LoginResponse><Kod>{MASK}</Kod></LoginResponse>",
		)
		self.assertEqual(
			mask_payload("<Root><Takip>TR-123</Takip><Password>gizli</Root><Sonraki>OK</Sonraki>"),
			f"<Root><Takip>TR-123</Takip><Password>{MASK}</Root><Sonraki>OK</Sonraki>",
		)
		self.assertEqual(
			mask_payload(f"<R><Token><!-- </Token> -->{_XML_SECRET}</Token></R>"),
			f"<R><Token>{MASK}</Token></R>",
		)
		self.assertEqual(
			mask_payload(f"<R><Token><![CDATA[</Token>]]>{_XML_SECRET}</Token></R>"),
			f"<R><Token>{MASK}</Token></R>",
		)
		self.assertEqual(mask_payload(f"<Sifre><![CDATA[{_XML_SECRET}]]></Sifre>"), f"<Sifre>{MASK}</Sifre>")

	def test_criterion_is_linear(self):
		"""Kapı kalktı: düz metin artık XML döngüsüne GİRİYOR, doğrusallık korunmalı.

		Ölçüt tarama bütçesi `_MIN_TAG_SCAN_BUDGET` (256 KiB) ile kırpılır ve
		bütçe biterse GÜVENLİ yöne (özet) gider; `log.py::MAX_BODY_BYTES` 64 KiB
		olduğu için gerçek gövdeler bu dala hiç girmez.
		"""
		for label, payload in (
			("plain_lt_soup", "a < b " * 100_000),
			("plain_pairs_with_lt", "x < y, sifre=SECRETVALUE123 " * 50_000),
			("leading_space_soup", " " * 500_000 + "a < b"),
			("markup_then_plain_soup", "<Sifre>x</Sifre>" + "a < b " * 100_000),
			("sub_budget_plain", "x < y, sifre=SECRETVALUE123 " * 2_000),
		):
			started = time.monotonic()
			mask_payload(payload)
			with self.subTest(case=label):
				self.assertLess(time.monotonic() - started, 5.0)

	def test_body_at_the_log_truncation_ceiling_is_not_summarized(self):
		"""64 KiB (gerçek tavan) düz metin ölçüt bütçesinin ALTINDA kalır → özet YOK."""
		payload = ("x < y, sifre=SECRETVALUE123 " * 5_000)[: 64 * 1024]

		masked = mask_payload(payload)

		self.assertNotIn(_SUMMARY_PREFIX, masked)
		self.assertNotIn("SECRETVALUE123", masked)


class TestXmlScanBudget(unittest.TestCase):
	"""O(k·n) — memoizasyon FARKLI adlarda çalışmıyordu, bütçe de yoktu.

	ÖLÇÜLDÜ (1 MB): k=100 → 0,028 sn; k=2000 → 0,491 sn; k=5000 → 1,254 sn
	(düz doğrusal). Gerçek tavan olan 64 KiB kırpmasında 7406 farklı etiket
	0,200 sn/satır ediyordu — tipik gövdenin 10-25 katı. `direction='inbound'`
	saldırgan kontrolünde ve her satır bir RQ işçisini bloke ediyor.
	"""

	LIMIT_SECONDS = 0.5

	def _timed(self, payload: str) -> float:
		started = time.monotonic()
		mask_payload(payload)
		return time.monotonic() - started

	def test_many_distinct_sensitive_tags_stay_cheap(self):
		payload = "".join(f"<Password{index}>" for index in range(5000)) + "q" * (1024 * 1024)

		self.assertLess(self._timed(payload), self.LIMIT_SECONDS)

	def test_case_variants_do_not_multiply_the_scan(self):
		"""`dead_tags` HAM adla anahtarlıydı: `<Password>`/`<passWord>` ayrı taranıyordu."""
		payload = "".join(
			f"<pass{'W' if index % 2 else 'w'}ord{index % 2}>" for index in range(5120)
		) + "q" * (1024 * 1024)

		self.assertLess(self._timed(payload), self.LIMIT_SECONDS)

	def test_real_ceiling_is_the_log_truncation_window(self):
		"""64 KiB tavanında 7406 farklı etiket 0,200 sn/satır sürüyordu."""
		tags = "".join(f"<Password{index}>" for index in range(7406))
		payload = (tags + "q" * (64 * 1024))[: 64 * 1024]

		self.assertLess(self._timed(payload), self.LIMIT_SECONDS)


# ---------------------------------------------------------------------------
# Hassas ELEMANIN KENDİ ÖZNİTELİĞİ (9. tur)
# ---------------------------------------------------------------------------


class TestSensitiveElementAttributes(unittest.TestCase):
	"""ELEMAN hassassa ÖZNİTELİK DEĞERLERİ de hassastır — ölçülmüş sızıntı (9. tur).

	`_mask_xml_elements` hassas bir açılış etiketi bulunca etiketin TAMAMINI
	(öznitelik bloğu dahil) HAM yazıyor, yalnız İÇERİĞİ `***` yapıyordu; kendi
	kendine kapanan hassas etikette ise HİÇ maskeleme yapmıyordu. Koddaki gerekçe
	"değeri öznitelikte, onu `_mask_delimited_pairs` ele alır"dı ve YANLIŞTI: o
	katman yalnız ÖZNİTELİK ADINA bakar, "içinde bulunduğun ELEMAN hassas"
	bilgisini hiç almaz. İKİ KATMANIN SÖZLEŞMESİ TAM BURADA AYRIŞIYORDU.

	Ölçülen (`mask_payload`, jeton taşıyıcının YANITINDAKİ oturum jetonu yerine
	geçiyor — değeri önceden BİLİNMEZ, birincil değer-tabanlı katman YARDIM EDEMEZ):

		'<Sifre deger="SESSIONTOKEN_ABC999"/>'               → DEĞİŞMEDEN
		'<Sifre deger="SESSIONTOKEN_ABC999">icerik</Sifre>'  → '…ABC999">***</Sifre>'
		'<R><ApiKey k="SESSIONTOKEN_ABC999"/><Takip>TR-1</Takip></R>' → DEĞİŞMEDEN

	İkinci satır YANILTICI maskedir: çıktıda `***` görünür, operatör "redakte
	edildi" sanır, jeton yanı başındaki öznitelikte durur. Girdilerin hepsi İYİ
	BİÇİMLİ XML'dir (ElementTree kabul eder) — hiçbir fail-safe dalı tetiklenmez,
	yani bu `_find_close_tag` sınıfıyla aynı aileden: "yanlış anladım ama
	anladığımı sandım."
	"""

	#: Ölçülen beş sızıntı vektörü + KONTROL (bu hep doğruydu).
	MEASURED = (
		f'<Sifre deger="{_XML_SECRET}"/>',
		f'<Sifre deger="{_XML_SECRET}">icerik</Sifre>',
		f'<Envelope><Body><LoginResult><Token id="{_XML_SECRET}"/></LoginResult></Body></Envelope>',
		f'<Password value="{_XML_SECRET}"></Password>',
		f'<R><ApiKey k="{_XML_SECRET}"/><Takip>TR-1</Takip></R>',
		f'<R><Deger sifre="{_XML_SECRET}"/></R>',
	)

	def test_measured_vectors_no_longer_leak(self):
		for payload in self.MEASURED:
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, mask_payload(payload))

	def test_every_sensitive_name_and_attribute_name(self):
		"""TOPLU: 63 hassas ad × 10 öznitelik adı × 2 şekil = 1260 vektör, 1260'ı sızıyordu."""
		attributes = ("deger", "value", "id", "k", "v", "data", "content", "x", "attr", "param")
		names = sorted(DEFAULT_SENSITIVE_KEYS)
		checked = 0
		for name in names:
			for attribute in attributes:
				for payload in (
					f'<{name} {attribute}="{_XML_SECRET}"/>',
					f'<{name} {attribute}="{_XML_SECRET}">icerik</{name}>',
				):
					checked += 1
					masked = mask_payload(payload)
					with self.subTest(payload=payload):
						self.assertNotIn(_XML_SECRET, masked)
		self.assertEqual(checked, len(names) * len(attributes) * 2)
		self.assertGreaterEqual(checked, 1260, "Vektör kümesi küçülmüş")

	def test_self_closing_sensitive_tag_is_masked(self):
		"""Eskiden `continue` ediliyordu — HİÇ maskeleme yoktu."""
		self.assertEqual(mask_payload(f'<Sifre deger="{_XML_SECRET}"/>'), f'<Sifre deger="{MASK}"/>')
		self.assertEqual(mask_payload(f"<Sifre deger='{_XML_SECRET}'/>"), f"<Sifre deger='{MASK}'/>")
		self.assertEqual(mask_payload(f"<Sifre deger={_XML_SECRET}/>"), f"<Sifre deger={MASK}/>")

	def test_attribute_names_and_tag_name_are_preserved(self):
		"""Yalnız DEĞERLER gider — teşhis için gereken yapı bilgisi ayakta kalır."""
		masked = mask_payload(f'<Sifre a="1" deger="{_XML_SECRET}" b=\'2\'>icerik</Sifre>')

		self.assertEqual(masked, f'<Sifre a="{MASK}" deger="{MASK}" b=\'{MASK}\'>{MASK}</Sifre>')

	def test_all_attribute_values_go_regardless_of_their_name(self):
		"""FAIL-CLOSED: eleman hassassa öznitelik ADINA BAKILMAZ (`xmlns` dahil)."""
		masked = mask_payload(f'<Sifre xmlns:ns="http://x/y" ns:deger="{_XML_SECRET}"/>')

		self.assertEqual(masked, f'<Sifre xmlns:ns="{MASK}" ns:deger="{MASK}"/>')

	def test_insensitive_element_attributes_are_untouched(self):
		"""REGRESYON: hassas OLMAYAN elemanda ad-tabanlı davranış AYNEN korunur."""
		self.assertEqual(
			mask_payload('<Adres il="Istanbul" ilce="Sisli"/>'), '<Adres il="Istanbul" ilce="Sisli"/>'
		)
		self.assertEqual(
			mask_payload('<Adres il="Istanbul">Merkez</Adres>'), '<Adres il="Istanbul">Merkez</Adres>'
		)
		self.assertEqual(mask_payload(f'<Adres sifre="{_XML_SECRET}"/>'), f'<Adres sifre="{MASK}"/>')
		self.assertEqual(
			mask_payload(f"<Login password=\"{_SECRET}\" kullanici='{_SECRET}' sehir='İstanbul'/>"),
			f"<Login password=\"{MASK}\" kullanici='{MASK}' sehir='İstanbul'/>",
		)

	def test_empty_and_attributeless_tags_are_untouched(self):
		self.assertEqual(mask_payload("<Sifre/>"), "<Sifre/>")
		self.assertEqual(
			mask_payload("<R><Sifre/><Takip>TR-1</Takip></R>"), "<R><Sifre/><Takip>TR-1</Takip></R>"
		)

	def test_self_closing_mask_does_not_open_ancestor_depth(self):
		"""REGRESYON: 7. turun `self_closing_same_name` kilidi bozulmamalı."""
		self.assertEqual(
			mask_payload(f"<R><Kod/><Kod>{_XML_SECRET}</Kod></R>"), f"<R><Kod/><Kod>{MASK}</Kod></R>"
		)

	def test_truncated_sensitive_open_tag_fails_closed(self):
		"""64 KiB KIRPMASININ ORTASINDA KESİLEN ÖZNİTELİK — 9. turda ölçüldü.

		`_TAG_END_TRUNCATED`ın gerekçesi "kuyrukta ELEMAN İÇERİĞİ olamaz, tarayıcı
		güvenle durur"du ve İÇERİK için doğrudur; kuyrukta ÖZNİTELİK DEĞERİ
		olabileceği hesaba katılmamıştı. `log.py::MAX_BODY_BYTES` kırpması
		maskelemeden ÖNCE yapıldığı için bu yol ERİŞİLEBİLİRDİR: 301 kesim
		noktalı süpürmede öznitelikli gövde bu tek dal yüzünden ham sızıyordu
		(düzeltmeden sonra dört gövde şeklinde de 0 sızıntı).
		"""
		self.assertNotIn(_XML_SECRET, mask_payload(f'<Sifre deger="{_XML_SECRET}'))
		self.assertEqual(
			mask_payload(f'<R><Takip>TR-9</Takip><Sifre deger="{_XML_SECRET}'),
			f"<R><Takip>TR-9</Takip>{MASK}",
		)

	def test_truncated_insensitive_tag_is_not_overmasked(self):
		"""Sıradan yarım etiket ve düz metin AYNEN geçmeye devam eder."""
		for payload in ("metin sonunda <Takip", "<Adres il", "a < b", "deger < 5 sifre kadar"):
			with self.subTest(payload=payload):
				self.assertEqual(mask_payload(payload), payload)

	def test_wrappers_behave_identically(self):
		for payload in self.MEASURED:
			with self.subTest(payload=payload):
				self.assertNotIn(_XML_SECRET, str(mask_payload({"body": payload})))
				self.assertNotIn(_XML_SECRET, str(mask_payload(payload.encode("utf-8"))))


# ---------------------------------------------------------------------------
# Fail-safe YERELLEŞTİRME — yerel tetikleyici, yerel eylem (9. tur)
# ---------------------------------------------------------------------------


class TestLocalizedFailClosed(unittest.TestCase):
	"""Dört fail-safe dalı TEK bir çözülemeyen `<` yüzünden TÜM gövdeyi siliyordu.

	`log.py::MAX_BODY_BYTES` (64 KiB) kırpması maskelemeden ÖNCE yapılır, yani bu
	dal gerçek taşıyıcı yanıtlarında RUTİN olarak tetiklenir. 301 kesim
	noktasında ölçüldü (gerçekçi TR kargo XML'i):

		öznitelikli gövde: 130/301 kesim noktası TÜM gövdeyi siliyor
		CDATA'lı gövde:    154/301
		düz gövde:          40/301
		JSON gövde:          0/301   (sorun XML/HTML'e özgü)

	Operatöre kalan ortalama karakter: özet 32.000-57.000 | yerelleştirme 65.380.

	YENİ KURAL: korunacak ön ek VARSA yerelleştir (`ön ek + ***`), YOKSA özetle.
	Özet, ön ek yokken bayt/alan sayısını taşıyan TEK bilgi kaynağıdır.

	BİLİNEN TAKAS: özet, ön ekte "YANLIŞ POZİTİF bir sınır iddiası" olsaydı onu da
	siliyordu — tesadüfi bir İKİNCİ savunma. Yerelleştirme onu bırakır. O sınıf
	7. turda `_find_close_tag` derinlik sayımıyla kapatıldı ve
	`TestXmlSameNameDescendant` ile kilitlidir.
	"""

	#: Ana oturumun ölçtüğü 12 özet-üreten vektör — hepsinde sır GİZLİ kalmalı.
	LEAK_VECTORS = {
		"nested_unclosed": f"<Sifre><Deger>{_XML_SECRET}",
		"stray_close": f"<R><Sifre></Yanlis>{_XML_SECRET}<!",
		"bare_lt_in_value": f'<Sifre>x<Child a="></Sifre>">{_XML_SECRET}</Child>',
		"unclosed_quote": f'<R><Takip>TR-9</Takip><a b="><Sifre>{_XML_SECRET}',
		"entity": f'<Sifre>x<!ENTITY e "</Sifre>">{_XML_SECRET}</Sifre>',
		"doctype_subset": f"<Sifre><!DOCTYPE d [</Sifre>]>{_XML_SECRET}</Sifre>",
		"digit_leading_name": f"<R><2Sifre>{_XML_SECRET}</2Sifre></R>",
		"unclosed_cdata": f"<R><Takip>TR-9</Takip><Sifre><![CDATA[{_XML_SECRET}",
		"trailing_bare_lt": f"<R><Takip>TR-9</Takip><Sifre>{_XML_SECRET}</Sifre></R><",
		"unparsable_prefix": f"a < b <Sifre>{_XML_SECRET}</Sifre>",
		"truncated_sensitive": f"<R><Takip>TR-9</Takip><Sifre>{_XML_SECRET}</Sif",
		"ancestorless": f"<Sifre><Deger><Alt>{_XML_SECRET}</Alt>",
	}

	def test_twelve_measured_vectors_keep_the_secret_hidden(self):
		self.assertEqual(len(self.LEAK_VECTORS), 12, "Vektör kümesi küçülmüş")
		for label, payload in self.LEAK_VECTORS.items():
			with self.subTest(case=label):
				assert_fail_closed(self, payload)

	def test_vectors_keep_the_secret_hidden_in_every_wrapper(self):
		"""Tek küme kuralı: dict/bytes/list kabında da aynı sonuç."""
		for label, payload in self.LEAK_VECTORS.items():
			with self.subTest(case=label):
				self.assertNotIn(_XML_SECRET, str(mask_payload({"response_body": payload})))
				self.assertNotIn(_XML_SECRET, str(mask_payload(payload.encode("utf-8"))))
				self.assertNotIn(_XML_SECRET, str(mask_payload([{"a": [payload]}])))

	def test_diagnostics_before_the_unresolved_point_survive(self):
		"""ASIL KAZANÇ: takip numarası / durum / şube artık silinmiyor."""
		payload = "<Root><Takip>TR-123456</Takip><Durum>Teslim</Durum><Sube>Kadikoy</Sube></Root><!"
		masked = mask_payload(payload)

		self.assertEqual(
			masked, f"<Root><Takip>TR-123456</Takip><Durum>Teslim</Durum><Sube>Kadikoy</Sube></Root>{MASK}"
		)
		for token in ("TR-123456", "Teslim", "Kadikoy"):
			self.assertIn(token, masked)

	def test_masked_prefix_is_kept_and_the_tail_still_goes(self):
		"""Ön ekte ZATEN maskelenmiş bir hassas eleman varsa o da korunur."""
		self.assertEqual(
			mask_payload(f"<R><Sifre>{_XML_SECRET}</Sifre><Takip>TR-7</Takip><!"),
			f"<R><Sifre>{MASK}</Sifre><Takip>TR-7</Takip>{MASK}",
		)
		self.assertEqual(
			mask_payload(f'<R><Sifre a="{_XML_SECRET}"/><Takip>TR-7</Takip><!'),
			f'<R><Sifre a="{MASK}"/><Takip>TR-7</Takip>{MASK}',
		)

	def test_no_preservable_prefix_still_summarizes(self):
		"""ÖLÇÜLMÜŞ İSTİSNA: `lt == 0` olan HTML hata sayfasında özet DAHA BİLGİLİ."""
		for payload in (
			"<!DOCTYPE html><html><body>500 Internal Server Error</body></html>",
			f"<!DOCTYPE html><html><body><Sifre>{_XML_SECRET}</Sifre></body></html>",
			f'<a b="><Sifre>{_XML_SECRET}',
			f"<Sifre><Deger>{_XML_SECRET}",
		):
			with self.subTest(payload=payload):
				masked = mask_payload(payload)
				self.assertTrue(masked.startswith(_SUMMARY_PREFIX), masked)
				self.assertNotIn(_XML_SECRET, masked)

	def test_localization_never_leaves_a_tail_behind(self):
		"""BEYAZ KUTU DEĞİL, DAVRANIŞ: yerelleştirilmiş çıktı DAİMA `***` ile biter."""
		for label, payload in self.LEAK_VECTORS.items():
			masked = mask_payload(payload)
			with self.subTest(case=label):
				if not masked.startswith(_SUMMARY_PREFIX):
					self.assertTrue(masked.endswith(MASK), masked)

	def test_overmasking_stays_closed(self):
		"""REGRESYON: markup İÇERMEYEN düz metin hâlâ DEĞİŞMEDEN geçer."""
		for payload in (
			"a < b",
			"error: 5 < 10 gecti",
			"timeout <2 sn> asildi",
			"ConnectionError: <Response [500]>",
			"deger <bos> geldi",
			"1 < 2 < 3",
		):
			with self.subTest(payload=payload):
				self.assertEqual(mask_payload(payload), payload)
		self.assertEqual(mask_payload("x < y, sifre=SECRETVALUE123"), f"x < y, sifre={MASK}")


# ---------------------------------------------------------------------------
# Anahtar/değer katmanı — kapanmamış sınır fail-open'ı (10. tur)
# ---------------------------------------------------------------------------


class TestUnclosedValueBoundaryFailsClosed(unittest.TestCase):
	"""`_mask_delimited_pairs` "anlayamadığım yeri ham bırak" varsayımıyla çalışıyordu.

	Anahtar DOĞRU tanınıyor, ama değerin kapanış tırnağı (ya da kapanış
	parantezi) bulunamayınca `_scan_value` `None` dönüyor ve DEĞER HİÇ
	MASKELENMİYORDU. Bu, XML tarafının 7. turda öğrendiği doktrinin
	("sınırı güvenle belirleyemiyorsan HAM BIRAKMA, kapat") anahtar/değer
	tarafına HİÇ uygulanmamış hâliydi.

	ERİŞİLEBİLİRLİK ÖLÇÜLDÜ: `log.py::MAX_BODY_BYTES` (64 KiB) kırpması
	OTOMATİKTİR ve gövdenin SONUNDAN keser; kesim bir değerin ortasına
	düştüğünde tam olarak bu şekil oluşur. 301 kesim noktalı süpürme
	(ÖNCE → SONRA, ham sızan kesim noktası sayısı):

		JSON gövde:         4 → 0
		Python-repr gövde:  4 → 0
		XML / CDATA / öznitelikli XML / HTTP başlık / YAML / curl / SOAP:  0 → 0

	`secret_values` bu sınıfta YARDIM ETMEZ: taşıyıcının YANITINDA dönen bir
	oturum jetonunun değeri önceden bilinmez, dolayısıyla `strip_partial_secret_tail`
	de devreye giremez — ANAHTAR-tabanlı bu katman TEK savunmadır.
	"""

	#: Ana oturumun ölçtüğü dört sızıntı vektörü + tırnak/parantez varyantları.
	LEAK_VECTORS = {
		"json_double_quote": f'{{"a":1,"sifre":"{_XML_SECRET}',
		"equals_double_quote": f'sifre="{_XML_SECRET}',
		"equals_single_quote": f"sifre='{_XML_SECRET}",
		"json_api_key": f'{{"api_key":"{_XML_SECRET}',
		"python_repr_single_quote": f"{{'sifre': '{_XML_SECRET}",
		"tuple_value_unclosed": f"auth=('user','{_XML_SECRET}",
		"unclosed_mid_text": f'sifre="{_XML_SECRET}, digerleri devam ediyor',
		"unclosed_then_newline": f'sifre="{_XML_SECRET}\ntakip=TR-123456',
	}

	def test_measured_leak_vectors_are_masked(self):
		for label, payload in self.LEAK_VECTORS.items():
			with self.subTest(case=label):
				masked = mask_payload(payload)
				self.assertNotIn(_XML_SECRET, masked, "HAM jeton kaldı")
				self.assertTrue(masked.endswith(MASK), masked)

	def test_leak_vectors_are_masked_in_every_wrapper(self):
		"""Tek küme kuralı: dict/bytes/list kabında da aynı sonuç."""
		for label, payload in self.LEAK_VECTORS.items():
			with self.subTest(case=label):
				self.assertNotIn(_XML_SECRET, str(mask_payload({"response_body": payload})))
				self.assertNotIn(_XML_SECRET, str(mask_payload(payload.encode("utf-8"))))
				self.assertNotIn(_XML_SECRET, str(mask_payload([{"a": [payload]}])))

	def test_unquoted_value_was_already_fail_closed(self):
		"""Boşluk YALNIZ tırnaklı/parantezli şekildeydi — tırnaksız kardeş ZATEN kapalıydı.

		Sonlandırıcı bulunamayınca değer metnin sonuna kadar maskeleniyordu; bu
		tur tırnaklı şekilleri o davranışla SİMETRİK hâle getirir.
		"""
		self.assertEqual(mask_payload(f"sifre={_XML_SECRET}"), f"sifre={MASK}")
		self.assertEqual(mask_payload(f"sifre: {_XML_SECRET}"), f"sifre: {MASK}")
		self.assertEqual(mask_payload(f'{{"a":1,"sifre":{_XML_SECRET}'), f'{{"a":1,"sifre":"{MASK}"')

	def test_opening_quote_is_kept_and_closing_quote_is_not_claimed(self):
		"""Kapanış tırnağı YAZILMAZ: "değer burada bitti" YANLIŞ iddiası kurulmaz."""
		self.assertEqual(mask_payload(f'sifre="{_XML_SECRET}'), f'sifre="{MASK}')
		self.assertEqual(mask_payload(f"sifre='{_XML_SECRET}"), f"sifre='{MASK}")

	def test_bracket_value_over_budget_also_fails_closed(self):
		"""`_match_bracket` `None`'ı İKİ durumu birleştirir; ikisi de kapalı olmalı.

		(1) kapanış hiç yok (kırpma), (2) kapanış `_MAX_BRACKET_SCAN` bütçesinin
		ötesinde. İkisi de ÖLÇÜLDÜ ve ham sızıyordu.
		"""
		truncated = f"auth=('user','{_XML_SECRET}"
		over_budget = f"auth=('user','{_XML_SECRET}'," + "x" * 5_000 + ")"
		for payload in (truncated, over_budget):
			with self.subTest(payload=payload[:40]):
				self.assertNotIn(_XML_SECRET, mask_payload(payload))

	# --- KAPANMIŞ DEĞER REGRESYONU — bu kural oraya SIZARSA kuyruk yok olur ---

	def test_closed_values_behave_exactly_as_before(self):
		"""KRİTİK: fail-closed dal yalnız `None` sınırında işler.

		Kapanmış bir değerde kuralın sızması gövdenin TÜM kuyruğunu silerdi —
		9. turda XML tarafında ölçülen ve geri alınan hatanın ta kendisi.
		"""
		cases = {
			'{"sifre":"X","takip":"TR-9"}': '{"sifre": "***", "takip": "TR-9"}',
			f'sifre="{_XML_SECRET}" takip=TR-9': f'sifre="{MASK}" takip=TR-9',
			f"sifre='{_XML_SECRET}' takip=TR-9": f"sifre='{MASK}' takip=TR-9",
			f"auth=('user','{_XML_SECRET}') takip=TR-9": f"auth={MASK} takip=TR-9",
			f"Authorization: Basic {_XML_SECRET}\nX-Takip: TR-9": f"Authorization: {MASK}\nX-Takip: TR-9",
		}
		for payload, expected in cases.items():
			with self.subTest(payload=payload[:40]):
				self.assertEqual(mask_payload(payload), expected)

	def test_closed_json_keeps_the_diagnostic_tail(self):
		masked = mask_payload(f'{{"sifre":"{_XML_SECRET}","takip":"TR-9","durum":"OK"}}')
		self.assertNotIn(_XML_SECRET, masked)
		self.assertIn("TR-9", masked)
		self.assertIn("OK", masked)

	def test_truncation_sweep_leaks_nothing(self):
		"""64 KiB kırpmasının kanonik şekli: 301 kesim noktası, HEDEF 0 ham sızıntı."""
		bodies = {
			"json": (
				f'{{"islem":"gonderi","takip":"TR-123456","sifre":"{_XML_SECRET}",'
				f'"adres":{{"il":"Istanbul"}},"api_key":"{_XML_SECRET}","durum":"OK"}}'
			),
			"python_repr": f"{{'islem': 'gonderi', 'sifre': '{_XML_SECRET}', 'takip': 'TR-123456'}}",
			"xml": f"<E><H><Sifre>{_XML_SECRET}</Sifre></H><B><Takip>TR-9</Takip></B></E>",
			"xml_attr": f'<R><Sifre deger="{_XML_SECRET}">x</Sifre><Takip>TR-9</Takip></R>',
			"headers": f"POST /x HTTP/1.1\nAuthorization: Basic {_XML_SECRET}\nX-Takip: TR-9\n",
			"yaml": f"islem: gonderi\nsifre: {_XML_SECRET}\ntakip: TR-123456\n",
			"curl": f"curl -X POST -H 'X-Api-Key: {_XML_SECRET}' https://api.kargo.tr/v1",
		}
		points = 301
		for label, body in bodies.items():
			leaked = 0
			size = len(body)
			for step in range(points):
				cut = 1 + (step * (size - 1)) // (points - 1)
				piece = body[:cut]
				if _XML_SECRET in piece and _XML_SECRET in mask_payload(piece):
					leaked += 1
			with self.subTest(body=label):
				self.assertEqual(leaked, 0, f"{label}: {leaked}/{points} kesim noktası ham sızdırdı")

	def test_overmasking_locks_stay_closed(self):
		"""9. turun aşırı-maskeleme kazanımları BOZULMAMALI."""
		for payload in (
			"a < b",
			"error: 5 < 10 gecti",
			"timeout <2 sn> asildi",
			"ConnectionError: <Response [500]>",
			"deger <bos> geldi",
			"1 < 2 < 3",
			'<Adres il="Istanbul" ilce="Sisli"/>',
		):
			with self.subTest(payload=payload):
				self.assertEqual(mask_payload(payload), payload)
		self.assertEqual(mask_payload("x < y, sifre=SECRETVALUE123"), f"x < y, sifre={MASK}")

	def test_diagnostic_fields_stay_visible(self):
		for field in (
			"tracking_number",
			"barcode",
			"order_no",
			"status_code",
			"idempotency_key",
			"request_id",
			"hata_kodu",
			"durum_kodu",
		):
			with self.subTest(field=field):
				self.assertIn("TR-123456", mask_payload(f'{{"{field}":"TR-123456"}}'))
				# Kapanmamış tırnak: alan HASSAS DEĞİL, fail-closed dal HİÇ girmemeli.
				self.assertIn("TR-123456", mask_payload(f'{{"{field}":"TR-123456'))


# ---------------------------------------------------------------------------
# Anahtar normalizasyonu — rakam bitişik ve NFD regresyonları
# ---------------------------------------------------------------------------


class TestKeyNormalizationRegressions(unittest.TestCase):
	"""Ölçülmüş iki kör nokta: harf↔rakam sınırı ve NFD Unicode."""

	#: TR kargo SOAP'ı çok hesaplı kurulumlarda rutin olarak bu adları taşır.
	DIGIT_ADJACENT = (
		"password2",
		"Password1",
		"sifre2",
		"Sifre2",
		"şifre2",
		"apiKey2",
		"api_key2",
		"token1",
		"pwd1",
		"Kod2",
		"musteri_kodu2",
		"secret1",
		"key2",
	)

	def _leaks(self, key: str) -> list[str]:
		"""Anahtarı DÖRT taşıma biçiminde dener; sızan biçimleri döndürür."""
		probes = {
			"querystring": f"{key}={_SECRET}",
			"json_text": f'{{"{key}": "{_SECRET}"}}',
			"xml": f"<{key}>{_SECRET}</{key}>",
			"mapping": {key: _SECRET},
		}
		return [name for name, probe in probes.items() if _SECRET in str(mask_payload(probe))]

	def test_digit_adjacent_keys_are_masked(self):
		"""`secret_2` maskeleniyordu ama `secret2` HAM geçiyordu — boşluk kapandı."""
		for key in self.DIGIT_ADJACENT:
			with self.subTest(key=key):
				self.assertEqual(self._leaks(key), [])

	def test_delimited_siblings_still_work(self):
		"""Rakam sınırı eklenirken çalışan vaka bozulmamalı."""
		for key in ("secret_2", "password_2", "api_key_v2"):
			with self.subTest(key=key):
				self.assertEqual(self._leaks(key), [])

	def test_nfd_decomposed_keys_are_masked(self):
		"""`unicodedata.normalize('NFD', 'ŞİFRE')` HAM sızıyordu.

		NFD'de `ş` = `s` + U+0327 (combining cedilla) ve hem denylist hem
		`_TR_ASCII_MAP` tek kod noktalı harf bekliyordu. NFD, macOS kaynaklı
		gövdelerin ve bazı Java/.NET SOAP yığınlarının VARSAYILANIDIR.
		"""
		import unicodedata

		for key in ("ŞİFRE", "şifre", "MÜŞTERİ_KODU", "Şifre", "şifre2"):
			with self.subTest(key=key):
				self.assertEqual(self._leaks(unicodedata.normalize("NFD", key)), [])

	def test_nfc_spelling_still_masked(self):
		"""NFC yazımlar zaten çalışıyordu; NFKC eklenirken bozulmadığının kanıtı."""
		for key in ("ŞİFRE", "şifre", "MÜŞTERİ_KODU", "musteriŞifre"):
			with self.subTest(key=key):
				self.assertEqual(self._leaks(key), [])

	def test_diagnostic_keys_are_still_visible(self):
		"""Yanlış pozitif ödünleşmesi kontrol altında: teşhis alanları GÖRÜNÜR kalmalı."""
		for key in ("barcode", "tracking_number", "idempotency_key", "order_no", "status_code"):
			with self.subTest(key=key):
				self.assertIn(_SECRET, mask_payload(f"{key}={_SECRET}"))


# ---------------------------------------------------------------------------
# Tek doğruluk kaynağı
# ---------------------------------------------------------------------------


class TestContractSingleSource(unittest.TestCase):
	"""`VALID_OPERATIONS` DÖRT yerde yazılıydı; sapma sessiz veri kaybı üretir."""

	@staticmethod
	def _doctype_json() -> dict:
		path = (
			Path(frappe.get_app_path("tradehub_core"))
			/ "tradehub_core"
			/ "doctype"
			/ "carrier_integration_log"
			/ "carrier_integration_log.json"
		)
		return json.loads(path.read_text(encoding="utf-8"))

	def _options(self, fieldname: str) -> list[str]:
		for field in self._doctype_json()["fields"]:
			if field.get("fieldname") == fieldname:
				return field["options"].split("\n")
		raise AssertionError(f"{fieldname} alanı DocType JSON'unda yok")

	def test_log_module_reuses_constants(self):
		self.assertIs(VALID_OPERATIONS, INTEGRATION_LOG_OPERATIONS)
		self.assertIs(VALID_DIRECTIONS, INTEGRATION_LOG_DIRECTIONS)

	def test_constants_order_matches_set(self):
		self.assertEqual(frozenset(INTEGRATION_LOG_OPERATION_ORDER), INTEGRATION_LOG_OPERATIONS)
		self.assertEqual(frozenset(INTEGRATION_LOG_DIRECTION_ORDER), INTEGRATION_LOG_DIRECTIONS)

	def test_doctype_operation_options_match_constants(self):
		self.assertEqual(self._options("operation"), list(INTEGRATION_LOG_OPERATION_ORDER))

	def test_doctype_direction_options_match_constants(self):
		self.assertEqual(self._options("direction"), list(INTEGRATION_LOG_DIRECTION_ORDER))

	def test_masked_fields_include_error_message(self):
		"""İki katman aynı kör noktayı paylaşıyordu: `error_message` ikisinde de yoktu."""
		self.assertIn("error_message", MASKED_LOG_FIELDS)

	def test_contract_declares_every_field_that_is_actually_masked(self):
		"""Sözleşme ÜÇ alan bildiriyor, gerçek maskeleme DÖRDÜNÜ kapsıyordu.

		Sapma üç tur devredildi (`log.py` yorumunda "bu turda kapsam dışı" olarak
		duruyordu) ve panele EKSİK bildirim gidiyordu: `error_code` hem yazıcıda
		hem DocType controller'ında maskeleniyor. Referans yazıcının DAVRANIŞIDIR.
		"""
		from tradehub_core.logistics.contract import PROVISIONAL_ENTITIES

		self.assertEqual(
			sorted(PROVISIONAL_ENTITIES["integration_log"]["masked_fields"]),
			sorted(CONTROLLER_MASKED_FIELDS),
		)


# ---------------------------------------------------------------------------
# Yazıcı
# ---------------------------------------------------------------------------


class _IntegrationLogBase(FrappeTestCase):
	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		self.assertIsNotNone(self.carrier, "Seed edilmiş Logistics Provider yok")

	def tearDown(self):
		frappe.db.delete(INTEGRATION_LOG_DOCTYPE, {"carrier": self.carrier})
		frappe.db.commit()

	def _write(self, **overrides) -> str | None:
		payload = {
			"carrier": self.carrier,
			"operation": "create_shipment",
			"direction": "outbound",
			"succeeded": True,
		}
		payload.update(overrides)
		return write_integration_log(**payload)


class TestIntegrationLogWriter(_IntegrationLogBase):
	def test_successful_write(self):
		name = self._write(http_status=200, duration_ms=350, attempt=1, is_retriable=False)
		self.assertIsNotNone(name)

		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertEqual(doc.carrier, self.carrier)
		self.assertEqual(doc.operation, "create_shipment")
		self.assertEqual(doc.direction, "outbound")
		self.assertEqual(doc.succeeded, 1)
		self.assertEqual(doc.http_status, 200)
		self.assertEqual(doc.duration_ms, 350)
		self.assertEqual(doc.attempt, 1)
		self.assertEqual(doc.is_retriable, 0)

	def test_never_raises_and_returns_none_on_failure(self):
		"""Log yazımı çökse bile iş akışı KIRILMAZ."""
		with (
			mock.patch("frappe.get_doc", side_effect=RuntimeError("db down")),
			mock.patch("frappe.log_error") as logged,
		):
			result = self._write()

		self.assertIsNone(result)
		self.assertTrue(logged.called, "Sessiz yutma yasak — frappe.log_error çağrılmalı")

	def test_never_raises_even_when_log_error_itself_raises(self):
		"""REGRESYON: `log_error` bir Error Log SATIRI yazar — DB çöktüyse o da patlar.

		Eski testte `log_error` mock'landığı için bu dal hiç koşmuyordu ve
		istisna gerçek hayatta dışarı sızıyordu (konteynerde doğrulandı).
		"""
		with (
			mock.patch("frappe.get_doc", side_effect=RuntimeError("db down")),
			mock.patch("frappe.log_error", side_effect=RuntimeError("error log da yazılamıyor")),
		):
			self.assertIsNone(self._write())

	def test_contract_violation_survives_failing_log_error(self):
		"""`_split_choice` içindeki `log_error` de korumalı olmalı."""
		with mock.patch("frappe.log_error", side_effect=RuntimeError("boom")):
			name = self._write(operation="frobnicate")
		self.assertIsNotNone(name, "İhlal kaydı, log_error patlasa bile yazılmalı")

	def test_masking_applied_even_if_caller_skips_it(self):
		"""Çağıran ham credential geçse bile sütuna maskelenmiş hali yazılır."""
		name = self._write(
			request_body={"api_key": _SECRET, "nested": {"webhook_secret": _SECRET}},
			response_body=json.dumps({"access_token": _SECRET, "status": "OK"}),
		)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)

		self.assertNotIn(_SECRET, doc.request_body)
		self.assertNotIn(_SECRET, doc.response_body)
		self.assertIn(MASK, doc.request_body)
		self.assertIn("OK", doc.response_body)

	def test_soap_body_is_masked_end_to_end(self):
		name = self._write(
			request_body=f"<Login><Sifre>{_SECRET}</Sifre><MusteriAdi>İstoç</MusteriAdi></Login>",
		)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(_SECRET, doc.request_body)
		self.assertIn("İstoç", doc.request_body)

	def test_error_message_is_masked(self):
		"""REGRESYON: `error_message` yalnız kırpılıyordu, HİÇ maskelenmiyordu.

		`requests` bağlantı hatası metni tam URL'i query string'iyle taşır.
		`error_code` üzerinde de assert var: davranışı testten OKUNABİLİR kılmak
		için (QA turu bulgusu — eskiden alan yazılıyor ama hiç doğrulanmıyordu).
		"""
		raw = (
			"ConnectionError: HTTPSConnectionPool(host='kargo.example.com'): "
			f"/api/v1/gonderi?musteri_kodu=42&sifre={_SECRET} bağlanılamadı"
		)
		name = self._write(
			succeeded=False,
			error_message=raw,
			error_code=f"AUTH_FAILED sifre={_SECRET}",
			secret_values=(),
		)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)

		self.assertNotIn(_SECRET, doc.error_message)
		self.assertIn(MASK, doc.error_message)
		self.assertIn("kargo.example.com", doc.error_message)
		# `error_code` de MASKELENİR — yazıcı yolu bunu hep yapıyordu ama test
		# etmiyordu, controller yolu ise hiç yapmıyordu (bkz. CONTROLLER_MASKED_FIELDS).
		self.assertNotIn(_SECRET, doc.error_code)
		self.assertIn(MASK, doc.error_code)

	def test_error_code_is_redacted_by_value(self):
		name = self._write(succeeded=False, error_code=f"E-{_SECRET}", secret_values=[_SECRET])
		self.assertNotIn(_SECRET, frappe.db.get_value(INTEGRATION_LOG_DOCTYPE, name, "error_code"))

	def test_contract_violation_value_is_masked_in_envelope(self):
		"""MAJOR: `violations` zarfa HAM konuyordu — ne maskeleme ne redaksiyon dokunuyordu."""
		with mock.patch("frappe.log_error"):
			name = self._write(operation=f"sifre={_SECRET}", secret_values=[_SECRET])

		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(_SECRET, doc.request_body)
		self.assertIn(MASK, json.loads(doc.request_body)["_contract_violation"]["operation"])

	def test_contract_violation_value_is_masked_in_error_log(self):
		"""MAJOR: `_split_choice` ham değeri **Error Log**'a yazıyordu.

		Error Log, `Carrier Integration Log`'dan DAHA GENİŞ okuma yetkisine
		sahiptir ve `MASKED_LOG_FIELDS` oraya HİÇ uygulanmaz — bu, "çağıranın
		maskelemeyi atlaması MÜMKÜN DEĞİL" invaryantını delen yoldu.
		"""
		with mock.patch("frappe.log_error") as logged:
			self._write(operation=f"sifre={_SECRET}", secret_values=[_SECRET])

		written = " ".join(str(call) for call in logged.call_args_list)
		self.assertTrue(logged.called)
		self.assertNotIn(_SECRET, written)

	def test_deeply_nested_body_does_not_drop_the_log_row(self):
		"""MAJOR: 3 KB'lık iç içe JSON `RecursionError` → yazıcı `None` → SATIR DÜŞÜYORDU.

		`direction='inbound'` gövdesi saldırgan kontrolünde olduğu için bu bir
		denetim izi BASTIRMA yoluydu.
		"""
		self.assertIsNotNone(
			self._write(direction="inbound", request_body='{"a":' * 500 + "1" + "}" * 500, secret_values=())
		)

	def test_escape_heavy_body_respects_byte_budget(self):
		"""MAJOR: zarf bütçesi JSON KAÇIŞINI saymıyordu — ölçüldü: 130.963 bayt (2.00x).

		Alan `Code`/longtext olduğu için insert patlamıyor; hata SESSİZDİ ve log
		tablosu iki katı hızla şişiyordu (gövde kısmen saldırgan kontrolünde).
		"""
		for label, body in (
			("tırnak-yoğun", '"' * (MAX_BODY_BYTES * 3)),
			("ters-bölü yoğun", "\\" * (MAX_BODY_BYTES * 3)),
			("satır-sonu yoğun", "\n" * (MAX_BODY_BYTES * 3)),
			("karışık", ('"\\\n a' * (MAX_BODY_BYTES // 2))),
		):
			name = self._write(response_body=body, secret_values=())
			stored = frappe.db.get_value(INTEGRATION_LOG_DOCTYPE, name, "response_body")
			self.assertLessEqual(len(stored.encode("utf-8")), MAX_BODY_BYTES, label)
			json.loads(stored)  # zarf HER KOŞULDA ayrıştırılabilir kalmalı

	def test_envelope_shrink_does_not_mutate_caller_dict(self):
		"""QA: `truncated['envelope_shrunk'] = True` çağıranın iç sözlüğünü mutasyona uğratıyordu."""
		truncated = {"field": "body", "original_bytes": 10}
		envelope = {"_truncated": truncated, "body": '"' * (MAX_BODY_BYTES * 2)}

		log_module._serialize_envelope(envelope)
		self.assertNotIn("envelope_shrunk", truncated)

	def test_truncated_body_leaves_no_secret_prefix(self):
		"""MAJOR: kırpma sınırında sırrın YARISI ham kalıyordu (ölçüldü: 202 karakter)."""
		secret = "S" + "k" * 306 + "E"
		body = "A" * (MAX_BODY_BYTES - 202) + secret + "B" * 500

		name = self._write(response_body=body, secret_values=[secret])
		stored = frappe.db.get_value(INTEGRATION_LOG_DOCTYPE, name, "response_body")
		for length in range(6, len(secret) + 1):
			self.assertNotIn(secret[:length], stored, f"ön ek uzunluğu={length}")

	def test_omitted_secret_values_is_warned_once(self):
		"""MAJOR: birincil savunma SESSİZCE kapalı kalabiliyordu.

		İmzayı zorunlu kılmak `adapters/http_client.py`'yi kırardı; bunun yerine
		"unuttum" (argüman hiç yok) ile "sır yok" (`secret_values=()`) ayrıştırılır.
		"""
		with mock.patch.object(log_module, "_omission_warned", False):
			with mock.patch("frappe.log_error") as logged:
				self.assertIsNotNone(self._write())
			titles = [call.args[1] for call in logged.call_args_list if len(call.args) > 1]
			self.assertIn("logistics.integration.secret_values_omitted", titles)

		with mock.patch("frappe.log_error") as logged:
			self.assertIsNotNone(self._write(secret_values=()))
		self.assertFalse(logged.called, "Açıkça `()` geçen çağrı UYARILMAMALI")

	def test_extra_secret_values_apply_without_silencing_the_sentinel(self):
		"""AYRI KANAL: adapter jetonu `secret_values` HİÇ geçilmeden de redakte edilir.

		Kimlik dokümanının plaintext'i okunamadığında çağıran `secret_values`'ı
		bilerek geçmez (nöbetçi tetiklensin diye). Eskiden `extra` sırlar aynı
		argümanda taşındığı için onlar da birlikte düşüyordu — oysa adapter'ın
		ürettiği kısa ömürlü jeton taşıyıcının YANITINDA geri döner ve
		denylist'in en kolay atladığı materyaldir.
		"""
		token = "OTURUM_JETONU_777"
		with mock.patch.object(log_module, "_omission_warned", False):
			with mock.patch("frappe.log_error") as logged:
				name = self._write(
					response_body=f"<Xyz42>{token}</Xyz42>",
					extra_secret_values=[token],
				)
			titles = [call.args[1] for call in logged.call_args_list if len(call.args) > 1]
			self.assertIn(
				"logistics.integration.secret_values_omitted",
				titles,
				"`extra_secret_values` nöbetçiyi SUSTURDU",
			)

		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(token, doc.response_body)

	def test_extra_secret_values_merge_with_the_primary_set(self):
		"""İki kaynak birleşir — biri diğerini bastırmaz."""
		token = "OTURUM_JETONU_777"
		name = self._write(
			response_body=f"<A>{_SECRET}</A><B>{token}</B>",
			secret_values=[_SECRET],
			extra_secret_values=[token],
		)

		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(_SECRET, doc.response_body)
		self.assertNotIn(token, doc.response_body)

	def test_same_name_descendant_never_reaches_the_stored_column(self):
		"""UÇTAN UCA (7. tur): `_find_close_tag` sızıntısı DocType sütununa iniyordu.

		Tehdit modeli modülün kendi gerekçesi: taşıyıcının YANITINDA dönen oturum
		jetonu `secret_values` içinde YOKTUR (burada bilerek geçilmiyor), yani
		birincil katman tanım gereği kapalı ve kırılan ikincil katman TEK savunma.
		`Carrier Integration Log`'u okuyan `Carrier Integration Manager` jetonu düz
		metin görüyordu.
		"""
		token = "SESSIONTOKEN_ABC999"
		body = f"<LoginResponse><Kod><Kod>01</Kod>{token}</Kod></LoginResponse>"

		name = self._write(response_body=body, secret_values=())

		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(token, doc.response_body)

	def test_error_message_redacted_by_value(self):
		"""Anahtar adı tanınmasa bile bilinen DEĞER birebir silinir."""
		name = self._write(
			succeeded=False,
			error_message=f"TimeoutError: token <{_SECRET}> ile bağlantı kurulamadı",
			secret_values=[_SECRET],
		)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(_SECRET, doc.error_message)

	def test_secret_values_redacted_in_bodies_and_headers(self):
		name = self._write(
			request_body={"gorunmez": _SECRET},
			request_headers={"X-Trace": f"trace-{_SECRET}"},
			response_body=f"<Sonuc>{_SECRET}</Sonuc>",
			secret_values=[_SECRET],
		)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(_SECRET, doc.request_body)
		self.assertNotIn(_SECRET, doc.response_body)

	def test_headers_are_masked_and_folded_into_request_body(self):
		name = self._write(
			request_body={"order": "ORD-1"},
			request_headers={"Authorization": f"Bearer {_SECRET}", "Content-Type": "application/json"},
		)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		envelope = json.loads(doc.request_body)

		self.assertEqual(envelope["headers"]["Authorization"], MASK)
		self.assertEqual(envelope["headers"]["Content-Type"], "application/json")
		self.assertEqual(envelope["body"]["order"], "ORD-1")

	def test_envelope_key_order_puts_body_last(self):
		"""Kırpma önce en ucuz veriyi budasın: metaveri başta, gövde sonda."""
		name = self._write(
			operation="frobnicate",
			request_body={"order": "ORD-1"},
			request_headers={"Content-Type": "application/json"},
		)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		keys = list(json.loads(doc.request_body).keys())
		self.assertEqual(keys, ["_contract_violation", "headers", "body"])

	def test_large_body_envelope_stays_parseable(self):
		"""Kırpılmış gövde ARTIK ayrıştırılabilir bir zarfın içinde."""
		huge = {"data": "x" * (MAX_BODY_BYTES * 3)}
		name = self._write(response_body=huge)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)

		envelope = json.loads(doc.response_body)  # patlarsa F3 de patlıyor demektir
		self.assertTrue(envelope["_truncated"]["original_bytes"] > MAX_BODY_BYTES)
		self.assertIsInstance(envelope["body"], str)
		self.assertLessEqual(len(doc.response_body.encode("utf-8")), MAX_BODY_BYTES + 200)

	def test_truncation_happens_before_masking(self):
		"""Maskeleme yalnız KIRPILMIŞ metni görmeli — 50 MB regex'ten geçmemeli."""
		huge = {"payload": "y" * (MAX_BODY_BYTES * 4)}
		with mock.patch(
			"tradehub_core.logistics.integration.log.mask_payload",
			side_effect=lambda body, **kwargs: body,
		) as masker:
			self._write(response_body=huge)

		seen = masker.call_args_list[-1].args[0]
		self.assertIsInstance(seen, str, "Kırpma sonrası maskelemeye metin gitmeli")
		self.assertLessEqual(len(seen.encode("utf-8")), MAX_BODY_BYTES)

	def test_small_body_is_not_truncated(self):
		name = self._write(response_body={"status": "OK"})
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertEqual(json.loads(doc.response_body), {"status": "OK"})

	def test_out_of_contract_operation_is_still_recorded(self):
		"""Sözleşme dışı değer kaydı DÜŞÜRMEZ; ham değer zarfta saklanır."""
		with mock.patch("frappe.log_error") as logged:
			name = self._write(operation="frobnicate", direction="sideways")

		self.assertIsNotNone(name, "Sözleşme ihlali kaydı düşürmemeli")
		self.assertTrue(logged.called, "İhlal Error Log'a yazılmalı")

		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		envelope = json.loads(doc.request_body)
		self.assertEqual(envelope["_contract_violation"]["operation"], "frobnicate")
		self.assertEqual(envelope["_contract_violation"]["direction"], "sideways")

	def test_contract_violation_is_queryable_via_error_code(self):
		"""Boş Select + zarf = SORGULANAMAZ. `error_code` ihlali görünür kılar."""
		with mock.patch("frappe.log_error"):
			name = self._write(operation="frobnicate")

		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertEqual(doc.error_code, CONTRACT_VIOLATION_CODE)
		self.assertTrue(
			frappe.db.exists(INTEGRATION_LOG_DOCTYPE, {"name": name, "error_code": CONTRACT_VIOLATION_CODE})
		)

	def test_existing_error_code_is_not_overwritten_by_violation(self):
		with mock.patch("frappe.log_error"):
			name = self._write(operation="frobnicate", error_code="CARRIER_TIMEOUT")
		self.assertEqual(frappe.db.get_value(INTEGRATION_LOG_DOCTYPE, name, "error_code"), "CARRIER_TIMEOUT")

	def test_unparsable_int_fields_become_zero(self):
		"""Int sütunu NULL kabul etmiyor; çevrilemeyen değer 0 olarak yazılır."""
		name = self._write(http_status="not-a-number")
		self.assertEqual(frappe.db.get_value(INTEGRATION_LOG_DOCTYPE, name, "http_status"), 0)


# ---------------------------------------------------------------------------
# Zarf bütçesi — iskelet de tavana tabi
# ---------------------------------------------------------------------------


class TestEnvelopeBudget(unittest.TestCase):
	"""2.00x bulgusunun kardeşi: yalnız `body` daraltılıyordu, İSKELET sınırsızdı."""

	def test_huge_headers_cannot_blow_the_ceiling(self):
		"""ÖLÇÜLDÜ: 2000 × 500 baytlık başlıkla çıktı 1.031.244 bayt = tavanın 15,74 katı.

		`overhead > MAX_BODY_BYTES` olduğunda `budget` sıfıra düşüyor ve döngü
		ilk turda `budget == 0` dalından tavanı AŞAN metni döndürüyordu.
		Bugün ulaşılabilir değil (başlıkları `_build_headers` kuruyor) ama
		`Carrier Account.additional_config` serbest bir JSON alanı ve
		`Carrier Integration Manager` oraya yazabiliyor.
		"""
		headers = {f"X-Diag-{index}": "h" * 500 for index in range(2000)}

		serialized = log_module._serialize_request({"ref": "SHP-1"}, headers, None, ())

		self.assertIsNotNone(serialized)
		self.assertLessEqual(len(serialized.encode("utf-8")), MAX_BODY_BYTES)

	def test_shrunk_envelope_stays_valid_json_and_marks_the_drop(self):
		"""Düşürülen parça SESSİZ kalmamalı — operatör eksiği görebilmeli."""
		headers = {f"X-Diag-{index}": "h" * 500 for index in range(2000)}

		envelope = json.loads(log_module._serialize_request({"ref": "SHP-1"}, headers, None, ()))

		self.assertTrue(envelope.get("_headers_dropped"))
		self.assertNotIn("headers", envelope)

	def test_normal_envelope_keeps_its_headers(self):
		"""Kırpma yalnız TAVANA DAYANINCA devreye girer; olağan çağrı bozulmaz."""
		envelope = json.loads(log_module._serialize_request({"ref": "SHP-1"}, {"X-Diag": "ok"}, None, ()))

		self.assertEqual(envelope["headers"], {"X-Diag": "ok"})
		self.assertNotIn("_headers_dropped", envelope)


# ---------------------------------------------------------------------------
# DocType controller — append-only + ikinci maskeleme
# ---------------------------------------------------------------------------


class TestIntegrationLogDocType(_IntegrationLogBase):
	"""Yazıcı ATLANDIĞINDA da savunma ayakta mı?"""

	def _insert_raw(self, **fields) -> str:
		payload = {
			"doctype": INTEGRATION_LOG_DOCTYPE,
			"carrier": self.carrier,
			"operation": "track",
			"direction": "inbound",
			"succeeded": 0,
		}
		payload.update(fields)
		doc = frappe.get_doc(payload)
		doc.insert(ignore_permissions=True)
		return doc.name

	def test_before_insert_masks_when_writer_is_bypassed(self):
		"""Veri taşıma script'i / test fixture'ı doğrudan insert ederse de maskelenir."""
		name = self._insert_raw(
			request_body=json.dumps({"api_key": _SECRET}),
			response_body=f"<Sifre>{_SECRET}</Sifre>",
		)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(_SECRET, doc.request_body)
		self.assertNotIn(_SECRET, doc.response_body)

	def test_before_insert_masks_error_message(self):
		"""REGRESYON: controller'ın alan listesinde `error_message` YOKTU."""
		name = self._insert_raw(error_message=f"auth başarısız: sifre={_SECRET}")
		self.assertNotIn(_SECRET, frappe.db.get_value(INTEGRATION_LOG_DOCTYPE, name, "error_message"))

	def test_before_insert_masks_error_code(self):
		"""QA: `error_code` yalnız YAZICI yolunda maskeleniyordu — asimetri ölçüldü."""
		self.assertIn("error_code", CONTROLLER_MASKED_FIELDS)

		name = self._insert_raw(error_code=f"AUTH sifre={_SECRET}")
		self.assertNotIn(_SECRET, frappe.db.get_value(INTEGRATION_LOG_DOCTYPE, name, "error_code"))

	def test_before_insert_fails_closed_when_masking_explodes(self):
		"""MAJOR: derinlemesine-savunma katmanı ÇÖKME YÜZEYİNE dönüşüyordu.

		Maskeleme patlarsa alan `***` olmalı (fail-closed) — ham değer ASLA
		kalmamalı ve insert ASLA düşmemeli.
		"""
		with (
			mock.patch(
				"tradehub_core.tradehub_core.doctype.carrier_integration_log."
				"carrier_integration_log.mask_payload",
				side_effect=RecursionError("maximum recursion depth exceeded"),
			),
			mock.patch("frappe.log_error"),
		):
			name = self._insert_raw(request_body=json.dumps({"api_key": _SECRET}))

		stored = frappe.db.get_value(INTEGRATION_LOG_DOCTYPE, name, "request_body")
		self.assertEqual(stored, MASK)

	def test_validate_blocks_update(self):
		"""Append-only: var olan kayıt güncellenemez."""
		name = self._insert_raw(error_code="E1")
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		doc.error_code = "E2"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Saklama job'ı
# ---------------------------------------------------------------------------


class TestIntegrationLogRetention(_IntegrationLogBase):
	def _age(self, name: str, days: int) -> None:
		"""Kaydın `creation` damgasını geriye alır (saklama eşiğini test etmek için)."""
		old = add_to_date(now_datetime(), days=-days)
		frappe.db.set_value(INTEGRATION_LOG_DOCTYPE, name, "creation", old, update_modified=False)
		frappe.db.commit()

	@contextmanager
	def _retention(self, days: int):
		with mock.patch.object(retention, "get_retention_days", return_value=days):
			yield

	def test_expired_deleted_and_recent_kept(self):
		old_names = [self._write(error_code=f"OLD-{i}") for i in range(3)]
		fresh = self._write(error_code="FRESH")
		for name in old_names:
			self._age(name, 120)

		with self._retention(90):
			result = retention.purge_expired_integration_logs(requeue=False)

		self.assertEqual(result["deleted"], 3)
		for name in old_names:
			self.assertFalse(frappe.db.exists(INTEGRATION_LOG_DOCTYPE, name))
		self.assertTrue(frappe.db.exists(INTEGRATION_LOG_DOCTYPE, fresh))

	def test_batch_limit_is_respected(self):
		names = [self._write(error_code=f"BATCH-{i}") for i in range(5)]
		for name in names:
			self._age(name, 200)

		with self._retention(90):
			result = retention.purge_expired_integration_logs(limit=2, requeue=False)

		self.assertEqual(result["deleted"], 2)
		self.assertEqual(frappe.db.count(INTEGRATION_LOG_DOCTYPE, {"carrier": self.carrier}), 3)

	def test_explicit_limit_does_not_requeue(self):
		"""Çağıran kısmi koşum İSTEDİYSE geride kalmak arıza değildir."""
		for name in [self._write(error_code=f"L-{i}") for i in range(4)]:
			self._age(name, 200)

		with self._retention(90), mock.patch.object(retention, "_enqueue_remaining") as enq:
			result = retention.purge_expired_integration_logs(limit=1)

		self.assertFalse(enq.called)
		self.assertFalse(result["requeued"])

	def test_time_budget_stops_run_and_requeues_remainder(self):
		"""Tavan artık KAYIT değil SÜRE; dolduğunda kalan iş sessizce bırakılmaz."""
		for name in [self._write(error_code=f"B-{i}") for i in range(5)]:
			self._age(name, 200)

		with (
			self._retention(90),
			mock.patch.object(retention, "DELETE_CHUNK_SIZE", 2),
			mock.patch.object(retention, "_enqueue_remaining", return_value=True) as enq,
			mock.patch("frappe.log_error") as logged,
		):
			result = retention.purge_expired_integration_logs(time_budget=0.0)

		self.assertEqual(result["deleted"], 2)
		self.assertTrue(result["budget_exhausted"], "Süre bütçesi dolduğu işaretlenmeli")
		self.assertGreaterEqual(result["remaining"], 3)
		self.assertTrue(result["requeued"])
		self.assertTrue(enq.called)
		self.assertTrue(logged.called, "Sessizce geride kalmak yasak — uyarı loglanmalı")

	def test_remaining_is_zero_when_caught_up(self):
		for name in [self._write(error_code=f"C-{i}") for i in range(2)]:
			self._age(name, 200)

		with self._retention(90):
			result = retention.purge_expired_integration_logs(requeue=False)

		self.assertEqual(result["remaining"], 0)
		self.assertFalse(result["budget_exhausted"])

	def test_retention_disabled_deletes_nothing(self):
		name = self._write(error_code="KEEP")
		self._age(name, 500)

		with self._retention(0):
			result = retention.purge_expired_integration_logs()

		self.assertEqual(result["deleted"], 0)
		self.assertEqual(result["skipped"], "retention_disabled")
		self.assertTrue(frappe.db.exists(INTEGRATION_LOG_DOCTYPE, name))

	def test_zero_limit_skips(self):
		result = retention.purge_expired_integration_logs(limit=0)
		self.assertEqual(result["skipped"], "zero_limit")

	def test_default_retention_is_90_days(self):
		self.assertEqual(retention.DEFAULT_RETENTION_DAYS, 90)

	def test_settings_value_is_used(self):
		original = frappe.db.get_single_value("Logistics Settings", retention.RETENTION_FIELD)
		try:
			frappe.db.set_single_value("Logistics Settings", retention.RETENTION_FIELD, 7)
			self.assertEqual(retention.get_retention_days(), 7)
		finally:
			frappe.db.set_single_value("Logistics Settings", retention.RETENTION_FIELD, original or 90)
			frappe.db.commit()

	def test_scheduler_entry_swallows_errors(self):
		with (
			mock.patch.object(retention, "purge_expired_integration_logs", side_effect=RuntimeError("boom")),
			mock.patch("frappe.log_error") as logged,
		):
			result = retention.run_scheduled()

		self.assertEqual(result["skipped"], "error")
		self.assertTrue(logged.called)

	def test_scheduler_entry_survives_failing_log_error(self):
		with (
			mock.patch.object(retention, "purge_expired_integration_logs", side_effect=RuntimeError("boom")),
			mock.patch("frappe.log_error", side_effect=RuntimeError("error log da yazılamıyor")),
		):
			self.assertEqual(retention.run_scheduled()["skipped"], "error")

	def test_scheduler_entry_survives_failing_get_traceback(self):
		"""QA: bu modül `log.py`'nin korumalı traceback desenini DEVRALMAMIŞTI.

		`_safe_log_error(frappe.get_traceback(), ...)` deseninde `get_traceback()`
		SARMALAYICININ ARGÜMANIDIR: fırlatırsa istisna korumaya hiç girmeden
		dışarı sızar ve aynı `daily` listesindeki SONRAKİ scheduler işleri düşer.
		"""
		with (
			mock.patch.object(retention, "purge_expired_integration_logs", side_effect=RuntimeError("boom")),
			mock.patch("frappe.get_traceback", side_effect=RuntimeError("traceback alınamıyor")),
			mock.patch("frappe.log_error"),
		):
			self.assertEqual(retention.run_scheduled()["skipped"], "error")

	def test_settings_read_survives_failing_get_traceback(self):
		with (
			mock.patch("frappe.db.get_single_value", side_effect=RuntimeError("db down")),
			mock.patch("frappe.get_traceback", side_effect=RuntimeError("traceback alınamıyor")),
			mock.patch("frappe.log_error"),
		):
			self.assertEqual(retention.get_retention_days(), retention.DEFAULT_RETENTION_DAYS)


# ---------------------------------------------------------------------------
# İzinler — satıcıya HİÇ açılmaz
# ---------------------------------------------------------------------------


@contextmanager
def _acting_as(roles: list[str], seller_profile: str | None = None):
	with (
		mock.patch("frappe.get_roles", return_value=list(roles)),
		mock.patch(
			"tradehub_core.utils.tenant._get_seller_profile_for_user",
			return_value=seller_profile,
		),
	):
		yield


class TestIntegrationLogPermissions(FrappeTestCase):
	SELLER = "cil-seller@example.com"
	PLATFORM = "cil-ops@example.com"

	def test_seller_query_returns_nothing(self):
		"""Satıcı rolüyle sorgu koşulu hiçbir kaydı döndürmez."""
		with _acting_as(["Seller Logistics"], seller_profile="SEL-00001"):
			self.assertEqual(carrier_integration_log_query_conditions(self.SELLER), "1=0")

	def test_tenant_user_with_ops_role_still_blocked(self):
		"""Tenant'lı Logistics Operator da platform logunu göremez."""
		with _acting_as(["Logistics Operator"], seller_profile="SEL-00001"):
			self.assertEqual(carrier_integration_log_query_conditions(self.SELLER), "1=0")
			self.assertFalse(carrier_integration_log_has_permission(None, "read", self.SELLER))

	def test_platform_operator_can_read(self):
		with _acting_as(["Logistics Operator"], seller_profile=None):
			self.assertEqual(carrier_integration_log_query_conditions(self.PLATFORM), "")
			self.assertTrue(carrier_integration_log_has_permission(None, "read", self.PLATFORM))

	def test_platform_operator_cannot_write(self):
		"""Append-only: okuma rolleri yazma/silme yapamaz."""
		with _acting_as(["Logistics Operator"], seller_profile=None):
			for ptype in ("write", "create", "delete"):
				self.assertFalse(carrier_integration_log_has_permission(None, ptype, self.PLATFORM), ptype)

	def test_unrelated_role_blocked(self):
		with _acting_as(["Customer"], seller_profile=None):
			self.assertEqual(carrier_integration_log_query_conditions("buyer@example.com"), "1=0")
			self.assertFalse(carrier_integration_log_has_permission(None, "read", "buyer@example.com"))

	def test_guest_blocked(self):
		self.assertEqual(carrier_integration_log_query_conditions("Guest"), "1=0")
		self.assertFalse(carrier_integration_log_has_permission(None, "read", "Guest"))

	def test_administrator_full_access(self):
		self.assertEqual(carrier_integration_log_query_conditions("Administrator"), "")
		self.assertTrue(carrier_integration_log_has_permission(None, "read", "Administrator"))

	def test_system_manager_full_access(self):
		with _acting_as(["System Manager"], seller_profile=None):
			self.assertEqual(carrier_integration_log_query_conditions(self.PLATFORM), "")
			self.assertTrue(carrier_integration_log_has_permission(None, "delete", self.PLATFORM))


# ---------------------------------------------------------------------------
# 9. denetim turu — kardeş fonksiyonlar arasındaki sözleşme boşlukları
# ---------------------------------------------------------------------------

#: 311 karakterlik sır: PEM özel anahtar / SAML assertion / uzun bearer sınıfı.
#: Uzunluk BİLEREK `_ERROR_MESSAGE_LIMIT` (1000) ve `_ERROR_CODE_LIMIT` (140)
#: sınırlarını AŞACAK biçimde seçildi — kırpma sırrın ORTASINA denk gelmeli.
_LONG_SECRET = "SESSIONKEY_" + "Z" * 300


def _longest_raw_prefix(haystack: str, secret: str) -> int:
	"""`haystack` içinde HAM duran en uzun `secret` ön ekinin uzunluğu."""
	for length in range(len(secret), 3, -1):
		if secret[:length] in haystack:
			return length
	return 0


class TestShortTextPartialSecret(unittest.TestCase):
	"""BULGU 1: `_mask_short_text` kırpma sınırında YARIM sır bırakıyordu.

	`_mask_with_truncation` bu sınıfı `strip_partial_secret_tail` ile kapatmıştı;
	AYNI sözleşmeyi (KIRP → MASKELE) uygulayan `_mask_short_text` düzeltmeyi
	DEVRALMAMIŞTI — bu modülün geçmişindeki "kardeş fonksiyon" hata deseni.

	ÖNCE (ölçüldü, 9. tur):
		error_message (1000) → sırrın ilk **100** karakteri sütuna HAM.
		error_code    (140)  → sırrın ilk **105** karakteri sütuna HAM.
	SONRA: her ikisinde de ham ön ek 0.
	"""

	def setUp(self):
		self.secrets = build_secret_variants([_LONG_SECRET])

	def test_error_message_limit_leaves_no_partial_secret(self):
		# Sır 900. karakterde başlasın: 1000'lik kırpma tam ORTASINA denk gelir.
		text = "Tasiyici hata: " + "A" * 885 + _LONG_SECRET + " son"

		masked = log_module._mask_short_text(text, log_module._ERROR_MESSAGE_LIMIT, self.secrets)

		self.assertEqual(_longest_raw_prefix(masked, _LONG_SECRET), 0, masked[-80:])
		self.assertIn(MASK, masked)

	def test_error_code_limit_leaves_no_partial_secret(self):
		text = "Tasiyici hata: " + "A" * 20 + _LONG_SECRET + " son"

		masked = log_module._mask_short_text(text, log_module._ERROR_CODE_LIMIT, self.secrets)

		self.assertEqual(_longest_raw_prefix(masked, _LONG_SECRET), 0, masked[-80:])

	def test_ellipsis_is_appended_after_the_tail_is_stripped(self):
		"""SIRA BAĞLAYICI: `…` (U+2026) kuyruğa yapışırsa ön ek eşleşmesini BOZAR.

		Eski sürüm `…`'i kırpma anında ekliyordu; `strip_partial_secret_tail`
		sonradan çağrılsa bile `'...ZZZ…'` hiçbir varyantın öneki olmadığı için
		ETKİSİZ kalırdı (ölçüldü). Bu test kesme İZİNİN (`***`) doğrudan `…`'den
		önce geldiğini — yani ellipsis'in EN SON eklendiğini — sabitler.
		"""
		text = "Tasiyici hata: " + "A" * 885 + _LONG_SECRET + " son"

		masked = log_module._mask_short_text(text, log_module._ERROR_MESSAGE_LIMIT, self.secrets)

		self.assertTrue(masked.endswith(f"{MASK}…"), masked[-20:])

	def test_short_text_is_untouched_when_it_fits(self):
		"""Kırpma YOKSA ellipsis de yok — olağan çağrı bozulmamalı."""
		self.assertEqual(log_module._mask_short_text("kisa mesaj", 140, ()), "kisa mesaj")

	def test_masking_growth_truncation_also_strips_the_tail(self):
		"""Maskeleme metni uzatırsa İKİNCİ kırpma yapılır; o da yarım sır üretebilir."""
		text = "sifre=" + "B" * 400 + _LONG_SECRET

		masked = log_module._mask_short_text(text, 200, self.secrets)

		self.assertLessEqual(len(masked), 201, "limit + tek `…` karakteri")
		self.assertEqual(_longest_raw_prefix(masked, _LONG_SECRET), 0, masked[-80:])

	def test_sibling_body_path_stays_closed(self):
		"""Kardeş yol (`_mask_with_truncation`) regresyona girmemeli."""
		body = "x" * (MAX_BODY_BYTES - 100) + _LONG_SECRET

		masked, original_bytes = log_module._mask_with_truncation(body, self.secrets)

		self.assertIsNotNone(original_bytes)
		self.assertEqual(_longest_raw_prefix(masked, _LONG_SECRET), 0)


class TestNonStringDictKeys(unittest.TestCase):
	"""BULGU 2: `str` olmayan sözlük anahtarı tavanı VE tüm log satırını düşürüyordu.

	Üç adımlı zincir (ölçüldü, 9. tur):
		1. `_iterencode_bounded` `TypeError`'ı yutup `('', False)` — "taşma YOK".
		2. `_truncate_input` orijinali KIRPMADAN geri veriyor → `MAX_BODY_BYTES`
		   sessizce devre dışı (`{('tuple','key'):1, 'pad':'A'*300000}` →
		   `overflow=None`, 300 KB kırpılmadı).
		3. `_to_text` / `_serialize_envelope` içindeki `json.dumps` AYNI hatayı
		   KORUMASIZ fırlatıyor → dış `except` → **KAYIT TAMAMEN DÜŞÜYOR**.

	ERİŞİLEBİLİRLİK: bugün `http_client._log` gövdelere yalnız `str | None`
	geçiyor. Sınıf `direction='inbound'` webhook alıcısıyla açılır ve `bytes`
	anahtar egzotik DEĞİL — `urllib.parse.parse_qs(body_bytes)` doğrudan `bytes`
	anahtarlı sözlük üretir; form-encoded taşıyıcı callback'i tam bu biçimdedir.
	"""

	#: `json.dumps`'ın reddettiği anahtar türleri (`int` KABUL edilir, kontrol).
	HOSTILE_KEYS = {
		"bytes": {b"sifre": b"x"},
		"tuple": {("tuple", "key"): 1},
		"frozenset": {frozenset({1}): 2},
	}

	def test_iterencode_bounded_says_unknown_not_no_overflow(self):
		"""`except` dalı artık "taşma yok" (False) değil "BİLMİYORUM" (None) der."""
		for label, obj in self.HOSTILE_KEYS.items():
			with self.subTest(label):
				_, overflow = log_module._iterencode_bounded(obj, MAX_BODY_BYTES)
				self.assertIsNone(overflow, "False dönmek tavanı sessizce kapatıyordu")

		self.assertEqual(log_module._iterencode_bounded({5: "x"}, MAX_BODY_BYTES)[1], False)

	def test_ceiling_is_enforced_for_non_serializable_keys(self):
		"""ÖNCE: 300 KB kırpılmadan geçiyordu. SONRA: tavan uygulanır."""
		for label, obj in self.HOSTILE_KEYS.items():
			with self.subTest(label):
				body = {**obj, "pad": "A" * 300_000}

				prepared, original_bytes = log_module._truncate_input(body)

				self.assertIsNotNone(original_bytes, "kırpma kararı BİLİNMİYOR → güvenli yön: kırp")
				self.assertGreater(original_bytes, MAX_BODY_BYTES)
				self.assertLessEqual(len(str(prepared).encode("utf-8")), MAX_BODY_BYTES + 16)

	def test_small_hostile_body_keeps_its_structure(self):
		"""Sınır altındaki gövde KIRPILMAZ — yapısal maskeleme korunmalı."""
		prepared, original_bytes = log_module._truncate_input({b"sifre": b"x", "ref": "SHP-1"})

		self.assertIsNone(original_bytes)
		self.assertIsInstance(prepared, dict)
		self.assertEqual(set(prepared), {"sifre", "ref"})

	def test_serializers_never_raise_on_hostile_keys(self):
		for label, obj in self.HOSTILE_KEYS.items():
			with self.subTest(label):
				self.assertIsInstance(log_module._serialize_body(obj, ()), str)
				self.assertIsInstance(log_module._serialize_request(obj, {"X-A": "b"}, None, ()), str)
				self.assertIsInstance(log_module._to_text(obj), str)
				self.assertIsInstance(log_module._encoded_size(obj), int)
				self.assertIsInstance(
					log_module._serialize_envelope({"_truncated": {"field": "body"}, "body": obj}, ()),
					str,
				)

	def test_output_stays_parseable_json(self):
		"""F3 ekranı zarfı her koşulda ayrıştırabilmeli."""
		for label, obj in self.HOSTILE_KEYS.items():
			with self.subTest(label):
				envelope = json.loads(log_module._serialize_request(obj, {"X-A": "b"}, None, ()))
				self.assertIn("body", envelope)

	def test_bytes_key_reaches_the_denylist_after_repair(self):
		"""YAN FAYDA: `b'sifre'` → `'sifre'` olduğu için anahtar denylist'i ARTIK görüyor.

		`masking.py::_normalize_key`'in `bytes` anahtarı tanımaması AYRI bir
		bulgudur (bu turda kapsam dışı); burada yalnız onarımın denylist'e
		çalışabilir bir anahtar verdiği sabitlenir.
		"""
		self.assertEqual(json.loads(log_module._serialize_body({b"sifre": b"x"}, ())), {"sifre": MASK})

	def test_circular_reference_does_not_raise(self):
		"""`ValueError` (döngüsel referans) da aynı korumadan geçmeli."""
		body: dict = {"ref": "SHP-1"}
		body["self"] = body

		self.assertIsInstance(log_module._serialize_body(body, ()), str)

	def test_parse_qs_webhook_shape(self):
		"""Erişilebilirliğin GERÇEK vektörü: form-encoded webhook gövdesi."""
		parsed = urllib.parse.parse_qs(b"barkod=123&sifre=SUPERSECRETVALUE")

		self.assertIsInstance(next(iter(parsed)), bytes, "parse_qs bytes anahtar üretir")
		serialized = log_module._serialize_body(parsed, build_secret_variants([_SECRET]))
		self.assertIsInstance(serialized, str)
		self.assertNotIn(_SECRET, serialized)


class TestHostileBodyKeepsTheRow(_IntegrationLogBase):
	"""Sözleşme: "ASLA fırlatmaz" korunmalı ama KAYIT DA DÜŞMEMELİ (madde 3)."""

	def test_bytes_key_body_still_writes_a_row(self):
		"""ÖNCE: `None` döndü (satır tamamen kayıp). SONRA: satır yazılır."""
		name = self._write(
			direction="inbound",
			operation="webhook",
			request_body=urllib.parse.parse_qs(b"barkod=123&sifre=SUPERSECRETVALUE"),
			response_body={b"durum": b"OK"},
			secret_values=[_SECRET],
		)

		self.assertIsNotNone(name, "str olmayan anahtar denetim izini bastırmamalı")
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(_SECRET, doc.request_body)
		self.assertIn("barkod", doc.request_body)
		self.assertIn("OK", doc.response_body)

	def test_writer_never_raises_for_hostile_bodies(self):
		"""İnvaryant yeniden doğrulanır: hiçbir gövde biçimi istisna sızdırmaz."""
		circular: dict = {"ref": "SHP-1"}
		circular["self"] = circular

		for label, body in (
			("tuple-key", {("a", "b"): 1}),
			("frozenset-key", {frozenset({1}): 2}),
			("circular", circular),
			("huge-hostile", {b"k": 1, "pad": "A" * 300_000}),
		):
			with self.subTest(label):
				self.assertIsNotNone(self._write(request_body=body, secret_values=()), label)

	def test_partial_secret_never_reaches_the_error_message_column(self):
		"""BULGU 1 uçtan uca: sütunda sırrın ham ön eki KALMAMALI."""
		name = self._write(
			succeeded=False,
			error_message="Tasiyici hata: " + "A" * 885 + _LONG_SECRET + " son",
			error_code="AUTH " + "A" * 20 + _LONG_SECRET,
			secret_values=[_LONG_SECRET],
		)

		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertEqual(_longest_raw_prefix(doc.error_message, _LONG_SECRET), 0)
		self.assertEqual(_longest_raw_prefix(doc.error_code, _LONG_SECRET), 0)


# ---------------------------------------------------------------------------
# 10. denetim turu — düzeltmenin KENDİSİNİN açtığı yollar
# ---------------------------------------------------------------------------

#: Anahtar KONUMUNDA sınanan sır (`_SECRET` değer konumunda kullanılıyor).
_KEY_SECRET = "SUPERSECRET123"

#: `text` ailesinin MariaDB bayt tavanları — `Small Text` gibi varchar OLMAYAN
#: sütunlarda `_validate_length` uzunluk denetimi YAPMAZ, sınır sütunun kendisidir.
_TEXT_COLUMN_BYTES = {
	"text": 65_535,
	"mediumtext": 16_777_215,
	"longtext": 4_294_967_295,
}


class TestEllipsisBudget(unittest.TestCase):
	"""BULGU 1: `…` bütçesiz eklendiği için çıktı `limit + 1` oluyordu.

	9. tur `…`'i EN SONA taşıyıp sızıntıyı kapattı ama hiçbir kırpma adımı ona
	YER AYIRMADI. `error_code` bir `Data` alanıdır (varchar 140) ve Frappe
	`_validate_length` 141 karakteri `CharacterLengthExceededError` ile reddeder;
	dış `except` yakalar, `None` döner ve **SATIR HİÇ YAZILMAZ**.

	ÖNCE (konteynerde ölçüldü):
		girdi 140 -> cikti 140 | girdi 141 -> cikti 141 | girdi 200 -> cikti 141
		write_integration_log(error_code=140) -> KAYIT YAZILDI
		write_integration_log(error_code=200) -> KAYIT DUSTU
		130.000 örneklik fuzz: ham sır ön eki 0, **tavan aşımı 2.717**
	SONRA:
		girdi 141/200/5000 -> cikti 140 (hepsi)
		write_integration_log(error_code=200/5000) -> KAYIT YAZILDI
		aynı fuzz: ham sır ön eki 0, tavan aşımı **0**
	"""

	#: `_mask_short_text`'in üretimde çağrıldığı ÜÇ sınır.
	LIMITS = (
		log_module._ERROR_CODE_LIMIT,
		log_module._ERROR_MESSAGE_LIMIT,
		log_module._VIOLATION_LIMIT,
	)

	def test_output_never_exceeds_the_limit(self):
		"""Sınırın ETRAFINDAKİ her uzunlukta çıktı tavanın altında kalmalı."""
		for limit in self.LIMITS:
			for length in (limit - 2, limit - 1, limit, limit + 1, limit + 60, limit * 40):
				with self.subTest(limit=limit, length=length):
					out = log_module._mask_short_text("A" * length, limit, ())
					self.assertLessEqual(len(out), limit, f"{length} -> {len(out)}")

	def test_ellipsis_only_marks_a_real_truncation(self):
		"""Bütçe ayırmak "her çıktıya `…` koy" DEĞİLDİR — sığan metin bozulmaz."""
		limit = log_module._ERROR_CODE_LIMIT

		self.assertEqual(log_module._mask_short_text("A" * limit, limit, ()), "A" * limit)
		self.assertTrue(log_module._mask_short_text("A" * (limit + 1), limit, ()).endswith("…"))

	def test_masking_growth_path_also_respects_the_budget(self):
		"""İKİNCİ kırpma (maskeleme metni uzattı) da ellipsis payını ayırmalı."""
		text = "sifre=" + "B" * 400 + _LONG_SECRET

		masked = log_module._mask_short_text(text, 200, build_secret_variants([_LONG_SECRET]))

		self.assertLessEqual(len(masked), 200)
		self.assertTrue(masked.endswith("…"))

	def test_budget_did_not_reopen_the_partial_secret_leak(self):
		"""9. turun kazanımı KORUNMALI: bütçe ayırmak yarım sır bırakmamalı.

		Konteynerde 130.000 örnekle koşuldu (0 sızıntı / 0 aşım); burada aynı
		süpürmenin deterministik ve hızlı bir dilimi sabitlenir.
		"""
		import random

		rng = random.Random(20260827)
		alphabet = "ABCXYZ0189 =:,\"'{}<>&"
		for _ in range(400):
			body = "".join(
				rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(rng.randint(20, 320))
			)
			secret = "SESSIONKEY_" + body
			variants = build_secret_variants([secret])
			for limit in (log_module._ERROR_CODE_LIMIT, log_module._ERROR_MESSAGE_LIMIT):
				pad = rng.randint(0, limit + 40)
				text = "".join(rng.choice(alphabet) for _ in range(pad)) + secret + "TAIL"
				out = log_module._mask_short_text(text, limit, variants)
				self.assertLessEqual(len(out), limit)
				self.assertEqual(_longest_raw_prefix(out, secret), 0, out[-80:])


class TestColumnLimitsMatchTheDocType(FrappeTestCase):
	"""`_ERROR_CODE_LIMIT` / `_ERROR_MESSAGE_LIMIT` ↔ DocType JSON sapması KİLİTLİ.

	BULGU 1 sessiz kalabildi çünkü sabit ile sütun sınırı arasındaki eşitliği
	hiçbir şey denetlemiyordu. Sapma sessiz kaldığı sürece bulgu HER sütun sınırı
	değişikliğinde geri gelir: `error_code` `Data`(140) yerine bir `length` alırsa
	ya da fieldtype daralırsa yazıcı yine tavanı aşar ve satır DÜŞER.

	Referans üretilmiş bir kopya değil, Frappe'nin KENDİ `type_map`'i ve DocType
	JSON'unun kendisidir — `_validate_length` de tam olarak o ikisine bakar.
	"""

	@staticmethod
	def _field(fieldname: str) -> dict:
		path = (
			Path(frappe.get_app_path("tradehub_core"))
			/ "tradehub_core"
			/ "doctype"
			/ "carrier_integration_log"
			/ "carrier_integration_log.json"
		)
		for field in json.loads(path.read_text(encoding="utf-8"))["fields"]:
			if field.get("fieldname") == fieldname:
				return field
		raise AssertionError(f"{fieldname} alanı DocType JSON'unda yok")

	def _assert_limit_fits_column(self, fieldname: str, constant: int) -> None:
		field = self._field(fieldname)
		column_type, default_length = frappe.db.type_map[field["fieldtype"]]
		explicit = int(field.get("length") or 0)

		if column_type == "varchar":
			# `_validate_length` KARAKTER sayar; sabit sütunla BİREBİR eşit olmalı.
			# Küçük olsaydı teşhis boşuna kaybedilirdi, büyük olsaydı satır düşerdi.
			self.assertEqual(
				constant,
				explicit or int(default_length),
				f"{fieldname}: sabit ile sütun sınırı ayrıştı — satır DÜŞER",
			)
			return

		self.assertIn(column_type, _TEXT_COLUMN_BYTES, f"{fieldname}: tanınmayan sütun türü")
		if explicit:
			self.assertLessEqual(constant, explicit, f"{fieldname}: açık `length` sabitin altında")
		# `text` ailesinde sınır BAYTTIR; en kötü UTF-8 karakteri 4 bayt eder.
		self.assertLessEqual(constant * 4, _TEXT_COLUMN_BYTES[column_type], fieldname)

	def test_error_code_limit_matches_the_column(self):
		self._assert_limit_fits_column("error_code", log_module._ERROR_CODE_LIMIT)

	def test_error_message_limit_fits_the_column(self):
		self._assert_limit_fits_column("error_message", log_module._ERROR_MESSAGE_LIMIT)

	def test_writer_survives_a_column_length_attack(self):
		"""Sözleşme uçtan uca: uzun `error_code` denetim izini BASTIRAMAZ."""
		carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		try:
			for length in (141, 200, 5000):
				with self.subTest(length=length):
					name = write_integration_log(
						carrier=carrier,
						operation="create_shipment",
						direction="outbound",
						succeeded=False,
						error_code="A" * length,
						secret_values=(),
					)
					self.assertIsNotNone(name, "uzunluk yolu satırı düşürüyor")
					self.assertLessEqual(
						len(frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name).error_code),
						log_module._ERROR_CODE_LIMIT,
					)
		finally:
			frappe.db.delete(INTEGRATION_LOG_DOCTYPE, {"carrier": carrier})
			frappe.db.commit()


class TestSecretInKeyPosition(unittest.TestCase):
	"""BULGU 2: sözlük ANAHTARI konumundaki sır HAM yazılıyordu.

	`_redact_deep` yalnız DEĞER yapraklarını redakte ediyordu. Ölçüldü:

		_redact_deep({'SUPERSECRET123': 'v'}, …) -> {'SUPERSECRET123': 'v'}  HAM
		mask_payload('{"SUPERSECRET123":"v"}', …) -> {"***": "v"}            MASKELİ

	Yani `masking.py`'nin ilan ettiği TEK KÜME KURALI ölçülerek ihlal ediliyordu.
	9. turun `_coerce_json_keys` onarımı sınıfı AĞIRLAŞTIRMIŞTI: `bytes`/`tuple`
	anahtarlı gövdeler eskiden `TypeError` ile kaydı düşürüyor (kazara
	fail-closed), onarımdan sonra geçerli `str`'e çevrilip YAZILIYORDU — uçtan
	uca ölçüldü: `request_body: {"SUPERSECRET123": ["1"]}`.
	"""

	def setUp(self):
		self.secrets = build_secret_variants([_KEY_SECRET])

	def _serialized(self, body) -> str:
		return log_module._serialize_body(body, self.secrets)

	def test_flat_dict_key_is_redacted(self):
		self.assertEqual(log_module._redact_deep({_KEY_SECRET: "v"}, self.secrets), {MASK: "v"})

	def test_nested_dict_key_is_redacted(self):
		self.assertEqual(
			log_module._redact_deep({"data": {_KEY_SECRET: 1}}, self.secrets),
			{"data": {MASK: 1}},
		)

	def test_single_set_rule_holds_across_shapes(self):
		"""Aynı içerik dict / JSON metni / querystring — AYNI sonuç."""
		self.assertEqual(json.loads(self._serialized({_KEY_SECRET: "v"})), {MASK: "v"})
		self.assertEqual(json.loads(self._serialized(f'{{"{_KEY_SECRET}":"v"}}')), {MASK: "v"})
		self.assertNotIn(_KEY_SECRET, self._serialized(f"{_KEY_SECRET}=v"))

	def test_parse_qs_webhook_key_no_longer_leaks(self):
		"""GERÇEK vektör: `parse_qs(body_bytes)` sırrı ANAHTAR konumuna koyar."""
		body = urllib.parse.parse_qs(f"{_KEY_SECRET}=1".encode())

		serialized = self._serialized(body)

		self.assertNotIn(_KEY_SECRET, serialized)
		self.assertEqual(json.loads(serialized), {MASK: ["1"]})

	def test_header_names_are_redacted_too(self):
		"""`mask_headers` çıktısı da aynı daldan geçer — başlık ADLARI da kapanır."""
		envelope = json.loads(
			log_module._serialize_request(
				None, {_KEY_SECRET: "v", "X-Trace": _KEY_SECRET}, None, self.secrets
			)
		)

		self.assertEqual(envelope["headers"], {MASK: "v", "X-Trace": MASK})

	def test_denylist_runs_before_key_redaction(self):
		"""SIRA BAĞLAYICI: redaksiyon onarım adımına taşınsaydı `sifre` KAÇARDI.

		`_coerce_json_keys` içinde redakte edilseydi anahtar denylist'i `***`
		görür ve `b'sifre'` onarımının YAN FAYDASI kaybolurdu.
		"""
		self.assertEqual(json.loads(self._serialized({b"sifre": "X"})), {"sifre": MASK})

	def test_diagnostic_keys_stay_visible(self):
		"""AŞIRI MASKELEME YOK: yalnız `secret_values` ile eşleşen anahtar değişir."""
		diagnostic = {
			"tracking_number": "TR1",
			"barcode": "B1",
			"order_no": "O1",
			"status_code": "200",
			"idempotency_key": "IK1",
			"request_id": "RQ1",
			"hata_kodu": "E1",
		}

		self.assertEqual(sorted(log_module._redact_deep(dict(diagnostic), self.secrets)), sorted(diagnostic))
		self.assertEqual(sorted(json.loads(self._serialized(dict(diagnostic)))), sorted(diagnostic))

	def test_non_string_keys_are_passed_through_untouched(self):
		"""Redaksiyon yalnız `str` anahtara uygulanır; `int` anahtar bozulmaz."""
		self.assertEqual(log_module._redact_deep({5: "v"}, self.secrets), {5: "v"})

	def test_no_secrets_means_no_change(self):
		"""`secrets` boşken anahtarlar OLDUĞU GİBİ kalır (redaksiyon devre dışı)."""
		self.assertEqual(log_module._redact_deep({_KEY_SECRET: "v"}, ()), {_KEY_SECRET: "v"})


class _ExplodingStr:
	"""`__str__`/`__repr__`'ü istisna fırlatan gövde yaprağı."""

	def __str__(self) -> str:
		raise KeyError("bum")

	__repr__ = __str__


class _ExplodingMapping(dict):
	"""`items()`'ı `TypeError` fırlatan Mapping — `_coerce_json_keys` yolu."""

	def items(self):
		raise TypeError("items patladi")


class TestSerializersNeverRaiseOnAnyExceptionClass(unittest.TestCase):
	"""BULGU 3: "ASLA fırlatmaz" sözleşmesi DAR `except` demeti yüzünden delikti.

	`_json_text`'in iki `except`'i `(TypeError, ValueError, RecursionError)` idi;
	`default=str` KEYFİ bir `__str__` çağırır ve oradan gelen başka bir istisna
	sınıfı dışarı sızıyordu. `_truncate_structure`'daki `_coerce_json_keys(body)`
	çağrısı ise tamamen KORUMASIZDI.

	ÖNCE (ölçüldü): `_json_text`, `_to_text`, `_encoded_size`,
	`_serialize_envelope`, `_serialize_body`, `_iterencode_bounded` ve
	`_truncate_structure` HEPSİ fırlattı; `write_integration_log` `None` döndü.
	"""

	def test_every_serializer_survives_an_exploding_str(self):
		body = {"k": _ExplodingStr()}

		self.assertIsInstance(log_module._json_text(body), str)
		self.assertIsInstance(log_module._to_text(body), str)
		self.assertIsInstance(log_module._encoded_size(body), int)
		self.assertIsInstance(log_module._serialize_body(body, ()), str)
		self.assertIsInstance(log_module._serialize_request(body, {"X-A": "b"}, None, ()), str)
		self.assertIsInstance(log_module._serialize_envelope({"body": body}, ()), str)

	def test_output_stays_parseable_json(self):
		"""F3 ekranı fırlatmayan ama BOZUK bir metinle de baş edemez."""
		parsed = json.loads(log_module._json_text({"k": _ExplodingStr()}))

		self.assertEqual(parsed, {"_serialization_failed": "dict"})

	def test_truncate_structure_survives_an_exploding_items(self):
		prepared, original_bytes = log_module._truncate_structure(_ExplodingMapping(a=1))

		self.assertIsNone(original_bytes)
		self.assertEqual(prepared, {"_serialization_failed": "_ExplodingMapping"})

	def test_iterencode_still_says_unknown_not_no_overflow(self):
		"""ÜÇ DEĞERLİ SÖZLEŞME BOZULMADI: `None` = BİLMİYORUM, asla `False` değil."""
		self.assertIsNone(log_module._iterencode_bounded({"k": _ExplodingStr()}, MAX_BODY_BYTES)[1])
		self.assertIs(log_module._iterencode_bounded({"a": 1}, MAX_BODY_BYTES)[1], False)
		self.assertIs(log_module._iterencode_bounded({"a": "A" * 200}, 64)[1], True)

	def test_safe_type_name_falls_back_instead_of_raising(self):
		class _NoName:
			pass

		self.assertEqual(log_module._safe_type_name(_NoName()), "_NoName")
		self.assertIsInstance(log_module._safe_type_name(_ExplodingStr()), str)


class TestTenthRoundWriterInvariants(_IntegrationLogBase):
	"""Üç düzeltmenin uçtan uca kanıtı — sözleşmenin dört maddesi de ayakta."""

	def test_secret_in_key_position_never_reaches_the_column(self):
		"""ÖNCE: `request_body: {"SUPERSECRET123": ["1"]}` — sır SÜTUNDA HAM."""
		name = self._write(
			direction="inbound",
			operation="webhook",
			request_body=urllib.parse.parse_qs(f"{_KEY_SECRET}=1".encode()),
			request_headers={_KEY_SECRET: "v"},
			secret_values=[_KEY_SECRET],
		)

		self.assertIsNotNone(name)
		doc = frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name)
		self.assertNotIn(_KEY_SECRET, doc.request_body)

	def test_long_error_code_still_writes_the_row(self):
		"""ÖNCE: 200 karakterlik `error_code` KAYDI TAMAMEN DÜŞÜRÜYORDU."""
		name = self._write(succeeded=False, error_code="A" * 200, secret_values=())

		self.assertIsNotNone(name, "uzunluk yolu denetim izini bastırıyor")
		self.assertTrue(frappe.get_doc(INTEGRATION_LOG_DOCTYPE, name).error_code.endswith("…"))

	def test_writer_never_raises_and_keeps_the_row(self):
		"""Madde 1 + madde 3 birlikte: fırlatma YOK, `None` de YOK."""
		for label, body in (
			("exploding-str", {"k": _ExplodingStr()}),
			("exploding-items", _ExplodingMapping(a=1)),
			("secret-key", {_KEY_SECRET: "v"}),
		):
			with self.subTest(label):
				self.assertIsNotNone(self._write(request_body=body, secret_values=[_KEY_SECRET]), label)


# ---------------------------------------------------------------------------
# 10. TUR — `masking.py` bulguları (ALTI dal, hepsi ÖLÇÜLEREK açıldı)
# ---------------------------------------------------------------------------

#: Bu bloğun jetonu — bir taşıyıcının YANITINDA dönen oturum jetonu yerine geçer.
#: Değeri sistem ÖNCEDEN BİLMEZ (`secret_values`'ta YOKTUR), yani değer-tabanlı
#: BİRİNCİL katman bu sınıfların hiçbirinde yardım edemez; ölçülen tek savunma
#: anahtar/etiket tabanlı İKİNCİL katmandır.
_GAP_TOKEN = "SESSIONTOKEN_ABC999"


class TestSeparatorGapFailsClosed(unittest.TestCase):
	"""BULGU 1: ayraçtan sonra SATIR SONU gelince değer HİÇ maskelenmiyordu.

	`_scan_value`'nun boşluk penceresi yalnız `' \\t'` atlıyor ve 8 karakterle
	sınırlıydı; `=` sonrası `\\n`/`\\r` ya da 8'den çok boşluk gelince değerin
	başlangıcı bulunamıyor, fonksiyon `None` dönüyor ve `_mask_delimited_pairs`
	çifti ATLIYORDU — yani HİÇ MASKELEME YOKTU (fail-OPEN).

	ERİŞİLEBİLİR, KIRPMA GEREKTİRMEZ: XML 1.0 `Eq ::= S? '=' S?` gereği `=`
	etrafında satır sonu MEŞRUDUR ve .NET/Java SOAP yığınlarının
	öznitelik-başına-satır düzeninde rutindir. Aşağıdaki vektörlerin hepsi İYİ
	BİÇİMLİ XML'dir (ElementTree kabul eder), hiçbir fail-safe dalı tetiklenmez.

	KÖK NEDEN ASİMETRİYDİ: `_mask_tag_attributes` (9. tur) hassas ELEMANDA
	`\\r\\n\\t` atlar ve doğru maskeler; `_scan_value` hassas ÖZNİTELİKTE
	atlamıyordu — üstelik `_mask_tag_attributes` docstring'i hassas OLMAYAN
	elemanın özniteliklerini AÇIKÇA o katmana devrediyordu.
	"""

	def test_measured_leak_vectors_are_all_closed(self):
		"""Ana oturumun ölçtüğü ALTI vektör — hepsi DEĞİŞMEDEN geçiyordu."""
		vectors = (
			f'<Kayit sifre=\n"{_GAP_TOKEN}">x</Kayit>',
			f'<Kayit\n  sifre =\n  "{_GAP_TOKEN}"\n  takip="TR-1"/>',
			f'<Kayit sifre=          "{_GAP_TOKEN}"/>',
			f"<Kayit api_key=\n'{_GAP_TOKEN}'/>",
			f"<Kayit sifre=\n{_GAP_TOKEN}",
			f"Authorization:\r\n Basic {_GAP_TOKEN}",
		)
		for raw in vectors:
			with self.subTest(raw=raw[:40]):
				self.assertNotIn(_GAP_TOKEN, mask_payload(raw))

	def test_directed_sweep_leaks_nothing(self):
		"""116 vektörlük süpürme: ayraç × boşluk şekli × tırnak şekli."""
		separators = ("=", " =", "= ", " = ")
		gaps = ("\n", "\r\n", "\r", "\n  ", "  \n", "\t\n", " " * 9, " " * 12, "\n\n", "\n\t ", " \n ")
		shapes = ('<Kayit {k}{s}{g}"{t}"/>', "<Kayit {k}{s}{g}'{t}'/>", '<Kayit {k}{s}{g}"{t}">i</Kayit>')
		leaked = [
			raw
			for key in ("sifre", "api_key")
			for sep in separators
			for gap in gaps
			for shape in shapes
			for raw in (shape.format(k=key, s=sep, g=gap, t=_GAP_TOKEN),)
			if _GAP_TOKEN in mask_payload(raw)
		]

		self.assertEqual(leaked, [], f"{len(leaked)} vektör HAM sızdı")

	def test_gap_is_symmetric_with_sensitive_element_attributes(self):
		"""Aynı boşluk şekli hassas ELEMANDA da hassas ÖZNİTELİKTE de kapanır."""
		self.assertNotIn(_GAP_TOKEN, mask_payload(f'<Sifre deger=\n"{_GAP_TOKEN}"/>'))
		self.assertNotIn(_GAP_TOKEN, mask_payload(f'<Kayit sifre=\n"{_GAP_TOKEN}"/>'))

	def test_separator_at_end_of_text_fails_closed(self):
		"""Ayraçtan sonra yalnız boşluk kaldıysa değer KIRPILMIŞ olabilir."""
		self.assertEqual(mask_payload("sifre="), f"sifre={MASK}")
		self.assertEqual(mask_payload("sifre:   "), f"sifre:{MASK}")

	def test_gap_fix_does_not_touch_closed_values(self):
		"""KRİTİK REGRESYON KAPISI: kapanmış değerde kuyruk AYNEN yaşar."""
		cases = {
			'{"sifre":"X","takip":"TR-9"}': '{"sifre": "***", "takip": "TR-9"}',
			f'sifre="{_GAP_TOKEN}" takip=TR-9': f'sifre="{MASK}" takip=TR-9',
			f"Authorization: Basic {_GAP_TOKEN}\nX-Takip: TR-9": f"Authorization: {MASK}\nX-Takip: TR-9",
			f'<Kayit sifre="{_GAP_TOKEN}" takip="TR-9"/>': f'<Kayit sifre="{MASK}" takip="TR-9"/>',
		}
		for raw, expected in cases.items():
			with self.subTest(raw=raw[:40]):
				self.assertEqual(mask_payload(raw), expected)

	def test_over_masking_locks_still_hold(self):
		"""Düz metin hata mesajları DEĞİŞMEDEN geçmeye devam eder."""
		for raw in ("a < b", "error: 5 < 10 gecti", "timeout <2 sn> asildi", "1 < 2 < 3"):
			with self.subTest(raw=raw):
				self.assertEqual(mask_payload(raw), raw)

	def test_over_masking_cost_is_bounded_to_one_line(self):
		"""ÖLÇÜLMÜŞ VE KABUL EDİLMİŞ BEDEL: değeri BOŞ bir başlık BİR satır yutar.

		Kayıp TEK SATIRLADIR — sonlandırıcı hemen sonraki satır sonunda durur ve
		gövdenin kuyruğu YAŞAR. Değeri DOLU olan başlıklarda hiçbir şey değişmez
		(`test_gap_fix_does_not_touch_closed_values`).
		"""
		masked = mask_payload("Content-Type: json\nAuthorization:\nX-Takip: TR-9\nDurum: OK")

		self.assertNotIn("TR-9", masked)
		self.assertIn("Content-Type: json", masked)
		self.assertIn("Durum: OK", masked)


class TestSecretInMappingKeyPosition(unittest.TestCase):
	"""BULGU 2: `_mask_mapping` ANAHTAR konumundaki sırrı HAM bırakıyordu.

	Modülün kendi ilan ettiği TEK KÜME KURALI (aynı içerik dict / JSON metni /
	querystring olarak gelse de AYNI sonuç) ölçülerek ihlal ediliyordu:

		mask_payload({'SUPERSECRET123': 'v'},  …) → {'SUPERSECRET123': 'v'}  HAM
		mask_payload('{"SUPERSECRET123":"v"}', …) → {"***": "v"}            MASKELİ

	`log.py::_redact_deep`'in aynı boşluğu PARALEL olarak kapatıldı
	(`TestSecretInKeyPosition`); bu sınıf `masking.py` tarafını kilitler.
	"""

	def setUp(self):
		self.secret = "SUPERSECRET123"

	def test_flat_and_nested_keys_are_redacted(self):
		self.assertEqual(mask_payload({self.secret: "v"}, secret_values=[self.secret]), {MASK: "v"})
		self.assertEqual(
			mask_payload({"data": {self.secret: 1}}, secret_values=[self.secret]),
			{"data": {MASK: 1}},
		)

	def test_single_set_rule_holds_across_all_three_shapes(self):
		"""dict / JSON metni / querystring — ÜÇÜ DE sırrı anahtar konumunda kapatır."""
		as_dict = mask_payload({self.secret: "v"}, secret_values=[self.secret])
		as_json = mask_payload(f'{{"{self.secret}":"v"}}', secret_values=[self.secret])
		as_query = mask_payload(f"{self.secret}=v", secret_values=[self.secret])

		self.assertEqual(as_dict, {MASK: "v"})
		self.assertEqual(json.loads(as_json), {MASK: "v"})
		self.assertNotIn(self.secret, as_query)

	def test_denylist_decision_runs_before_key_redaction(self):
		"""SIRA BAĞLAYICI: redaksiyon önce koşsaydı denylist `***` görür, `sifre`yi KAÇIRIRDI."""
		self.assertEqual(
			mask_payload({"sifre": "X"}, secret_values=["sifre_ama_uzun_bir_sir"]),
			{"sifre": MASK},
		)

	def test_diagnostic_keys_stay_visible_in_key_position(self):
		"""AŞIRI MASKELEME YASAK: yalnız `secret_values` ile EŞLEŞEN anahtar değişir."""
		diagnostic = {
			"tracking_number": "TR1",
			"barcode": "B1",
			"order_no": "O1",
			"status_code": 200,
			"idempotency_key": "IK1",
			"request_id": "RQ1",
			"hata_kodu": "E1",
		}

		masked = mask_payload(dict(diagnostic), secret_values=[self.secret])

		self.assertEqual(sorted(masked), sorted(diagnostic))

	def test_non_string_keys_are_untouched(self):
		"""`int`/`tuple` anahtar redaksiyona SOKULMAZ — tür bozulmaz."""
		self.assertEqual(mask_payload({5: "v"}, secret_values=[self.secret]), {5: "v"})

	def test_mask_mapping_entry_point_shares_the_rule(self):
		"""`mask_mapping` public yüzeyi de aynı daldan geçer."""
		self.assertEqual(mask_mapping({self.secret: "v"}, secret_values=[self.secret]), {MASK: "v"})


class TestBracketBudgetKeepsTheTail(unittest.TestCase):
	"""BULGU 3: `_match_bracket` bütçe tükenmesi gövdenin KUYRUĞUNU yiyordu.

	`None` İKİ AYRI durumu birleştiriyordu: "kapanış hiç yok" (kırpma — kuyruk
	zaten boş, metnin sonuna maskelemek DOĞRU) ve "kapanış `_MAX_BRACKET_SCAN`
	bütçesinin ötesinde" (kuyruk VAR ve DOLU). İkincisinde metnin sonuna
	maskelemek SAF teşhis kaybıydı — düz METİN yolu, yani `error_message`.
	"""

	TAIL = " | takip=TR-123456 | sube=SISLI | durum=Teslim | http=200"

	def test_tail_survives_when_the_bracket_budget_is_exhausted(self):
		"""ÖNCE: girdi 5078 → çıktı 22; takip/şube/durum/http'nin TAMAMI gidiyordu."""
		masked = mask_payload("Kargo hatasi: auth=(" + "x" * 5_000 + ")" + self.TAIL)

		self.assertIn("TR-123456", masked)
		self.assertIn("durum=Teslim", masked)
		self.assertIn("http=200", masked)

	def test_within_budget_behaviour_is_unchanged(self):
		"""Bütçe İÇİNDEKİ kapanışta davranış AYNEN korunur (kuyruk zaten sağlamdı)."""
		masked = mask_payload("Kargo hatasi: auth=(" + "x" * 1_000 + ")" + self.TAIL)

		self.assertEqual(masked, f"Kargo hatasi: auth={MASK}{self.TAIL}")

	def test_budget_exhaustion_still_masks_the_secret(self):
		"""SIZINTI AÇMAZ: sırrın durduğu ilk 4096 karakter yine maskelenir."""
		masked = mask_payload(f"auth=('user','{_GAP_TOKEN}'," + "x" * 5_000 + ")")

		self.assertNotIn(_GAP_TOKEN, masked)

	def test_scanning_continues_past_the_budget_window(self):
		"""Bütçenin ÖTESİNDEKİ hassas anahtar eskiden HİÇ taranmıyordu."""
		masked = mask_payload("auth=('a'," + "x" * 5_000 + f") sifre={_GAP_TOKEN}")

		self.assertNotIn(_GAP_TOKEN, masked)

	def test_truncated_bracket_still_fails_closed(self):
		"""Kapanış HİÇ yoksa davranış DEĞİŞMEZ: metnin sonuna kadar maskelenir."""
		self.assertNotIn(_GAP_TOKEN, mask_payload(f"auth=('user','{_GAP_TOKEN}"))


class TestSensitiveTagAttributesHonourTheAllowlist(unittest.TestCase):
	"""BULGU 4: `_mask_tag_attributes` `NON_SENSITIVE_KEYS`'i TAMAMEN atlıyordu.

	Operatör modülün BELGELENMİŞ kaçış kapısına bir teşhis alanı eklediğinde bu
	yolda HİÇBİR ŞEY değişmiyor ve nedenini de göremiyordu. `<Kod>` TR kargo
	XML'inin en yaygın sonuç/durum elemanıdır (`kod` denylist'te) — yani bu,
	nadir değil BASKIN yol.
	"""

	def test_allowlisted_attributes_survive_on_a_sensitive_element(self):
		raw = (
			'<Kod tracking_number="TR123456789" error_code="4021" '
			'status_code="401" barkod="1234567890123">E</Kod>'
		)

		masked = mask_payload(raw)

		self.assertIn('tracking_number="TR123456789"', masked)
		self.assertIn('error_code="4021"', masked)
		self.assertIn('status_code="401"', masked)
		self.assertIn('barkod="1234567890123"', masked)

	def test_element_content_is_still_masked(self):
		"""Kaçış kapısı ÖZNİTELİĞE aittir; hassas elemanın İÇERİĞİ yine gider."""
		self.assertEqual(mask_payload("<Kod>01</Kod>"), f"<Kod>{MASK}</Kod>")

	def test_non_allowlisted_attributes_are_still_masked(self):
		"""9. turun kazancı AYNEN korunur — 1260 vektörün sıfır sızıntısı dahil."""
		names = sorted(DEFAULT_SENSITIVE_KEYS)
		attrs = ("deger", "value", "v", "k", "id", "type", "name", "data", "x", "content")
		leaked = [
			raw
			for name in names
			for attr in attrs
			for raw in (
				f'<{name} {attr}="{_GAP_TOKEN}"/>',
				f'<{name} {attr}="{_GAP_TOKEN}">icerik</{name}>',
			)
			if _GAP_TOKEN in mask_payload(raw)
		]

		self.assertEqual(len(names) * len(attrs) * 2, 1_260, "vektör sayısı sözleşmesi")
		self.assertEqual(leaked, [], f"{len(leaked)} vektör HAM sızdı")

	def test_allowlist_is_full_name_not_suffix(self):
		"""Modülün kendi kuralı: allowlist SON EK olarak uygulanmaz."""
		masked = mask_payload(f'<Sifre musteri_tracking_number="{_GAP_TOKEN}"/>')

		self.assertNotIn(_GAP_TOKEN, masked)

	def test_non_sensitive_element_attributes_are_untouched(self):
		raw = '<Adres il="Istanbul" ilce="Sisli"/>'

		self.assertEqual(mask_payload(raw), raw)

	def test_boolean_attribute_is_a_documented_limit(self):
		"""BELGELENMİŞ SINIR: `=` ile TÜKETİLMEYEN belirteç ham kalır.

		ÖLÇÜLDÜ VE ERİŞİLEMEZ: iyi biçimli XML'de öznitelik değeri HER ZAMAN `=`
		sonrası tırnaklıdır (`AttValue` üretimi başka biçim tanımaz). Kapatmak
		`<Sifre disabled/>` gibi boolean özniteliklerde aşırı maskeleme üretir.
		Davranış DEĞİŞİRSE bu test GEREKÇESİYLE güncellenmelidir.
		"""
		self.assertEqual(mask_payload("<Sifre disabled/>"), "<Sifre disabled/>")


class TestSummaryDeclaresTheTruth(unittest.TestCase):
	"""BULGU 5 + 6: fail-safe özetin İKİ ölçülmüş kusuru.

	5. `_count_sensitive_tags` çözülemeyen bölgede `break` ediyordu ve `_fail_closed`
	   özeti YALNIZ `lt == 0`da ürettiği için o nokta HER ZAMAN indeks 0'dı — özetin
	   taşıdığı TEK teşhis bilgisi baskın dalda YAPISAL OLARAK yanlıştı.
	6. Özete inme kapısı KONUMSALDI (`lt == 0`): aynı gövde tek karakterlik bir
	   önekle %93 daha az bilgi veriyordu.
	"""

	HTML = "<!DOCTYPE html>\n<html><body>502 Bad Gateway hata sayfasi</body></html>"

	def test_summary_counts_sensitive_tags_past_an_unresolved_region(self):
		"""ÖNCE: gövdede 2 hassas eleman VARKEN özet "0 hassas alan" diyordu."""
		payload = f"<!DOCTYPE html>\n<html><body><Sifre>{_GAP_TOKEN}</Sifre><ApiKey>K2</ApiKey></body></html>"

		masked = mask_payload(payload)

		self.assertEqual(masked, XML_BOUNDARY_UNRESOLVED.format(len(payload.encode("utf-8")), 2))
		self.assertNotIn(_GAP_TOKEN, masked)

	def test_zero_is_reported_only_when_it_is_true(self):
		"""Hassas eleman GERÇEKTEN yoksa sayı yine 0'dır — fazla sayım da yok."""
		self.assertEqual(
			mask_payload(self.HTML),
			XML_BOUNDARY_UNRESOLVED.format(len(self.HTML.encode("utf-8")), 0),
		)

	def test_invisible_prefixes_still_reach_the_summary(self):
		"""BULGU 6: tek boşluk / BOM / satır sonu özeti YOK ETMEZ."""
		summary_prefix = XML_BOUNDARY_UNRESOLVED.split("{", 1)[0]
		for label, prefix in (
			("space", " "),
			("bom", "﻿"),
			("newline", "\n"),
			("nbsp", "\xa0"),
			("null", "\x00"),
			("zwsp", "​"),
			("idsp", "　"),
			("tab", "\t"),
		):
			with self.subTest(label):
				masked = mask_payload(prefix + self.HTML)
				self.assertTrue(masked.startswith(summary_prefix), masked)

	def test_informative_prefixes_are_still_localized(self):
		"""GERÇEK bilgi taşıyan ön ek 9. turun yerelleştirmesini KORUR."""
		for prefix in ("HTTP 500: ", "Sunucu hatasi: ", "ï»¿", "'"):
			with self.subTest(prefix=prefix):
				masked = mask_payload(prefix + self.HTML)
				self.assertEqual(masked, f"{prefix}{MASK}")

	def test_localization_gain_is_unchanged(self):
		"""9. turun kazancı: bilgi taşıyan ön ekte teşhis YAŞAR."""
		self.assertEqual(
			mask_payload("<Root><Takip>TR-123456</Takip></Root><!"),
			f"<Root><Takip>TR-123456</Takip></Root>{MASK}",
		)

	def test_comment_content_in_the_prefix_is_a_documented_limit(self):
		"""BELGELENMİŞ SINIR: yerelleştirme ön ekteki YORUM/CDATA içeriğini ham bırakır.

		9. tur ÖNCESİ de doğruydu — `_markup_region_end` "bölgenin içi karakter
		verisidir" der ve bir yorumun içindeki `<Sifre>` bir eleman DEĞİLDİR —
		ama eski GLOBAL özet o bölgeyi TESADÜFEN örtüyordu. Kapatmanın bedeli
		her yorum satırını maskelemektir; gerçek çözüm çağıranın `secret_values`
		geçmesidir. Davranış DEĞİŞİRSE bu test GEREKÇESİYLE güncellenmelidir.
		"""
		raw = f"<!-- <Sifre>{_GAP_TOKEN}</Sifre> -->x<!"

		self.assertIn(_GAP_TOKEN, mask_payload(raw))
		self.assertNotIn(_GAP_TOKEN, mask_payload(raw, secret_values=[_GAP_TOKEN]))


# ---------------------------------------------------------------------------
# 11. tur — 10. turda kapatılan sızıntının AYNA GÖRÜNTÜLERİ
# ---------------------------------------------------------------------------


_PRE_GAP_TOKEN = "SESSIONTOKEN_ABC999"


class TestSeparatorPreGapIsSymmetric(unittest.TestCase):
	"""BULGU 1: ayraçtan ÖNCE boşluk/satır sonu varsa değer HİÇ maskelenmiyordu.

	10. tur `_scan_value`'nun ayraçtan SONRAKİ penceresini `' \\t\\r\\n'` + ÜST
	SINIRSIZ yaptı; ayraçtan ÖNCEKİ sınıf (`_PAIR_KEY_RE`) `[ \\t]{0,8}` olarak
	KALDI. XML 1.0 `Eq ::= S? '=' S?` boşluğu `=` işaretinin İKİ YANINDA da meşru
	sayar, yani kapatılan sızıntının tam SİMETRİĞİ açık kalmıştı.

	ERİŞİLEBİLİR: aşağıdaki gövdelerin hepsi İYİ BİÇİMLİ XML'dir (ElementTree
	kabul eder) ve biçimlendirilmiş/hizalanmış SOAP yanıtlarında `sifre` ile `=`
	arasına hizalama boşluğu ya da satır sonu koymak rutindir. Değer taşıyıcının
	YANITINDAKİ jetondur → `secret_values`'ta YOKTUR → değer-tabanlı BİRİNCİL
	katman bu sınıfta YARDIM EDEMEZ; anahtar-tabanlı katman TEK savunmadır.

	DERS (turun kendisi): bir sınırın İKİ YANI varsa, bir yanı düzeltmek ötekini
	düzeltmez — kapatılan her sızıntı için AYNASI ayrıca ölçülmelidir.
	"""

	def test_measured_leak_vectors_are_all_closed(self):
		"""Ana oturumun ölçtüğü DÖRT sızıntı vektörü — hepsi DEĞİŞMEDEN geçiyordu."""
		vectors = (
			f'<Kayit sifre\n="{_PRE_GAP_TOKEN}"/>',
			f'<Kayit sifre \n = "{_PRE_GAP_TOKEN}"/>',
			f'<Kayit sifre          ="{_PRE_GAP_TOKEN}"/>',
			f"sifre\n= {_PRE_GAP_TOKEN}",
		)
		for raw in vectors:
			with self.subTest(raw=raw[:40]):
				self.assertNotIn(_PRE_GAP_TOKEN, mask_payload(raw))

	def test_control_vectors_keep_working(self):
		"""ANA OTURUMUN KONTROLLERİ: tek boşluk ve boşluksuz şekiller bozulmadı."""
		self.assertEqual(mask_payload('<Kayit sifre ="X"/>'), f'<Kayit sifre ="{MASK}"/>')
		self.assertEqual(mask_payload('<Kayit sifre="X"/>'), f'<Kayit sifre="{MASK}"/>')

	def test_directed_sweep_leaks_nothing(self):
		"""Ad × ayraç-öncesi şekil × ayraç-sonrası şekil × biçim süpürmesi.

		Süpürme ayraç-SONRASI şekilleri de içerir: 10. turun kazancı ayraç-ÖNCESİ
		genişletmeyle birlikte de ayakta kalmalıdır (iki pencere BİRLİKTE ölçülür).
		"""
		names = ("sifre", "api_key", "password", "musteri_kodu", "authorization", "token")
		pre_gaps = ("", " ", "\t", "\n", "\r\n", " \n ", "\n\t", " " * 10, "\t" * 9, "\n\n", "\r\n\r\n")
		post_gaps = ("", " ", "\n", "\r\n", " " * 10)
		shapes = (
			'<Kayit {k}{p}={q}"{t}"/>',
			"<Kayit {k}{p}={q}'{t}'/>",
			"<Kayit {k}{p}={q}{t} />",
			"{k}{p}:{q}{t}",
			'{{"a":1,"{k}"{p}:{q}"{t}"}}',
			"{k}{p}={q}{t}&b=2",
		)
		leaked = [
			raw
			for key in names
			for pre in pre_gaps
			for post in post_gaps
			for shape in shapes
			for raw in (shape.format(k=key, p=pre, q=post, t=_PRE_GAP_TOKEN),)
			if _PRE_GAP_TOKEN in str(mask_payload(raw))
		]

		self.assertEqual(leaked, [], f"{len(leaked)} vektör HAM sızdı")

	def test_blank_line_gap_is_closed_too(self):
		"""REDDEDİLEN "EN FAZLA BİR SATIR SONU" SINIRININ ARTIĞI.

		Ara çözüm olarak boşluk sınıfını `[ \\t]*(?:(?:\\r\\n?|\\n)[ \\t]*)?` ile
		"en fazla BİR satır sonu"na bağlamak ölçüldü: 25 gerçekçi teşhis metnindeki
		7 zarardan yalnız 1'ini geri kazanıyordu (%14), buna karşılık BOŞ SATIRLI
		ön eki KALICI olarak açık bırakıyordu — aynı süpürmede 840/840 ham. Bir
		sonraki turun bulacağı sızıntı sınıfını %14 teşhis için açık bırakmak bu
		modülün fail-closed doktrinine aykırıdır; sınıf bu yüzden ÜST SINIRSIZDIR.
		"""
		for raw in (
			f'<Kayit sifre\n\n="{_PRE_GAP_TOKEN}"/>',
			f'<Kayit sifre\n \n = "{_PRE_GAP_TOKEN}"/>',
			f'<Kayit api_key\n\n\n= "{_PRE_GAP_TOKEN}"/>',
			f"sifre\n\n= {_PRE_GAP_TOKEN}",
			f'<Kayit sifre\r\n\r\n="{_PRE_GAP_TOKEN}"/>',
		):
			with self.subTest(raw=raw[:40]):
				self.assertNotIn(_PRE_GAP_TOKEN, mask_payload(raw))

	def test_over_masking_is_not_a_new_class(self):
		"""TAKAS ÖLÇÜMÜNÜN KİLİT BULGUSU — bedel YENİ bir sınıf DEĞİL.

		Genişletme, "hassas görünen kelime satır sonunda, `=` sonraki satırın
		başında" şeklindeki meşru metinleri de yer. Ölçüldü: bu vakaların satır
		sonu BOŞLUKLA değiştirilmiş hâli BUGÜN DE maskeleniyor — yani değişiklik
		modülün ZATEN KABUL ETTİĞİ yanlış-pozitif ödünleşmesini satır sonları
		boyunca TUTARLI hâle getirir, yeni bir ödünleşme AÇMAZ.
		"""
		pairs = (
			("Alanlar: sifre = 5 karakter olmali", "Alanlar: sifre\n= 5 karakter olmali"),
			("Kod = 4021 hatasi", "Kod\n= 4021 hatasi"),
			("key = deger esleme tablosu", "key\n= deger esleme tablosu"),
		)
		for same_line, across_lines in pairs:
			with self.subTest(text=same_line):
				self.assertNotEqual(mask_payload(same_line), same_line)
				self.assertNotEqual(mask_payload(across_lines), across_lines)

	def test_over_masking_cost_is_bounded_to_one_token(self):
		"""BEDELİN BÜYÜKLÜĞÜ ÖLÇÜLDÜ: sonlandırıcı bir sonraki boşlukta durur.

		Gövdenin KUYRUĞU yaşar — teşhis tamamen ölmez. 25 gerçekçi metnin
		7'sinde ölçülen zararın hepsi bu şekildeydi.
		"""
		masked = mask_payload("Liste:\n- token\n=========\n- takip: TR-9")

		self.assertNotIn("=========", masked)
		self.assertIn("- takip: TR-9", masked)

	def test_multiline_diagnostics_without_a_sensitive_key_are_untouched(self):
		"""Hassas ad GEÇMEYEN çok satırlı teşhis metinleri DEĞİŞMEDEN geçer."""
		for raw in (
			"HTTP/1.1 200 OK\nContent-Type: text/xml\nX-Takip: TR-9\nDurum: Teslim",
			"Kargo firmasi yanit vermedi\nDeneme = 3\nSure = 30 sn",
			"Islem ozeti\n===========\ntakip=TR-123456\ndurum=Teslim\nhttp=200",
			"Sevkiyat olusturuldu\ntracking_number: TR987654321\nbarcode: 8690000000001",
			"Beklenen: 5 < 10\nGercek: 12\nDurum = HATA",
			"Hata: sifre alani bos\n\nDurum = Teslim",
		):
			with self.subTest(raw=raw[:40]):
				self.assertEqual(mask_payload(raw), raw)

	def test_over_masking_locks_still_hold(self):
		"""Aşırı-maskeleme kilitleri DEĞİŞMEDEN geçmeye devam eder."""
		for raw in (
			"a < b",
			"error: 5 < 10 gecti",
			"timeout <2 sn> asildi",
			"ConnectionError: <Response [500]>",
			"deger <bos> geldi",
			"1 < 2 < 3",
			"metin sonunda <Takip",
			'<Adres il="Istanbul" ilce="Sisli"/>',
		):
			with self.subTest(raw=raw):
				self.assertEqual(mask_payload(raw), raw)

	def test_closed_values_and_tails_are_untouched(self):
		"""KRİTİK REGRESYON KAPISI: kapanmış değerde kuyruk AYNEN yaşar."""
		cases = {
			'{"sifre":"X","takip":"TR-9"}': '{"sifre": "***", "takip": "TR-9"}',
			"x < y, sifre=SECRETVALUE123": f"x < y, sifre={MASK}",
			f'<Kayit sifre\n="{_PRE_GAP_TOKEN}" takip="TR-9"/>': (f'<Kayit sifre\n="{MASK}" takip="TR-9"/>'),
			f"Authorization\n: Basic {_PRE_GAP_TOKEN}\nX-Takip: TR-9": (
				f"Authorization\n: {MASK}\nX-Takip: TR-9"
			),
		}
		for raw, expected in cases.items():
			with self.subTest(raw=raw[:40]):
				self.assertEqual(mask_payload(raw), expected)

	def test_diagnostic_escape_hatch_still_visible(self):
		"""`NON_SENSITIVE_KEYS` kaçış kapısı ayraç-öncesi boşlukla da çalışır."""
		raw = '<Kod tracking_number\n="TR123456789" error_code = "4021">E</Kod>'

		masked = mask_payload(raw)

		self.assertIn("TR123456789", masked)
		self.assertIn("4021", masked)

	def test_whitespace_class_must_stay_a_single_character_class(self):
		"""ReDoS — SINIF ASLA İKİ PARÇAYA BÖLÜNMEMELİ.

		`[ \\t]*(?:\\r?\\n)?[ \\t]*` biçimi (iki BİTİŞİK sınırsız nicelikleyici)
		klasik `a*a*` polinom patlamasıdır ve ÖLÇÜLDÜ: `'sifre' + ' '*n + 'X'`
		girdisinde n=20 000 → 2,630 s, n=200 000 → 262,844 s. Tek sınıf
		(`[ \\t\\r\\n]*`) geri izlemeyi adım başına O(1) yapar: aynı girdide
		n=200 000 → 0,021 s. Bu test o farkı KALICI olarak kilitler.
		"""
		limit = 5.0
		cases = {
			"spaces_then_separator": "sifre" + " " * 500_000 + "=X",
			"newlines_then_separator": "sifre" + "\n" * 500_000 + "=X",
			"spaces_then_no_separator": "sifre" + " " * 500_000 + "X",
			"tabs_then_no_separator": "sifre" + "\t" * 500_000 + "X",
			"newlines_then_no_separator": "sifre" + "\n" * 500_000 + "X",
			"alternating_space_newline": "sifre" + " \n" * 250_000 + "=X",
			"repeated_cross_line_pairs": "sifre\n=v\n" * 125_000,
		}
		for label, payload in cases.items():
			with self.subTest(case=label):
				started = time.monotonic()
				mask_payload(payload)
				self.assertLess(time.monotonic() - started, limit)


class TestHeaderNameRedactionIsPublic(unittest.TestCase):
	"""BULGU 2: `mask_headers` DOĞRUDAN çağrıldığında başlık ADI ham kalıyordu.

	Ölçüldü:

		mask_headers({'SUPERSECRET123': 'v', 'X-Trace': 'SUPERSECRET123'},
		             secret_values=['SUPERSECRET123'])
			→ {'SUPERSECRET123': 'v', 'X-Trace': '***'}   ADI HAM

	`log.py::_redact_deep` YAZICI yolunda bunu kapatıyordu (uçtan uca boşluk YOK
	— bkz. `TestSecretInKeyPosition.test_header_names_are_redacted_too`), ama
	`mask_headers` PUBLIC bir API'dir ve doğrudan çağrılabilir. Savunma,
	çağıranın hangi kapıdan girdiğine bağlı olamaz. Bu, 10. turda `_mask_mapping`
	için kapatılan boşluğun başlık tarafındaki AYNASIDIR.
	"""

	SECRET = "SUPERSECRET123"

	def test_secret_in_header_name_is_redacted(self):
		masked = mask_headers({self.SECRET: "v", "X-Trace": self.SECRET}, secret_values=[self.SECRET])

		self.assertEqual(masked, {MASK: "v", "X-Trace": MASK})

	def test_pair_sequence_input_takes_the_same_path(self):
		"""`requests` liste-of-tuple taşıyıcısı da aynı daldan geçer."""
		masked = mask_headers([(self.SECRET, "v"), ("X-Trace", self.SECRET)], secret_values=[self.SECRET])

		self.assertEqual(masked, {MASK: "v", "X-Trace": MASK})

	def test_denylist_runs_before_key_redaction(self):
		"""SIRA BAĞLAYICI: anahtar önce redakte edilseydi denylist `***` görürdü.

		Sırrın KENDİSİ hassas bir başlık adıysa karar yine ADIYLA verilmeli;
		aksi hâlde `Authorization` gibi bir ad denylist'ten KAÇARDI.
		"""
		masked = mask_headers({"Authorization": "Basic X"}, secret_values=["Authorization"])

		self.assertEqual(masked, {MASK: MASK})

	def test_diagnostic_header_names_stay_visible(self):
		"""AŞIRI MASKELEME YASAK: yalnız `secret_values` ile EŞLEŞEN ad değişir."""
		headers = {
			"Content-Type": "application/json",
			"X-Request-Id": "rq-1",
			"Idempotency-Key": "ik-1",
			"User-Agent": "tradehub/1.0",
			"X-Trace": "tr-1",
		}

		masked = mask_headers(headers, secret_values=[self.SECRET])

		self.assertEqual(masked, headers)

	def test_nested_header_values_still_masked(self):
		"""Yapısal değerler yolu (Mapping/liste) bozulmadı."""
		masked = mask_headers({"X-Meta": {self.SECRET: "v", "sifre": "p"}}, secret_values=[self.SECRET])

		self.assertEqual(masked["X-Meta"], {MASK: "v", "sifre": MASK})

	def test_non_string_keys_are_left_alone(self):
		"""`str` olmayan anahtar redaksiyona sokulmaz — `_mask_mapping` ile aynı."""
		self.assertEqual(mask_headers({7: "v"}, secret_values=[self.SECRET]), {7: "v"})

	def test_still_never_raises(self):
		"""Sözleşme korunur: `mask_headers` fırlatmaz."""
		self.assertEqual(mask_headers(object()), {})
		self.assertEqual(mask_headers(None), {})
