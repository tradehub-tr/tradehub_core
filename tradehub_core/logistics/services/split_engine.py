# Copyright (c) 2024, Istoc.com and contributors
# For license information, please see license.txt

"""Çok satıcılı/depolu sipariş bölme motoru (Dalga B — LOG-045).

INV-1..5 split invariant'larının veri katmanı: kalan miktar hesabı
(get_remaining_qty) ve Order'dan taslak Shipment üretimi
(create_shipment_draft_from_order). Invariant doğrulaması
logistics/hooks.py validate_split_invariants içindedir.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import cint

from tradehub_core.logistics.constants import ShipmentStatus
from tradehub_core.logistics.exceptions import IdempotencyConflictError, SplitInvariantError


def get_remaining_qty(order_item_name: str, exclude_shipment: str | None = None) -> int:
	"""Order Item için henüz sevk edilmemiş kalan miktarı döndürür.

	Cancelled/Returned sevkiyatlardaki miktarlar sevk edilmiş SAYILMAZ
	(INV-5: iptal/iade kalan miktarı geri açar). exclude_shipment,
	validate senaryosu içindir: mevcut bir Shipment kaydedilirken kendi
	DB'deki eski satırları toplama dahil edilmemelidir.

	Args:
		order_item_name: Order Item child kaydının adı.
		exclude_shipment: Toplam dışında tutulacak Shipment adı (opsiyonel).

	Returns:
		Kalan sevk edilebilir miktar (>= 0).

	Bilinen sınırlama (check-then-insert yarışı): bu okuma ile takip eden
	Shipment insert'i arasında eşzamanlı ikinci bir istek aynı kalan miktarı
	görebilir ve INV-1 toplamı yarış altında aşılabilir. Satır kilidi
	(SELECT ... FOR UPDATE) Görev 18'de değerlendirilecek — şimdilik kod
	değiştirilmedi.
	"""
	ordered_qty: int = cint(frappe.db.get_value("Order Item", order_item_name, "quantity"))

	ShipmentItem = frappe.qb.DocType("Shipment Item")
	Shipment = frappe.qb.DocType("Shipment")

	query = (
		frappe.qb.from_(ShipmentItem)
		.join(Shipment)
		.on(ShipmentItem.parent == Shipment.name)
		.select(Sum(ShipmentItem.qty))
		.where(ShipmentItem.order_item == order_item_name)
		.where(Shipment.status.notin([ShipmentStatus.CANCELLED, ShipmentStatus.RETURNED]))
	)
	if exclude_shipment:
		query = query.where(Shipment.name != exclude_shipment)

	shipped: int = cint(query.run()[0][0] or 0)
	return max(0, ordered_qty - shipped)


def create_shipment_draft_from_order(
	order: str,
	items: list[dict] | None = None,
	idempotency_key: str | None = None,
) -> Document:
	"""Order'dan Draft durumunda Shipment oluşturur (LOG-045).

	seller_profile/buyer/shipping_method Order'dan kopyalanır. items None
	ise siparişin tüm kalemleri KALAN miktarlarının tamamıyla taslağa
	alınır. Doc insert edilip döndürülür (Draft status) — before_insert
	snapshot hook'ları ve validate invariant kontrolleri böylece çalışmış
	olur.

	Args:
		order: Order doc adı.
		items: [{"order_item": ..., "listing": ..., "qty": ...}, ...] veya None.
		idempotency_key: Opsiyonel; aynı key ile mevcut Shipment varsa
			yenisi açılmaz, mevcut döndürülür.

	Returns:
		Insert edilmiş Draft Shipment dokümanı.
	"""
	# İdempotency: aynı key ile daha önce oluşturulmuş sevkiyat varsa onu döndür.
	if idempotency_key:
		# Composite lookup (key + order): idempotency_key kolonu global unique
		# KALIR (şema), ama arama order ile scope'lanır — başka tenant'ın/order'ın
		# key'i buradan hiç dönmez (IDOR kapama: yabancı sevkiyat sızdırılamaz).
		existing: str | None = frappe.db.get_value(
			"Shipment", {"idempotency_key": idempotency_key, "order": order}, "name"
		)
		if existing:
			return frappe.get_doc("Shipment", existing)

		# Aynı key farklı bir order için kullanılmışsa: insert'teki opak
		# duplicate-key hatası yerine anlamlı HTTP 409 (IdempotencyConflictError).
		if frappe.db.exists("Shipment", {"idempotency_key": idempotency_key}):
			frappe.throw(
				_("Idempotency anahtarı farklı bir sipariş için zaten kullanılmış."),
				exc=IdempotencyConflictError,
			)

	order_doc: Document = frappe.get_doc("Order", order)

	if items is None:
		items = []
		for order_item in order_doc.get("items") or []:
			remaining: int = get_remaining_qty(order_item.name)
			if remaining > 0:
				items.append(
					{
						"order_item": order_item.name,
						"listing": order_item.listing,
						"qty": remaining,
					}
				)

	if not items:
		frappe.throw(
			_("Sevk edilecek kalem yok — siparişin tüm kalemleri zaten sevkiyata bağlanmış."),
			exc=SplitInvariantError,
		)

	# Order.shipping_method serbest metin (Data) — yalnız geçerli bir
	# Shipping Method kaydına karşılık geliyorsa Link alanına kopyalanır.
	shipping_method: str | None = order_doc.get("shipping_method") or None
	if shipping_method and not frappe.db.exists("Shipping Method", shipping_method):
		shipping_method = None

	shipment: Document = frappe.get_doc(
		{
			"doctype": "Shipment",
			"order": order,
			"seller_profile": order_doc.seller,
			"buyer": order_doc.buyer,
			"shipping_method": shipping_method,
			"status": ShipmentStatus.DRAFT,
			"idempotency_key": idempotency_key,
			"items": items,
		}
	)
	shipment.insert()
	return shipment
