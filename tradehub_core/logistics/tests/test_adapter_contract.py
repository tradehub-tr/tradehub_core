# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-102: Carrier adapter sozlesme testi.

MockCarrierAdapter'in BaseCarrierAdapter ABC'sini dogru implement
ettigini ve adapter registry mekanizmasinin calistigini dogrular.
"""

from __future__ import annotations

import unittest

from tradehub_core.logistics.adapters.base import (
	BaseCarrierAdapter,
	CarrierCapability,
	QuoteRequest,
	QuoteResponse,
	ShipmentRequest,
	ShipmentResponse,
	TrackingResponse,
)
from tradehub_core.logistics.adapters.carriers.mock_carrier import MockCarrierAdapter
from tradehub_core.logistics.adapters.registry import (
	_CARRIER_REGISTRY,
	get_adapter,
	list_registered_carriers,
	register_carrier,
)


class TestMockCarrierAdapterContract(unittest.TestCase):
	"""MockCarrierAdapter'in ABC sozlesmesine uygunlugunu test eder."""

	def setUp(self) -> None:
		self.adapter: MockCarrierAdapter = MockCarrierAdapter()

	def test_is_subclass_of_base(self) -> None:
		"""MockCarrierAdapter, BaseCarrierAdapter'in alt sinifi olmali."""
		self.assertIsInstance(self.adapter, BaseCarrierAdapter)

	def test_has_required_attributes(self) -> None:
		"""name, display_name, capabilities attribute'lari mevcut olmali."""
		self.assertTrue(hasattr(self.adapter, "name"))
		self.assertTrue(hasattr(self.adapter, "display_name"))
		self.assertTrue(hasattr(self.adapter, "capabilities"))
		self.assertIsInstance(self.adapter.name, str)
		self.assertIsInstance(self.adapter.display_name, str)
		self.assertIsInstance(self.adapter.capabilities, set)

	def test_name_not_empty(self) -> None:
		"""Adapter name bos olmamali."""
		self.assertTrue(len(self.adapter.name) > 0)

	def test_supports_all_base_capabilities(self) -> None:
		"""Mock adapter temel capability'leri desteklemeli."""
		required: set[CarrierCapability] = {
			CarrierCapability.CREATE_SHIPMENT,
			CarrierCapability.TRACK,
			CarrierCapability.QUOTE,
		}
		for cap in required:
			self.assertTrue(
				self.adapter.supports(cap),
				f"Mock adapter {cap.value!r} capability'sini desteklemiyor.",
			)

	def test_authenticate_returns_dict(self) -> None:
		"""authenticate() dict donmeli."""
		result: dict = self.adapter.authenticate()
		self.assertIsInstance(result, dict)
		self.assertIn("token", result)

	def test_track_returns_tracking_response(self) -> None:
		"""track() TrackingResponse donmeli."""
		result: TrackingResponse = self.adapter.track("TEST-123")
		self.assertIsInstance(result, TrackingResponse)
		self.assertIsNotNone(result.current_status)
		self.assertGreater(len(result.events), 0)

	def test_create_shipment_returns_response(self) -> None:
		"""create_shipment() ShipmentResponse donmeli."""
		request: ShipmentRequest = ShipmentRequest(
			origin={"city": "Istanbul"},
			destination={"city": "Ankara"},
			parcels=[{"weight": 5.0}],
		)
		result: ShipmentResponse = self.adapter.create_shipment(request)
		self.assertIsInstance(result, ShipmentResponse)
		self.assertTrue(len(result.tracking_number) > 0)
		self.assertTrue(len(result.carrier_shipment_id) > 0)

	def test_get_quote_returns_response(self) -> None:
		"""get_quote() QuoteResponse donmeli."""
		request: QuoteRequest = QuoteRequest(
			origin={"city": "Istanbul"},
			destination={"city": "Ankara"},
			parcels=[{"weight": 5.0}],
		)
		result: QuoteResponse = self.adapter.get_quote(request)
		self.assertIsInstance(result, QuoteResponse)
		self.assertGreater(len(result.rates), 0)
		self.assertEqual(result.currency, "TRY")

	def test_supports_method_works(self) -> None:
		"""supports() metodu capability kontrolu yapmali."""
		self.assertTrue(self.adapter.supports(CarrierCapability.TRACK))
		# Tum capability'leri destekleyen mock icin hepsi True olmali
		for cap in self.adapter.capabilities:
			self.assertTrue(self.adapter.supports(cap))


class TestAdapterRegistry(unittest.TestCase):
	"""Adapter registry mekanizmasi testleri."""

	def setUp(self) -> None:
		"""Her test oncesi registry'yi temizle."""
		self._original_registry: dict = dict(_CARRIER_REGISTRY)
		_CARRIER_REGISTRY.clear()

	def tearDown(self) -> None:
		"""Her test sonrasi registry'yi geri yukle."""
		_CARRIER_REGISTRY.clear()
		_CARRIER_REGISTRY.update(self._original_registry)

	def test_register_and_retrieve(self) -> None:
		"""Adapter kaydet ve geri al."""
		register_carrier("mock_carrier", MockCarrierAdapter)
		adapter: BaseCarrierAdapter = get_adapter("mock_carrier")
		self.assertIsInstance(adapter, MockCarrierAdapter)

	def test_list_registered_carriers(self) -> None:
		"""Kayitli carrier'lari listele."""
		register_carrier("mock_carrier", MockCarrierAdapter)
		carriers: list = list_registered_carriers()
		self.assertGreater(len(carriers), 0)
		codes: list[str] = [c["carrier_code"] for c in carriers]
		self.assertIn("mock_carrier", codes)

	def test_unknown_carrier_raises(self) -> None:
		"""Bilinmeyen carrier kodu hata firlatmali."""
		with self.assertRaises(KeyError):
			get_adapter("bilinmeyen_firma")

	def test_register_invalid_class_raises(self) -> None:
		"""BaseCarrierAdapter'dan turetilmemis sinif kaydedilemez."""
		with self.assertRaises(TypeError):
			register_carrier("invalid", str)  # type: ignore[arg-type]

	def test_register_empty_code_raises(self) -> None:
		"""Bos carrier kodu ile kayit yapilamaz."""
		with self.assertRaises(ValueError):
			register_carrier("", MockCarrierAdapter)

	def test_duplicate_registration_raises(self) -> None:
		"""Ayni carrier kodu iki kez kaydedilemez."""
		register_carrier("mock_carrier", MockCarrierAdapter)
		with self.assertRaises(ValueError):
			register_carrier("mock_carrier", MockCarrierAdapter)


if __name__ == "__main__":
	unittest.main()
