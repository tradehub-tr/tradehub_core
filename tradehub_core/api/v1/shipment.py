# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Sevkiyat CRUD + durum gecis API'leri (v1, authenticated)."""

from __future__ import annotations

import frappe
from frappe import _


@frappe.whitelist()
def create_shipment(
	order_id: str,
	carrier: str | None = None,
	tracking_number: str | None = None,
) -> dict:
	"""Yeni sevkiyat olusturur.

	Args:
		order_id: Bagli Order ID.
		carrier: Kargo firmasi.
		tracking_number: Takip numarasi.

	Returns:
		Olusturulan sevkiyat bilgisi.
	"""
	frappe.only_for(["Marketplace Seller", "Logistics Manager", "Logistics Operator"])
	# TODO(TUR-105): Shipment DocType CRUD implementasyonu
	frappe.throw(
		_("Sevkiyat olusturma henuz aktif degil."),
		exc=frappe.ValidationError,
	)


@frappe.whitelist()
def update_shipment_status(
	shipment_id: str,
	status: str,
	note: str | None = None,
) -> dict:
	"""Sevkiyat durumunu gunceller.

	Args:
		shipment_id: Sevkiyat ID.
		status: Yeni durum.
		note: Opsiyonel durum notu.

	Returns:
		Guncellenmis sevkiyat bilgisi.
	"""
	frappe.only_for(["Marketplace Seller", "Logistics Manager", "Logistics Operator"])
	# TODO(TUR-106): Durum gecis motoru implementasyonu
	frappe.throw(
		_("Sevkiyat durum guncellemesi henuz aktif degil."),
		exc=frappe.ValidationError,
	)


@frappe.whitelist()
def get_shipment_detail(shipment_id: str) -> dict:
	"""Sevkiyat detayini dondurur.

	Buyer veya seller izolasyonu uygulanir: kullanici yalnizca kendi
	siparisine bagli sevkiyati goruntuleyebilir.

	Args:
		shipment_id: Sevkiyat ID.

	Returns:
		Sevkiyat detay bilgisi.
	"""
	# TODO(TUR-107): Shipment detail implementasyonu
	# TODO(TUR-107): doc = frappe.get_doc("Shipment", shipment_id)
	# TODO(TUR-107): doc.check_permission("read")  # buyer/seller izolasyonu
	frappe.throw(
		_("Sevkiyat detay servisi henuz aktif degil."),
		exc=frappe.ValidationError,
	)


@frappe.whitelist()
def list_shipments(
	order_id: str | None = None,
	status: str | None = None,
	page: int = 1,
	page_size: int = 20,
) -> dict:
	"""Sevkiyatlari listeler.

	Seller tenant izolasyonu uygulanir: frappe.get_list uzerinden
	permission_query_conditions devreye girer ve kullanici yalnizca
	kendi tenant'ina ait sevkiyatlari goruntuler.

	Args:
		order_id: Opsiyonel Order ID filtresi.
		status: Opsiyonel durum filtresi.
		page: Sayfa numarasi.
		page_size: Sayfa boyutu.

	Returns:
		Sevkiyat listesi ve sayfalama bilgisi.
	"""
	# TODO(TUR-108): Shipment list implementasyonu
	# TODO(TUR-108): frappe.get_list kullanilacak (permission_query_conditions ile tenant izolasyonu)
	frappe.throw(
		_("Sevkiyat listeleme henuz aktif degil."),
		exc=frappe.ValidationError,
	)


@frappe.whitelist()
def cancel_shipment(shipment_id: str, reason: str | None = None) -> dict:
	"""Sevkiyati iptal eder.

	Args:
		shipment_id: Sevkiyat ID.
		reason: Iptal nedeni.

	Returns:
		Iptal edilmis sevkiyat bilgisi.
	"""
	frappe.only_for(["Marketplace Seller", "Logistics Manager", "Logistics Operator"])
	# TODO(TUR-109): Shipment cancel implementasyonu
	frappe.throw(
		_("Sevkiyat iptali henuz aktif degil."),
		exc=frappe.ValidationError,
	)
