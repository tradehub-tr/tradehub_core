# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Dalga B: Durum geçiş motorunun saf kural testleri (LOG-049).

transition_status motorunun kural kısmı frappe'siz test edilebilsin diye
is_transition_allowed(from, to) saf fonksiyonu logistics/constants.py'ye
ayrıldı — bu dosya yalnız o fonksiyonu test eder (geçerli/geçersiz/no-op/
terminal senaryoları). constants.py modülü importlib ile doğrudan dosyadan
yüklenir; paket __init__ zinciri (frappe import eden logistics/__init__.py)
bilinçli olarak atlanır — test bench OLMADAN standalone çalışır.

Frappe gerektiren kısımlar (transition_status'un doc yazımı, Shipment Event
üretimi + event_hash yarış no-op'u, tarih damgaları, cancel_shipment,
hooks.py doc_event akışları) Dalga C bench testlerinde doğrulanacaktır.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

# constants.py'yi paket zincirini tetiklemeden doğrudan yükle (frappe'siz).
_CONSTANTS_PATH = Path(__file__).resolve().parent.parent / "constants.py"
_spec = importlib.util.spec_from_file_location("_logistics_constants_standalone", _CONSTANTS_PATH)
assert _spec is not None and _spec.loader is not None
constants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(constants)

ALLOWED_TRANSITIONS = constants.ALLOWED_TRANSITIONS
TERMINAL_STATUSES = constants.TERMINAL_STATUSES
ShipmentStatus = constants.ShipmentStatus
is_transition_allowed = constants.is_transition_allowed


class TestValidTransitions(unittest.TestCase):
	"""Matristeki tüm geçerli geçişler kabul edilmeli."""

	def test_all_matrix_transitions_allowed(self) -> None:
		"""ALLOWED_TRANSITIONS'daki her (from, to) çifti True dönmeli."""
		for from_status, targets in ALLOWED_TRANSITIONS.items():
			for to_status in targets:
				self.assertTrue(
					is_transition_allowed(from_status, to_status),
					f"Matriste tanımlı geçiş reddedildi: {from_status!r} -> {to_status!r}",
				)

	def test_happy_path_chain(self) -> None:
		"""Tipik yaşam döngüsü zinciri baştan sona geçerli olmalı."""
		chain: list[str] = [
			ShipmentStatus.DRAFT,
			ShipmentStatus.PENDING,
			ShipmentStatus.READY_FOR_PICKUP,
			ShipmentStatus.PICKED_UP,
			ShipmentStatus.IN_TRANSIT,
			ShipmentStatus.OUT_FOR_DELIVERY,
			ShipmentStatus.DELIVERED,
		]
		# Ardışık çiftler index ile — zip(strict=) 3.10+, test 3.9'da da koşabilmeli.
		for index in range(len(chain) - 1):
			from_status, to_status = chain[index], chain[index + 1]
			self.assertTrue(
				is_transition_allowed(from_status, to_status),
				f"Happy path geçişi reddedildi: {from_status!r} -> {to_status!r}",
			)

	def test_failed_retry_transition(self) -> None:
		"""Failed'dan In Transit'e retry geçişi geçerli olmalı."""
		self.assertTrue(is_transition_allowed(ShipmentStatus.FAILED, ShipmentStatus.IN_TRANSIT))


class TestInvalidTransitions(unittest.TestCase):
	"""Matris dışı geçişler reddedilmeli."""

	def test_all_non_matrix_transitions_denied(self) -> None:
		"""Matriste OLMAYAN her (from, to) çifti (no-op hariç) False dönmeli."""
		for from_status in ShipmentStatus.ALL:
			allowed: set[str] = ALLOWED_TRANSITIONS.get(from_status, set())
			for to_status in ShipmentStatus.ALL:
				if to_status == from_status or to_status in allowed:
					continue
				self.assertFalse(
					is_transition_allowed(from_status, to_status),
					f"Matris dışı geçiş kabul edildi: {from_status!r} -> {to_status!r}",
				)

	def test_backward_transition_denied(self) -> None:
		"""Geriye doğru geçiş (Delivered -> In Transit) reddedilmeli."""
		self.assertFalse(is_transition_allowed(ShipmentStatus.DELIVERED, ShipmentStatus.IN_TRANSIT))

	def test_skip_ahead_transition_denied(self) -> None:
		"""Ara durum atlayan geçiş (Draft -> Delivered) reddedilmeli."""
		self.assertFalse(is_transition_allowed(ShipmentStatus.DRAFT, ShipmentStatus.DELIVERED))

	def test_unknown_status_fail_closed(self) -> None:
		"""Bilinmeyen kaynak durum fail-closed olmalı (False)."""
		self.assertFalse(is_transition_allowed("Bilinmeyen Durum", ShipmentStatus.PENDING))


class TestNoOpTransitions(unittest.TestCase):
	"""Aynı duruma geçiş = idempotent no-op (motor event üretmeden döner)."""

	def test_same_status_always_allowed(self) -> None:
		"""Her durum için X -> X geçişi True dönmeli (sessiz no-op)."""
		for status in ShipmentStatus.ALL:
			self.assertTrue(
				is_transition_allowed(status, status),
				f"No-op geçiş reddedildi: {status!r} -> {status!r}",
			)

	def test_terminal_same_status_is_noop(self) -> None:
		"""Terminal durumda bile X -> X no-op olarak kabul edilmeli."""
		for status in TERMINAL_STATUSES:
			self.assertTrue(is_transition_allowed(status, status))


class TestTerminalStatuses(unittest.TestCase):
	"""Terminal durumlardan çıkış matrisle engelli olmalı."""

	def test_no_exit_from_terminal(self) -> None:
		"""Terminal durumdan farklı HERHANGİ bir duruma geçiş False dönmeli."""
		for terminal in TERMINAL_STATUSES:
			for to_status in ShipmentStatus.ALL:
				if to_status == terminal:
					continue
				self.assertFalse(
					is_transition_allowed(terminal, to_status),
					f"Terminal durumdan çıkış kabul edildi: {terminal!r} -> {to_status!r}",
				)

	def test_terminal_set_matches_empty_matrix_rows(self) -> None:
		"""TERMINAL_STATUSES, matriste boş satırı olan durumlarla tutarlı olmalı."""
		empty_rows: set[str] = {
			status for status, targets in ALLOWED_TRANSITIONS.items() if not targets
		}
		self.assertEqual(TERMINAL_STATUSES, empty_rows)


class TestSellerTransitions(unittest.TestCase):
	"""G0 matrisi (C2): satıcı geçiş alt kümesinin saf kural testleri."""

	def test_seller_subset_of_allowed(self) -> None:
		"""Satıcı matrisi genel matrisin ALT KÜMESİ olmalı — satıcıya genel
		motorun reddedeceği bir geçiş açmak iki kuralı çelişkiye düşürür."""
		for from_status, targets in constants.SELLER_ALLOWED_TRANSITIONS.items():
			for to_status in targets:
				self.assertTrue(
					is_transition_allowed(from_status, to_status),
					f"Satıcıya açık ama genel matriste yasak: {from_status!r} -> {to_status!r}",
				)

	def test_seller_can_confirm_pickup(self) -> None:
		"""FBM 'confirm shipment' karşılığı: Alıma Hazır -> Alındı satıcıya açık."""
		self.assertTrue(
			constants.is_seller_transition_allowed(
				ShipmentStatus.READY_FOR_PICKUP, ShipmentStatus.PICKED_UP
			)
		)

	def test_seller_cannot_cancel_or_deliver(self) -> None:
		"""İptal ve teslim kararları platformda kalmalı (G0: iptal yalnız
		Logistics Manager; teslim taşıyıcı/operasyon olayı)."""
		for from_status in ShipmentStatus.ALL:
			self.assertFalse(
				constants.is_seller_transition_allowed(from_status, ShipmentStatus.CANCELLED),
				f"Satıcıya iptal açılmış: {from_status!r}",
			)
			self.assertFalse(
				constants.is_seller_transition_allowed(from_status, ShipmentStatus.DELIVERED),
				f"Satıcıya teslim açılmış: {from_status!r}",
			)


if __name__ == "__main__":
	unittest.main()
