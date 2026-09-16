# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""09-BE webhook dilimi / BE-2: adapter webhook sozlesmesi testleri.

Kapsam:
- W1 saf HMAC helper'i (`adapters/signature.py`) — gecerli/bozuk/eksik imza,
  bos secret, bozuk prefix, compare_digest kilidi (AC-3), exception'sizlik.
- BaseCarrierAdapter.verify_webhook_signature default'u (case-insensitive
  header okuma + saf fonksiyona delegasyon) ve override noktalari.
- BaseCarrierAdapter.parse_webhook default'u (capability deseni, AC-11/12).
- MockCarrierAdapter.parse_webhook (spec mock semasi -> TrackingEvent).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest import mock

import tradehub_core.logistics.adapters.signature as signature_module
from tradehub_core.logistics.adapters.base import (
	BaseCarrierAdapter,
	CarrierCapability,
	TrackingEvent,
)
from tradehub_core.logistics.adapters.carriers.mock_carrier import MockCarrierAdapter
from tradehub_core.logistics.adapters.signature import verify_hmac_signature
from tradehub_core.logistics.exceptions import CarrierAPIError, CarrierCapabilityError

SECRET: str = "test-webhook-secret"
BODY: bytes = b'{"tracking_number": "MOCK123", "status_code": "DLV"}'


def _sign(body: bytes, secret: str = SECRET, prefix: str = "sha256=") -> str:
	"""Testler icin beklenen imza basligini uret."""
	return prefix + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class TestVerifyHmacSignaturePure(unittest.TestCase):
	"""W1 saf fonksiyonu: frappe'siz, exception'siz, sabit-zamanli."""

	def test_valid_signature_returns_true(self) -> None:
		self.assertTrue(verify_hmac_signature(BODY, _sign(BODY), SECRET))

	def test_wrong_secret_returns_false(self) -> None:
		self.assertFalse(verify_hmac_signature(BODY, _sign(BODY, secret="baska-secret"), SECRET))

	def test_tampered_body_returns_false(self) -> None:
		self.assertFalse(verify_hmac_signature(BODY + b"x", _sign(BODY), SECRET))

	def test_missing_header_returns_false(self) -> None:
		self.assertFalse(verify_hmac_signature(BODY, None, SECRET))
		self.assertFalse(verify_hmac_signature(BODY, "", SECRET))
		self.assertFalse(verify_hmac_signature(BODY, "   ", SECRET))

	def test_empty_secret_returns_false(self) -> None:
		"""Secret'i bos hesap ASLA gecemez (AC-4'un adapter katmani ayagi)."""
		self.assertFalse(verify_hmac_signature(BODY, _sign(BODY, secret=""), ""))
		self.assertFalse(verify_hmac_signature(BODY, _sign(BODY), ""))
		self.assertFalse(verify_hmac_signature(BODY, _sign(BODY), None))  # type: ignore[arg-type]

	def test_malformed_prefix_returns_false(self) -> None:
		digest: str = _sign(BODY)[len("sha256=") :]
		self.assertFalse(verify_hmac_signature(BODY, digest, SECRET))  # prefix yok
		self.assertFalse(verify_hmac_signature(BODY, "sha512=" + digest, SECRET))
		self.assertFalse(verify_hmac_signature(BODY, "SHA256=" + digest, SECRET))  # birebir prefix
		self.assertFalse(verify_hmac_signature(BODY, "sha256=", SECRET))  # hex bos

	def test_hex_case_insensitive(self) -> None:
		"""Tasiyicilar buyuk harfli hex gonderebilir — kabul edilir."""
		header: str = "sha256=" + _sign(BODY)[len("sha256=") :].upper()
		self.assertTrue(verify_hmac_signature(BODY, header, SECRET))

	def test_surrounding_whitespace_tolerated(self) -> None:
		self.assertTrue(verify_hmac_signature(BODY, "  " + _sign(BODY) + "  ", SECRET))

	def test_custom_prefix_parameter(self) -> None:
		header: str = _sign(BODY, prefix="hmac-v1=")
		self.assertTrue(verify_hmac_signature(BODY, header, SECRET, prefix="hmac-v1="))
		self.assertFalse(verify_hmac_signature(BODY, header, SECRET))  # default prefix'le gecmez

	def test_never_raises_on_garbage_inputs(self) -> None:
		"""Saf fonksiyon sozlesmesi: hicbir girdi exception uretmez."""
		garbage_cases: list[tuple] = [
			("not-bytes", _sign(BODY), SECRET),  # raw_body str
			(None, _sign(BODY), SECRET),  # raw_body None
			(BODY, "sha256=zzzzçö", SECRET),  # non-ascii/non-hex — compare_digest tuzagi
			(BODY, 12345, SECRET),  # header int
			(BODY, _sign(BODY), 12345),  # secret int
			(BODY, _sign(BODY), SECRET, None),  # prefix None
		]
		for case in garbage_cases:
			with self.subTest(case=case):
				self.assertFalse(verify_hmac_signature(*case))

	def test_bytearray_body_accepted(self) -> None:
		self.assertTrue(verify_hmac_signature(bytearray(BODY), _sign(BODY), SECRET))

	def test_uses_compare_digest_not_equality(self) -> None:
		"""AC-3 kilidi: karsilastirma hmac.compare_digest ile yapilir."""
		with mock.patch.object(signature_module.hmac, "compare_digest", wraps=hmac.compare_digest) as spy:
			self.assertTrue(verify_hmac_signature(BODY, _sign(BODY), SECRET))
		spy.assert_called_once()

	def test_module_is_frappe_free(self) -> None:
		"""W1: saf modul frappe import etmez (endpoint fallback'i bench'siz test edilebilir)."""
		import ast
		import inspect

		tree: ast.Module = ast.parse(inspect.getsource(signature_module))
		imported: list[str] = []
		for node in ast.walk(tree):
			if isinstance(node, ast.Import):
				imported.extend(alias.name for alias in node.names)
			elif isinstance(node, ast.ImportFrom):
				imported.append(node.module or "")
		for name in imported:
			self.assertFalse(
				name == "frappe" or name.startswith("frappe."),
				f"Saf modul frappe import ediyor: {name}",
			)


class TestBaseVerifyWebhookSignatureDefault(unittest.TestCase):
	"""Base default'u: header'i case-insensitive okur, saf fonksiyona delege eder."""

	def setUp(self) -> None:
		self.adapter: MockCarrierAdapter = MockCarrierAdapter()

	def test_valid_header_exact_case(self) -> None:
		headers: dict[str, str] = {"X-Webhook-Signature": _sign(BODY)}
		self.assertTrue(self.adapter.verify_webhook_signature(BODY, headers, SECRET))

	def test_valid_header_case_insensitive(self) -> None:
		"""HTTP basliklari normalize gelebilir — lowercase/uppercase anahtar da okunur."""
		for key in ("x-webhook-signature", "X-WEBHOOK-SIGNATURE", "x-Webhook-signature"):
			with self.subTest(key=key):
				self.assertTrue(self.adapter.verify_webhook_signature(BODY, {key: _sign(BODY)}, SECRET))

	def test_missing_header_returns_false(self) -> None:
		self.assertFalse(self.adapter.verify_webhook_signature(BODY, {}, SECRET))
		self.assertFalse(self.adapter.verify_webhook_signature(BODY, {"X-Other": "sha256=abc"}, SECRET))

	def test_invalid_signature_returns_false(self) -> None:
		headers: dict[str, str] = {"X-Webhook-Signature": _sign(BODY, secret="yanlis")}
		self.assertFalse(self.adapter.verify_webhook_signature(BODY, headers, SECRET))

	def test_empty_secret_returns_false(self) -> None:
		headers: dict[str, str] = {"X-Webhook-Signature": _sign(BODY)}
		self.assertFalse(self.adapter.verify_webhook_signature(BODY, headers, ""))

	def test_default_delegates_to_pure_function(self) -> None:
		"""W1: default implementasyon endpoint fallback'iyle AYNI saf fonksiyonu cagirir."""
		with mock.patch.object(signature_module.hmac, "compare_digest", wraps=hmac.compare_digest) as spy:
			headers: dict[str, str] = {"X-Webhook-Signature": _sign(BODY)}
			self.assertTrue(self.adapter.verify_webhook_signature(BODY, headers, SECRET))
		spy.assert_called_once()

	def test_carrier_specific_override_via_attributes(self) -> None:
		"""Ozel semali tasiyici header adi/prefix'i attribute'la degistirebilmeli."""

		class _CustomSchemeAdapter(MockCarrierAdapter):
			webhook_signature_header: str = "X-Custom-Sig"
			webhook_signature_prefix: str = "hmac-v1="

		adapter: _CustomSchemeAdapter = _CustomSchemeAdapter()
		headers: dict[str, str] = {"x-custom-sig": _sign(BODY, prefix="hmac-v1=")}
		self.assertTrue(adapter.verify_webhook_signature(BODY, headers, SECRET))
		# Default semanin basligi bu adapter icin artik gecersiz
		self.assertFalse(adapter.verify_webhook_signature(BODY, {"X-Webhook-Signature": _sign(BODY)}, SECRET))


class TestParseWebhookDefault(unittest.TestCase):
	"""parse_webhook default'u capability desenine uyar (cancel_shipment vb. gibi)."""

	def test_no_webhook_capability_raises_capability_error(self) -> None:
		class _NoWebhookAdapter(MockCarrierAdapter):
			capabilities: set[CarrierCapability] = {CarrierCapability.TRACK}

		adapter: _NoWebhookAdapter = _NoWebhookAdapter()
		with self.assertRaises(CarrierCapabilityError):
			BaseCarrierAdapter.parse_webhook(adapter, BODY, {})

	def test_capability_declared_but_not_implemented_still_raises(self) -> None:
		"""WEBHOOK bildirilmis ama override edilmemisse de CarrierCapabilityError (AC-11)."""
		adapter: MockCarrierAdapter = MockCarrierAdapter()
		with self.assertRaises(CarrierCapabilityError):
			BaseCarrierAdapter.parse_webhook(adapter, BODY, {})


class TestMockParseWebhook(unittest.TestCase):
	"""Mock adapter spec semasini TrackingEvent listesine cevirir."""

	def setUp(self) -> None:
		self.adapter: MockCarrierAdapter = MockCarrierAdapter()
		self.event_payload: dict = {
			"tracking_number": "MOCK123ABC",
			"status_code": "DLV",
			"status_text": "Teslim edildi.",
			"event_time": "2026-09-16T10:30:00+03:00",
			"location": "Ankara",
		}

	def test_single_event_parsed(self) -> None:
		raw: bytes = json.dumps(self.event_payload).encode("utf-8")
		events: list[TrackingEvent] = self.adapter.parse_webhook(raw, {})
		self.assertEqual(len(events), 1)
		event: TrackingEvent = events[0]
		self.assertIsInstance(event, TrackingEvent)
		self.assertEqual(event.timestamp, "2026-09-16T10:30:00+03:00")
		self.assertEqual(event.status, "DLV")
		self.assertEqual(event.description, "Teslim edildi.")
		self.assertEqual(event.location, "Ankara")
		# Ham carrier payload'i raw'da tasinir (AC-8: ham carrier_status_code + tracking cozumu)
		self.assertEqual(event.raw["tracking_number"], "MOCK123ABC")
		self.assertEqual(event.raw["status_code"], "DLV")

	def test_location_optional(self) -> None:
		payload: dict = dict(self.event_payload)
		del payload["location"]
		events: list[TrackingEvent] = self.adapter.parse_webhook(json.dumps(payload).encode("utf-8"), {})
		self.assertIsNone(events[0].location)

	def test_list_payload_parsed(self) -> None:
		second: dict = dict(self.event_payload, status_code="OFD", status_text="Dagitimda.")
		raw: bytes = json.dumps([self.event_payload, second]).encode("utf-8")
		events: list[TrackingEvent] = self.adapter.parse_webhook(raw, {})
		self.assertEqual(len(events), 2)
		self.assertEqual(events[1].status, "OFD")

	def test_malformed_json_raises_meaningful_error(self) -> None:
		with self.assertRaises(CarrierAPIError):
			self.adapter.parse_webhook(b"{bozuk json", {})

	def test_non_utf8_body_raises(self) -> None:
		with self.assertRaises(CarrierAPIError):
			self.adapter.parse_webhook(b"\xff\xfe\x00", {})

	def test_non_object_toplevel_raises(self) -> None:
		with self.assertRaises(CarrierAPIError):
			self.adapter.parse_webhook(b'"sadece-string"', {})
		with self.assertRaises(CarrierAPIError):
			self.adapter.parse_webhook(b"42", {})

	def test_non_object_list_item_raises(self) -> None:
		with self.assertRaises(CarrierAPIError):
			self.adapter.parse_webhook(b'[{"tracking_number": "X"}, 42]', {})

	def test_missing_required_field_raises(self) -> None:
		for field in ("tracking_number", "status_code", "status_text", "event_time"):
			payload: dict = dict(self.event_payload)
			del payload[field]
			with self.subTest(missing=field):
				with self.assertRaises(CarrierAPIError):
					self.adapter.parse_webhook(json.dumps(payload).encode("utf-8"), {})

	def test_no_webhook_capability_wins_over_parse(self) -> None:
		"""Capability kapaliysa govde hic ayristirilmadan CarrierCapabilityError."""

		class _NoWebhookMock(MockCarrierAdapter):
			capabilities: set[CarrierCapability] = set()

		with self.assertRaises(CarrierCapabilityError):
			_NoWebhookMock().parse_webhook(json.dumps(self.event_payload).encode("utf-8"), {})

	def test_mock_implements_both_webhook_methods(self) -> None:
		"""AC-12: mock_carrier iki webhook metodunu da implement eder."""
		self.assertIn("parse_webhook", MockCarrierAdapter.__dict__)
		self.assertIn("verify_webhook_signature", MockCarrierAdapter.__dict__)
		self.assertTrue(MockCarrierAdapter().supports(CarrierCapability.WEBHOOK))

	def test_mock_verify_signature_end_to_end(self) -> None:
		raw: bytes = json.dumps(self.event_payload).encode("utf-8")
		headers: dict[str, str] = {"X-Webhook-Signature": _sign(raw)}
		self.assertTrue(self.adapter.verify_webhook_signature(raw, headers, SECRET))
		self.assertFalse(self.adapter.verify_webhook_signature(raw + b" ", headers, SECRET))


if __name__ == "__main__":
	unittest.main()
