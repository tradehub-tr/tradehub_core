# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 2.6 — ABAC (Attribute-Based Access Control) Context Builder'ları.

OpenFGA conditions runtime'ında `context={"amount": 7450}` gibi attribute'ları
kullanır. Bu modül, check() çağrısı öncesinde uygun context dict'ini üretir.

Kullanım:

    from tradehub_core.services import abac_context, rebac_client

    ctx = abac_context.build_order_context(order)
    allowed = rebac_client.check(
        user="user:can@x.com",
        relation="can_approve_l1",
        object=f"order_approval:{approval_name}",
        context=ctx,  # {"amount": 7450, "currency": "EUR", ...}
    )

Detay: model.fga conditions tanımı, docs/yetki/faz-2/01-tasarim-kararlari.md
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe

# ---------------------------------------------------------------------------
# Order context (amount, currency, category, supplier)
# ---------------------------------------------------------------------------


def build_order_context(order_doc_or_name: Any) -> dict[str, Any]:
	"""Order için ABAC context dict üret.

	Returns:
	    {
	      "amount": float,
	      "currency": "EUR",
	      "category": str | None,
	      "supplier": str | None,
	      "buyer": str | None,
	    }
	"""
	if isinstance(order_doc_or_name, str):
		order = frappe.get_doc("Order", order_doc_or_name)
	else:
		order = order_doc_or_name

	return {
		"amount": float(order.get("total") or 0),
		"currency": order.get("currency") or "EUR",
		"category": _extract_order_category(order),
		"supplier": order.get("seller_profile"),
		"buyer": order.get("buyer"),
	}


def _extract_order_category(order) -> str | None:
	"""Order line item'larından dominant kategoriyi çıkar.

	Faz 2.6'da basit: ilk line item'ın listing.product_category değerini al.
	Birden çok kategori varsa "mixed" döner. Faz 3'te detaylı kategorize.
	"""
	# Order child table varsa
	items = getattr(order, "items", None) or getattr(order, "order_items", None)
	if not items:
		return None

	categories = set()
	for item in items:
		listing_id = getattr(item, "listing", None) or getattr(item, "listing_id", None)
		if not listing_id:
			continue
		cat = frappe.db.get_value("Listing", listing_id, "category")
		if cat:
			categories.add(cat)

	if not categories:
		return None
	if len(categories) == 1:
		return next(iter(categories))
	return "mixed"


# ---------------------------------------------------------------------------
# Region context (user → regions list)
# ---------------------------------------------------------------------------


def build_region_context(user: str | None = None) -> dict[str, Any]:
	"""User için region context (PII gating için).

	Returns:
	    {"user_regions": ["TR", "EU"], "user_jurisdiction": "KVKK"}
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return {"user_regions": [], "user_jurisdiction": None}

	# User.regions Custom Field (Faz 1.2'de Table MultiSelect olarak eklendi)
	regions_rows = frappe.get_all(
		"Subscription Plan Region",
		filters={"parent": user, "parenttype": "User"},
		pluck="region",
	)

	# Alternatif: User Profile.country veya tenant region'undan çıkar
	if not regions_rows:
		# Fallback: tenant region'u
		from tradehub_core.utils.tenant import get_current_seller_profile

		tenant = get_current_seller_profile()
		if tenant:
			regions_rows = frappe.get_all(
				"Subscription Plan Region",
				filters={"parent": tenant, "parenttype": "Admin Seller Profile"},
				pluck="region",
			)

	# Jurisdiction (her bölgenin KVKK/GDPR mapping'i)
	jurisdictions = set()
	for r in regions_rows:
		j = frappe.db.get_value("Region", r, "jurisdiction")
		if j:
			jurisdictions.add(j)

	return {
		"user_regions": regions_rows or [],
		"user_jurisdiction": _dominant_jurisdiction(jurisdictions),
	}


def _dominant_jurisdiction(jurisdictions: set[str]) -> str | None:
	"""Birden çok bölgesi varsa en kısıtlı (KVKK > GDPR > diğer) seçer."""
	if not jurisdictions:
		return None
	# Sıkı → gevşek
	priority = ["KVKK", "GDPR", "MENA", "CIS", "OTHER"]
	for j in priority:
		if j in jurisdictions:
			return j
	return next(iter(jurisdictions))


# ---------------------------------------------------------------------------
# Time context (request timestamp + business hours)
# ---------------------------------------------------------------------------


def build_time_context(business_hours: tuple[int, int] = (9, 18)) -> dict[str, Any]:
	"""Request zamanı için context.

	Args:
	    business_hours: (start_hour, end_hour) — varsayılan 09:00-18:00

	Returns:
	    {"request_time": iso, "request_hour": int, "start_hour": int, "end_hour": int}
	"""
	now = datetime.now()
	return {
		"request_time": now.isoformat(),
		"request_hour": now.hour,
		"start_hour": business_hours[0],
		"end_hour": business_hours[1],
	}


# ---------------------------------------------------------------------------
# Combined context (tipik kullanım için)
# ---------------------------------------------------------------------------


def build_full_context(
	*,
	order: Any = None,
	user: str | None = None,
	include_time: bool = False,
) -> dict[str, Any]:
	"""Birden çok kaynaktan birleşik context dict.

	Args:
	    order: Order doc veya name (opsiyonel)
	    user: User (opsiyonel, region için)
	    include_time: Zaman context'i de dahil et

	Returns:
	    Tüm context anahtarları birleşik dict
	"""
	ctx: dict[str, Any] = {}

	if order is not None:
		ctx.update(build_order_context(order))

	if user is not None or order is None:
		ctx.update(build_region_context(user))

	if include_time:
		ctx.update(build_time_context())

	return ctx


# ---------------------------------------------------------------------------
# Python-side condition evaluator (sidecar fail-closed fallback)
# ---------------------------------------------------------------------------
#
# OpenFGA conditions normalde sidecar'da değerlendirilir. Ancak sidecar down
# olduğunda Python tarafında basit fallback hesaplaması yapabiliriz.
# Bu sadece UI gating için kullanılır; güvenlik kararı yine fail-closed.


def evaluate_needs_approval_l1(amount: float) -> bool:
	"""Local fallback — model.fga'daki needs_approval_l1 condition."""
	return 500 < amount <= 5000


def evaluate_needs_approval_l2(amount: float) -> bool:
	"""Local fallback — model.fga'daki needs_approval_l2 condition."""
	return amount > 5000


def evaluate_user_in_region(user_regions: list[str], target_region: str) -> bool:
	"""Local fallback — model.fga'daki user_in_region condition."""
	return target_region in (user_regions or [])


def evaluate_within_business_hours(request_hour: int, start_hour: int = 9, end_hour: int = 18) -> bool:
	"""Local fallback — within_business_hours condition."""
	return start_hour <= request_hour < end_hour
