# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 2.5 — Order Approval whitelisted API endpoints.

Endpoints:
  - list_pending_approvals() → caller'ın onaylayabileceği bekleyen Order Approval'lar
  - get_approval_detail(name)
  - approve(name, comment)
  - reject(name, reason)
  - get_order_approval_status(order_name)

Detay: docs/yetki/faz-2/03-faz-2-detayli-plan.md §2.5
"""

from __future__ import annotations

import frappe
from frappe import _

from tradehub_core.services import approval_workflow


@frappe.whitelist()
def list_pending_approvals() -> list[dict]:
	"""Caller'ın onaylayabileceği bekleyen Order Approval'lar.

	Frappe'nin `permission_query_conditions` ile filtreleme yapmıyoruz —
	bunun yerine Approval Rule'daki approver chain üzerinden direkt query.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Yetki gerekli."), frappe.PermissionError)

	# Caller'ın bulunduğu Approval Rule'ları + level'ları bul
	approver_rows = frappe.get_all(
		"Approval Rule Approver",
		filters={"approver": user},
		fields=["parent", "approver_level"],
	)

	if not approver_rows:
		return []

	# Aktif Order Approval'lar — caller'ın level'ında pending olanlar
	pending_approvals = []
	for row in approver_rows:
		rule_name = row["parent"]
		level = row["approver_level"]

		status_filter = "Pending L1" if level == 1 else "Pending L2"
		approvals = frappe.get_all(
			"Order Approval",
			filters={
				"approval_rule": rule_name,
				"status": status_filter,
				"current_level": level,
			},
			fields=[
				"name",
				"order",
				"organization",
				"status",
				"current_level",
				"max_level",
				"amount",
				"currency",
				"requisitioner",
				"started_at",
				"expires_at",
			],
			order_by="started_at asc",
		)
		pending_approvals.extend(approvals)

	# Dedup
	seen = set()
	unique = []
	for a in pending_approvals:
		if a["name"] not in seen:
			seen.add(a["name"])
			unique.append(a)

	return unique


@frappe.whitelist()
def get_approval_detail(name: str) -> dict:
	"""Tek Order Approval detayı (log + rule snapshot dahil)."""
	if not frappe.db.exists("Order Approval", name):
		frappe.throw(_("Order Approval bulunamadı."))

	approval = frappe.get_doc("Order Approval", name)

	# Yetki: caller approver mı, requisitioner mı veya admin mı?
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	is_admin = bool(roles & {"System Manager", "Marketplace Admin", "Administrator"})
	is_requisitioner = approval.requisitioner == user

	# Approver mı?
	rule = frappe.get_doc("Approval Rule", approval.approval_rule)
	all_approvers = (
		rule.get_approvers_at_level(1) + rule.get_approvers_at_level(2)
	)
	is_approver = user in all_approvers

	if not (is_admin or is_requisitioner or is_approver):
		frappe.throw(_("Bu onayı görme yetkiniz yok."), frappe.PermissionError)

	return {
		"name": approval.name,
		"order": approval.order,
		"organization": approval.organization,
		"status": approval.status,
		"current_level": approval.current_level,
		"max_level": approval.max_level,
		"amount": float(approval.amount or 0),
		"currency": approval.currency,
		"requisitioner": approval.requisitioner,
		"started_at": str(approval.started_at) if approval.started_at else None,
		"finalized_at": str(approval.finalized_at) if approval.finalized_at else None,
		"expires_at": str(approval.expires_at) if approval.expires_at else None,
		"rejection_reason": approval.rejection_reason,
		"approval_log": [
			{
				"timestamp": str(log.timestamp) if log.timestamp else None,
				"approver": log.approver,
				"action": log.action,
				"level": log.level,
				"comment": log.comment,
			}
			for log in (approval.approval_log or [])
		],
		"rule_approvers": {
			"l1": rule.get_approvers_at_level(1),
			"l2": rule.get_approvers_at_level(2),
		},
	}


@frappe.whitelist()
def approve(name: str, comment: str = "") -> dict:
	"""Order Approval'ı onayla."""
	new_status = approval_workflow.approve(name, comment=comment)
	return {
		"name": name,
		"new_status": new_status,
		"message": _("Onay kaydedildi. Yeni durum: {0}").format(new_status),
	}


@frappe.whitelist()
def reject(name: str, reason: str = "") -> dict:
	"""Order Approval'ı reddet."""
	if not reason or not reason.strip():
		frappe.throw(_("Reddetme nedeni zorunludur."))
	new_status = approval_workflow.reject(name, reason=reason)
	return {
		"name": name,
		"new_status": new_status,
		"message": _("Sipariş reddedildi."),
	}


@frappe.whitelist()
def get_order_approval_status(order_name: str) -> dict:
	"""Bir Order için aktif Order Approval'ın özet durumu.

	Storefront/buyer kullanır: "Sipariş Onay Bekliyor" durumu için.
	"""
	if not frappe.db.exists("Order", order_name):
		frappe.throw(_("Order bulunamadı."))

	# Caller bu order'ı görebilmeli (Frappe permission_query_conditions zaten kontrol ediyor)
	order = frappe.get_doc("Order", order_name)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	is_admin = bool(roles & {"System Manager", "Marketplace Admin"})
	is_buyer = order.buyer == user
	if not (is_admin or is_buyer):
		# Approver da olabilir
		approver_rows = frappe.get_all(
			"Approval Rule Approver", filters={"approver": user}, pluck="parent"
		)
		approval = frappe.db.get_value(
			"Order Approval",
			{"order": order_name, "approval_rule": ["in", approver_rows or [""]]},
			"name",
		)
		if not approval:
			frappe.throw(_("Bu siparişin onay durumunu görme yetkiniz yok."), frappe.PermissionError)

	# En son aktif veya terminal Order Approval
	approval_name = frappe.db.get_value(
		"Order Approval",
		{"order": order_name},
		"name",
		order_by="creation desc",
	)
	if not approval_name:
		return {"has_approval": False, "message": _("Bu sipariş için onay zinciri kurulmamış.")}

	approval = frappe.get_doc("Order Approval", approval_name)
	rule = frappe.get_doc("Approval Rule", approval.approval_rule)
	current_approvers = rule.get_approvers_at_level(approval.current_level)

	return {
		"has_approval": True,
		"approval_name": approval.name,
		"status": approval.status,
		"current_level": approval.current_level,
		"max_level": approval.max_level,
		"is_terminal": approval.is_terminal(),
		"current_approvers": current_approvers,
		"started_at": str(approval.started_at) if approval.started_at else None,
		"expires_at": str(approval.expires_at) if approval.expires_at else None,
	}
