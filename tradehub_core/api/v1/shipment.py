# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Sevkiyat CRUD + durum gecis API'leri (v1, authenticated) — Dalga C (LOG-053).

Standart yanit formati (docs/LOGISTICS-ARCHITECTURE.md P bolumu):
  {"ok": True, "data": ..., "meta": {"api_version": "v1"}}
Hatalar @logistics_endpoint sozlesme zarfina girer (E2E denetimi 2026-09,
bulgu A): onceki surum ham frappe.throw yaniti donduruyordu ve panel
error.code uzerinden dallanamadigi icin INTERNAL_ERROR gosteriyordu.
Zarf sekli (logistics/api_utils.py — FE karsiligi logisticsEnvelope.js):
  {"ok": False, "error": {"code": "NOT_FOUND", "message": "..."}} + HTTP 404 vb.

Yetki katmanlari:
  - @frappe.whitelist() (guest YOK) + _require_authenticated_user guard'i
  - Order uzerinde order_has_permission (create akisi — Order DocPerm modeli
    rol-seviyesi read vermez, sahiplik/tenant kontrolu tek kaynaktan cagrilir)
  - Shipment uzerinde check_permission + logistics/permissions.py hook zinciri
  - Liste sorgulari frappe.get_list ile (shipment_query_conditions devrede)
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate

from tradehub_core.logistics.api_utils import logistics_endpoint
from tradehub_core.logistics.constants import API_VERSION, TERMINAL_STATUSES, ShipmentStatus

# Sozlesme daralmasi (BILINCLI — QA bulgusu 2026-09-07):
# docs/logistics-api.schema.json provisional.shipment.list_fields 17 alan tanimlar;
# liste yaniti bunlarin FE'nin gercekten tukettigi + zararsiz alt kumesini tasir.
# Sizinti yuzeyi dar tutulur (g0-security.spec.ts ALLOWED_LIST_FIELDS strict set):
#   - MALIYET alanlari (shipping_cost, carrier_cost, ... total_cost) ASLA — G0 siniri.
#   - seller_profile / buyer / shipment_type / channel / carrier_service: FE liste
#     ekrani tuketmiyor, bilincli olarak disarida (ihtiyac dogarsa e2e allowlist
#     ile BIRLIKTE eklenir).
#   - actual_delivery: yalniz is_delayed hesabi icin cekilir, yanittan dusurulur
#     (_LIST_INTERNAL_FIELDS).
# Yanita ayrica iki HESAPLANAN alan eklenir (_annotate_list_rows):
#   - is_delayed: DocType'ta saklanan kolon YOK (TUR-112 SLA monitor henuz stub);
#     status + estimated_delivery + actual_delivery'den turetilir.
#   - package_count: kolon yok; Shipment Package child sayisi tek grouped sorguyla.
_LIST_FIELDS: tuple[str, ...] = (
	"name",
	"order",
	"status",
	"carrier",
	"tracking_number",
	"estimated_delivery",
	"chargeable_weight",
	"creation",
	"ship_date",
	"modified",
)

# Sorguya dahil ama yanittan dusurulen alanlar (yalniz turev hesap girdisi).
_LIST_INTERNAL_FIELDS: tuple[str, ...] = ("actual_delivery",)

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


def _compute_is_delayed(row: Mapping, today: datetime.date) -> int:
	"""Gecikme turevi (TUR-112 sozlesme alani) — saklanan kolon yokken hesaplanir.

	Kural (contract.py SAMPLE_SHIPMENTS fixture'lariyla hizali):
	  - estimated_delivery yoksa yargi verilemez → 0 (emin degilsen guvenli taraf).
	  - Teslim edildiyse (actual_delivery dolu): gecikme = teslim gunu > ETA.
	  - Teslim edilmediyse: kapali sevkiyat (TERMINAL_STATUSES: Delivered/
	    Returned/Cancelled) rozet almaz; acik sevkiyatta bugun > ETA ise 1.
	SLA monitor job'i (TUR-112) saklanan alani getirdiginde tek otorite o olur;
	bu turev o gun kaldirilir.
	"""
	estimated = row.get("estimated_delivery")
	if not estimated:
		return 0
	estimated_date: datetime.date = getdate(estimated)
	actual = row.get("actual_delivery")
	if actual:
		return cint(getdate(actual) > estimated_date)
	if row.get("status") in TERMINAL_STATUSES:
		return 0
	return cint(today > estimated_date)


def _annotate_list_rows(rows: list[dict]) -> None:
	"""Liste satirlarina hesaplanan alanlari ekler, internal alanlari dusurur.

	Satir basina EK SORGU YOK (N+1 yasak): package_count sayfanin tum adlari
	icin TEK grouped sorguyla cekilir; is_delayed zaten cekilmis kolonlardan
	Python'da turetilir.
	"""
	if not rows:
		return

	names: list[str] = [row["name"] for row in rows]
	# get_all gerekcesi: Shipment Package child tablodur, kendi DocPerm'i yok —
	# parent satirlar yukaridaki get_list'te shipment_query_conditions ile zaten
	# filtrelendi; sorgu YALNIZ o sayfanin adlariyla sinirli (sizinti yok).
	package_counts: dict[str, int] = {
		agg["parent"]: cint(agg["qty"])
		for agg in frappe.get_all(
			"Shipment Package",
			filters={"parenttype": "Shipment", "parent": ["in", names]},
			fields=["parent", "count(name) as qty"],
			group_by="parent",
		)
	}

	today: datetime.date = getdate(nowdate())
	for row in rows:
		row["package_count"] = package_counts.get(row["name"], 0)
		row["is_delayed"] = _compute_is_delayed(row, today)
		for field in _LIST_INTERNAL_FIELDS:
			row.pop(field, None)


def _get_shipment_or_404(name: str) -> frappe.model.document.Document:
	"""Sevkiyati getirir; kayit yoksa VEYA okuma yetkisi yoksa DoesNotExistError.

	frappe.get_doc'un ham (Ingilizce) mesaji yerine Turkce mesaj uretilir;
	@logistics_endpoint DoesNotExistError'i NOT_FOUND zarfina esler (bulgu A).

	Anti-enumeration (denetim 2026-09-04, madde 3): kayit VAR ama okuma yetkisi
	YOKSA 403 donmek kaydin varligini dogrulardi — yetkisiz kullanici kayit-yok
	ile AYNI NOT_FOUND(404) yanitini alir (ayni mesajla). PERMISSION_DENIED
	yalniz "kayda okumasi var ama ISLEME yetkisi yok" durumlarina kalir
	(o durumda varlik bilgisi zaten mesru olarak biliniyor).
	"""
	not_found_msg: str = _("Sevkiyat bulunamadı: {0}").format(name)
	if not frappe.db.exists("Shipment", name):
		frappe.throw(not_found_msg, frappe.DoesNotExistError)
	doc = frappe.get_doc("Shipment", name)
	try:
		doc.check_permission("read")
	except frappe.PermissionError:
		# DENY audit satiri check_permission → shipment_has_permission →
		# _log_deny zincirinde zaten yazildi; istemciye varlik sizdirilmez.
		frappe.throw(not_found_msg, frappe.DoesNotExistError)
	return doc


@frappe.whitelist()
@logistics_endpoint()
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

	# P1-6a: bos string idempotency key None'a normalize edilir — '' unique
	# kolona yazilmasin (split_engine de ayrica normalize eder; cift katman).
	idempotency_key = idempotency_key or None

	# Olmayan Order ham DoesNotExistError yerine i18n mesajla NOT_FOUND
	# zarfina esleniyor (get_doc'un Ingilizce mesaji panele sizmasin).
	# Anti-enumeration (denetim 2026-09-04, madde 3): asagida yetki reddi de
	# AYNI mesajla NOT_FOUND doner — 403, Order adinin varligini dogrulardi.
	order_not_found_msg: str = _("Sipariş bulunamadı: {0}").format(order)
	if not frappe.db.exists("Order", order):
		frappe.throw(order_not_found_msg, frappe.DoesNotExistError)

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
		# Anti-enumeration: kayit-yok ile yetki-yok ayirt edilemez olmali —
		# PermissionError(403) yerine ayni mesajla NOT_FOUND(404).
		frappe.throw(order_not_found_msg, frappe.DoesNotExistError)

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
@logistics_endpoint()
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
		fields=list(_LIST_FIELDS + _LIST_INTERNAL_FIELDS),
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length,
	)

	# is_delayed + package_count turevleri (QA 2026-09-07: FE "Gecikmis" rozeti
	# row.is_delayed bekliyor); internal alanlar yanittan dusurulur.
	_annotate_list_rows(shipments)

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
@logistics_endpoint()
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

	# Okuma yetkisi _get_shipment_or_404 icinde kontrol edilir — yetkisiz
	# erisim varlik sizdirmayan NOT_FOUND(404) alir (madde 3).
	doc = _get_shipment_or_404(name)

	from tradehub_core.logistics.permissions import (
		mask_shipment_cost_dict,
		mask_shipment_cost_fields,
	)

	# API yaniti onload'dan gecmez — maske doc uzerinde burada uygulanir.
	mask_shipment_cost_fields(doc)

	data: dict = doc.as_dict()

	# `as_dict()` Currency/Float alanlarda None'i 0'a ceviriyor; yukaridaki
	# doc maskesi bu yuzden yanitta gorunmez oluyordu (maskelenen maliyet
	# `null` degil `0` cikiyordu — "gizlendi" ile "ucretsiz" ayirt edilemez).
	# Maske sozlukte TEKRAR uygulanir; doc'taki maske kaydetme yolunu korudugu
	# icin yerinde kalir.
	mask_shipment_cost_dict(data, user)

	# F8c: internal_note + idempotency_key operasyonel alanlardir — platform
	# lojistik rolleri ve sevkiyatin seller tenant'i disindaki kullaniciya
	# (buyer okuma yolu) yanittan cikarilir.
	if not _can_view_operational_fields(user, doc):
		data.pop("internal_note", None)
		data.pop("idempotency_key", None)

	# Liste ile ayni turev — detay rozeti de row.is_delayed'den cizilir
	# (ShipmentDetailScreen.vue); saklanan kolon gelince (TUR-112) kalkar.
	data["is_delayed"] = _compute_is_delayed(data, getdate(nowdate()))

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


def _seller_can_transition(doc: frappe.model.document.Document, user: str, to_status: str) -> bool:
	"""Satıcı bu geçişi yapabilir mi? (G0 matrisi C2 — dar yol.)

	Üç koşul birden: Seller Logistics rolü + sevkiyat kullanıcının kendi
	tenant'ında + geçiş SELLER_ALLOWED_TRANSITIONS alt kümesinde.
	"""
	from tradehub_core.logistics.constants import is_seller_transition_allowed
	from tradehub_core.logistics.permissions import _get_user_seller_profile

	if "Seller Logistics" not in frappe.get_roles(user):
		return False

	seller_profile: str | None = _get_user_seller_profile(user)
	if not seller_profile or seller_profile != doc.get("seller_profile"):
		return False

	return is_seller_transition_allowed(doc.status, to_status)


@frappe.whitelist()
@logistics_endpoint()
def update_shipment_status(name: str, status: str, note: str | None = None) -> dict:
	"""Sevkiyat durumunu gecis motoru uzerinden gunceller.

	ALLOWED_TRANSITIONS disindaki gecisler ShipmentStateError ile reddedilir;
	ayni duruma gecis sessiz no-op'tur (event uretilmez).

	G0 matrisi (C2): write DocPerm'i olmayan satici YALNIZ kendi tenant'indaki
	sevkiyati SELLER_ALLOWED_TRANSITIONS alt kumesiyle gecirebilir
	(_seller_can_transition dar yolu); diger her sey PermissionError.

	Args:
		name: Shipment doc adi.
		status: Hedef durum (ShipmentStatus degerlerinden biri).
		note: Event'e yazilacak opsiyonel not.

	Returns:
		{"ok": True, "data": {"name", "status", "previous_status"}, "meta": {...}}.
	"""
	user: str = _require_authenticated_user()

	doc = _get_shipment_or_404(name)
	try:
		doc.check_permission("write")
	except frappe.PermissionError:
		# G0 dar yolu: satıcı DocPerm write taşımaz ama KENDİ sevkiyatını
		# "kargoya verildi" işaretleyebilir (SELLER_ALLOWED_TRANSITIONS,
		# FBM confirm-shipment deseni). Koşullar tutmuyorsa orijinal
		# PermissionError aynen yükselir.
		if not _seller_can_transition(doc, user, status):
			raise
		# ignore_permissions gerekçesi: dar yol yukarıda üç koşulla (rol +
		# tenant eşleşmesi + geçiş alt kümesi) doğrulandı; transition_status
		# içindeki doc.save() aksi hâlde aynı DocPerm duvarına çarpardı.
		doc.flags.ignore_permissions = True
	previous_status: str = doc.status

	from tradehub_core.logistics.services.shipment_service import transition_status

	doc = transition_status(doc, status, source="Manual", note=note)

	return {
		"ok": True,
		"data": {"name": doc.name, "status": doc.status, "previous_status": previous_status},
		"meta": _meta(),
	}


@frappe.whitelist()
@logistics_endpoint()
def cancel_shipment(name: str, reason: str | None = None) -> dict:
	"""Sevkiyati iptal eder (yalniz cancel yetkili roller — J.2 matrisi).

	Frappe'nin cancel ptype'i submittable-olmayan DocType'ta DocPerm
	katmanindan gecmeyebilir; bu durumda kural kaynagi olan
	logistics.permissions.shipment_has_permission (cancel → yalniz
	Logistics Manager) fallback olarak dogrudan uygulanir.

	P1-6b: sevkiyat ZATEN Cancelled ise servis no-op doner — reason
	internal_note'a YAZILMAZ, event uretilmez ve yanit meta'sinda
	"already_cancelled": true isaretlenir.

	Args:
		name: Shipment doc adi.
		reason: Iptal nedeni (event note + internal_note). Zaten iptal
			edilmis sevkiyatta yok sayilir.

	Returns:
		{"ok": True, "data": {"name", "status"}, "meta": {...}}.
	"""
	user: str = _require_authenticated_user()

	doc = _get_shipment_or_404(name)
	try:
		doc.check_permission("cancel")
	except frappe.PermissionError:
		from tradehub_core.logistics.permissions import shipment_has_permission

		# Fallback: cancel ptype non-submittable Shipment'ta Frappe DocPerm
		# katmanindan gecmezse kural matrisi (permissions.py) son soz sahibidir.
		if not shipment_has_permission(doc, "cancel", user):
			raise

	from tradehub_core.logistics.services.shipment_service import cancel_shipment as cancel_shipment_service

	# P1-6b: transition oncesi status Cancelled ise servis no-op donecek.
	already_cancelled: bool = doc.status == ShipmentStatus.CANCELLED

	doc = cancel_shipment_service(doc, reason or "")

	return {
		"ok": True,
		"data": {"name": doc.name, "status": doc.status},
		"meta": _meta(already_cancelled=True if already_cancelled else None),
	}
