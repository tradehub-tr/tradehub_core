# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.2 — Entitlement cache sync hook'ları.

Plan veya Store Subscription değiştiğinde ilgili store'ların entitlement
cache'lerini invalidate eder. Bu, kullanıcının plan değişikliğini en geç
5 dakika içinde yansıması yerine **anında** yansımasını sağlar.

Detay: docs/yetki/TradeHub-Yetkilendirme-Mimarisi-v2.md §3, §9
"""

import frappe

from tradehub_core.entitlement.core import invalidate_plan_cache, invalidate_store_cache


def on_store_subscription_update(doc, method=None) -> None:
	"""Store Subscription on_update / after_insert hook.

	1. Cache invalidate (entitlement'in 5dk TTL'ini bypass et)
	2. Plan downgrade ise sub-user role profilelerini yeni plan'a göre sync et
	"""
	if not doc.store:
		return
	invalidate_store_cache(doc.store)

	# Plan değişikliği var mı?
	if not doc.previous_plan or doc.previous_plan == doc.plan:
		return

	# Downgrade ise sub-user'ları yeni plan'a uyarla
	try:
		from tradehub_core.services.subscription_downgrade import (
			apply_role_downgrade_for_plan_change,
			is_downgrade,
		)

		if is_downgrade(doc.previous_plan, doc.plan):
			result = apply_role_downgrade_for_plan_change(doc.store, doc.plan)
			frappe.logger().info(
				f"Plan downgrade {doc.previous_plan}→{doc.plan} for {doc.store}: "
				f"downgraded={len(result['downgraded'])}, "
				f"deactivated={len(result['deactivated'])}, "
				f"unchanged={len(result['unchanged'])}"
			)
	except Exception as exc:  # noqa: BLE001 — hook failure ana save'i bozmasın
		frappe.log_error(
			f"Plan downgrade sub-user sync fail (store={doc.store}, {doc.previous_plan}→{doc.plan}): {exc}",
			"subscription_downgrade",
		)


def on_subscription_plan_update(doc, method=None) -> None:
	"""Subscription Plan on_update hook.

	Bu plana sahip tüm aktif store'ların cache'ini invalidate et.
	"""
	if not doc.name:
		return
	invalidate_plan_cache(doc.name)

	# FAZ 4.1 — Public pricing cache (storefront sell.html)
	try:
		from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

		invalidate_pricing_cache()
	except Exception as exc:  # noqa: BLE001 — cache invalidation kritik değil
		frappe.log_error(f"public pricing cache invalidate fail: {exc}", "pricing_cache")

	# Audit log (Faz 1.4'te ADL'ye yazılacak)
	frappe.logger().info(
		f"Subscription Plan '{doc.name}' güncellendi; "
		f"is_active={doc.is_active}, ilgili tüm store cache'leri invalidate edildi."
	)
