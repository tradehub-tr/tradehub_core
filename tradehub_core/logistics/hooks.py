# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü doc_event handler stub fonksiyonları.

Bu fonksiyonlar hooks.py doc_events üzerinden Shipment DocType'ına
bağlanır. Şu an stub olarak tanımlanmıştır, implementasyon ilerleyen
fazlarda tamamlanacaktır.
"""

from __future__ import annotations

from frappe.model.document import Document


def validate_state_transition(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat durum geçişini doğrular.

	ALLOWED_TRANSITIONS matrisine göre geçersiz durum geçişlerini engeller.
	Geçersiz geçiş durumunda ShipmentStateError fırlatır.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	pass


def snapshot_addresses(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat adres snapshot'ı alır.

	Gönderici ve alıcı adreslerinin anlık kopyasını sevkiyat üzerine
	kaydeder. Adres sonradan değişse bile sevkiyattaki bilgi korunur.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	pass


def snapshot_items(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat kalem snapshot'ı alır.

	Sevk edilen ürün kalemlerinin anlık kopyasını (miktar, ağırlık, hacim)
	sevkiyat üzerine kaydeder.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	pass


def on_shipment_created(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat oluşturulduğunda tetiklenen handler.

	Yeni sevkiyat oluşturulduğunda bildirim gönderme, dashboard
	güncelleme ve ilgili Order durumunu ayarlama işlemlerini yapar.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	pass


def on_shipment_status_change(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat durum değişikliğinde tetiklenen handler.

	Durum değişikliğinde tracking log kaydı, bildirim gönderme ve
	ilgili Order fulfillment durumunu güncelleme işlemlerini tetikler.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	pass


def update_order_fulfillment(doc: Document, method: str | None = None) -> None:
	"""Order.fulfillment_status alanını günceller.

	Sevkiyat durumuna göre bağlı Order'ın fulfillment_status alanını
	hesaplar ve günceller. Kısmi sevkiyat, tam sevkiyat ve iptal
	durumlarını yönetir.

	NOT: fulfillment_status alanı TUR-105 kapsamında Order DocType'ına
	eklenecektir. Bu alan mevcut olana kadar fonksiyon stub olarak kalır.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	pass


def validate_split_invariants(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat bölme değişmezlerini kontrol eder (INV-1..5).

	INV-1: Bölünen kalemlerin toplam miktarı orijinal miktara eşit olmalı.
	INV-2: Bölünmüş sevkiyatlar aynı Order'a bağlı olmalı.
	INV-3: Bölünmüş sevkiyatlarda kalem çakışması olmamalı.
	INV-4: Bölme sonrası orijinal sevkiyat durumu güncellenmiş olmalı.
	INV-5: Terminal durumdaki sevkiyat bölünemez.

	Kural ihlalinde SplitInvariantError fırlatır.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	pass
