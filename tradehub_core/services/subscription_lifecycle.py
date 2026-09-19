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

BE-4 — ücretli abonelik lifecycle'ı (`process_paid_lifecycle`, ayrı cron kaydı):
  3) `send_renewal_reminders` — active + current_period_end dolu aboneliklere
     T-7 / T-1 dönem sonu hatırlatması (renewal_reminder_*_sent bayraklarıyla
     idempotent; copy cancel_at_period_end'e göre 'yenileme' / 'sona erme').
  4) `finalize_cancellations` — dönem sonu geçmiş + cancel_at_period_end=1 →
     state machine üzerinden `canceled` (Amazon Seller modeli, AC-8).
  5) `expire_paid_periods` — dönem sonu geçmiş + bayrak=0 → `past_due` (paywall).

Dunning dalları (BE-3, Faz C dilim 1) — past_due artık HOŞGÖRÜ penceresi:
  6) `send_dunning_reminders` — past_due aboneliklere dönem sonundan T+1/T+3/T+7
     sonra kademeli hatırlatma (dunning_reminder_*_sent cascade bayrakları).
  7) `suspend_delinquent_subscriptions` — T+14 geçmiş past_due → `suspended`
     (suspend_source='dunning') + vitrin gizleme (hide_store_listings, enqueue long).
  8) `expire_dunning_subscriptions` — T+30 geçmiş dunning-suspended → `expired`
     (cancellation_reason='dunning_expired'); manuel suspend YAKALANMAZ (D1).

Gelecekteki lifecycle job'ları (auto-renew, win-back, vb.) bu modüle eklenebilir.
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import cint, get_datetime, now_datetime

from tradehub_core.audit import log_decision
from tradehub_core.services.storefront_visibility import hide_store_listings
from tradehub_core.utils.notify import notify

_THREE_DAYS = 3 * 24 * 3600
_SEVEN_DAYS = 7 * 24 * 3600
_ONE_DAY = 24 * 3600
_TWO_HOURS = 2 * 3600

# Dunning pencere süreleri (gün) — Bora onayladı 2026-09-15 (spec risk kaydı);
# onay/karar değişirse yalnız bu iki satır güncellenir.
_DUNNING_SUSPEND_DAYS = 14
_DUNNING_EXPIRE_DAYS = 30

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


# ---------------------------------------------------------------------------
# BE-4 — Ücretli abonelik lifecycle'ı (dönem sonu hatırlatma / fesih / past_due)
# ---------------------------------------------------------------------------


def _owner_users_by_store(store_ids: list[str]) -> dict[str, str]:
	"""store (Admin Seller Profile.name) → owner user e-postası (batch, N+1 önle)."""
	unique_ids = list({s for s in store_ids if s})
	if not unique_ids:
		return {}
	# get_all gerekçe: scheduler sistem işi, perm bypass kasıtlı.
	return {
		r.name: r.user
		for r in frappe.get_all(
			"Admin Seller Profile",
			filters={"name": ["in", unique_ids]},
			fields=["name", "user"],
		)
	}


def _due_renewal_stage(sub, remaining_seconds: float) -> tuple[str | None, dict]:
	"""Gönderilecek T-7/T-1 aşaması + set edilecek bayraklar.

	`_due_reminder_stage`'in idempotent cascade deseninin kopyası (AC-9): en acil
	gönderilmemiş aşama seçilir, o aşama + daha az acil bayraklar birlikte set
	edilir — T-1 gidince geç/çift T-7 bildirimi gönderilmez.
	"""
	if remaining_seconds <= _ONE_DAY and not sub.renewal_reminder_1d_sent:
		return "1d", {"renewal_reminder_1d_sent": 1, "renewal_reminder_7d_sent": 1}
	if remaining_seconds <= _SEVEN_DAYS and not sub.renewal_reminder_7d_sent:
		return "7d", {"renewal_reminder_7d_sent": 1}
	return None, {}


def _renewal_copy(stage: str, cancel_scheduled: bool, end_str: str) -> tuple[str, str]:
	"""Hatırlatma başlık + mesajı — iki varyant (spec BE-4).

	bayrak=0 → 'yenileme yaklaşıyor'; cancel_at_period_end=1 → 'aboneliğiniz X
	tarihinde sona erecek — geri alabilirsiniz'.
	"""
	when = "yarın" if stage == "1d" else "7 gün sonra"
	if cancel_scheduled:
		return (
			f"Aboneliğiniz {when} sona erecek",
			f"Aboneliğiniz {end_str} tarihinde sona erecek — dilediğiniz an iptali geri alabilirsiniz.",
		)
	return (
		f"Aboneliğiniz {when} yenilenecek",
		f"Abonelik döneminiz {end_str} tarihinde sona eriyor. Kesintisiz devam için yenileme "
		"ödemenizi hazırlayın.",
	)


def send_renewal_reminders() -> dict:
	"""Active + current_period_end dolu aboneliklere T-7 / T-1 dönem sonu hatırlatması.

	Idempotent: her aşama renewal_reminder_*_sent bayrağıyla dönem başına yalnız
	1 kez (AC-9); yeni dönemde bayraklar controller'da sıfırlanır (BE-1).
	"""
	now = now_datetime()
	# get_all gerekçe: scheduler sistem işi, perm bypass kasıtlı.
	subs = frappe.get_all(
		"Store Subscription",
		filters={"status": "active", "current_period_end": ["is", "set"]},
		fields=[
			"name",
			"store",
			"current_period_end",
			"cancel_at_period_end",
			"renewal_reminder_7d_sent",
			"renewal_reminder_1d_sent",
		],
	)
	if not subs:
		return {"sent": 0}

	owner_by_store = _owner_users_by_store([s.store for s in subs])

	sent = 0
	for s in subs:
		try:
			remaining = (get_datetime(s.current_period_end) - now).total_seconds()
			if remaining <= 0:
				continue  # dönem sonu geçmiş → finalize/past_due aşamaları işler
			stage, flags = _due_renewal_stage(s, remaining)
			if not stage:
				continue
			owner = owner_by_store.get(s.store)
			if owner:
				end_str = get_datetime(s.current_period_end).strftime("%d.%m.%Y")
				title, message = _renewal_copy(stage, bool(cint(s.cancel_at_period_end)), end_str)
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
			frappe.log_error(f"renewal reminder fail: {s.name}: {exc}", "subscription_lifecycle.renewal")

	frappe.db.commit()
	return {"sent": sent}


def _flush_entitlement_caches(scope: str) -> None:
	"""Entitlement + pricing cache flush — expire_trial'daki desenin aynısı.

	Status değişen mağazaların capability'leri anında kesilmeli/güncellenmeli
	(aksi halde cache TTL'ine kadar eski erişim sürer).
	"""
	try:
		frappe.cache().delete_keys("tradehub:entitlement:")
		frappe.cache().delete_keys("tradehub:pricing:public")
	except Exception:
		frappe.log_error(f"cache flush failed in {scope}", f"subscription_lifecycle.{scope}")


def finalize_cancellations() -> dict:
	"""Dönem sonu geçmiş + cancel_at_period_end=1 aktifleri `canceled` yap (AC-8).

	Geçiş state machine ÜZERİNDEN (doc.save): canceled_at set etme ve bayrak
	sıfırlama Store Subscription controller'ında otomatik. Fesih günü bildirimi +
	HIGH audit + entitlement cache flush.
	"""
	now = now_datetime()
	# get_all gerekçe: scheduler sistem işi, perm bypass kasıtlı.
	due = frappe.get_all(
		"Store Subscription",
		filters={"status": "active", "cancel_at_period_end": 1, "current_period_end": ["<", now]},
		fields=["name", "store", "plan", "current_period_end"],
	)
	owner_by_store = _owner_users_by_store([s.store for s in due])

	canceled: list[str] = []
	for sub in due:
		try:
			# Idempotent: işlem öncesi re-check (race önlemi — bu arada revoke
			# edilmiş veya başka süreç status'u değiştirmiş olabilir).
			# M1: for_update=True → SELECT ... FOR UPDATE (kilit → yeniden doğrula
			# → işle): eşzamanlı kullanıcı/admin işlemi (ör. revoke) commit edene
			# kadar bu satırda BEKLENİR ve en güncel status okunur; kilit
			# çakışmasında davranış beklemedir (InnoDB lock wait), timeout'ta
			# kayıt-başına try/except loglayıp sonraki kayda geçer.
			row = frappe.db.get_value(
				"Store Subscription",
				sub.name,
				["status", "cancel_at_period_end"],
				as_dict=True,
				for_update=True,
			)
			if not row or row.status != "active" or not cint(row.cancel_at_period_end):
				continue

			doc = frappe.get_doc("Store Subscription", sub.name)
			doc.status = "canceled"
			# Scheduler context'i — user session yok, sistem geçişi kasıtlı.
			doc.save(ignore_permissions=True)
			canceled.append(sub.name)

			owner = owner_by_store.get(sub.store)
			if owner:
				end_str = get_datetime(sub.current_period_end).strftime("%d.%m.%Y")
				title = "Aboneliğiniz sona erdi"
				message = (
					f"Planladığınız iptal gerçekleşti: aboneliğiniz {end_str} tarihi itibarıyla sona erdi. "
					"Dilediğiniz zaman yeni bir paket seçerek geri dönebilirsiniz."
				)
				notify(
					recipient_user=owner,
					type="system",
					title=title,
					message=message,
					action_url="/abonelik",
					reference_doctype="Store Subscription",
					reference_name=sub.name,
					send_email=True,
					email_subject=title,
					email_body=message,
				)
			log_decision(
				action="subscription.cancellation_finalized",
				decision="ALLOW",
				rule_id="auth.subscription_cancellation",
				layer="L0",
				object_doctype="Store Subscription",
				object_name=sub.name,
				tenant=sub.store,
				plan_code=sub.plan,
				severity="HIGH",
				context={"period_end": str(sub.current_period_end), "source": "lifecycle_job"},
			)
		except Exception as exc:  # noqa: BLE001 — bir sub'un fail'i diğerlerini durdurmasın
			frappe.log_error(
				f"finalize cancellation fail: {sub.name}: {exc}",
				"subscription_lifecycle.finalize_cancellations",
			)

	if canceled:
		_flush_entitlement_caches("finalize_cancellations")

	frappe.db.commit()
	return {"canceled_count": len(canceled), "canceled_subscriptions": canceled}


def expire_paid_periods() -> dict:
	"""Dönem sonu geçmiş + iptal planı OLMAYAN aktifleri `past_due` yap (AC-8).

	Dunning Faz C dilim 1 sonrası past_due HOŞGÖRÜ penceresi (erişim sürer);
	T+0 bildirimi copy'sine hoşgörü bitişi eklendi (AC-12 — geçiş başına en
	fazla 1 bildirim davranışı DEĞİŞMEZ). Ödeme onayı gelince
	upgrade_subscription_plan satırı yeniden `active` yapar.
	"""
	now = now_datetime()
	# get_all gerekçe: scheduler sistem işi, perm bypass kasıtlı.
	due = frappe.get_all(
		"Store Subscription",
		filters={"status": "active", "cancel_at_period_end": 0, "current_period_end": ["<", now]},
		fields=["name", "store", "plan", "current_period_end"],
	)
	owner_by_store = _owner_users_by_store([s.store for s in due])

	past_due: list[str] = []
	for sub in due:
		try:
			# Idempotent re-check: bu arada iptal planlanmışsa (bayrak=1) kayıt
			# finalize'ın işi — bir sonraki koşuda o dal işler, burada atla.
			row = frappe.db.get_value(
				"Store Subscription", sub.name, ["status", "cancel_at_period_end"], as_dict=True
			)
			if not row or row.status != "active" or cint(row.cancel_at_period_end):
				continue

			doc = frappe.get_doc("Store Subscription", sub.name)
			doc.status = "past_due"
			# Scheduler context'i — user session yok, sistem geçişi kasıtlı.
			doc.save(ignore_permissions=True)
			past_due.append(sub.name)

			# Erişim kesen otomatik geçiş audit'e yazılır — finalize'daki HIGH
			# ile tutarlı (ADL severity skalasında MEDIUM yok: LOW/NORMAL/HIGH).
			log_decision(
				action="subscription.period_expired",
				decision="ALLOW",
				rule_id="auth.subscription_lifecycle",
				layer="L0",
				object_doctype="Store Subscription",
				object_name=sub.name,
				tenant=sub.store,
				plan_code=sub.plan,
				severity="HIGH",
				context={
					"period_end": str(sub.current_period_end),
					"new_status": "past_due",
					"source": "lifecycle_job",
				},
			)

			owner = owner_by_store.get(sub.store)
			if owner:
				period_end = get_datetime(sub.current_period_end)
				end_str = period_end.strftime("%d.%m.%Y")
				grace_str = _dunning_grace_end_str(period_end)
				title = "Abonelik döneminiz sona erdi — ödeme bekleniyor"
				message = (
					f"Abonelik döneminiz {end_str} tarihinde sona erdi ve yenileme ödemesi alınamadı. "
					f"Erişiminiz {grace_str} tarihine kadar sürer — kesinti yaşamamak için yenileme "
					"ödemenizi tamamlayın."
				)
				notify(
					recipient_user=owner,
					type="system",
					title=title,
					message=message,
					action_url="/abonelik",
					reference_doctype="Store Subscription",
					reference_name=sub.name,
					send_email=True,
					email_subject=title,
					email_body=message,
				)
		except Exception as exc:  # noqa: BLE001 — bir sub'un fail'i diğerlerini durdurmasın
			frappe.log_error(
				f"paid period expire fail: {sub.name}: {exc}",
				"subscription_lifecycle.expire_paid_periods",
			)

	if past_due:
		_flush_entitlement_caches("expire_paid_periods")

	frappe.db.commit()
	return {"past_due_count": len(past_due), "past_due_subscriptions": past_due}


# ---------------------------------------------------------------------------
# BE-3 — Dunning dalları (past_due hoşgörü penceresi → suspend → fesih)
# ---------------------------------------------------------------------------


def _dunning_grace_end_str(period_end) -> str:
	"""Hoşgörü penceresi bitişi (current_period_end + T+14) — bildirim copy'si için."""
	return (get_datetime(period_end) + timedelta(days=_DUNNING_SUSPEND_DAYS)).strftime("%d.%m.%Y")


def _due_dunning_stage(sub, overdue_seconds: float) -> tuple[str | None, dict]:
	"""Gönderilecek T+1/T+3/T+7 dunning aşaması + set edilecek bayraklar.

	`_due_reminder_stage` / `_due_renewal_stage` idempotent cascade deseninin
	kopyası (AC-2), yön ters: gecikme BÜYÜDÜKÇE aciliyet artar. En gecikmiş
	gönderilmemiş aşama seçilir ve o aşama + daha az acil bayraklar birlikte
	set edilir — T+7 gidince geç/çift T+1/T+3 bildirimi gönderilmez.
	"""
	if overdue_seconds >= _SEVEN_DAYS and not sub.dunning_reminder_7d_sent:
		return "7d", {
			"dunning_reminder_7d_sent": 1,
			"dunning_reminder_3d_sent": 1,
			"dunning_reminder_1d_sent": 1,
		}
	if overdue_seconds >= _THREE_DAYS and not sub.dunning_reminder_3d_sent:
		return "3d", {"dunning_reminder_3d_sent": 1, "dunning_reminder_1d_sent": 1}
	if overdue_seconds >= _ONE_DAY and not sub.dunning_reminder_1d_sent:
		return "1d", {"dunning_reminder_1d_sent": 1}
	return None, {}


def _dunning_copy(stage: str, grace_str: str) -> tuple[str, str]:
	"""Dunning hatırlatma başlık + mesajı (spec BE-3 copy sözleşmesi)."""
	titles = {
		"1d": "Yenileme ödemenizi bekliyoruz",
		"3d": "Yenileme ödemeniz 3 gündür bekleniyor",
		"7d": "Son hatırlatma — yenileme ödemenizi bekliyoruz",
	}
	message = (
		f"Abonelik döneminiz sona erdi ve yenileme ödemenizi bekliyoruz. Erişiminiz {grace_str} "
		"tarihine kadar sürer — kesinti yaşamamak için ödemenizi tamamlayın."
	)
	return titles[stage], message


def send_dunning_reminders() -> dict:
	"""past_due aboneliklere dönem sonundan T+1/T+3/T+7 sonra hatırlatma (AC-2).

	Idempotent: her aşama dunning_reminder_*_sent bayrağıyla dönem başına yalnız
	1 kez; yeni dönemde bayraklar controller'da sıfırlanır (BE-2). Dönüş değeri
	`first_reminded` bu koşuda İLK hatırlatmasını alan (önceden tamamen bayraksız)
	kayıtları listeler — suspend dalının D4b emniyeti aynı koşuda bu kayıtları
	askıya almasın diye (deploy sonrası ilk koşuda önce hatırlatma gider).
	"""
	now = now_datetime()
	# get_all gerekçe: scheduler sistem işi, perm bypass kasıtlı.
	subs = frappe.get_all(
		"Store Subscription",
		filters={"status": "past_due", "current_period_end": ["is", "set"]},
		fields=[
			"name",
			"store",
			"current_period_end",
			"dunning_reminder_1d_sent",
			"dunning_reminder_3d_sent",
			"dunning_reminder_7d_sent",
		],
	)
	if not subs:
		return {"sent": 0, "first_reminded": []}

	owner_by_store = _owner_users_by_store([s.store for s in subs])

	sent = 0
	first_reminded: list[str] = []
	for s in subs:
		try:
			overdue = (now - get_datetime(s.current_period_end)).total_seconds()
			if overdue <= 0:
				continue  # dönem sonu geçmemiş — bu dalın işi değil
			stage, flags = _due_dunning_stage(s, overdue)
			if not stage:
				continue
			had_any_flag = bool(
				cint(s.dunning_reminder_1d_sent)
				or cint(s.dunning_reminder_3d_sent)
				or cint(s.dunning_reminder_7d_sent)
			)
			owner = owner_by_store.get(s.store)
			if owner:
				title, message = _dunning_copy(stage, _dunning_grace_end_str(s.current_period_end))
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
			if not had_any_flag:
				first_reminded.append(s.name)
		except Exception as exc:  # noqa: BLE001 — bir sub'un fail'i diğerlerini durdurmasın
			frappe.log_error(f"dunning reminder fail: {s.name}: {exc}", "subscription_lifecycle.dunning")

	frappe.db.commit()
	return {"sent": sent, "first_reminded": first_reminded}


def suspend_delinquent_subscriptions(first_reminded: tuple[str, ...] | list[str] = ()) -> dict:
	"""T+14 geçmiş past_due abonelikleri `suspended` yap + vitrini gizle (AC-3/AC-4).

	D4b EMNİYETİ (iki katman): (1) en az bir dunning_reminder_*_sent bayrağı set
	olmadan suspend EDİLMEZ; (2) `first_reminded` (aynı koşuda İLK hatırlatmasını
	alan kayıtlar) bu koşuda atlanır — deploy sonrası ilk koşuda herkese önce
	hatırlatma gider, kimse uyarısız vitrin kaybetmez (bir sonraki koşu askıya alır).
	suspend_source='dunning' save ÖNCESİ set edilir (D1 — T+30 feshi yalnız bu
	işaretli kayıtları yakalar); suspended_at damgası controller'da otomatik (BE-2).
	"""
	now = now_datetime()
	cutoff = now - timedelta(days=_DUNNING_SUSPEND_DAYS)
	# get_all gerekçe: scheduler sistem işi, perm bypass kasıtlı.
	due = frappe.get_all(
		"Store Subscription",
		filters={"status": "past_due", "current_period_end": ["<", cutoff]},
		fields=[
			"name",
			"store",
			"plan",
			"current_period_end",
			"dunning_reminder_1d_sent",
			"dunning_reminder_3d_sent",
			"dunning_reminder_7d_sent",
		],
	)
	owner_by_store = _owner_users_by_store([s.store for s in due])

	suspended: list[str] = []
	for sub in due:
		try:
			# D4b katman 1: hiç hatırlatılmamış kayıt uyarısız askıya alınmaz.
			if not (
				cint(sub.dunning_reminder_1d_sent)
				or cint(sub.dunning_reminder_3d_sent)
				or cint(sub.dunning_reminder_7d_sent)
			):
				continue
			# D4b katman 2: ilk hatırlatması BU koşuda giden kayıt bir sonraki koşuyu bekler.
			if sub.name in first_reminded:
				continue

			# Idempotent: işlem öncesi re-check (race önlemi — bu arada ödeme
			# onaylanıp 'active' olmuş olabilir). M1: for_update=True kilitli
			# okuma — suspend penceresinde commit olan ödeme onayı beklenir ve
			# en güncel status görülür (mağaza yanlışlıkla askıya YAZILMAZ);
			# kilit çakışmasında davranış bekleme, timeout'ta dal try/except'i.
			current_status = frappe.db.get_value("Store Subscription", sub.name, "status", for_update=True)
			if current_status != "past_due":
				continue

			doc = frappe.get_doc("Store Subscription", sub.name)
			doc.status = "suspended"
			# D1: dunning işareti — yalnız bu job yazar; validate girişte dokunmaz,
			# suspended'dan çıkışta 'manual' default'una döner (BE-2).
			doc.suspend_source = "dunning"
			# Scheduler context'i — user session yok, sistem geçişi kasıtlı.
			doc.save(ignore_permissions=True)
			suspended.append(sub.name)

			# Vitrin gizleme — çok ürünlü mağaza için arkaya (BE-1 sözleşmesi:
			# storefront_visibility enqueue YAPMAZ, çağıranın işi); commit sonrası
			# ki job bayat status okumasın.
			frappe.enqueue(
				hide_store_listings,
				store=sub.store,
				queue="long",
				enqueue_after_commit=True,
			)

			log_decision(
				action="subscription.dunning_suspended",
				decision="ALLOW",
				rule_id="auth.subscription_lifecycle",
				layer="L0",
				object_doctype="Store Subscription",
				object_name=sub.name,
				tenant=sub.store,
				plan_code=sub.plan,
				severity="HIGH",
				context={
					"period_end": str(sub.current_period_end),
					"new_status": "suspended",
					"suspend_source": "dunning",
					"source": "lifecycle_job",
				},
			)

			owner = owner_by_store.get(sub.store)
			if owner:
				expire_str = (
					get_datetime(sub.current_period_end) + timedelta(days=_DUNNING_EXPIRE_DAYS)
				).strftime("%d.%m.%Y")
				title = "Mağazanız askıya alındı"
				message = (
					"Yenileme ödemesi alınamadığı için mağazanız askıya alındı ve vitrininiz geçici "
					"olarak pasifleştirildi. Ödemenizi tamamladığınızda vitrininiz otomatik geri açılır; "
					f"ödeme yapılmazsa aboneliğiniz {expire_str} tarihinde sona erecek."
				)
				notify(
					recipient_user=owner,
					type="system",
					title=title,
					message=message,
					action_url="/abonelik",
					reference_doctype="Store Subscription",
					reference_name=sub.name,
					send_email=True,
					email_subject=title,
					email_body=message,
				)
		except Exception as exc:  # noqa: BLE001 — bir sub'un fail'i diğerlerini durdurmasın
			frappe.log_error(
				f"dunning suspend fail: {sub.name}: {exc}",
				"subscription_lifecycle.suspend_delinquent",
			)

	if suspended:
		_flush_entitlement_caches("suspend_delinquent")

	frappe.db.commit()
	return {"suspended_count": len(suspended), "suspended_subscriptions": suspended}


def expire_dunning_subscriptions() -> dict:
	"""T+30 geçmiş dunning-suspended abonelikleri `expired` yap (AC-7).

	D1: sorgu SEVİYESİNDE suspend_source='dunning' filtresi — admin'in Desk'ten
	manuel suspend ettiği mağaza (suspend_source='manual') T+30 otomatik feshinin
	TAMAMEN dışında kalır (süresiz kilit niyeti korunur). suspended'dan çıkışta
	controller suspend_source'u temizlediği için filtre geçişten ÖNCE uygulanmalı.
	Veri/listing SİLİNMEZ; expired→active mevcut geçişiyle yeniden abonelik mümkün.
	"""
	now = now_datetime()
	cutoff = now - timedelta(days=_DUNNING_EXPIRE_DAYS)
	# get_all gerekçe: scheduler sistem işi, perm bypass kasıtlı.
	due = frappe.get_all(
		"Store Subscription",
		filters={
			"status": "suspended",
			"suspend_source": "dunning",  # D1 — manuel suspend YAKALANMAZ
			"suspended_at": ["is", "set"],
			"current_period_end": ["<", cutoff],
		},
		fields=["name", "store", "plan", "current_period_end", "suspended_at"],
	)
	owner_by_store = _owner_users_by_store([s.store for s in due])

	expired: list[str] = []
	for sub in due:
		try:
			# Idempotent re-check (race önlemi): bu arada ödeme onaylanıp 'active'
			# olmuş ya da suspend_source değişmiş olabilir — D1 filtresi burada da.
			# M1: for_update=True kilitli okuma (kilit → yeniden doğrula → işle);
			# çakışmada bekleme, timeout'ta kayıt-başına try/except devralır.
			row = frappe.db.get_value(
				"Store Subscription",
				sub.name,
				["status", "suspend_source"],
				as_dict=True,
				for_update=True,
			)
			if not row or row.status != "suspended" or row.suspend_source != "dunning":
				continue

			doc = frappe.get_doc("Store Subscription", sub.name)
			doc.status = "expired"
			doc.cancellation_reason = "dunning_expired"
			# Scheduler context'i — user session yok, sistem geçişi kasıtlı.
			doc.save(ignore_permissions=True)
			expired.append(sub.name)

			log_decision(
				action="subscription.dunning_expired",
				decision="ALLOW",
				rule_id="auth.subscription_lifecycle",
				layer="L0",
				object_doctype="Store Subscription",
				object_name=sub.name,
				tenant=sub.store,
				plan_code=sub.plan,
				severity="HIGH",
				context={
					"period_end": str(sub.current_period_end),
					"suspended_at": str(sub.suspended_at),
					"new_status": "expired",
					"cancellation_reason": "dunning_expired",
					"source": "lifecycle_job",
				},
			)

			owner = owner_by_store.get(sub.store)
			if owner:
				title = "Aboneliğiniz sona erdi"
				message = (
					"Yenileme ödemesi alınamadığı için askıdaki aboneliğiniz sona erdi. Verileriniz ve "
					"ürünleriniz silinmedi — dilediğiniz zaman yeni bir paket seçerek mağazanızı "
					"yeniden açabilirsiniz."
				)
				notify(
					recipient_user=owner,
					type="system",
					title=title,
					message=message,
					action_url="/abonelik",
					reference_doctype="Store Subscription",
					reference_name=sub.name,
					send_email=True,
					email_subject=title,
					email_body=message,
				)
		except Exception as exc:  # noqa: BLE001 — bir sub'un fail'i diğerlerini durdurmasın
			frappe.log_error(
				f"dunning expire fail: {sub.name}: {exc}",
				"subscription_lifecycle.expire_dunning",
			)

	if expired:
		_flush_entitlement_caches("expire_dunning")

	frappe.db.commit()
	return {"expired_count": len(expired), "expired_subscriptions": expired}


def process_paid_lifecycle() -> dict:
	"""Cron giriş noktası (BE-4 + BE-3): reminder → finalize → past_due → dunning.

	Sıra kasıtlı (AC-11): finalize past_due'dan ÖNCE koşar ki dönem sonu geçmiş +
	cancel_at_period_end=1 kayıt iki dalda iki kez işlenmesin (spec BE-4). Dunning
	adımları mevcut sıranın SONUNDA: hatırlatma → T+14 suspend → T+30 fesih;
	`first_reminded` köprüsü D4b emniyetinin 2. katmanı (aynı koşuda ilk
	hatırlatma + suspend birlikte olmaz). Job toplamı idempotent: ikinci koşuda
	durumu değişecek yeni kayıt yoksa hiçbir kayıt değişmez.
	"""
	reminders = send_renewal_reminders()
	finalized = finalize_cancellations()
	past_due = expire_paid_periods()
	dunning_reminders = send_dunning_reminders()
	suspended = suspend_delinquent_subscriptions(
		first_reminded=dunning_reminders.get("first_reminded") or ()
	)
	dunning_expired = expire_dunning_subscriptions()
	return {
		"reminders": reminders,
		"finalized": finalized,
		"past_due": past_due,
		"dunning_reminders": dunning_reminders,
		"suspended": suspended,
		"dunning_expired": dunning_expired,
	}
