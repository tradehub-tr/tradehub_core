# Copyright (c) 2024, Istoc.com and contributors
# For license information, please see license.txt

"""Kargo firma adapter sozlesmesi (Abstract Base Class)."""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from typing import Any, Optional

from frappe import _

from tradehub_core.logistics.exceptions import CarrierCapabilityError


class CarrierCapability(enum.Enum):
	"""Bir kargo firmasinin destekledigi yetenekler."""

	QUOTE = "quote"
	CREATE_SHIPMENT = "create_shipment"
	CANCEL_SHIPMENT = "cancel_shipment"
	LABEL = "label"
	PICKUP = "pickup"
	TRACK = "track"
	WEBHOOK = "webhook"
	MULTI_PARCEL = "multi_parcel"
	COD = "cod"
	INSURANCE = "insurance"


# ---------------------------------------------------------------------------
# Veri kontratlari (Data Contracts)
# ---------------------------------------------------------------------------


@dataclass
class QuoteRequest:
	"""Fiyat teklifi istegi."""

	origin: dict[str, Any]
	destination: dict[str, Any]
	parcels: list[dict[str, Any]]
	service_type: Optional[str] = None


@dataclass
class QuoteResponse:
	"""Fiyat teklifi yaniti."""

	rates: list[dict[str, Any]]
	currency: str = "TRY"
	raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShipmentRequest:
	"""Gonderi olusturma istegi."""

	origin: dict[str, Any] = field(default_factory=dict)
	destination: dict[str, Any] = field(default_factory=dict)
	parcels: list[dict[str, Any]] = field(default_factory=list)
	service_type: Optional[str] = None
	reference_number: Optional[str] = None
	cod_amount: Optional[float] = None
	insurance_amount: Optional[float] = None
	metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShipmentResponse:
	"""Gonderi olusturma yaniti."""

	tracking_number: str
	carrier_shipment_id: str
	label_url: Optional[str] = None
	raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrackingEvent:
	"""Tek bir takip olayi."""

	timestamp: str
	status: str
	description: str
	location: Optional[str] = None
	raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrackingResponse:
	"""Takip sorgu yaniti."""

	events: list[TrackingEvent] = field(default_factory=list)
	current_status: Optional[str] = None
	raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class CancelResponse:
	"""Gonderi iptal yaniti."""

	success: bool
	message: str = ""
	raw_response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract Base Adapter
# ---------------------------------------------------------------------------


class BaseCarrierAdapter(abc.ABC):
	"""Tum kargo firma adapterleri icin temel soyut sinif.

	Her yeni kargo entegrasyonu bu sinifi miras almali ve
	abstract metotlari implement etmelidir.
	"""

	name: str = ""
	display_name: str = ""

	def __init__(
		self,
		credential_doc: Optional[dict[str, Any]] = None,
		environment: str = "production",
	) -> None:
		self.credential_doc: Optional[dict[str, Any]] = credential_doc
		self.environment: str = environment
		self.capabilities: set[CarrierCapability] = getattr(self, "capabilities", set())

	# -------------------------------------------------------------------
	# Abstract metotlar (zorunlu)
	# -------------------------------------------------------------------

	@abc.abstractmethod
	def authenticate(self) -> dict[str, Any]:
		"""Kargo firmasina kimlik dogrulama yap."""
		...

	@abc.abstractmethod
	def get_quote(self, request: QuoteRequest) -> QuoteResponse:
		"""Fiyat teklifi al."""
		...

	@abc.abstractmethod
	def create_shipment(self, request: ShipmentRequest) -> ShipmentResponse:
		"""Yeni gonderi olustur."""
		...

	@abc.abstractmethod
	def track(self, tracking_number: str) -> TrackingResponse:
		"""Gonderi takip bilgisi sorgula."""
		...

	# -------------------------------------------------------------------
	# Opsiyonel metotlar (varsayilan CarrierCapabilityError — HTTP 400)
	# -------------------------------------------------------------------

	def cancel_shipment(self, shipment_id: str) -> CancelResponse:
		"""Gonderiyi iptal et."""
		raise CarrierCapabilityError(
			_("{0} adapteri iptal islemini desteklemiyor.").format(self.display_name)
		)

	def get_label(self, shipment_id: str, fmt: str = "PDF") -> bytes:
		"""Gonderi etiketini indir."""
		raise CarrierCapabilityError(
			_("{0} adapteri etiket indirmeyi desteklemiyor.").format(self.display_name)
		)

	def schedule_pickup(self, request: dict[str, Any]) -> dict[str, Any]:
		"""Kurye cagrisi planla."""
		raise CarrierCapabilityError(
			_("{0} adapteri kurye cagrisini desteklemiyor.").format(self.display_name)
		)

	# -------------------------------------------------------------------
	# Yardimci metotlar
	# -------------------------------------------------------------------

	def supports(self, capability: CarrierCapability) -> bool:
		"""Adapterin belirli bir yetenegi destekleyip desteklemedigini kontrol et."""
		return capability in self.capabilities

	def _check_capability(self, capability: CarrierCapability) -> None:
		"""Yetenek kontrolu yap, desteklenmiyorsa CarrierCapabilityError firlat."""
		if not self.supports(capability):
			raise CarrierCapabilityError(
				_("{0} adapteri {1} yetenegini desteklemiyor.").format(
					self.display_name, capability.value
				)
			)

	def __repr__(self) -> str:
		return f"<{self.__class__.__name__} name={self.name!r} env={self.environment!r}>"
