"""FAZ 3.5 — Role Delegation servisi.

Bir kullanıcının belirli süre boyunca başka bir kullanıcı adına rol kullanmasını sağlar.

Lifecycle:
  pending → active → (expired | revoked)

API:
  create_delegation(delegator, delegate, role, tenant, starts_at, ends_at, reason)
  activate_delegation(name)       — pending → active, role atar, audit log
  revoke_delegation(name, reason) — active → revoked, role kaldırır
  expire_overdue_delegations()    — scheduler hourly
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime


def create_delegation(
	delegator: str,
	delegate: str,
	role: str,
	tenant: str | None,
	starts_at: datetime,
	ends_at: datetime,
	reason: str = "",
) -> str:
	"""Pending delegation kaydı oluşturur."""
	if delegator == delegate:
		frappe.throw(_("Kendine delegation yapılamaz"), exc=frappe.ValidationError)
	if starts_at >= ends_at:
		frappe.throw(_("ends_at, starts_at'tan sonra olmalı"), exc=frappe.ValidationError)

	doc = frappe.new_doc("Role Delegation")
	doc.delegator = delegator
	doc.delegate = delegate
	doc.role = role
	doc.tenant = tenant
	doc.starts_at = starts_at
	doc.ends_at = ends_at
	doc.reason = reason
	doc.status = "pending"
	doc.auto_revoke = 1
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	_audit("delegation.create", doc.name, "ALLOW", delegate, reason or "delegation_created")
	return doc.name


def activate_delegation(name: str, approver: str | None = None) -> None:
	doc = frappe.get_doc("Role Delegation", name)
	if doc.status != "pending":
		frappe.throw(_("Yalnızca pending delegation aktive edilebilir: {0}").format(doc.status))

	approver = approver or frappe.session.user
	_assign_role(doc.delegate, doc.role, until=doc.ends_at)

	doc.status = "active"
	doc.approved_by = approver
	doc.approved_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	_audit("delegation.activate", name, "ALLOW", doc.delegate, "delegation_activated")
	_log_role_change_safe(
		user=doc.delegate, role=doc.role, operation="delegate_assign",
		reason=f"delegation:{name}",
	)


def revoke_delegation(name: str, reason: str = "") -> None:
	doc = frappe.get_doc("Role Delegation", name)
	if doc.status not in {"pending", "active"}:
		frappe.throw(_("Bu delegation revoke edilemez: {0}").format(doc.status))

	if doc.status == "active":
		_unassign_role(doc.delegate, doc.role)

	doc.status = "revoked"
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	_audit("delegation.revoke", name, "ALLOW", doc.delegate, reason or "delegation_revoked",
		severity="MEDIUM")
	_log_role_change_safe(
		user=doc.delegate, role=doc.role, operation="delegate_revoke",
		reason=f"delegation:{name}:{reason}",
	)


def expire_overdue_delegations(now: datetime | None = None) -> dict[str, Any]:
	"""Hourly scheduler entry — active+auto_revoke delegation'lardan ends_at geçmiş olanları kapat."""
	now = now or now_datetime()

	candidates = frappe.get_all(
		"Role Delegation",
		filters={
			"status": "active",
			"auto_revoke": 1,
			"ends_at": ["<=", now],
		},
		pluck="name",
	)

	expired = 0
	for name in candidates:
		try:
			doc = frappe.get_doc("Role Delegation", name)
			_unassign_role(doc.delegate, doc.role)
			doc.status = "expired"
			doc.save(ignore_permissions=True)
			expired += 1
			_audit("delegation.expire", name, "ALLOW", doc.delegate, "auto_expired")
			_log_role_change_safe(
				user=doc.delegate, role=doc.role, operation="delegate_expire",
				reason=f"delegation:{name}",
			)
		except Exception as exc:
			frappe.log_error(f"expire_overdue_delegations: {name} → {exc}", "Delegation Service")

	frappe.db.commit()
	return {"checked": len(candidates), "expired": expired}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assign_role(user: str, role: str, until: datetime | None = None) -> None:
	"""Add role to user + set temporary_role_until."""
	try:
		user_doc = frappe.get_doc("User", user)
		existing_roles = {r.role for r in (user_doc.roles or [])}
		if role not in existing_roles:
			user_doc.append("roles", {"role": role})
		if until:
			user_doc.temporary_role_until = until
		user_doc.save(ignore_permissions=True)
	except Exception as exc:
		frappe.log_error(f"_assign_role failed: {exc}", "Delegation Service")
		frappe.throw(_("Rol atama başarısız: {0}").format(exc), exc=frappe.ValidationError)


def _unassign_role(user: str, role: str) -> None:
	"""Remove role from user."""
	try:
		user_doc = frappe.get_doc("User", user)
		user_doc.roles = [r for r in (user_doc.roles or []) if r.role != role]
		# Eğer başka aktif delegation yoksa temporary_role_until temizle
		other_active = frappe.db.get_value(
			"Role Delegation",
			{"delegate": user, "status": "active", "role": ["!=", role]},
			"name",
		)
		if not other_active:
			user_doc.temporary_role_until = None
		user_doc.save(ignore_permissions=True)
	except Exception as exc:
		frappe.log_error(f"_unassign_role failed: {exc}", "Delegation Service")


def _audit(action: str, name: str, decision: str, target: str, reason: str,
	severity: str = "LOW") -> None:
	try:
		from tradehub_core.audit import log_decision

		log_decision(
			actor=frappe.session.user or "System",
			action=action,
			decision=decision,
			rule_id=f"delegation.{action.split('.')[-1]}",
			layer="L2",
			object_doctype="Role Delegation",
			object_name=name,
			severity=severity,
			context={"reason": reason, "target_user": target},
		)
	except Exception as exc:
		frappe.log_error(f"delegation audit failed: {exc}", "Delegation Service")


def _log_role_change_safe(user: str, role: str, operation: str, reason: str) -> None:
	"""operation: 'delegate_assign' | 'delegate_revoke' | 'delegate_expire'."""
	try:
		from tradehub_core.audit import log_role_change

		log_role_change(
			target_user=user,
			change_type=operation,
			changed_by=frappe.session.user or "System",
			reason=reason,
			after_roles=[role] if role else None,
			is_temporary=True,
		)
	except Exception as exc:
		frappe.log_error(f"_log_role_change_safe failed: {exc}", "Delegation Service")
