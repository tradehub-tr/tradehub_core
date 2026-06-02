# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.3 — Procurement (Onaylı Tedarikçi + Cost Center) endpoint'leri.

Endpoints:
  Cost Center:
    - get_cost_center_tree()
    - upsert_cost_center(...)
    - delete_cost_center(name)
    - check_budget_availability(cost_center, amount)

  Supplier Whitelist:
    - get_approved_suppliers()
    - upsert_supplier_list(...)
    - delete_supplier_list(name)
    - check_supplier_approval(supplier, amount, categories)
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from tradehub_core.services import cost_center as cc_service
from tradehub_core.services import supplier_whitelist as sw_service
from tradehub_core.utils import tenant as tenant_utils

_WRITE_ROLES = {"System Manager", "Administrator", "Buyer", "Compliance Officer"}


def _require_write_role() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if not (roles & _WRITE_ROLES):
		frappe.throw(
			_("Bu işlem için Buyer veya System Manager yetkisi gerekli"),
			exc=frappe.PermissionError,
		)


def _is_super_admin() -> bool:
	"""System Manager / Administrator → tüm tenant'ları görür."""
	roles = set(frappe.get_roles(frappe.session.user))
	return bool(roles & {"System Manager", "Administrator"})


def _resolve_caller_tenant(allow_global: bool = False) -> str | None:
	"""Caller'ın tenant'ını çöz.

	Super Admin için `None` döner (= tüm tenant'lar).
	Normal user için tenant bulunamazsa PermissionError.
	"""
	if _is_super_admin():
		return None
	tenant = tenant_utils._get_seller_profile_for_user(frappe.session.user)  # noqa: SLF001
	if not tenant:
		if allow_global:
			return None
		frappe.throw(_("Mevcut kullanıcının tenant'ı bulunamadı"), exc=frappe.PermissionError)
	return tenant


# ---------------------------------------------------------------------------
# Cost Center
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_cost_center_tree(tenant: str | None = None) -> list[dict]:
	tenant = tenant or _resolve_caller_tenant(allow_global=True)
	return cc_service.get_tree(tenant)


@frappe.whitelist()
def upsert_cost_center(
	cost_center_code: str,
	cost_center_name: str,
	tenant: str | None = None,
	parent_cost_center: str | None = None,
	linked_organization: str | None = None,
	monthly_budget: float = 0,
	currency: str = "EUR",
	budget_period: str = "monthly",
	is_group: bool | int = 0,
	is_active: bool | int = 1,
	description: str = "",
) -> dict:
	_require_write_role()
	tenant = tenant or _resolve_caller_tenant()
	if not tenant:
		frappe.throw(
			_("Cost Center oluşturmak için tenant gerekli (Super Admin manuel seçmeli)"),
			exc=frappe.ValidationError,
		)

	existing = frappe.db.get_value(
		"Cost Center",
		{"tenant": tenant, "cost_center_code": cost_center_code},
		"name",
	)

	if existing:
		doc = frappe.get_doc("Cost Center", existing)
	else:
		doc = frappe.new_doc("Cost Center")
		doc.tenant = tenant
		doc.cost_center_code = cost_center_code

	doc.cost_center_name = cost_center_name
	doc.parent_cost_center = parent_cost_center or None
	doc.linked_organization = linked_organization or None
	doc.monthly_budget = float(monthly_budget or 0)
	doc.currency = currency
	doc.budget_period = budget_period
	doc.is_group = 1 if str(is_group) in {"1", "True", "true"} else 0
	doc.is_active = 1 if str(is_active) in {"1", "True", "true"} else 0
	doc.description = description
	doc.save()
	frappe.db.commit()

	return {"ok": True, "name": doc.name, "created": not existing}


@frappe.whitelist()
def delete_cost_center(name: str) -> dict:
	_require_write_role()
	frappe.delete_doc("Cost Center", name, ignore_permissions=False)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def check_budget_availability(cost_center: str, amount: float) -> dict:
	"""UI preflight — does NOT audit."""
	decision = cc_service.validate_budget(cost_center, float(amount or 0))
	return {
		"decision": decision.decision,
		"reason": decision.reason,
		"cost_center": decision.cost_center,
		"current_spend": decision.current_spend,
		"budget": decision.budget,
		"remaining": decision.remaining,
	}


# ---------------------------------------------------------------------------
# Approved Supplier List
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_approved_suppliers(tenant: str | None = None) -> list[dict]:
	tenant = tenant or _resolve_caller_tenant(allow_global=True)
	filters: dict = {}
	if tenant:
		filters["tenant"] = tenant
	lists = frappe.get_all(
		"Approved Supplier List",
		filters=filters,
		fields=[
			"name",
			"list_name",
			"is_default",
			"is_active",
			"effective_from",
			"effective_to",
		],
		order_by="modified desc",
	)
	for lst in lists:
		entries = frappe.get_all(
			"Approved Supplier Entry",
			filters={"parent": lst["name"], "parenttype": "Approved Supplier List"},
			fields=[
				"supplier",
				"min_order_amount",
				"max_order_amount",
				"allowed_categories",
				"is_active",
				"notes",
			],
		)
		lst["suppliers"] = entries
	return lists


@frappe.whitelist()
def upsert_supplier_list(
	list_name: str,
	tenant: str | None = None,
	name: str | None = None,
	is_default: bool | int = 0,
	is_active: bool | int = 1,
	effective_from: str | None = None,
	effective_to: str | None = None,
	suppliers: list | str | None = None,
	notes: str = "",
) -> dict:
	_require_write_role()
	tenant = tenant or _resolve_caller_tenant()
	if not tenant:
		frappe.throw(
			_("Liste oluşturmak için tenant gerekli (Super Admin manuel seçmeli)"),
			exc=frappe.ValidationError,
		)

	if isinstance(suppliers, str):
		try:
			suppliers = json.loads(suppliers)
		except json.JSONDecodeError:
			frappe.throw(_("suppliers geçerli JSON olmalı"), exc=frappe.ValidationError)
	suppliers = suppliers or []

	if name:
		doc = frappe.get_doc("Approved Supplier List", name)
	else:
		doc = frappe.new_doc("Approved Supplier List")
		doc.tenant = tenant

	doc.list_name = list_name
	doc.is_default = 1 if str(is_default) in {"1", "True", "true"} else 0
	doc.is_active = 1 if str(is_active) in {"1", "True", "true"} else 0
	doc.effective_from = effective_from or None
	doc.effective_to = effective_to or None
	doc.notes = notes

	doc.set("suppliers", [])
	for s in suppliers:
		if not isinstance(s, dict) or not s.get("supplier"):
			continue
		doc.append(
			"suppliers",
			{
				"supplier": s["supplier"],
				"min_order_amount": float(s.get("min_order_amount") or 0),
				"max_order_amount": float(s.get("max_order_amount") or 0),
				"allowed_categories": s.get("allowed_categories", ""),
				"is_active": 1 if s.get("is_active", 1) else 0,
				"notes": s.get("notes", ""),
			},
		)

	doc.save()
	frappe.db.commit()

	return {"ok": True, "name": doc.name}


@frappe.whitelist()
def delete_supplier_list(name: str) -> dict:
	_require_write_role()
	frappe.delete_doc("Approved Supplier List", name, ignore_permissions=False)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def check_supplier_approval(
	supplier: str,
	amount: float = 0,
	categories: list | str | None = None,
	tenant: str | None = None,
) -> dict:
	"""UI preflight — does NOT audit."""
	tenant = tenant or _resolve_caller_tenant()

	if isinstance(categories, str):
		try:
			categories = json.loads(categories)
		except json.JSONDecodeError:
			categories = [c.strip() for c in categories.split(",") if c.strip()]

	decision = sw_service.is_supplier_approved(
		tenant=tenant,
		supplier=supplier,
		amount=float(amount or 0),
		categories=categories,
	)
	return {
		"decision": decision.decision,
		"reason": decision.reason,
		"matched_list": decision.matched_list,
		"matched_entry": decision.matched_entry,
	}
