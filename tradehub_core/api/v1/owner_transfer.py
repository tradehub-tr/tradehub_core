# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.5 — Owner Transfer API endpoint'leri."""

from __future__ import annotations

import frappe
from frappe import _

from tradehub_core.services import owner_transfer as ot


@frappe.whitelist()
def list_transfers(status: str | None = None, tenant: str | None = None) -> list[dict]:
	user = frappe.session.user
	roles = set(frappe.get_roles(user))

	filters: dict = {}
	if status:
		filters["status"] = status
	if tenant:
		filters["tenant"] = tenant
	# Owner sadece kendi tenant'ı; System Manager hepsini görür
	if not (roles & {"System Manager", "Administrator", "Compliance Officer"}):
		filters["current_owner"] = user

	return frappe.get_all(
		"Owner Transfer Request",
		filters=filters,
		fields=[
			"name",
			"tenant",
			"current_owner",
			"proposed_owner",
			"status",
			"owner_confirmed_at",
			"super_admin_approved_at",
			"super_admin_approved_by",
			"effective_at",
			"is_force_transfer",
			"reason",
			"rejection_reason",
		],
		order_by="modified desc",
	)


@frappe.whitelist()
def request_transfer(
	tenant: str,
	proposed_owner: str,
	reason: str = "",
	is_force: bool | int = 0,
) -> dict:
	force = str(is_force) in {"1", "true", "True"}
	if force:
		roles = set(frappe.get_roles(frappe.session.user))
		if "System Manager" not in roles and "Administrator" not in roles:
			frappe.throw(_("Force transfer sadece System Manager"), exc=frappe.PermissionError)

	name = ot.create_transfer(
		tenant=tenant,
		proposed_owner=proposed_owner,
		reason=reason,
		is_force=force,
	)
	return {"ok": True, "name": name}


@frappe.whitelist()
def confirm_transfer(name: str) -> dict:
	ot.confirm_by_current_owner(name)
	return {"ok": True, "name": name, "status": "awaiting_super_admin"}


@frappe.whitelist()
def approve_transfer(name: str) -> dict:
	ot.approve_by_super_admin(name)
	return {"ok": True, "name": name, "status": "completed"}


@frappe.whitelist()
def reject_transfer(name: str, reason: str) -> dict:
	ot.reject(name, reason)
	return {"ok": True, "name": name, "status": "rejected"}


@frappe.whitelist()
def cancel_transfer(name: str) -> dict:
	ot.cancel(name)
	return {"ok": True, "name": name, "status": "cancelled"}
