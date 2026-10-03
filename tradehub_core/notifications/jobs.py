"""Zamanlanmış bildirim işleri: günlük/haftalık özet ve sipariş onay hatırlatması.

Özet: yalnız seçili e-posta kanalı açık ve `ozetlenebilir` olayların `digest_pending` kayıtları.
Anında olaylar özete girmez; özetin kendisi özete alınmaz; boş özet gönderilmez. Her öğe tek bir
özete bağlanır (`digest_delivery`), bu yüzden sıklık değişince aynı olay iki özette görünmez.
Kullanıcı başına batch; döngü başına sınırsız sorgu yok.

Hatırlatma: VARSAYILAN KAPALI (opt-in, Platform Notification Settings). Gerçek bekleyen satıcı
işlemi: "Ödeme Bekleniyor" durumunda alıcının dekont yüklediği sipariş (satıcının ödeme onayı
bekleniyor). SLA / otomatik iptal tanımı kodda olmadığından e-postada süre vaadi yoktur.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime

from tradehub_core.notifications import catalog, dispatch, preferences, schedule, store

BATCH_USERS = 200


def run_digests() -> dict:
	"""Saatlik: zamanı gelen özet öğelerini kullanıcı başına tek e-postada toplar."""
	now = now_datetime()
	D = frappe.qb.DocType(store.DELIVERY)
	users = (
		frappe.qb.from_(D)
		.select(D.user)
		.distinct()
		.where(D.status == "digest_pending")
		.where(D.due_at <= now)
		.limit(BATCH_USERS)
	).run(pluck=True)
	sent = 0
	for user in users:
		try:
			if _digest_user(user, now):
				sent += 1
			frappe.db.commit()
		except Exception:  # noqa: BLE001 — bir kullanıcının hatası diğerlerini durdurmasın
			frappe.db.rollback()
			frappe.log_error(title=f"notification digest {user}")
	return {"users": len(users), "digests": sent}


def _digest_user(user: str, now) -> bool:
	rows = frappe.get_all(
		store.DELIVERY,
		filters={"user": user, "status": "digest_pending", "due_at": ["<=", now]},
		fields=["name", "event", "payload", "creation"],
		order_by="creation asc",
		limit=500,
	)
	if not rows:
		return False
	choices, prow = preferences.stored_choices(user)
	kind = (prow.frequency if prow else None) or "instant"
	if kind not in ("daily", "weekly"):
		kind = "daily"
	rules = preferences.event_rules()
	keep = []
	for r in rows:
		rule = rules.get(r.event)
		if not rule or not preferences.choice(rule, choices, r.event, "email"):
			dispatch._finish(r.name, "cancelled", error_code="PREFERENCE_OFF")
		else:
			keep.append(r)
	if not keep:
		return False  # boş özet gönderilmez
	s = preferences.settings()
	tz = s["digest_timezone"]
	period = schedule.period_key(kind, preferences._aware_now(), tz)
	data = _digest_data(user, kind, keep, s["digest_group_limit"])
	result = dispatch.emit(f"digest.{kind}", user, data, f"{user}:{period}", meta={"type": "system"})
	created = result["deliveries"][0] if result["deliveries"] else None
	if "email" not in result["handled"]:
		# Özet şablonu yayından kalktıysa öğeler tek tek anında gönderilir; bekletilip kaybolmaz.
		for r in keep:
			with store._Write():
				frappe.db.set_value(store.DELIVERY, r.name, {"status": "queued", "due_at": now})
			frappe.enqueue(
				"tradehub_core.notifications.dispatch.process",
				queue="short",
				delivery=r.name,
				enqueue_after_commit=True,
			)
		return False
	for r in keep:
		with store._Write():
			frappe.db.set_value(
				store.DELIVERY, r.name, {"status": "digested", "digest_delivery": created, "payload": None}
			)
	return bool(created)


def _digest_data(user, kind, rows, limit) -> dict:
	groups: dict[str, dict] = {}
	for r in rows:
		item = (store._json(r.payload, {}) or {}).get("digest_item") or {}
		cat = item.get("category") or (catalog.get(r.event) or {}).get("category", "")
		g = groups.setdefault(
			cat, {"title": catalog.CATEGORIES.get(cat, {}).get("title", cat), "count": 0, "items": []}
		)
		g["count"] += 1
		if len(g["items"]) < limit:
			g["items"].append(
				{
					"title": item.get("title") or "",
					"time": dispatch.fmt_dt(item.get("at") or r.creation),
					"url": _absolute(item.get("url") or "/pages/dashboard/buyer-dashboard.html"),
				}
			)
	out_groups = []
	for g in groups.values():
		more = g["count"] - len(g["items"])
		out_groups.append({**g, "more": more > 0, "more_n": more})
	name = frappe.db.get_value("User", user, "full_name") or user
	base = dispatch.base_url()
	today = dispatch.fmt_date(now_datetime())
	return {
		"recipient_name": name,
		"digest_title": f"{today} {'günlük' if kind == 'daily' else 'haftalık'} özeti",
		"period": today,
		"total_count": len(rows),
		"generated_at": dispatch.fmt_dt(now_datetime()),
		"groups": out_groups,
		"digest_url": f"{base}/pages/dashboard/buyer-dashboard.html",
		"preferences_url": f"{base}/pages/dashboard/settings.html#bildirimler",
	}


def _absolute(url: str) -> str:
	return f"{dispatch.base_url()}{url}" if url.startswith("/") else url


def run_order_reminders() -> dict:
	"""Saatlik, opt-in. Ayar kapalıysa ya da süre 0 ise hiçbir şey yapmaz."""
	s = preferences.settings()
	if not s["order_reminder_enabled"] or s["order_reminder_after_hours"] <= 0:
		return {"enabled": False}
	cutoff = add_to_date(now_datetime(), hours=-s["order_reminder_after_hours"])
	orders = frappe.get_all(
		"Order",
		filters={"status": "Ödeme Bekleniyor", "receipt_url": ["is", "set"], "order_date": ["<=", cutoff]},
		fields=["name", "seller", "buyer", "total", "currency", "order_date"],
		limit=200,
	)
	sellers = (
		{
			r.name: r.user
			for r in frappe.get_all(
				"Admin Seller Profile",
				filters={"name": ["in", list({o.seller for o in orders if o.seller})]},
				fields=["name", "user", "seller_name"],
			)
		}
		if orders
		else {}
	)
	sent = 0
	for o in orders:
		owner = sellers.get(o.seller)
		if not owner:
			continue
		hours = int((now_datetime() - frappe.utils.get_datetime(o.order_date)).total_seconds() // 3600)
		data = order_reminder_data(o, hours)
		# Aynı sipariş için gün başına tek hatırlatma (olay oluşumu = sipariş × gün).
		res = dispatch.emit(
			"order.confirm_reminder",
			owner,
			data,
			f"{o.name}:{now_datetime():%Y-%m-%d}",
			meta={
				"type": "order",
				"reference_doctype": "Order",
				"reference_name": o.name,
				"recipient_role": "seller",
			},
		)
		sent += len(res["deliveries"])
	frappe.db.commit()
	return {"enabled": True, "orders": len(orders), "deliveries": sent}


def order_reminder_data(order, hours: int) -> dict:
	items = (
		frappe.get_all("Order Item", filters={"parent": order.name}, fields=["name"])
		if frappe.db.table_exists("Order Item")
		else []
	)
	buyer_company = frappe.db.get_value("Order", order.name, "billing_company_name") or frappe.db.get_value(
		"User", order.buyer, "full_name"
	)
	store_name = frappe.db.get_value("Admin Seller Profile", order.seller, "seller_name") or order.seller
	base = dispatch.base_url()
	return {
		"order_no": order.name,
		"buyer_company": buyer_company or "",
		"items_count": len(items),
		"order_total": f"{frappe.utils.fmt_money(order.total, currency=order.currency)}",
		"ordered_at": dispatch.fmt_dt(order.order_date),
		"waiting_hours": hours,
		"seller_store_name": store_name or "",
		"order_url": f"{base}/panel/seller-orders",
		"preferences_url": f"{base}/pages/dashboard/settings.html#bildirimler",
	}
