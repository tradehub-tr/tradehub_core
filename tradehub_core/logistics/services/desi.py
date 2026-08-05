# Copyright (c) 2024, Istoc.com and contributors
# For license information, please see license.txt

"""Desi (hacimsel agirlik) hesaplama utility."""

from __future__ import annotations

import math
from typing import Literal

from frappe import _


def calculate_desi(
	length_cm: float,
	width_cm: float,
	height_cm: float,
	divisor: int = 3000,
	rounding: Literal["ceil", "floor", "none"] = "ceil",
) -> float:
	"""Hacimsel agirlik (desi) hesapla.

	Args:
		length_cm: Paket uzunlugu (cm).
		width_cm: Paket genisligi (cm).
		height_cm: Paket yuksekligi (cm).
		divisor: Hacimsel bolen (varsayilan 3000, uluslararasi 5000).
		rounding: Yuvarlama modu — "ceil", "floor" veya "none".

	Returns:
		Hesaplanan desi degeri.
	"""
	if length_cm < 0 or width_cm < 0 or height_cm < 0:
		raise ValueError(_("Boyut degerleri negatif olamaz."))
	if divisor <= 0:
		raise ValueError(_("Bolen sifir veya negatif olamaz."))

	volume: float = length_cm * width_cm * height_cm
	desi: float = volume / divisor

	if rounding == "ceil":
		return float(math.ceil(desi))
	elif rounding == "floor":
		return float(math.floor(desi))
	return round(desi, 4)


def get_chargeable_weight(actual_weight_kg: float, desi: float) -> float:
	"""Ucretlendirilebilir agirligi dondur (fiili vs hacimsel, hangisi buyukse).

	Args:
		actual_weight_kg: Fiili agirlik (kg).
		desi: Hacimsel agirlik (desi).

	Returns:
		Ucretlendirilebilir agirlik (kg).
	"""
	return max(actual_weight_kg, desi)


def calculate_shipment_totals(items: list[dict]) -> dict:
	"""Gonderi icindeki tum parcalar icin toplam agirlik, desi ve ucretlendirilebilir agirlik hesapla.

	Her item dict'i su alanlari icermelidir:
		- length_cm (float)
		- width_cm (float)
		- height_cm (float)
		- weight_kg (float)
		- qty (int, varsayilan 1)

	Opsiyonel:
		- divisor (int, varsayilan 3000)

	Args:
		items: Paket bilgilerini iceren dict listesi.

	Returns:
		{
			"total_weight": float,
			"total_desi": float,
			"chargeable_weight": float,
			"parcel_count": int,
		}
	"""
	total_weight: float = 0.0
	total_desi: float = 0.0
	parcel_count: int = 0

	for item in items:
		qty: int = int(item.get("qty", 1))
		divisor: int = int(item.get("divisor", 3000))

		desi: float = calculate_desi(
			length_cm=float(item["length_cm"]),
			width_cm=float(item["width_cm"]),
			height_cm=float(item["height_cm"]),
			divisor=divisor,
			rounding="ceil",
		)

		weight: float = float(item["weight_kg"])

		total_weight += weight * qty
		total_desi += desi * qty
		parcel_count += qty

	chargeable_weight: float = get_chargeable_weight(total_weight, total_desi)

	return {
		"total_weight": total_weight,
		"total_desi": total_desi,
		"chargeable_weight": chargeable_weight,
		"parcel_count": parcel_count,
	}
