# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Sevkiyat CRUD + durum gecis API'leri (v1, authenticated) — Dalga C (LOG-053).

Standart yanit formati (docs/LOGISTICS-ARCHITECTURE.md P bolumu):
  {"ok": True, "data": ..., "meta": {"api_version": "v1"}}
Hatalar frappe.throw ile firlatilir — framework HTTP yanitini
exception sinifinin http_status_code'una gore sarar.

Yetki katmanlari:
  - @frappe.whitelist() (guest YOK) + _require_authenticated_user guard'i
  - Order uzerinde order_has_permission (create akisi — Order DocPerm modeli
    rol-seviyesi read vermez, sahiplik/tenant kontrolu tek kaynaktan cagrilir)
  - Shipment uzerinde check_permission + logistics/permissions.py hook zinciri
  - Liste sorgulari frappe.get_list ile (shipment_query_conditions devrede)
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from tradehub_core.logistics.constants import API_VERSION, ShipmentStatus

_LIST_FIELDS: tuple[str, ...] = (
	"name",
	"order",
	"status",
	"carrier",
	"tracking_number",
	"estimated_delivery",
	"chargeable_weight",
	"creation",
)

_MAX_PAGE_LENGTH: int = 100

# F8c: internal_note + idempotency_key operasyonel alanlarını detay yanıtında
# görebilen platform rolleri (buyer'a sızdırılmaz; seller tenant'ı ayrıca muaf).
_OPERATIONAL_FIELD_ROLES: frozenset[str] = frozenset({
	"System Manager",
	"Logistics Manager",
	"Logistics Operator",
})


def _require_authenticated_user() -> str:
	"""Oturum kullanicisini dogrular ve dondurur (guest reddedilir).

	@frappe.whitelist() zaten guest'i engeller; bu guard defense-in-depth
	katmanidir (api/order.py _require_buyer emsali).
	"""
	user: str = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Bu islem icin giris yapmalisiniz."), frappe.AuthenticationError)
	return user


def _meta(**extra: object) -> dict:
	"""Standart meta blogu — api_version + opsiyonel ek alanlar."""
	meta: dict = {"api_version": API_VERSION}
	meta.update({k: v for k, v in extra.items() if v is not None})
	return meta


@frappe.whitelist()
def create_shipment(
	order: str,
	items: str | None = None,
	idempotency_key: str | None = None,
) -> dict:
	"""Order'dan Draft durumunda Shipment olusturur (split motoru uzerinden).

	items None ise siparisin tum kalemleri kalan miktarlariyla taslaga alinir.
	Ayni idempotency_key ile tekrar cagri yeni kayit acmaz, mevcut sevkiyati
	dondurur (split_engine idempotency sozlesmesi).

	Args:
		order: Order doc adi.
		items: JSON string — [{"order_item": ..., "listing": ..., "qty": ...}].
		idempotency_key: Opsiyonel tekrar-cagri anahtari.

	Returns:
		{"ok": True, "data": {sevkiyat ozeti}, "meta": {...}}.
	"""
	user: str = _require_authenticated_user()

	# Yetki: kullanici siparisi okuyabiliyor olmali. Order'in DocPerm modeli
	# (System Manager full + "All" if_owner=1) hicbir role doctype-seviyesi
	# read vermez — check_permission("read") sahibi olmayan HERKESI dusurur
	# (has_permission hook'lari yalniz kisitlar, grant edemez). Bu app'in
	# idiyomu Order erisimini tenant/sahiplik kontrolu ile vermek
	# (api/order.py get_seller_orders emsali); seller/buyer/org + platform +
	# ABAC mantiginin tek kaynagi olan order_has_permission hook fonksiyonu
	# bu yuzden dogrudan cagrilir. Olusan Shipment icin insert() sirasinda
	# create/write zinciri (DocPerm + shipment_has_permission) ayrica calisir.
	order_doc = frappe.get_doc("Order", order)

	from tradehub_core.permissions import order_has_permission

	if not order_has_permission(order_doc, "read", user):
		frappe.throw(_("Bu siparişe erişim yetkiniz yok."), frappe.PermissionError)

	parsed_items: list[dict] | None = frappe.parse_json(items) if items else None
	if parsed_items is not None and not isinstance(parsed_items, list):
		frappe.throw(
			_("items parametresi JSON liste olmalidir."),
			exc=frappe.ValidationError,
		)

	from tradehub_core.logistics.services.split_engine import create_shipment_draft_from_order

	shipment = create_shipment_draft_from_order(
		order,
		items=parsed_items,
		idempotency_key=idempotency_key,
	)

	return {
		"ok": True,
		"data": {
			"name": shipment.name,
			"order": shipment.order,
			"status": shipment.status,
			"seller_profile": shipment.get("seller_profile"),
			"items": [
				{"order_item": row.order_item, "listing": row.get("listing"), "qty": row.qty}
				for row in (shipment.get("items") or [])
			],
		},
		"meta": _meta(idempotency_key=idempotency_key),
	}


@frappe.whitelist()
def list_shipments(
	status: str | None = None,
	order: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 20,
) -> dict:
	"""Sevkiyatlari listeler (tenant izolasyonlu).

	frappe.get_list kullanilir — shipment_query_conditions otomatik uygulanir:
	seller kendi magazasinin, buyer kendi siparislerinin sevkiyatlarini gorur.

	Args:
		status: Opsiyonel durum filtresi (ShipmentStatus degerlerinden biri).
		order: Opsiyonel Order adi filtresi.
		limit_start: Sayfalama baslangici.
		limit_page_length: Sayfa boyutu (max 100).

	Returns:
		{"ok": True, "data": {"shipments": [...], "total": N, ...}, "meta": {...}}.
	"""
	_require_authenticated_user()

	if status and status not in ShipmentStatus.ALL:
		frappe.throw(_("Gecersiz sevkiyat durumu: {0}").format(status), exc=frappe.ValidationError)

	start: int = max(0, cint(limit_start))
	page_length: int = min(max(1, cint(limit_page_length) or 20), _MAX_PAGE_LENGTH)

	filters: dict = {}
	if status:
		filters["status"] = status
	if order:
		filters["order"] = order

	shipments = frappe.get_list(
		"Shipment",
		filters=filters,
		fields=list(_LIST_FIELDS),
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length,
	)

	# Toplam sayi — ayni filtre + ayni permission query conditions ile aggregate.
	# frappe.db.count permission katmanini BYPASS ederdi; get_list kullanilir.
	count_rows = frappe.get_list("Shipment", filters=filters, fields=["count(name) as total"])
	total: int = cint(count_rows[0].total) if count_rows else 0

	return {
		"ok": True,
		"data": {
			"shipments": shipments,
			"total": total,
			"limit_start": start,
			"limit_page_length": page_length,
		},
		"meta": _meta(),
	}


@frappe.whitelist()
def get_shipment_detail(name: str) -> dict:
	"""Sevkiyat detayini child tablolar dahil dondurur.

	Buyer/seller izolasyonu doc.check_permission("read") uzerinden
	(shipment_has_permission hook'u) uygulanir. Maliyet alanlari
	view.logistics_cost capability'si olmayan kullaniciya maskelenir —
	onload disi yol oldugu icin maske burada explicit cagrilir.

	Args:
		name: Shipment doc adi.

	Returns:
		{"ok": True, "data": {sevkiyat as_dict}, "meta": {...}}.
	"""
	user: str = _require_authenticated_user()

	doc = frappe.get_doc("Shipment", name)
	doc.check_permission("read")

	from tradehub_core.logistics.permissions import mask_shipment_cost_fields

	# API yaniti onload'dan gecmez — maske doc uzerinde burada uygulanir.
	mask_shipment_cost_fields(doc)

	data: dict = doc.as_dict()

	# F8c: internal_note + idempotency_key operasyonel alanlardir — platform
	# lojistik rolleri ve sevkiyatin seller tenant'i disindaki kullaniciya
	# (buyer okuma yolu) yanittan cikarilir.
	if not _can_view_operational_fields(user, doc):
		data.pop("internal_note", None)
		data.pop("idempotency_key", None)

	return {"ok": True, "data": data, "meta": _meta()}


def _can_view_operational_fields(user: str, doc: frappe.model.document.Document) -> bool:
	"""Kullanici operasyonel alanlari (internal_note, idempotency_key) gorebilir mi?

	Platform lojistik rolleri (System Manager / Logistics Manager /
	Logistics Operator) veya sevkiyatin seller tenant'i → True; buyer → False.
	"""
	if user == "Administrator":
		return True

	if set(frappe.get_roles(user)) & _OPERATIONAL_FIELD_ROLES:
		return True

	from tradehub_core.logistics.permissions import _get_user_seller_profile

	seller_profile: str | None = _get_user_seller_profile(user)
	return bool(seller_profile and seller_profile == doc.get("seller_profile"))


@frappe.whitelist()
def update_shipment_status(name: str, status: str, note: str | None = None) -> dict:
	"""Sevkiyat durumunu gecis motoru uzerinden gunceller.

	ALLOWED_TRANSITIONS disindaki gecisler ShipmentStateError ile reddedilir;
	ayni duruma gecis sessiz no-op'tur (event uretilmez).

	Args:
		name: Shipment doc adi.
		status: Hedef durum (ShipmentStatus degerlerinden biri).
		note: Event'e yazilacak opsiyonel not.

	Returns:
		{"ok": True, "data": {"name", "status", "previous_status"}, "meta": {...}}.
	"""
	_require_authenticated_user()

	doc = frappe.get_doc("Shipment", name)
	doc.check_permission("write")
	previous_status: str = doc.status

	from tradehub_core.logistics.services.shipment_service import transition_status

	doc = transition_status(doc, status, source="Manual", note=note)

	return {
		"ok": True,
		"data": {"name": doc.name, "status": doc.status, "previous_status": previous_status},
		"meta": _meta(),
	}


@frappe.whitelist()
def cancel_shipment(name: str, reason: str | None = None) -> dict:
	"""Sevkiyati iptal eder (yalniz cancel yetkili roller — J.2 matrisi).

	Frappe'nin cancel ptype'i submittable-olmayan DocType'ta DocPerm
	katmanindan gecmeyebilir; bu durumda kural kaynagi olan
	logistics.permissions.shipment_has_permission (cancel → yalniz
	Logistics Manager) fallback olarak dogrudan uygulanir.

	Args:
		name: Shipment doc adi.
		reason: Iptal nedeni (event note + internal_note).

	Returns:
		{"ok": True, "data": {"name", "status"}, "meta": {...}}.
	"""
	user: str = _require_authenticated_user()

	doc = frappe.get_doc("Shipment", name)
	try:
		doc.check_permission("cancel")
	except frappe.PermissionError:
		from tradehub_core.logistics.permissions import shipment_has_permission

		# Fallback: cancel ptype non-submittable Shipment'ta Frappe DocPerm
		# katmanindan gecmezse kural matrisi (permissions.py) son soz sahibidir.
		if not shipment_has_permission(doc, "cancel", user):
			raise

	from tradehub_core.logistics.services.shipment_service import cancel_shipment as cancel_shipment_service

	doc = cancel_shipment_service(doc, reason or "")

	return {
		"ok": True,
		"data": {"name": doc.name, "status": doc.status},
		"meta": _meta(),
	}
