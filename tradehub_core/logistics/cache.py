# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü cache yönetimi.

Dashboard ve sık erişilen lojistik verilerinin cache key'lerini tanımlar
ve invalidation fonksiyonlarını sağlar.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from tradehub_core.logistics.constants import CACHE_PREFIX

# ---------------------------------------------------------------------------
# Cache key tanımları
# ---------------------------------------------------------------------------

LOGISTICS_CACHE_KEYS: list[str] = [
	f"{CACHE_PREFIX}dashboard:seller:{{seller_id}}",
	f"{CACHE_PREFIX}dashboard:platform",
	f"{CACHE_PREFIX}carrier:list",
	f"{CACHE_PREFIX}carrier:capabilities:{{carrier_id}}",
	f"{CACHE_PREFIX}shipment:tracking:{{tracking_number}}",
	f"{CACHE_PREFIX}shipment:count:{{seller_id}}",
	f"{CACHE_PREFIX}settings",
]


def invalidate_logistics_dashboard(
	doc: Document | None = None,
	method: str | None = None,
) -> None:
	"""Tüm lojistik dashboard cache key'lerini siler.

	Shipment oluşturulduğunda, güncellendiğinde veya silindiğinde
	çağrılarak dashboard verilerinin güncelliğini sağlar.

	Args:
		doc: Tetikleyen doküman (varsa). Seller-spesifik cache temizliği
			için kullanılır.
		method: Frappe hook method adı.
	"""
	cache = frappe.cache

	# Platform dashboard cache'i her zaman temizle
	cache.delete_value(f"{CACHE_PREFIX}dashboard:platform")

	# Seller-spesifik cache temizliği — Shipment tenant alanı seller_profile
	# (Dalga B düzeltmesi: eski `seller` alan adı şemada hiç var olmadı).
	if doc and hasattr(doc, "seller_profile") and doc.seller_profile:
		seller_id = doc.seller_profile
		cache.delete_value(f"{CACHE_PREFIX}dashboard:seller:{seller_id}")
		cache.delete_value(f"{CACHE_PREFIX}shipment:count:{seller_id}")

	# Tracking cache temizliği
	if doc and hasattr(doc, "tracking_number") and doc.tracking_number:
		cache.delete_value(
			f"{CACHE_PREFIX}shipment:tracking:{doc.tracking_number}"
		)

	# Settings cache temizliği
	cache.delete_value(f"{CACHE_PREFIX}settings")

	# Cached doc invalidation — frappe.get_cached_doc sonucu da temizlensin
	frappe.clear_document_cache("Logistics Settings", "Logistics Settings")
