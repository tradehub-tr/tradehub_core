# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 1.2 — Entitlement (L0) public API.

Bu modül plan-bazlı yetenek/kota kontrolü için tek doğru kaynaktır.
Tüm korumalı eylemler (Listing oluşturma, sub-user ekleme, vb.) bu API'yı
çağırmalıdır.

Kullanım:

    from tradehub_core.entitlement import has_feature, within_quota, get_plan

    # Yetenek kontrolü
    if not has_feature(store, "feature.pim.multi_variant"):
        frappe.throw(_("Bu özellik planınızda mevcut değil."))

    # Kota kontrolü
    current_count = frappe.db.count("Listing", {"seller_profile": store})
    if not within_quota(store, "quota.max_products", current_count):
        frappe.throw(_("Ürün limitinize ulaştınız."))

Detay: docs/yetki/TradeHub-Yetkilendirme-Mimarisi-v2.md §3
"""

from tradehub_core.entitlement.core import (
	EntitlementError,
	check_feature_or_throw,
	check_quota_or_throw,
	get_active_subscription,
	get_capability_flags,
	get_plan,
	get_quota_limits,
	get_subscription_status,
	has_feature,
	invalidate_plan_cache,
	invalidate_store_cache,
	is_subscription_operational,
	within_quota,
)

__all__ = [
	"EntitlementError",
	"check_feature_or_throw",
	"check_quota_or_throw",
	"get_active_subscription",
	"get_capability_flags",
	"get_plan",
	"get_quota_limits",
	"get_subscription_status",
	"has_feature",
	"invalidate_plan_cache",
	"invalidate_store_cache",
	"is_subscription_operational",
	"within_quota",
]
