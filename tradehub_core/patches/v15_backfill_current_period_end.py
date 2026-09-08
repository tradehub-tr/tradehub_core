# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Backfill: aktif Store Subscription'larda hiç yazılmamış current_period_end (BE-1 / R1).

`current_period_end` bugüne kadar hiçbir kod yolunda yazılmadı; BE-2 (iptal uçları)
ve BE-4 (lifecycle job) bu alan olmadan işlevsiz. Bu patch mevcut `active`
aboneliklere idempotent şekilde dönem sonu yazar.

R1 (PM revizyonu — KRİTİK): `Store Subscription.billing_cycle` da hiç yazılmadı
(JSON default 'monthly'), ödeme talepleri ise default 'yearly' — bayat default'tan
türetme yasak. Dönem uzunluğu ÖNCE mağazanın son ONAYLI (status='confirmed')
`Subscription Payment.billing_cycle`'ından alınır, yoksa `sub.billing_cycle`'a
düşülür; `sub.billing_cycle` aynı patch'te senkronlanır.

Dönem sonu türetme sırası (hiçbir aktif mağaza backfill sonucu ANINDA past_due olamaz):
  1) (current_period_start || started_at) + cycle → gelecekteyse kullan
  2) geçmişteyse: son onaylı ödemenin onay tarihi (confirmed_at) + cycle → gelecekteyse kullan
  3) o da geçmişteyse / onaylı ödeme yoksa: taban now + 7 gün

Idempotent: yalnız current_period_end boş kayıtlar işlenir; ikinci koşu no-op.
"""

from __future__ import annotations

from datetime import datetime

import frappe
from frappe.utils import add_days, add_months, get_datetime, now_datetime

_CYCLE_MONTHS: dict[str, int] = {"monthly": 1, "yearly": 12}
_PAST_DUE_FLOOR_DAYS = 7


def execute() -> None:
	# has_column doctype adı bekler, tablo adı değil — "tab" öneki TableMissingError
	# fırlatır (aynı tuzak v15_9_30_media_asset_active_version.py'de ölçülmüştü).
	if not frappe.db.has_column("Store Subscription", "current_period_end"):
		return

	# Sistem migration'ı — permission bypass kasıtlı (get_all).
	subs = frappe.get_all(
		"Store Subscription",
		filters={"status": "active", "current_period_end": ["is", "not set"]},
		fields=["name", "store", "billing_cycle", "started_at", "current_period_start"],
	)
	if not subs:
		return

	latest_payment = _latest_confirmed_payment_by_store([s.store for s in subs if s.store])
	now = now_datetime()
	updated = 0

	for sub in subs:
		payment = latest_payment.get(sub.store)
		# R1: dönem uzunluğu kaynağı = son onaylı ödemenin cycle'ı, yoksa sub.billing_cycle.
		cycle = (payment.billing_cycle if payment else None) or sub.billing_cycle or "monthly"
		months = _CYCLE_MONTHS.get(cycle, 1)

		start, end = _derive_period(sub, payment, months, now)

		values: dict[str, object] = {
			"current_period_start": start,
			"current_period_end": end,
		}
		if cycle != sub.billing_cycle:
			values["billing_cycle"] = cycle  # R1: senkron — bayat default kalıcılaşmasın
		frappe.db.set_value("Store Subscription", sub.name, values, update_modified=False)
		updated += 1

	frappe.db.commit()
	frappe.logger().info(f"v15_backfill_current_period_end: {updated}/{len(subs)} abonelik backfill edildi")


def _latest_confirmed_payment_by_store(stores: list[str]) -> dict[str, frappe._dict]:
	"""Mağaza başına en yeni onaylı Subscription Payment (batch — N+1 önlenir)."""
	if not stores:
		return {}
	rows = frappe.get_all(
		"Subscription Payment",
		filters={"store": ["in", list(set(stores))], "status": "confirmed"},
		fields=["store", "billing_cycle", "confirmed_at"],
		order_by="confirmed_at desc",
	)
	latest: dict[str, frappe._dict] = {}
	for row in rows:
		latest.setdefault(row.store, row)  # DESC sırada ilk görülen = en yeni
	return latest


def _derive_period(
	sub: frappe._dict, payment: frappe._dict | None, months: int, now: datetime
) -> tuple[datetime, datetime]:
	"""(current_period_start, current_period_end) türet — sonuç asla geçmişte bitmez."""
	# 1) Mevcut dönem başı (yoksa started_at — reqd, her kayıtta var)
	base = get_datetime(sub.current_period_start or sub.started_at)
	end = add_months(base, months)
	if end > now:
		return base, end

	# 2) R1: türetilen dönem geçmişteyse son onaylı ödemenin onay tarihinden yeniden hesapla
	if payment and payment.confirmed_at:
		base = get_datetime(payment.confirmed_at)
		end = add_months(base, months)
		if end > now:
			return base, end

	# 3) R1 tabanı: o da geçmişteyse now + 7 gün — aktif mağaza anında past_due olamaz
	return now, add_days(now, _PAST_DUE_FLOOR_DAYS)
