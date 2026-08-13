# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü doc_event handler fonksiyonları (Dalga B).

Bu fonksiyonlar ana hooks.py doc_events üzerinden Shipment DocType'ına
bağlanır. Durum geçiş kuralı transition_status motoru ile AYNI saf
fonksiyondan gelir (logistics.constants.is_transition_allowed — DRY).
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import cint

from tradehub_core.logistics.cache import invalidate_logistics_dashboard
from tradehub_core.logistics.constants import ShipmentStatus, is_transition_allowed
from tradehub_core.logistics.exceptions import ShipmentStateError, SplitInvariantError

# Fulfillment hesabında "aktif" sayılmayan sevkiyat durumları:
# iptal/iade edilen sevkiyatın miktarı sevk edilmiş kabul edilmez.
_INACTIVE_SHIPMENT_STATUSES: tuple[str, ...] = (
	ShipmentStatus.CANCELLED,
	ShipmentStatus.RETURNED,
)

# Shipment Address Snapshot'a Addresses'ten birebir kopyalanan alanlar.
_ADDRESS_COPY_FIELDS: tuple[str, ...] = (
	"contact_name",
	"company",
	"phone_prefix",
	"phone",
	"country",
	"state",
	"city",
	"street",
	"apartment",
	"postal_code",
	"tax_no",
	"tax_office",
)


def validate_state_transition(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat durum geçişini doğrular (validate hook).

	ALLOWED_TRANSITIONS matrisine göre geçersiz durum geçişlerini engeller —
	transition_status motoru ile aynı saf kural (is_transition_allowed)
	kullanılır; Desk/API üzerinden yapılan doğrudan status yazımları da
	böylece aynı matrise tabidir. Geçersiz geçişte ShipmentStateError.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	if doc.is_new():
		return

	before = doc.get_doc_before_save()
	if before is None or before.status == doc.status:
		return

	if not is_transition_allowed(before.status, doc.status):
		frappe.throw(
			_("Geçersiz sevkiyat durum geçişi: {0} → {1}").format(_(before.status), _(doc.status)),
			exc=ShipmentStateError,
		)


def snapshot_addresses(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat adres snapshot'ı alır (before_insert hook, F kuralları).

	Origin: satıcının Admin Seller Profile'a bağlı (Addresses.seller) pickup
	adresi. Destination: Order.shipping_address'in işaret ettiği Addresses
	kaydı. Kaynak adres yoksa throw EDİLMEZ, satır boş bırakılır — Faz 4'te
	adres zorunluluğu API katmanında uygulanır (Dalga C).

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	# İdempotent: satırlar zaten doluysa (ör. API katmanı doldurdu) dokunma.
	if doc.get("address_snapshots"):
		return

	origin = _get_seller_origin_address(doc.get("seller_profile"))
	if origin is not None:
		_append_address_snapshot(doc, "Origin", origin)

	destination = _get_order_shipping_address(doc.get("order"))
	if destination is not None:
		_append_address_snapshot(doc, "Destination", destination)


def snapshot_items(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat kalem snapshot'ı alır (before_insert hook).

	items satırlarında item_name/unit_price boşsa Order Item'dan, ürün adı
	orada da yoksa Listing'den doldurur. Batch fetch — N+1 yok.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	rows = [
		row
		for row in (doc.get("items") or [])
		if row.get("order_item") and (not row.get("item_name") or row.get("unit_price") is None)
	]
	if not rows:
		return

	# get_all: sistem akışı (before_insert hook) — kullanıcı Shipment create
	# yetkisini zaten kanıtladı; Order Item child tablosuna DocPerm aranmaz.
	order_item_names = list({row.order_item for row in rows})
	order_items = {
		oi.name: oi
		for oi in frappe.get_all(
			"Order Item",
			filters={"name": ["in", order_item_names]},
			fields=["name", "listing", "listing_title", "variation", "unit_price"],
		)
	}

	# Order Item.listing_title boş kalanlar için Listing.title fallback'i.
	missing_title_listings = list(
		{oi.listing for oi in order_items.values() if oi.listing and not oi.listing_title}
	)
	listing_titles: dict[str, str] = {}
	if missing_title_listings:
		listing_titles = {
			listing.name: listing.title
			for listing in frappe.get_all(
				"Listing",
				filters={"name": ["in", missing_title_listings]},
				fields=["name", "title"],
			)
		}

	for row in rows:
		order_item = order_items.get(row.order_item)
		if order_item is None:
			continue
		if not row.get("item_name"):
			row.item_name = order_item.listing_title or listing_titles.get(order_item.listing) or ""
		if row.get("unit_price") is None:
			row.unit_price = order_item.unit_price
		if not row.get("listing"):
			row.listing = order_item.listing
		if not row.get("variation"):
			row.variation = order_item.variation


def on_shipment_created(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat oluşturulduğunda tetiklenen handler (after_insert).

	Dashboard cache'ini düşürür ve bağlı Order'ın fulfillment durumunu
	yeniden hesaplar.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	invalidate_logistics_dashboard(doc)
	update_order_fulfillment(doc)


def on_shipment_status_change(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat güncellemelerinde tetiklenen handler (on_update).

	Status değiştiyse Shipment Event yazar. transition_status motoru kendi
	event'ini yazıp doc.flags.th_transition_event_written bayrağını set
	eder — bayrak buradaki ikinci üretimi engeller. event_hash timestamp
	içerdiğinden unique constraint çift kaydı YAKALAMAZ; koruma bilinçli
	olarak bu bayraktır. Fulfillment + cache her update'te tazelenir
	(kalem miktarı değişiklikleri de fulfillment'ı etkiler; her ikisi de
	idempotent).

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	before = doc.get_doc_before_save()
	status_changed: bool = before is not None and before.status != doc.status

	if status_changed and not doc.flags.get("th_transition_event_written"):
		# Desk/doğrudan save ile yapılan durum değişikliği — event burada üretilir.
		from tradehub_core.logistics.services.shipment_service import _create_transition_event

		_create_transition_event(
			doc.name,
			before.status,
			doc.status,
			source="Manual",
			seller_profile=doc.get("seller_profile"),
		)
		doc.flags.th_transition_event_written = True

	update_order_fulfillment(doc)
	invalidate_logistics_dashboard(doc)


def update_order_fulfillment(doc: Document, method: str | None = None) -> None:
	"""Order.fulfillment_status + shipment_count alanlarını günceller (LOG-056).

	Aktif (Cancelled/Returned olmayan) sevkiyatlardaki Shipment Item qty
	toplamı, Order Item quantity toplamıyla karşılaştırılır:
	0 → Unfulfilled, kısmi → Partially Fulfilled, tam/aşkın → Fulfilled.
	Yazım frappe.db.set_value ile yapılır (validate/notify tetiklenmez,
	update_modified=False) — Order.before_save yan etkileri (sayaç şişmesi)
	bilinçli olarak devre dışı bırakılır.

	Args:
		doc: Shipment dokümanı (order alanı okunur).
		method: Frappe hook method adı.
	"""
	order_name: str | None = doc.get("order")
	if not order_name:
		return

	# Mevcut değerler + cache invalidation girdileri tek okumada (status/buyer:
	# invalidate_tailored_user_cache Order doc'undan bu alanları bekler).
	current = frappe.db.get_value(
		"Order",
		order_name,
		["fulfillment_status", "shipment_count", "status", "buyer", "owner"],
		as_dict=True,
	)
	if current is None:
		return

	OrderItem = frappe.qb.DocType("Order Item")
	ordered_qty: int = cint(
		frappe.qb.from_(OrderItem)
		.select(Sum(OrderItem.quantity))
		.where(OrderItem.parent == order_name)
		.run()[0][0]
		or 0
	)

	ShipmentItem = frappe.qb.DocType("Shipment Item")
	Shipment = frappe.qb.DocType("Shipment")
	shipped_qty: int = cint(
		frappe.qb.from_(ShipmentItem)
		.join(Shipment)
		.on(ShipmentItem.parent == Shipment.name)
		.select(Sum(ShipmentItem.qty))
		.where(Shipment.order == order_name)
		.where(Shipment.status.notin(list(_INACTIVE_SHIPMENT_STATUSES)))
		.run()[0][0]
		or 0
	)

	if shipped_qty <= 0 or ordered_qty <= 0:
		fulfillment_status = "Unfulfilled"
	elif shipped_qty < ordered_qty:
		fulfillment_status = "Partially Fulfilled"
	else:
		fulfillment_status = "Fulfilled"

	# shipment_count: aktif sevkiyat sayısı (iptal/iade edilenler sayılmaz —
	# fulfillment_status ile aynı "aktif" tanımı).
	shipment_count: int = frappe.db.count(
		"Shipment",
		{"order": order_name, "status": ["not in", list(_INACTIVE_SHIPMENT_STATUSES)]},
	)

	# Değer değişmediyse yazma + cache düşürme gereksiz (idempotent no-op).
	if (
		current.fulfillment_status == fulfillment_status
		and cint(current.shipment_count) == shipment_count
	):
		return

	frappe.db.set_value(
		"Order",
		order_name,
		{"fulfillment_status": fulfillment_status, "shipment_count": shipment_count},
		update_modified=False,
	)

	# F8b: frappe.db.set_value Order on_update doc_event'lerini TETİKLEMEZ —
	# ana hooks.py'de Order on_update'e kayıtlı tailored cache invalidation'ı
	# explicit çağrılır (best-effort; fonksiyon hatayı kendi içinde loglar).
	from tradehub_core.api.tailored import invalidate_tailored_user_cache

	invalidate_tailored_user_cache(current, method="on_update")


def validate_split_invariants(doc: Document, method: str | None = None) -> None:
	"""Sevkiyat bölme değişmezlerini kontrol eder (validate hook).

	INV-1: order_item başına bu doc'taki qty + diğer AKTİF sevkiyatlardaki
	qty toplamı, Order Item quantity'sini aşamaz.
	INV-5: satır qty en az 1 olmalı (0 ve negatif reddedilir — F8a).
	Her order_item bu sevkiyatın Order'ına ait olmalı (F3).
	İhlalde SplitInvariantError fırlatılır.

	Args:
		doc: Shipment dokümanı.
		method: Frappe hook method adı.
	"""
	from tradehub_core.logistics.services.split_engine import get_remaining_qty

	# F3: order_item satırları doc.order'a ait mi? (cross-tenant/yanlış-order koruması)
	_validate_items_belong_to_order(doc)

	# Bu doc'taki order_item başına toplam qty (aynı kaleme birden çok satır olabilir).
	own_qty: dict[str, int] = defaultdict(int)
	for row in doc.get("items") or []:
		qty: int = cint(row.get("qty"))
		if qty < 1:
			frappe.throw(
				_("Sevkiyat kalem miktarı en az 1 olmalıdır (satır {0}).").format(row.idx),
				exc=SplitInvariantError,
			)
		if row.get("order_item"):
			own_qty[row.order_item] += qty

	# İptal/iade edilen sevkiyatın miktarı artık sevk edilmiş sayılmaz —
	# INV-1 kontrolü aktif olmayan doc için anlamsızdır (iptal geçişini kilitlemesin).
	if doc.get("status") in _INACTIVE_SHIPMENT_STATUSES:
		return

	# order_item başına tek sorgu — bir sevkiyatta kalem sayısı küçüktür (tipik <10),
	# batch'lemenin getirisi sorgu karmaşıklığına değmez.
	exclude: str | None = None if doc.is_new() else doc.name
	for order_item_name, qty in own_qty.items():
		remaining: int = get_remaining_qty(order_item_name, exclude_shipment=exclude)
		if qty > remaining:
			frappe.throw(
				_(
					"Sipariş kalemi {0} için sevk miktarı aşımı: istenen {1}, kalan {2} (INV-1)."
				).format(order_item_name, qty, remaining),
				exc=SplitInvariantError,
			)


def _validate_items_belong_to_order(doc: Document) -> None:
	"""F3: her items satırının Order Item'ı doc.order'a ait olmalı.

	parent == doc.order + parenttype == "Order" birlikte doğrulanır — başka
	tenant'ın (veya aynı tenant'ın başka siparişinin) Order Item'ı ile
	sevkiyat açılması hem cross-tenant miktar-tüketme/oracle vektörünü hem
	yanlış-order kalemi hatasını kapatır. Tek batch sorgu — N+1 yok.
	"""
	order_item_names: list[str] = list(
		{row.order_item for row in doc.get("items") or [] if row.get("order_item")}
	)
	if not order_item_names:
		return

	# get_all: validate hook sistem akışı — Order Item child tablosuna DocPerm aranmaz.
	valid_names: set[str] = {
		oi.name
		for oi in frappe.get_all(
			"Order Item",
			filters={
				"name": ["in", order_item_names],
				"parent": doc.get("order"),
				"parenttype": "Order",
			},
			fields=["name"],
		)
	}

	for row in doc.get("items") or []:
		if row.get("order_item") and row.order_item not in valid_names:
			frappe.throw(
				_("Sipariş kalemi {0} bu sevkiyatın siparişine ait değil (satır {1}).").format(
					row.order_item, row.idx
				),
				exc=SplitInvariantError,
			)


# ---------------------------------------------------------------------------
# Snapshot yardımcıları
# ---------------------------------------------------------------------------


def _get_seller_origin_address(seller_profile: str | None) -> Document | None:
	"""Satıcının gönderim (Origin) adresini döndürür.

	Tercih sırası: purpose=Pickup olan adres (is_default önce), yoksa
	satıcının herhangi bir adresi. Hiç adres yoksa None.
	"""
	if not seller_profile:
		return None

	# get_all: sistem akışı (snapshot hook) — satıcının kendi adresi,
	# kullanıcı permission katmanı Shipment create'te zaten uygulandı.
	rows = frappe.get_all(
		"Addresses",
		filters={"seller": seller_profile},
		fields=["name", "purpose", "is_default"],
		order_by="is_default desc, modified desc",
		limit=20,
	)
	if not rows:
		return None

	pickup_rows = [row for row in rows if row.purpose == "Pickup"]
	chosen = (pickup_rows or rows)[0]
	return frappe.get_doc("Addresses", chosen.name)


def _get_order_shipping_address(order_name: str | None) -> Document | None:
	"""Order.shipping_address'in işaret ettiği Addresses kaydını döndürür.

	Order.shipping_address Text alandır ve checkout akışında Addresses doc
	adını taşır (api/cart.py); geçerli bir kayda çözülemezse None.
	"""
	if not order_name:
		return None

	address_name: str | None = frappe.db.get_value("Order", order_name, "shipping_address")
	if not address_name or not frappe.db.exists("Addresses", address_name):
		return None
	return frappe.get_doc("Addresses", address_name)


def _append_address_snapshot(doc: Document, snapshot_type: str, address: Document) -> None:
	"""Addresses kaydını Shipment Address Snapshot satırı olarak ekler."""
	row: dict = {"snapshot_type": snapshot_type, "source_address": address.name}
	for field in _ADDRESS_COPY_FIELDS:
		row[field] = address.get(field)
	doc.append("address_snapshots", row)
