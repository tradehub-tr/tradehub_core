# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik public API endpoint'leri (v1).

`tradehub_core/api/logistics.py`'den taşındı — lojistik yüzeyinin tamamı tek
sürümlü namespace altında toplanıyor (bkz. docs/LOGISTICS-ARCHITECTURE.md §4.1).
Taşıma kırıcı DEĞİL: eski yol hiçbir frontend'den çağrılmıyordu.

Buradaki endpoint'ler misafir kullanıcıya açıktır; satıcı/alıcı verisine dokunan
her şey `api/v1/shipment.py` ve `api/v1/logistics_catalog.py` altındadır.
"""

from __future__ import annotations

import frappe
from frappe import _

# STOREFRONT_VISIBLE_STATUSES: misafire yalnız yayında olan ilanların lojistik
# verisi gösterilir. Sabit `api/listing.py` ile ortak — kopyalanmıyor.
from tradehub_core.api.listing import STOREFRONT_VISIBLE_STATUSES
from tradehub_core.logistics.api_utils import logistics_endpoint, ok
from tradehub_core.logistics.exceptions import LogisticsError


def _assert_listing_publicly_visible(listing_id: str) -> None:
	"""İlan misafire görünür durumda değilse erişimi reddeder.

	GÜVENLİK: Bu kontrol olmadan taslak / reddedilmiş / arşivlenmiş bir ilanın
	kargo yöntemleri ve maliyetleri, ID'yi tahmin eden herkese açık oluyordu —
	`api/listing.get_shipping_methods` `frappe.get_doc` çağırıp durum kontrolü
	yapmıyor. Sarmalayıcı ikinci bir kapı açmamalı.
	"""
	status = frappe.db.get_value("Listing", listing_id, "status")
	if status is None:
		raise frappe.DoesNotExistError(_("İlan bulunamadı."))
	if status not in STOREFRONT_VISIBLE_STATUSES:
		# Var olduğunu da sızdırma — "bulunamadı" ile aynı yanıt
		raise frappe.DoesNotExistError(_("İlan bulunamadı."))


@frappe.whitelist(allow_guest=True)
@logistics_endpoint()
def get_available_shipping_methods(
	listing_id: str | None = None,
	lang: str = "tr",
) -> dict:
	"""Mevcut kargo yöntemlerini listeler.

	Feature flag KAPISI YOK: bu endpoint mevcut storefront davranışını sürdürüyor
	ve lojistik modülü kapalıyken de çalışmalı (kargo yöntemleri modülden önce
	de vardı).

	Args:
		listing_id: Opsiyonel ilan filtresi. Verilirse ilan yayında olmalı.
		lang: Dil kodu.

	Returns:
		Kargo yöntemleri listesi.
	"""
	from tradehub_core.api.listing import get_shipping_methods

	if listing_id:
		_assert_listing_publicly_visible(listing_id)

	# get_shipping_methods {"data": [...]} döndürüyor; zarfın içine ikinci bir
	# "data" katmanı koymamak için listeyi çıkarıyoruz → {"ok": true, "data": [...]}
	legacy_response = get_shipping_methods(listing_id=listing_id, lang=lang)
	return ok(legacy_response.get("data", []))


@frappe.whitelist(allow_guest=True)
@logistics_endpoint(flag="cost_estimation_enabled")
def estimate_shipping_cost(
	origin: str | None = None,
	destination: str | None = None,
	weight_kg: float | None = None,
	listing_id: str | None = None,
) -> dict:
	"""Tahmini kargo maliyetini hesaplar.

	Bayrak kapalıyken FEATURE_DISABLED (403) döner — istemci bunu "yetkiniz yok"
	ile karıştırmadan "bu özellik henüz açık değil" olarak gösterebilir.

	Args:
		origin: Gönderim bölge/il kodu.
		destination: Teslimat bölge/il kodu.
		weight_kg: Paket ağırlığı (kg).
		listing_id: Opsiyonel ilan ID'si.

	Returns:
		Tahmini maliyet bilgisi.
	"""
	if listing_id:
		_assert_listing_publicly_visible(listing_id)

	# Fiyatlandırma motoru F bloğunda yazılacak; bayrak açıldığında sessizce
	# yanlış sonuç dönmektense açık hata vermek doğru.
	raise LogisticsError(
		_("Kargo maliyet tahmini henüz uygulanmadı (fiyatlandırma motoru bekleniyor).")
	)


@frappe.whitelist(allow_guest=True)
@logistics_endpoint(flag="auto_tracking_enabled")
def track_shipment_public(tracking_number: str) -> dict:
	"""Takip numarasıyla kargo durumunu döndürür (public).

	Args:
		tracking_number: Kargo takip numarası.

	Returns:
		Takip durumu bilgisi.
	"""
	if not tracking_number or not tracking_number.strip():
		frappe.throw(_("Takip numarası zorunludur."))

	# Takip servisi F bloğunda yazılacak.
	raise LogisticsError(_("Kargo takip servisi henüz uygulanmadı."))
