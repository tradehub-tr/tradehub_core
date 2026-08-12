# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü sabitleri.

Sevkiyat durumları, geçiş matrisi, tip tanımları ve feature flag
default'larını içerir. Tüm lojistik modülleri bu sabitleri referans alır.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shipment Status
# ---------------------------------------------------------------------------

class ShipmentStatus:
	"""Sevkiyat durum string'leri."""

	DRAFT = "Draft"
	PENDING = "Pending"
	READY_FOR_PICKUP = "Ready for Pickup"
	PICKED_UP = "Picked Up"
	IN_TRANSIT = "In Transit"
	AT_WAREHOUSE = "At Warehouse"
	OUT_FOR_DELIVERY = "Out for Delivery"
	DELIVERED = "Delivered"
	RETURNED = "Returned"
	CANCELLED = "Cancelled"
	FAILED = "Failed"

	ALL: tuple[str, ...] = (
		DRAFT,
		PENDING,
		READY_FOR_PICKUP,
		PICKED_UP,
		IN_TRANSIT,
		AT_WAREHOUSE,
		OUT_FOR_DELIVERY,
		DELIVERED,
		RETURNED,
		CANCELLED,
		FAILED,
	)


# ---------------------------------------------------------------------------
# Terminal statuses — bu durumlara geçildiğinde sevkiyat kapanır
# ---------------------------------------------------------------------------

TERMINAL_STATUSES: set[str] = {
	ShipmentStatus.CANCELLED,
	ShipmentStatus.RETURNED,
	ShipmentStatus.DELIVERED,
}

# ---------------------------------------------------------------------------
# Allowed transitions — durum geçiş matrisi
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
	ShipmentStatus.DRAFT: {
		ShipmentStatus.PENDING,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.PENDING: {
		ShipmentStatus.READY_FOR_PICKUP,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.READY_FOR_PICKUP: {
		ShipmentStatus.PICKED_UP,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.PICKED_UP: {
		ShipmentStatus.IN_TRANSIT,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.IN_TRANSIT: {
		ShipmentStatus.AT_WAREHOUSE,
		ShipmentStatus.OUT_FOR_DELIVERY,
		ShipmentStatus.DELIVERED,
		ShipmentStatus.FAILED,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.AT_WAREHOUSE: {
		ShipmentStatus.IN_TRANSIT,
		ShipmentStatus.OUT_FOR_DELIVERY,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.OUT_FOR_DELIVERY: {
		ShipmentStatus.DELIVERED,
		ShipmentStatus.FAILED,
		ShipmentStatus.RETURNED,
	},
	ShipmentStatus.DELIVERED: set(),
	ShipmentStatus.RETURNED: set(),
	ShipmentStatus.CANCELLED: set(),
	ShipmentStatus.FAILED: {
		ShipmentStatus.IN_TRANSIT,
		ShipmentStatus.RETURNED,
		ShipmentStatus.CANCELLED,
	},
}


# ---------------------------------------------------------------------------
# Shipment Type
# ---------------------------------------------------------------------------

class ShipmentType:
	"""Sevkiyat tipleri."""

	STANDARD = "Standard"
	SELLER_DELIVERY = "Seller Delivery"
	BUYER_PICKUP = "Buyer Pickup"
	WAREHOUSE_TRANSFER = "Warehouse Transfer"

	ALL: tuple[str, ...] = (
		STANDARD,
		SELLER_DELIVERY,
		BUYER_PICKUP,
		WAREHOUSE_TRANSFER,
	)


# ---------------------------------------------------------------------------
# Leg Type
# ---------------------------------------------------------------------------

class LegType:
	"""Sevkiyat bacak tipleri."""

	PICKUP = "Pickup"
	LINE_HAUL = "Line Haul"
	TRANSFER = "Transfer"
	LAST_MILE = "Last Mile"
	RETURN = "Return"

	ALL: tuple[str, ...] = (
		PICKUP,
		LINE_HAUL,
		TRANSFER,
		LAST_MILE,
		RETURN,
	)


# ---------------------------------------------------------------------------
# Leg Status
# ---------------------------------------------------------------------------

class LegStatus:
	"""Sevkiyat bacak durumları."""

	PLANNED = "Planned"
	IN_PROGRESS = "In Progress"
	ARRIVED = "Arrived"
	COMPLETED = "Completed"
	CANCELLED = "Cancelled"

	ALL: tuple[str, ...] = (
		PLANNED,
		IN_PROGRESS,
		ARRIVED,
		COMPLETED,
		CANCELLED,
	)


# ---------------------------------------------------------------------------
# Cost Paid By
# ---------------------------------------------------------------------------

class CostPaidBy:
	"""Kargo ücretini ödeyen taraf."""

	SELLER = "Seller"
	BUYER = "Buyer"
	PLATFORM = "Platform"

	ALL: tuple[str, ...] = (
		SELLER,
		BUYER,
		PLATFORM,
	)


# ---------------------------------------------------------------------------
# Feature flag defaults
# ---------------------------------------------------------------------------

LOGISTICS_FEATURE_FLAGS: dict[str, bool] = {
	"carrier_api_enabled": False,
	"multi_carrier_enabled": False,
	"shipping_zone_pricing_enabled": False,
	"auto_tracking_enabled": False,
	"split_shipment_enabled": False,
	"multi_leg_enabled": False,
	"cost_estimation_enabled": False,
	"webhook_notifications_enabled": False,
	"return_flow_enabled": False,
	"seller_delivery_enabled": False,
	"buyer_pickup_enabled": False,
	"warehouse_transfer_enabled": False,
}


# ---------------------------------------------------------------------------
# Genel sabitler
# ---------------------------------------------------------------------------

CACHE_PREFIX: str = "tc:logistics:"

SHIPMENT_NAMING_SERIES: str = "SHP-.YYYY.-.#####"

API_VERSION: str = "v1"
