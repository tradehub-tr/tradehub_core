# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Kargo firma adapter sozlesmesi (Abstract Base Class)."""

from __future__ import annotations

import abc
import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from frappe import _

from tradehub_core.logistics.adapters.signature import verify_hmac_signature
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
	service_type: str | None = None


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
	service_type: str | None = None
	reference_number: str | None = None
	cod_amount: float | None = None
	insurance_amount: float | None = None
	metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShipmentResponse:
	"""Gonderi olusturma yaniti."""

	tracking_number: str
	carrier_shipment_id: str
	label_url: str | None = None
	raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrackingEvent:
	"""Tek bir takip olayi."""

	timestamp: str
	status: str
	description: str
	location: str | None = None
	raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrackingResponse:
	"""Takip sorgu yaniti."""

	events: list[TrackingEvent] = field(default_factory=list)
	current_status: str | None = None
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

	# Webhook imza semasi (default: platform HMAC-SHA256 semasi).
	# Ozel imza semali tasiyicilar bu attribute'lari VEYA
	# `verify_webhook_signature`'in kendisini override eder.
	# NOT: Kanonik sabitler `logistics/constants.py`'de (BE-1) — endpoint
	# fallback'i oradan okur; buradakiler adapter-bazli override noktasidir
	# ve default'ta ayni degerlerdir (W1).
	webhook_signature_header: str = "X-Webhook-Signature"
	webhook_signature_prefix: str = "sha256="

	def __init__(
		self,
		credential_doc: dict[str, Any] | None = None,
		environment: str = "production",
	) -> None:
		self.credential_doc: dict[str, Any] | None = credential_doc
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
	# Webhook metotlari (09-BE webhook dilimi — AC-12)
	# -------------------------------------------------------------------

	def verify_webhook_signature(self, raw_body: bytes, headers: Mapping[str, str], secret: str) -> bool:
		"""Inbound webhook imzasini dogrula (default: HMAC-SHA256).

		Default implementasyon `webhook_signature_header` basligini headers
		Mapping'inden BUYUK/KUCUK HARF DUYARSIZ okur (HTTP basliklari proxy
		katmanlarinda normalize gelebilir) ve W1'in saf helper'ina
		(`signature.verify_hmac_signature`) delege eder — endpoint'in
		adapter'siz fallback yoluyla AYNI fonksiyon.

		Ozel imza semali tasiyicilar bu metodu override eder.
		Asla exception firlatmaz; dogrulanamayan her istek False'tur.
		"""
		signature_header: str | None = None
		if headers:
			target: str = self.webhook_signature_header.lower()
			for key, value in headers.items():
				if isinstance(key, str) and key.lower() == target:
					signature_header = value
					break
		return verify_hmac_signature(raw_body, signature_header, secret, prefix=self.webhook_signature_prefix)

	def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> list[TrackingEvent]:
		"""Inbound webhook govdesini TrackingEvent listesine cevir.

		Opsiyonel metot — default'u once WEBHOOK capability kontrolu yapar
		(cancel_shipment vb. ile ayni desen), capability bildirilmis ama
		metot override edilmemisse yine CarrierCapabilityError firlatir
		(AC-11: job tarafinda CAPABILITY_UNSUPPORTED'a cevrilir).
		"""
		self._check_capability(CarrierCapability.WEBHOOK)
		raise CarrierCapabilityError(
			_("{0} adapteri webhook ayristirmayi desteklemiyor.").format(self.display_name)
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
