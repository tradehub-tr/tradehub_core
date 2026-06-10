# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Subscription lifecycle — scheduled state transitions.

İki iş:
  1) `send_trial_reminders` — trial bitişine 3 gün / 1 gün / 2 saat kala satıcıyı
     bilgilendirir (e-posta + panel-içi). Idempotent reminder_*_sent bayraklarıyla.
  2) `expire_trial_subscriptions` — trial_end geçmiş trial'ları `expired` yapar
     (ücretsiz katman yok → iptal değil paywall; veri korunur).

`process_trial_lifecycle` ikisini tek geçişte çalıştırır; hooks.py cron
(*/30 * * * *) bunu çağırır. 2 saat hassasiyeti için sub-daily gerekli.

Gelecekteki lifecycle job'ları (past_due → suspended dunning, auto-renew, vb.)
bu modüle eklenebilir.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_datetime, now_datetime

from tradehub_core.utils.notify import notify

_THREE_DAYS = 3 * 24 * 3600
_ONE_DAY = 24 * 3600
_TWO_HOURS = 2 * 3600

# Reminder aşaması → (başlık, mesaj). E-posta konusu = başlık, gövde = mesaj.
_REMINDER_COPY = {
	"3d": (
		"Pro denemeniz 3 gün sonra bitiyor",
		"Pro denemenizin bitmesine 3 gün kaldı. Kesintisiz devam için bir paket seçin.",
	),
	"1d": (
		"Pro denemeniz yarın bitiyor",
		"Pro denemeniz yarın sona eriyor. Erişiminizi kaybetmemek için aboneliğinizi başlatın.",
	),
	"2h": (
		"Pro denemeniz birazdan bitiyor",
		"Pro denemenizin bitmesine 2 saatten az kaldı. Hemen bir paket seçerek erişiminizi sürdürün.",
	),
}


def expire_trial_subscriptions() -> dict:
	"""Daily job: trial_end geçmiş 'trial' status'undaki subscription'ları
	canceled'a çevir.

	Senaryo:
	  Store Subscription oluşturuldu (status=trial, trial_end=2026-05-15)
	  2026-05-22'de bu job çalışır → status=canceled, cancellation_reason set.

	Pricing SLA gereği: trial süresi dolduktan sonra otomatik feature kesilmeli.
	"""
	now = now_datetime()
	expired_subs = frappe.get_all(
		"Store Subscription",
		filters={
			"status": "trial",
			"trial_end": ["<", now],
		},
		fields=["name", "store", "plan", "trial_end"],
	)

	canceled: list[str] = []
	for sub in expired_subs:
		try:
			# Idempotent: re-check status before processing (race condition önlemi —
			# scheduler + manual cancel aynı anda çalışırsa duplicate processing engellenir)
			current_status = frappe.db.get_value("Store Subscription", sub.name, "status")
			if current_status != "trial":
				continue  # zaten başka bir process tarafından değiştirilmiş

			doc = frappe.get_doc("Store Subscription", sub.name)
			# Ücretsiz katman YOK → trial bitince iptal değil `expired` (paywall).
			# Veri korunur; ödeme/yeniden abonelikle `active`e döner.
			doc.status = "expired"
			if doc.meta.has_field("cancellation_reason"):
				doc.cancellation_reason = "Trial period expired (auto)"
			doc.save(ignore_permissions=True)
			canceled.append(sub.name)
			frappe.logger().info(f"Trial expired: {sub.name} (store={sub.store}, trial_end={sub.trial_end})")
		except Exception as exc:  # noqa: BLE001 — bir sub'un fail'i diğerlerini durdurmasın
			frappe.log_error(
				f"Trial expire fail: {sub.name}: {exc}",
				"subscription_lifecycle.expire_trial",
			)

	# Entitlement cache flush — expired olan mağazaların capability'leri anında
	# kesilmeli (aksi halde cache TTL'ine kadar Pro özellikleri açık kalır).
	if canceled:
		try:
			frappe.cache().delete_keys("tradehub:entitlement:")
			frappe.cache().delete_keys("tradehub:pricing:public")
		except Exception:
			frappe.log_error("cache flush failed in expire_trial", "subscription_lifecycle.expire_trial")

	frappe.db.commit()

	return {
		"expired_count": len(canceled),
		"expired_subscriptions": canceled,
	}


def _due_reminder_stage(sub, remaining_seconds: float) -> tuple[str | None, dict]:
	"""Gönderilecek aşamayı + set edilecek bayrakları döndür.

	En acil gönderilmemiş aşama seçilir ve o aşama + daha az acil bayraklar set
	edilir (cascade) — böylece daha acil bildirim gidince geç/çift düşük-aciliyet
	bildirimi gönderilmez.
	"""
	if remaining_seconds <= _TWO_HOURS and not sub.reminder_2h_sent:
		return "2h", {"reminder_2h_sent": 1, "reminder_1d_sent": 1, "reminder_3d_sent": 1}
	if remaining_seconds <= _ONE_DAY and not sub.reminder_1d_sent:
		return "1d", {"reminder_1d_sent": 1, "reminder_3d_sent": 1}
	if remaining_seconds <= _THREE_DAYS and not sub.reminder_3d_sent:
		return "3d", {"reminder_3d_sent": 1}
	return None, {}


def send_trial_reminders() -> dict:
	"""Trial bitişine 3 gün / 1 gün / 2 saat kala satıcıya hatırlatma (e-posta + panel).

	Idempotent: her aşama Store Subscription.reminder_*_sent bayrağıyla yalnız 1 kez.
	"""
	now = now_datetime()
	subs = frappe.get_all(
		"Store Subscription",
		filters={"status": "trial", "trial_end": ["is", "set"]},
		fields=[
			"name",
			"store",
			"trial_end",
			"reminder_3d_sent",
			"reminder_1d_sent",
			"reminder_2h_sent",
		],
	)
	if not subs:
		return {"sent": 0}

	# Owner user'larını batch çek (N+1 önle): store = Admin Seller Profile.name → .user
	store_ids = list({s.store for s in subs if s.store})
	owner_by_store = (
		{
			r.name: r.user
			for r in frappe.get_all(
				"Admin Seller Profile",
				filters={"name": ["in", store_ids]},
				fields=["name", "user"],
			)
		}
		if store_ids
		else {}
	)

	sent = 0
	for s in subs:
		try:
			remaining = (get_datetime(s.trial_end) - now).total_seconds()
			if remaining <= 0:
				continue  # expiry ayrı aşamada
			stage, flags = _due_reminder_stage(s, remaining)
			if not stage:
				continue
			owner = owner_by_store.get(s.store)
			if owner:
				title, message = _REMINDER_COPY[stage]
				notify(
					recipient_user=owner,
					# Platform Notification.type Select'inde "subscription" yok → "system".
					type="system",
					title=title,
					message=message,
					action_url="/abonelik",
					reference_doctype="Store Subscription",
					reference_name=s.name,
					send_email=True,
					email_subject=title,
					email_body=message,
				)
			# Bayrağı her durumda set et (owner bulunamasa bile sonsuz retry olmasın).
			frappe.db.set_value("Store Subscription", s.name, flags, update_modified=False)
			sent += 1
		except Exception as exc:  # noqa: BLE001 — bir sub'un fail'i diğerlerini durdurmasın
			frappe.log_error(f"trial reminder fail: {s.name}: {exc}", "subscription_lifecycle.reminder")

	frappe.db.commit()
	return {"sent": sent}


def process_trial_lifecycle() -> dict:
	"""Cron (*/30 * * * *) giriş noktası: önce reminder'lar, sonra expiry.

	Tek fonksiyon — 2 saat reminder hassasiyeti için sub-daily çalışmalı.
	"""
	reminders = send_trial_reminders()
	expired = expire_trial_subscriptions()
	return {"reminders": reminders, "expired": expired}
