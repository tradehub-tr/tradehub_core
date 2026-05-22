# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Subscription lifecycle — scheduled state transitions.

K1 fix: Trial subscription'ları otomatik olarak süresi dolunca canceled'a alır.
Gelecekteki lifecycle job'ları (past_due → suspended dunning, çift period
auto-renew, vb.) bu modüle eklenebilir.

Scheduler kayıt: hooks.py scheduler_events["daily"].
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime


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
			doc = frappe.get_doc("Store Subscription", sub.name)
			doc.previous_plan = doc.plan  # downgrade hook tetiklemesi için
			doc.status = "canceled"
			# DocType'da varsa cancellation_reason set et
			if doc.meta.has_field("cancellation_reason"):
				doc.cancellation_reason = "Trial period expired (auto)"
			if doc.meta.has_field("canceled_at"):
				doc.canceled_at = now
			prev_flag = frappe.flags.ignore_permissions
			frappe.flags.ignore_permissions = True
			try:
				doc.save(ignore_permissions=True)
			finally:
				frappe.flags.ignore_permissions = prev_flag
			canceled.append(sub.name)
			frappe.logger().info(
				f"Trial expired: {sub.name} (store={sub.store}, trial_end={sub.trial_end})"
			)
		except Exception as exc:  # noqa: BLE001 — bir sub'un fail'i diğerlerini durdurmasın
			frappe.log_error(
				f"Trial expire fail: {sub.name}: {exc}",
				"subscription_lifecycle.expire_trial",
			)

	frappe.db.commit()

	return {
		"expired_count": len(canceled),
		"expired_subscriptions": canceled,
	}
