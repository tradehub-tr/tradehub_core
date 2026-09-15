"""BE-6 — Admin dikkat listesi: iptal-planlı + dunning abonelikleri (AC-12).

`list_attention_subscriptions` superadmin-only TEK uçtur; SubscriptionPaymentsView
"İptal Planlı & Ödemesi Geciken Mağazalar" bölümünü besler (AD-3). Yeni DocType
veya rapor YOK — mevcut Store Subscription satırlarından üç blok döner:

  cancellations   : status='active' + cancel_at_period_end=1 — dönem sonunda
                    kapanacak mağazalar, current_period_end asc (en yakın önce).
  dunning         : status IN ('past_due', 'suspended') — ödemesi geciken /
                    askıya alınmış mağazalar, current_period_end asc.
  reason_breakdown: cancellations bloğundaki iptal sebebi sayaçları — YALNIZ
                    görülen (>0) anahtarlar; allowlist'in sıfır kalanları yok.

Yetki: frappe.only_for(System Manager / Marketplace Admin) — diğer tüm roller 403.
BE-3 bağımlılığı: cancel_requested_at alanı Store Subscription'da mevcut.
"""

from __future__ import annotations

from typing import Any

import frappe

# GÜVENLİK — frappe.rate_limiter.rate_limit(key="user") KULLANMA: Frappe v15'te
# kova kimliği form_dict'ten okunur ve istemci `user=<rastgele>` ile limiti
# atlar. Proje-içi decorator kimliği frappe.session.user'dan türetir
# (detay: tradehub_core/api/rate_limit.py + test_subscription_cancellation).
from tradehub_core.api.rate_limit import rate_limit

_ADMIN_ROLES = ("System Manager", "Marketplace Admin")

# Admin listesi üst sınırı — sayfalama out_of_scope (PO), 500 satır panel
# bölümü için fazlasıyla yeterli; sınırsız çekim yasak (anti-pattern #7).
_LIST_LIMIT = 500

# Her iki blok da "en yakın tarih en üstte" okunur: cancellations'ta dönem sonu
# = fesih anı, dunning'de dönem sonu = gecikmenin başladığı sınır.
_ORDER_BY = "current_period_end asc"

_CANCELLATION_FIELDS = [
	"store",
	"plan",
	"cancellation_reason",
	"cancel_requested_at",
	"current_period_end",
]

_DUNNING_FIELDS = [
	"store",
	"plan",
	"status",
	"current_period_end",
	"suspended_at",
]


@frappe.whitelist()
@rate_limit(max_calls=30, window_seconds=300, scope="list_attention_subscriptions")
def list_attention_subscriptions() -> dict[str, Any]:
	"""Admin: dikkat gerektiren abonelikler (AC-12).

	Returns:
	    {cancellations: [...], dunning: [...], reason_breakdown: {sebep: adet}}
	    — her satırda store_name (Admin Seller Profile.seller_name, tek batch).
	"""
	frappe.only_for(_ADMIN_ROLES)

	# get_all bilinçli (get_list değil): uç yukarıda only_for ile superadmin'e
	# kilitli ve TÜM mağazaların abonelik satırları admin görünümüne ait —
	# tenant permission filtresi burada kasıtlı olarak devrede değil.
	cancellations = frappe.get_all(
		"Store Subscription",
		filters={"status": "active", "cancel_at_period_end": 1},
		fields=_CANCELLATION_FIELDS,
		order_by=_ORDER_BY,
		limit_page_length=_LIST_LIMIT,
	)
	dunning = frappe.get_all(
		"Store Subscription",
		filters={"status": ["in", ("past_due", "suspended")]},
		fields=_DUNNING_FIELDS,
		order_by=_ORDER_BY,
		limit_page_length=_LIST_LIMIT,
	)

	# store_name iki blok için TEK batch sorguyla eklenir (N+1 yok) —
	# list_subscription_payments'taki desenin ortaklaştırılmış hali.
	_attach_store_names([*cancellations, *dunning])

	# Sebep dağılımı: yalnız cancellations bloğundan, yalnız görülen anahtarlar
	# (>0) — sıfır sayaçlı allowlist anahtarı yanıta girmez (AC-12).
	reason_breakdown: dict[str, int] = {}
	for row in cancellations:
		reason = (row.get("cancellation_reason") or "").strip()
		if reason:
			reason_breakdown[reason] = reason_breakdown.get(reason, 0) + 1

	return {
		"cancellations": cancellations,
		"dunning": dunning,
		"reason_breakdown": reason_breakdown,
	}


def _attach_store_names(rows: list[dict[str, Any]]) -> None:
	"""Satırlara `store_name` ekle — Admin Seller Profile TEK batch sorgu (N+1 yok).

	Profili bulunmayan / seller_name'i boş mağazada store kimliğine düşülür
	(admin listesi satırı adsız kalmasın).
	"""
	store_ids = sorted({r["store"] for r in rows if r.get("store")})
	name_map: dict[str, str] = {}
	if store_ids:
		# get_all bilinçli: admin-only uçta yalnız ad haritası okunuyor.
		name_map = {
			p["name"]: p["seller_name"]
			for p in frappe.get_all(
				"Admin Seller Profile",
				filters={"name": ["in", store_ids]},
				fields=["name", "seller_name"],
			)
		}
	for r in rows:
		r["store_name"] = name_map.get(r["store"]) or r["store"]
