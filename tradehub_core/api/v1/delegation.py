# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.5 — Role Delegation API endpoint'leri."""

from __future__ import annotations

from datetime import datetime

import frappe
from frappe import _

from tradehub_core.services import delegation_service


@frappe.whitelist()
def list_my_delegations(role: str | None = None) -> dict:
	"""Caller'ın oluşturduğu (delegated) ve aldığı (received) delegation'lar."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Yetki gerekli"), exc=frappe.PermissionError)

	filters_out = {"delegator": user}
	filters_in = {"delegate": user}
	if role:
		filters_out["role"] = role
		filters_in["role"] = role

	fields = ["name", "delegator", "delegate", "role", "tenant", "status", "starts_at", "ends_at", "reason"]

	return {
		"delegated_by_me": frappe.get_all(
			"Role Delegation", filters=filters_out, fields=fields, order_by="ends_at desc"
		),
		"delegated_to_me": frappe.get_all(
			"Role Delegation", filters=filters_in, fields=fields, order_by="ends_at desc"
		),
	}


@frappe.whitelist()
def create_delegation(
	delegate: str,
	role: str,
	starts_at: str,
	ends_at: str,
	tenant: str | None = None,
	reason: str = "",
) -> dict:
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Yetki gerekli"), exc=frappe.PermissionError)

	name = delegation_service.create_delegation(
		delegator=user,
		delegate=delegate,
		role=role,
		tenant=tenant,
		starts_at=datetime.fromisoformat(starts_at) if isinstance(starts_at, str) else starts_at,
		ends_at=datetime.fromisoformat(ends_at) if isinstance(ends_at, str) else ends_at,
		reason=reason,
	)
	return {"ok": True, "name": name, "status": "pending"}


@frappe.whitelist()
def activate_delegation(name: str) -> dict:
	"""Owner / System Manager pending delegation'ı aktive eder."""
	roles = set(frappe.get_roles(frappe.session.user))
	if not (roles & {"System Manager", "Administrator", "Seller Owner"}):
		frappe.throw(_("Aktivasyon yetkisi yok"), exc=frappe.PermissionError)

	delegation_service.activate_delegation(name)
	return {"ok": True, "name": name, "status": "active"}


@frappe.whitelist()
def revoke_delegation(name: str, reason: str = "") -> dict:
	doc = frappe.get_doc("Role Delegation", name)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))

	if not (roles & {"System Manager", "Administrator", "Seller Owner"} or user == doc.delegator):
		frappe.throw(_("Revoke yetkisi yok"), exc=frappe.PermissionError)

	delegation_service.revoke_delegation(name, reason)
	return {"ok": True, "name": name, "status": "revoked"}
