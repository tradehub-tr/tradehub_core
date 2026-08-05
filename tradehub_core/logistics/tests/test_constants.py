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
	TERMINAL_STATUSES,
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


if __name__ == "__main__":
	unittest.main()
