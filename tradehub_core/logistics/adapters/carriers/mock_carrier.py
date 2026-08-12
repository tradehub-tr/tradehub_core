# Copyright (c) 2024, Istoc.com and contributors
# For license information, please see license.txt

"""Test ve development icin MockCarrierAdapter."""

from __future__ import annotations

import hashlib
from typing import Any

from tradehub_core.logistics.adapters.base import (
	BaseCarrierAdapter,
	CancelResponse,
	CarrierCapability,
	QuoteRequest,
	QuoteResponse,
	ShipmentRequest,
	ShipmentResponse,
	TrackingEvent,
	TrackingResponse,
)


class MockCarrierAdapter(BaseCarrierAdapter):
	"""Deterministik fake data ureten test/development adapter'i.

	Tum CarrierCapability degerlerini destekler.
	Gercek bir kargo firmasina HTTP cagrisi yapmaz.
	"""

	name: str = "mock_carrier"
	display_name: str = "Mock Carrier (Test)"
	capabilities: set[CarrierCapability] = {
		CarrierCapability.QUOTE,
		CarrierCapability.CREATE_SHIPMENT,
		CarrierCapability.CANCEL_SHIPMENT,
		CarrierCapability.LABEL,
		CarrierCapability.PICKUP,
		CarrierCapability.TRACK,
		CarrierCapability.WEBHOOK,
		CarrierCapability.MULTI_PARCEL,
		CarrierCapability.COD,
		CarrierCapability.INSURANCE,
	}

	def __init__(
		self,
		credential_doc: dict[str, Any] | None = None,
		environment: str = "sandbox",
	) -> None:
		super().__init__(credential_doc=credential_doc, environment=environment)
		self._authenticated: bool = False

	# -------------------------------------------------------------------
	# Zorunlu abstract metotlar
	# -------------------------------------------------------------------

	def authenticate(self) -> dict[str, Any]:
		"""Sahte kimlik dogrulama — her zaman basarili."""
		self._authenticated = True
		return {
			"token": "mock-token-abc123",
			"expires_in": 3600,
		}

	def get_quote(self, request: QuoteRequest) -> QuoteResponse:
		"""Deterministik fiyat teklifi dondur."""
		self._check_capability(CarrierCapability.QUOTE)

		parcel_count: int = len(request.parcels) if request.parcels else 1
		base_rate: float = 25.00 * parcel_count

		return QuoteResponse(
			rates=[
				{
					"service_type": request.service_type or "standard",
					"amount": base_rate,
					"currency": "TRY",
					"estimated_days": 3,
				},
				{
					"service_type": "express",
					"amount": base_rate * 1.5,
					"currency": "TRY",
					"estimated_days": 1,
				},
			],
			currency="TRY",
			raw_response={"mock": True},
		)

	def create_shipment(self, request: ShipmentRequest) -> ShipmentResponse:
		"""Deterministik gonderi olustur."""
		self._check_capability(CarrierCapability.CREATE_SHIPMENT)

		ref: str = request.reference_number or "NO-REF"
		tracking_hash: str = hashlib.md5(ref.encode()).hexdigest()[:12].upper()
		tracking_number: str = f"MOCK{tracking_hash}"

		return ShipmentResponse(
			tracking_number=tracking_number,
			carrier_shipment_id=f"MOCK-SHP-{tracking_hash}",
			label_url=f"https://mock-carrier.test/labels/{tracking_number}.pdf",
			raw_response={"mock": True, "reference": ref},
		)

	def track(self, tracking_number: str) -> TrackingResponse:
		"""Deterministik takip bilgisi dondur."""
		self._check_capability(CarrierCapability.TRACK)

		events: list[TrackingEvent] = [
			TrackingEvent(
				timestamp="2025-01-01T10:00:00+03:00",
				status="PICKED_UP",
				description="Gonderi teslim alindi.",
				location="Istanbul",
			),
			TrackingEvent(
				timestamp="2025-01-01T14:00:00+03:00",
				status="IN_TRANSIT",
				description="Aktarma merkezine ulasti.",
				location="Istanbul - Anadolu",
			),
			TrackingEvent(
				timestamp="2025-01-02T09:00:00+03:00",
				status="OUT_FOR_DELIVERY",
				description="Dagitima cikarildi.",
				location="Ankara",
			),
			TrackingEvent(
				timestamp="2025-01-02T15:00:00+03:00",
				status="DELIVERED",
				description="Teslim edildi.",
				location="Ankara",
			),
		]

		return TrackingResponse(
			events=events,
			current_status="DELIVERED",
			raw_response={"mock": True, "tracking_number": tracking_number},
		)

	# -------------------------------------------------------------------
	# Opsiyonel metotlar
	# -------------------------------------------------------------------

	def cancel_shipment(self, shipment_id: str) -> CancelResponse:
		"""Sahte iptal — her zaman basarili."""
		self._check_capability(CarrierCapability.CANCEL_SHIPMENT)

		return CancelResponse(
			success=True,
			message=f"Mock gonderi {shipment_id} iptal edildi.",
			raw_response={"mock": True, "cancelled_id": shipment_id},
		)

	def get_label(self, shipment_id: str, fmt: str = "PDF") -> bytes:
		"""Sahte etiket verisi dondur."""
		self._check_capability(CarrierCapability.LABEL)

		return b"%PDF-1.4 mock-label-content"

	def schedule_pickup(self, request: dict[str, Any]) -> dict[str, Any]:
		"""Sahte kurye cagrisi planla."""
		self._check_capability(CarrierCapability.PICKUP)

		return {
			"pickup_id": "MOCK-PICKUP-001",
			"scheduled_date": request.get("date", "2025-01-03"),
			"time_slot": request.get("time_slot", "09:00-12:00"),
			"status": "CONFIRMED",
			"mock": True,
		}
