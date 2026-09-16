# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-102: Durum makinesi ve sabit deger testleri.

ShipmentStatus durum gecis matrisinin tutarliligini,
terminal durumlarin degismezligini ve feature flag
varsayilanlarini dogrular.
"""

from __future__ import annotations

import unittest

from tradehub_core.logistics.constants import (
	ALLOWED_TRANSITIONS,
	LOGISTICS_FEATURE_FLAGS,
	MAX_WEBHOOK_BODY_BYTES,
	TERMINAL_STATUSES,
	WEBHOOK_DEDUPE_TTL_SECONDS,
	WEBHOOK_SIGNATURE_HEADER,
	WEBHOOK_SIGNATURE_PREFIX,
	ShipmentStatus,
)


class TestShipmentStatusConstants(unittest.TestCase):
	"""Sevkiyat durum makinesi invariant testleri."""

	def test_all_statuses_in_transition_map(self) -> None:
		"""Her durum ALLOWED_TRANSITIONS'da key olarak bulunmali."""
		for status in ShipmentStatus.ALL:
			self.assertIn(
				status,
				ALLOWED_TRANSITIONS,
				f"{status!r} durumu ALLOWED_TRANSITIONS'da key olarak eksik.",
			)

	def test_terminal_statuses_have_no_transitions(self) -> None:
		"""Terminal durumlardan cikis yok — bos set olmali."""
		for status in TERMINAL_STATUSES:
			transitions: set[str] = ALLOWED_TRANSITIONS.get(status, set())
			self.assertEqual(
				len(transitions),
				0,
				f"Terminal durum {status!r} bos olmayan gecislere sahip: {transitions}",
			)

	def test_draft_is_initial_status(self) -> None:
		"""Draft her zaman baslangic durumu olmali ve gecisleri bulunmali."""
		self.assertIn(ShipmentStatus.DRAFT, ALLOWED_TRANSITIONS)
		self.assertGreater(
			len(ALLOWED_TRANSITIONS[ShipmentStatus.DRAFT]),
			0,
			"Draft durumundan en az bir gecis olmali.",
		)

	def test_no_self_transitions(self) -> None:
		"""Bir durum kendisine gecis yapamaz."""
		for status, targets in ALLOWED_TRANSITIONS.items():
			self.assertNotIn(
				status,
				targets,
				f"{status!r} durumu kendisine gecis tanimlamis.",
			)

	def test_cancelled_reachable_from_early_states(self) -> None:
		"""Cancelled'a erken durumlardan (Draft, Pending) ulasilabilmeli."""
		early_states: list[str] = [
			ShipmentStatus.DRAFT,
			ShipmentStatus.PENDING,
		]
		for state in early_states:
			self.assertIn(
				ShipmentStatus.CANCELLED,
				ALLOWED_TRANSITIONS.get(state, set()),
				f"{state!r} durumundan Cancelled'a gecis tanimli degil.",
			)

	def test_delivered_is_terminal(self) -> None:
		"""Delivered terminal durumda olmali."""
		self.assertIn(ShipmentStatus.DELIVERED, TERMINAL_STATUSES)

	def test_returned_is_terminal(self) -> None:
		"""Returned terminal durumda olmali."""
		self.assertIn(ShipmentStatus.RETURNED, TERMINAL_STATUSES)

	def test_failed_can_retry(self) -> None:
		"""Basarisiz durumdan farkli durumlara gecis mumkun olmali."""
		failed_transitions: set[str] = ALLOWED_TRANSITIONS.get(
			ShipmentStatus.FAILED, set()
		)
		self.assertGreater(
			len(failed_transitions),
			0,
			"Failed durumundan en az bir gecis (retry) olmali.",
		)

	def test_transition_targets_are_valid_statuses(self) -> None:
		"""Gecis hedefleri gecerli ShipmentStatus degerleri olmali."""
		all_statuses: set[str] = set(ShipmentStatus.ALL)
		for source, targets in ALLOWED_TRANSITIONS.items():
			for target in targets:
				self.assertIn(
					target,
					all_statuses,
					f"{source!r} -> {target!r} gecisinde hedef gecerli bir durum degil.",
				)

	def test_status_all_tuple_not_empty(self) -> None:
		"""ShipmentStatus.ALL bos olmamali."""
		self.assertGreater(len(ShipmentStatus.ALL), 0)


class TestFeatureFlags(unittest.TestCase):
	"""Feature flag varsayilan deger testleri."""

	def test_all_flags_default_false(self) -> None:
		"""Tum feature flag'ler varsayilan olarak kapali olmali."""
		for flag_name, default_value in LOGISTICS_FEATURE_FLAGS.items():
			self.assertFalse(
				default_value,
				f"Feature flag {flag_name!r} varsayilan olarak acik — kapali olmali.",
			)

	def test_flag_keys_are_strings(self) -> None:
		"""Flag key'leri string olmali."""
		for key in LOGISTICS_FEATURE_FLAGS:
			self.assertIsInstance(
				key,
				str,
				f"Feature flag key'i string degil: {key!r}",
			)

	def test_flag_values_are_booleans(self) -> None:
		"""Flag degerleri boolean olmali."""
		for key, value in LOGISTICS_FEATURE_FLAGS.items():
			self.assertIsInstance(
				value,
				bool,
				f"Feature flag {key!r} degeri boolean degil: {value!r}",
			)

	def test_flags_dict_not_empty(self) -> None:
		"""Feature flags sozlugu bos olmamali."""
		self.assertGreater(len(LOGISTICS_FEATURE_FLAGS), 0)

	def test_carrier_webhook_flag_exists_and_default_off(self) -> None:
		"""Inbound webhook flag'i tanimli ve varsayilan KAPALI olmali (09-BE)."""
		self.assertIn("carrier_webhook_enabled", LOGISTICS_FEATURE_FLAGS)
		self.assertFalse(LOGISTICS_FEATURE_FLAGS["carrier_webhook_enabled"])

	def test_carrier_webhook_flag_distinct_from_notifications_flag(self) -> None:
		"""Gelen webhook flag'i, giden bildirim flag'inden AYRI olmali.

		`webhook_notifications_enabled` giden bildirimlerin flag'i — adi
		yaniltici oldugu icin yeniden kullanilmadi (spec risks listesi).
		"""
		self.assertIn("webhook_notifications_enabled", LOGISTICS_FEATURE_FLAGS)
		self.assertIn("carrier_webhook_enabled", LOGISTICS_FEATURE_FLAGS)


class TestWebhookConstants(unittest.TestCase):
	"""Carrier webhook alicisi sabit testleri (09-BE webhook dilimi)."""

	def test_max_body_bytes_is_128_kb(self) -> None:
		"""Govde ust siniri tam 128 KB olmali (AC-5)."""
		self.assertEqual(MAX_WEBHOOK_BODY_BYTES, 131072)
		self.assertEqual(MAX_WEBHOOK_BODY_BYTES, 128 * 1024)

	def test_dedupe_ttl_is_48_hours(self) -> None:
		"""Dedupe TTL tam 48 saat olmali (W4: AC-7 'saat' okunur, saniye degil)."""
		self.assertEqual(WEBHOOK_DEDUPE_TTL_SECONDS, 172800)
		self.assertEqual(WEBHOOK_DEDUPE_TTL_SECONDS, 48 * 60 * 60)

	def test_signature_header_name(self) -> None:
		"""Imza basligi sozlesmedeki adla birebir olmali."""
		self.assertEqual(WEBHOOK_SIGNATURE_HEADER, "X-Webhook-Signature")

	def test_signature_prefix(self) -> None:
		"""Imza deger oneki 'sha256=' olmali (GitHub webhook konvansiyonu)."""
		self.assertEqual(WEBHOOK_SIGNATURE_PREFIX, "sha256=")

	def test_signature_prefix_matches_algorithm_naming(self) -> None:
		"""Onek algoritma adiyla baslamali ve '=' ile bitmeli — ayristirici buna dayanir."""
		self.assertTrue(WEBHOOK_SIGNATURE_PREFIX.endswith("="))
		self.assertTrue(WEBHOOK_SIGNATURE_PREFIX.startswith("sha256"))

	def test_webhook_constants_types(self) -> None:
		"""Sayisal sabitler int, baslik sabitleri str olmali."""
		self.assertIsInstance(MAX_WEBHOOK_BODY_BYTES, int)
		self.assertIsInstance(WEBHOOK_DEDUPE_TTL_SECONDS, int)
		self.assertIsInstance(WEBHOOK_SIGNATURE_HEADER, str)
		self.assertIsInstance(WEBHOOK_SIGNATURE_PREFIX, str)


if __name__ == "__main__":
	unittest.main()
