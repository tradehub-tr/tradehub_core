"""Giden stok bildirimi — webhook + yoklama (MOGEM-665 · 5. aşama).

Akış:
1. Sipariş kaynaklı stok hareketi (`utils.stock` reserve/release/deduct/refund)
   `_recalculate_available(listing, reason=…)` içinden `emit_stock_change` çağırır.
   API'nin kendi yazdığı stok (`catalog.update_stock`) sebepsiz koşar → olay
   ÜRETİLMEZ; dış sistemin kendi güncellemesi ona geri yankılanmaz (kriter 5).
2. Olay `Catalog Outbound Event` olarak kalıcıdır (yoklama kaynağı `catalog.changes`).
3. Mağazanın API uygulamasında `webhook_url` varsa olay `queued` olur ve commit
   sonrası `deliver` kuyruğa girer; yoksa `skipped` (yalnız yoklama).
4. `deliver`: HMAC-SHA256 imza (`X-Istoc-Signature: sha256=<hex>`, sır =
   `API Application.webhook_secret`, imzalanan = kaydedilen payload metni), 10 sn
   zaman aşımı, 2xx → `sent`; aksi → `failed` + geri çekilme 1/5/15/60/360 dk;
   5. başarısızlık → `dead` (panelde görünür, elle yeniden kuyruğa alınır).
5. `sweep_due` (*/5 cron): süresi gelen `failed` + kuyrukta unutulmuş `queued`.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import frappe
import requests
from frappe.utils import add_to_date, get_datetime, now_datetime

from tradehub_core.bulk_import.feed_security import validate_feed_url

EVENT_TYPE = "stock.changed"
BACKOFF_MINUTES = (1, 5, 15, 60, 360)
MAX_ATTEMPTS = len(BACKOFF_MINUTES)
TIMEOUT_SECONDS = 10
SIGNATURE_HEADER = "X-Istoc-Signature"
SWEEP_BATCH = 200
STALE_QUEUED_MINUTES = 2
DOCTYPE = "Catalog Outbound Event"


def _app_for(seller: str):
	return frappe.db.get_value(
		"API Application",
		{"seller_profile": seller, "is_active": 1},
		["name", "webhook_url"],
		as_dict=True,
	)


def build_payload(ev: dict) -> dict:
	"""Dış sisteme giden gövde — yoklama (`changes`) ile aynı alanlar."""
	return {
		"id": ev.get("name"),
		"event": ev.get("event_type") or EVENT_TYPE,
		"reason": ev.get("reason"),
		"sku": ev.get("sku"),
		"listing_code": ev.get("listing_code"),
		"stock_qty": ev.get("stock_qty"),
		"reserved_qty": ev.get("reserved_qty"),
		"available_qty": ev.get("available_qty"),
		"occurred_at": str(ev.get("occurred_at")),
	}


def emit_stock_change(listing_name: str, reason: str) -> int | None:
	"""Stok hareketini olay olarak kaydet; webhook varsa iletimi kuyruğa al.

	Sipariş akışını asla düşürmez: her hata Error Log'a gider, None döner.
	"""
	try:
		vals = frappe.db.get_value(
			"Listing",
			listing_name,
			["seller_profile", "seller_sku", "listing_code", "stock_qty", "reserved_qty", "available_qty"],
			as_dict=True,
		)
		if not vals or not vals.seller_profile:
			return None
		app = _app_for(vals.seller_profile)
		webhook = bool(app and app.webhook_url)
		ev = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"seller_profile": vals.seller_profile,
				"listing": listing_name,
				"sku": vals.seller_sku,
				"listing_code": vals.listing_code,
				"event_type": EVENT_TYPE,
				"reason": reason,
				"stock_qty": vals.stock_qty,
				"reserved_qty": vals.reserved_qty,
				"available_qty": vals.available_qty,
				"occurred_at": now_datetime(),
				"status": "queued" if webhook else "skipped",
				"attempts": 0,
				"next_attempt_at": now_datetime() if webhook else None,
			}
		)
		# Sistem olayı: sipariş akışı alıcı oturumunda koşar, satıcının kaydını yazar.
		ev.insert(ignore_permissions=True)
		ev.db_set(
			"payload", json.dumps(build_payload(ev.as_dict()), ensure_ascii=False), update_modified=False
		)
		if webhook:
			frappe.enqueue(
				"tradehub_core.integration.outbound.deliver",
				queue="short",
				enqueue_after_commit=True,
				event=ev.name,
			)
		return ev.name
	except Exception:
		frappe.log_error(title=f"outbound.emit_stock_change {listing_name}", message=frappe.get_traceback())
		return None


def sign(secret: str, body: bytes) -> str:
	return "sha256=" + hmac.new((secret or "").encode("utf-8"), body, hashlib.sha256).hexdigest()


def deliver(event) -> dict:
	"""Tek olayı webhook'a gönder; sonucu olaya işle."""
	ev = frappe.get_doc(DOCTYPE, event)
	if ev.status not in ("queued", "failed"):
		return {"event": ev.name, "status": ev.status, "skipped": True}
	app = _app_for(ev.seller_profile)
	if not app or not app.webhook_url:
		ev.db_set({"status": "skipped", "last_error": "webhook tanımlı değil"}, update_modified=False)
		return {"event": ev.name, "status": "skipped"}

	secret = (
		frappe.get_doc("API Application", app.name).get_password("webhook_secret", raise_exception=False)
		or ""
	)
	body = (ev.payload or json.dumps(build_payload(ev.as_dict()), ensure_ascii=False)).encode("utf-8")
	headers = {
		"Content-Type": "application/json",
		"User-Agent": "Istoc-Webhook/1.0",
		SIGNATURE_HEADER: sign(secret, body),
		"X-Istoc-Event": ev.event_type or EVENT_TYPE,
		"X-Istoc-Delivery": str(ev.name),
	}
	http_status = None
	try:
		validate_feed_url(app.webhook_url)  # adres iletim anında yeniden süzülür (DNS değişebilir)
		resp = requests.post(app.webhook_url, data=body, headers=headers, timeout=TIMEOUT_SECONDS)
		http_status = resp.status_code
		ok = 200 <= resp.status_code < 300
		err = "" if ok else (resp.text or "")[:500]
	except (frappe.ValidationError, requests.RequestException) as e:
		ok, err = False, str(e)[:500]

	if ok:
		_mark_sent(ev, app.name, http_status)
	else:
		_mark_failed(ev, app.name, http_status, err)
	return {"event": ev.name, "status": ev.status, "http_status": http_status}


def _mark_sent(ev, app: str, http_status: int | None) -> None:
	ev.db_set(
		{
			"status": "sent",
			"attempts": int(ev.attempts or 0) + 1,
			"last_http_status": http_status or 0,  # Int NOT NULL; ağ hatasında HTTP durumu yok → 0
			"last_error": "",
			"delivered_at": now_datetime(),
			"next_attempt_at": None,
		},
		update_modified=False,
	)
	frappe.db.set_value("API Application", app, "webhook_failures", 0, update_modified=False)


def _mark_failed(ev, app: str, http_status: int | None, err: str) -> None:
	attempts = int(ev.attempts or 0) + 1
	dead = attempts >= MAX_ATTEMPTS
	ev.db_set(
		{
			"status": "dead" if dead else "failed",
			"attempts": attempts,
			"last_http_status": http_status or 0,  # Int NOT NULL; ağ hatasında HTTP durumu yok → 0
			"last_error": err,
			"next_attempt_at": None
			if dead
			else add_to_date(now_datetime(), minutes=BACKOFF_MINUTES[attempts - 1]),
		},
		update_modified=False,
	)
	# Sayaç panelde "webhook sorunlu" uyarısı için; atomik artış (yarışta kayıp olmasın).
	frappe.db.sql(
		"UPDATE `tabAPI Application` SET webhook_failures = COALESCE(webhook_failures, 0) + 1 WHERE name = %s",
		(app,),
	)


def requeue(event) -> None:
	"""Panelden elle yeniden dene: deneme sayacı sıfırlanır, commit sonrası iletilir."""
	frappe.db.set_value(
		DOCTYPE,
		event,
		{"status": "queued", "attempts": 0, "last_error": "", "next_attempt_at": now_datetime()},
		update_modified=False,
	)
	frappe.enqueue(
		"tradehub_core.integration.outbound.deliver", queue="short", enqueue_after_commit=True, event=event
	)


def sweep_due() -> dict:
	"""Zamanlayıcı (*/5 dk): süresi gelen `failed` + eskimiş `queued` olayları ilet."""
	now = now_datetime()
	due = frappe.get_all(
		DOCTYPE,
		filters={"status": "failed", "next_attempt_at": ["<=", now]},
		pluck="name",
		order_by="next_attempt_at asc",
		limit_page_length=SWEEP_BATCH,
	)
	stale = frappe.get_all(
		DOCTYPE,
		filters={"status": "queued", "modified": ["<=", add_to_date(now, minutes=-STALE_QUEUED_MINUTES)]},
		pluck="name",
		order_by="modified asc",
		limit_page_length=SWEEP_BATCH,
	)
	sent = failed = 0
	for name in [*due, *stale]:
		try:
			r = deliver(name)
			if r.get("status") == "sent":
				sent += 1
			elif r.get("status") in ("failed", "dead"):
				failed += 1
			frappe.db.commit()  # her olay bağımsız; biri patlarsa diğerleri kaybolmasın
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"outbound.sweep_due {name}", message=frappe.get_traceback())
	return {"due": len(due), "stale": len(stale), "sent": sent, "failed": failed}


def is_due(next_attempt_at) -> bool:
	return bool(next_attempt_at) and get_datetime(next_attempt_at) <= now_datetime()


def on_listing_trash(doc, method=None) -> None:
	"""Listing.on_trash — ürünün giden stok olaylarını kaskad sil.

	`listing` alanı Data (Link değil) olduğundan Frappe bağ denetimi yapmaz; olaylar
	kalsaydı seri geri sarmayla (`revert_series_if_last`) yeniden kullanılan bir ürün
	adına yanlışlıkla eşlenirdi (15 Eyl kampanyasında ölçüldü: 6 yetim olay yeni ürüne
	yapıştı). Denetim kaydı ürün ömrüyle sınırlı; yoklayan ERP zaten `next_since`
	imlecini geçmiştir.
	"""
	frappe.db.delete(DOCTYPE, {"listing": doc.name})
