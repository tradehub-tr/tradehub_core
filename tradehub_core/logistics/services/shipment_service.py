# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Shipment durum geçiş motoru (Dalga B — LOG-049/050/051).

transition_status tek geçiş noktasıdır: ALLOWED_TRANSITIONS doğrulaması,
status yazımı, tarih alanı damgaları ve Shipment Event üretimi aynı
request-level transaction içinde gerçekleşir. Desk/API üzerinden doğrudan
status değişiklikleri logistics/hooks.py validate_state_transition +
on_shipment_status_change ile aynı kural setine bağlanır
(saf kural: logistics.constants.is_transition_allowed).
"""

from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.logistics.constants import ShipmentStatus, is_transition_allowed
from tradehub_core.logistics.exceptions import ShipmentStateError


def transition_status(
	shipment: str | Document,
	new_status: str,
	*,
	source: str = "System",
	note: str | None = None,
) -> Document:
	"""Sevkiyatı yeni duruma geçirir (LOG-049).

	Davranış:
	  - Mevcut → yeni geçiş ALLOWED_TRANSITIONS'a karşı doğrulanır;
	    geçersizse ShipmentStateError fırlatılır.
	  - AYNI duruma geçiş sessiz no-op'tur (idempotency): doc değiştirilmeden
	    döndürülür, event üretilmez.
	  - Terminal durumdan çıkış matriste boş set olduğu için zaten engellidir.
	  - Başarılı geçişte: status + tarih damgaları güncellenir ve Shipment
	    Event yazılır. Frappe zaten request-level transaction kullanır —
	    status yazımı ve event insert'i aynı transaction'da commit/rollback
	    olur, ayrıca savepoint gerekmez.

	Args:
		shipment: Shipment adı veya Document nesnesi.
		new_status: Hedef durum (ShipmentStatus değerlerinden biri).
		source: Event kaynağı (System/Webhook/Poll/Manual).
		note: Event'e yazılacak opsiyonel not.

	Returns:
		Güncellenmiş (veya no-op'ta değiştirilmemiş) Shipment dokümanı.
	"""
	doc: Document = shipment if isinstance(shipment, Document) else frappe.get_doc("Shipment", shipment)
	from_status: str = doc.status

	# İdempotency: aynı duruma geçiş = sessiz no-op, event üretme.
	if from_status == new_status:
		return doc

	if not is_transition_allowed(from_status, new_status):
		frappe.throw(
			_("Geçersiz sevkiyat durum geçişi: {0} → {1}").format(_(from_status), _(new_status)),
			exc=ShipmentStateError,
		)

	doc.status = new_status
	_stamp_transition_dates(doc, new_status)

	# on_update hook'u (on_shipment_status_change) bu bayrağı görüp ikinci bir
	# event üretmez — event'i aşağıda source/note bilgisiyle motor yazar.
	doc.flags.th_transition_event_written = True
	doc.save()

	_create_transition_event(
		doc.name,
		from_status,
		new_status,
		source=source,
		note=note,
		seller_profile=doc.get("seller_profile"),
	)
	return doc


def cancel_shipment(shipment: str | Document, reason: str) -> Document:
	"""Sevkiyatı iptal eder (LOG-047).

	Hangi durumlardan iptale izin verildiği yalnızca ALLOWED_TRANSITIONS
	matrisinden gelir — burada ek kural yoktur. reason internal_note'a
	eklenir ve Order fulfillment yeniden hesaplanır.

	P1-6b: sevkiyat ZATEN Cancelled ise çağrı no-op'tur — reason
	internal_note'a YAZILMAZ (ilk iptalin nedeni ezilmesin/şişmesin) ve
	event üretilmez; doc değiştirilmeden döndürülür.

	Args:
		shipment: Shipment adı veya Document nesnesi.
		reason: İptal nedeni (event note + internal_note).

	Returns:
		İptal edilmiş Shipment dokümanı.
	"""
	doc: Document = shipment if isinstance(shipment, Document) else frappe.get_doc("Shipment", shipment)

	# P1-6b: zaten iptal — sessiz no-op, reason yazılmaz.
	if doc.status == ShipmentStatus.CANCELLED:
		return doc

	# internal_note geçişten ÖNCE doc'a yazılır: transition_status'un save'i
	# ile aynı kayıtta kalıcılaşır; geçersiz geçişte throw ile birlikte düşer.
	if reason:
		stamp: str = _("İptal nedeni: {0}").format(reason)
		doc.internal_note = f"{doc.internal_note}\n{stamp}" if doc.get("internal_note") else stamp

	doc = transition_status(doc, ShipmentStatus.CANCELLED, source="Manual", note=reason)

	# Order fulfillment yeniden hesap — on_update hook'u da tetikler ama
	# çağrı idempotent (db_set aynı değeri yazar); explicit tetikleme
	# hook kablolamasından bağımsız olarak sözleşmeyi garanti eder.
	from tradehub_core.logistics.hooks import update_order_fulfillment

	update_order_fulfillment(doc)
	return doc


def _stamp_transition_dates(doc: Document, new_status: str) -> None:
	"""Geçişe bağlı tarih alanlarını doldurur.

	Delivered → actual_delivery (her geçişte damgalanır: fiili teslim anı).
	Picked Up → ship_date (yalnız boşsa: manuel girilmiş tarih ezilmez).
	"""
	now = frappe.utils.now_datetime()
	if new_status == ShipmentStatus.DELIVERED:
		doc.actual_delivery = now
	elif new_status == ShipmentStatus.PICKED_UP and not doc.get("ship_date"):
		doc.ship_date = now.date()


def _create_transition_event(
	shipment_name: str,
	from_status: str,
	to_status: str,
	*,
	source: str = "System",
	note: str | None = None,
	seller_profile: str | None = None,
) -> Document | None:
	"""Durum geçişi için Shipment Event kaydı üretir (LOG-050).

	event_hash = sha256("{shipment}:{from}:{to}:{event_time.isoformat()}").
	Hash unique constraint'ine takılırsa (aynı geçiş iki worker'da aynı
	mikrosaniyede yarışmışsa) bu IdempotencyConflictError DEĞİLDİR — çakışan
	istek "farklı bir iş" değil, AYNI geçişin duplikasyonudur; event zaten
	yazılmıştır, sessiz no-op doğru davranıştır.

	Args:
		shipment_name: Shipment doc adı.
		from_status: Geçiş öncesi durum.
		to_status: Geçiş sonrası durum.
		source: Event kaynağı (System/Webhook/Poll/Manual).
		note: Opsiyonel açıklama.
		seller_profile: Shipment'ın tenant'ı (denormalize).

	Returns:
		Oluşan Shipment Event dokümanı; duplicate yarışında None.
	"""
	event_time = frappe.utils.now_datetime()
	event_hash: str = hashlib.sha256(
		f"{shipment_name}:{from_status}:{to_status}:{event_time.isoformat()}".encode()
	).hexdigest()

	event: Document = frappe.get_doc(
		{
			"doctype": "Shipment Event",
			"shipment": shipment_name,
			"seller_profile": seller_profile,
			"event_hash": event_hash,
			"event_time": event_time,
			"internal_status": to_status,
			"source": source,
			"actor": frappe.session.user,
			"note": note,
		}
	)
	try:
		# ignore_permissions: event append-only audit kaydıdır; kullanıcı
		# geçiş yetkisini Shipment write katmanında zaten kanıtladı, Shipment
		# Event için ayrıca DocPerm aranmaz (sistem/webhook akışları dahil).
		event.insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# Aynı geçişin yarış duplikasyonu — event mevcut, sessiz no-op.
		return None
	return event
