# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik public API endpoint'leri (storefront guest)."""

from __future__ import annotations

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_available_shipping_methods(
	listing_id: str | None = None,
	lang: str = "tr",
) -> dict:
	"""Mevcut kargo yontemlerini listeler.

	Mevcut api/listing.py'deki get_shipping_methods'u sarar.

	Args:
		listing_id: Opsiyonel listing ID filtresi.
		lang: Dil kodu (varsayilan "tr").

	Returns:
		Kargo yontemleri listesi.
	"""
	# TODO(TUR-104): Yeni katalog yapisi ile entegre et
	from tradehub_core.api.listing import get_shipping_methods

	return get_shipping_methods(listing_id=listing_id, lang=lang)


@frappe.whitelist(allow_guest=True)
def estimate_shipping_cost(
	origin: str | None = None,
	destination: str | None = None,
	weight_kg: float | None = None,
	listing_id: str | None = None,
) -> dict:
	"""Tahmini kargo maliyetini hesaplar.

	Args:
		origin: Gonderim bolge/il kodu.
		destination: Teslimat bolge/il kodu.
		weight_kg: Paket agirligi (kg).
		listing_id: Opsiyonel listing ID.

	Returns:
		Tahmini maliyet bilgisi.
	"""
	# TODO(TUR-121): Fiyatlandirma motoru entegrasyonu
	frappe.throw(
		_("Kargo maliyet tahmini henuz aktif degil."),
		exc=frappe.ValidationError,
	)


@frappe.whitelist(allow_guest=True)
def track_shipment_public(tracking_number: str) -> dict:
	"""Kargo takip bilgisini dondurur (public).

	Args:
		tracking_number: Kargo takip numarasi.

	Returns:
		Takip durumu bilgisi.
	"""
	# TODO(TUR-112): Takip servisi entegrasyonu
	if not tracking_number:
		frappe.throw(_("Takip numarasi zorunludur."))

	frappe.throw(
		_("Kargo takip servisi henuz aktif degil."),
		exc=frappe.ValidationError,
	)
