"""FAZ 3.5 — Owner Transfer servisi.

Owner mağaza devri 2-step approval'la yapılır:
  draft → awaiting_owner_confirm → awaiting_super_admin → completed

Force transfer (System Manager): tek adımda completed (owner kayıp/erişimsiz).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime


def create_transfer(
	tenant: str,
	proposed_owner: str,
	reason: str = "",
	is_force: bool = False,
) -> str:
	"""Devir talebi oluşturur. proposed_owner Co-Owner olmalı (or force=True ile bypass)."""
	current_owner = None
	# Admin Seller Profile'da tradehub_owner field'ı varsa öncelik ona ver
	if frappe.db.has_column("Admin Seller Profile", "tradehub_owner"):
		current_owner = frappe.db.get_value("Admin Seller Profile", tenant, "tradehub_owner")
	# Fallback: User.tradehub_is_owner=1 + tenant eşleşmesi
	if not current_owner:
		current_owner = frappe.db.get_value(
			"User", {"tradehub_tenant": tenant, "tradehub_is_owner": 1}, "name"
		)

	if not current_owner:
		frappe.throw(_("Tenant {0} için Owner bulunamadı").format(tenant), exc=frappe.ValidationError)

	if not is_force and not _is_co_owner(proposed_owner, tenant):
		frappe.throw(
			_("proposed_owner Co-Owner rolünde olmalı: {0}").format(proposed_owner),
			exc=frappe.ValidationError,
		)

	doc = frappe.new_doc("Owner Transfer Request")
	doc.tenant = tenant
	doc.current_owner = current_owner
	doc.proposed_owner = proposed_owner
	doc.reason = reason
	doc.is_force_transfer = 1 if is_force else 0
	doc.status = "awaiting_super_admin" if is_force else "awaiting_owner_confirm"
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	_audit(
		"owner_transfer.create", doc.name, "ALLOW",
		target=proposed_owner,
		reason=reason or "transfer_initiated",
		severity="MEDIUM",
	)
	return doc.name


def confirm_by_current_owner(name: str) -> None:
	doc = frappe.get_doc("Owner Transfer Request", name)
	if doc.status != "awaiting_owner_confirm":
		frappe.throw(_("Bu transfer owner onayında değil: {0}").format(doc.status))

	if frappe.session.user != doc.current_owner:
		frappe.throw(
			_("Sadece mevcut Owner ({0}) bu onayı verebilir").format(doc.current_owner),
			exc=frappe.PermissionError,
		)

	doc.owner_confirmed_at = now_datetime()
	doc.status = "awaiting_super_admin"
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	_audit("owner_transfer.owner_confirm", name, "ALLOW", doc.proposed_owner,
		"owner_confirmed", severity="MEDIUM")


def approve_by_super_admin(name: str) -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if "System Manager" not in roles and "Administrator" not in roles:
		frappe.throw(
			_("Sadece System Manager bu onayı verebilir"),
			exc=frappe.PermissionError,
		)

	doc = frappe.get_doc("Owner Transfer Request", name)
	if doc.status != "awaiting_super_admin":
		frappe.throw(_("Transfer Super Admin onayında değil: {0}").format(doc.status))

	# Owner flag swap
	try:
		frappe.db.set_value("User", doc.current_owner, "tradehub_is_owner", 0)
		frappe.db.set_value("User", doc.proposed_owner, "tradehub_is_owner", 1)
		# Admin Seller Profile owner field güncelle (varsa)
		if frappe.db.has_column("Admin Seller Profile", "tradehub_owner"):
			frappe.db.set_value("Admin Seller Profile", doc.tenant, "tradehub_owner", doc.proposed_owner)
	except Exception as exc:
		frappe.log_error(f"owner swap failed: {exc}", "Owner Transfer")
		frappe.throw(_("Owner devri başarısız: {0}").format(exc))

	doc.super_admin_approved_at = now_datetime()
	doc.super_admin_approved_by = frappe.session.user
	doc.effective_at = doc.super_admin_approved_at
	doc.status = "completed"
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	_audit("owner_transfer.complete", name, "ALLOW", doc.proposed_owner,
		f"transfer_complete_from_{doc.current_owner}", severity="HIGH")

	# Role Change Log
	_log_role_change_safe(doc.proposed_owner, "Seller Owner", "promote_to_owner", f"otr:{name}")
	_log_role_change_safe(doc.current_owner, "Seller Owner", "demote_from_owner", f"otr:{name}")


def reject(name: str, reason: str) -> None:
	doc = frappe.get_doc("Owner Transfer Request", name)
	if doc.status in {"completed", "cancelled", "rejected"}:
		frappe.throw(_("Transfer zaten kapanmış: {0}").format(doc.status))

	doc.status = "rejected"
	doc.rejection_reason = reason
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	_audit("owner_transfer.reject", name, "DENY", doc.proposed_owner, reason, severity="MEDIUM")


def cancel(name: str) -> None:
	"""Current owner kendi başlattığı transfer'ı (awaiting_*'da iken) iptal edebilir."""
	doc = frappe.get_doc("Owner Transfer Request", name)
	if not doc.status.startswith("awaiting"):
		frappe.throw(_("İptal sadece awaiting aşamasında mümkün: {0}").format(doc.status))
	if frappe.session.user != doc.current_owner:
		frappe.throw(_("Sadece mevcut Owner iptal edebilir"), exc=frappe.PermissionError)
	doc.status = "cancelled"
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	_audit("owner_transfer.cancel", name, "ALLOW", doc.proposed_owner, "owner_cancelled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_co_owner(user: str, tenant: str) -> bool:
	role_profile = frappe.db.get_value("User", user, "role_profile_name")
	if role_profile == "Seller Co-Owner":
		return True
	# Veya rolde "Seller Co-Owner" var mı
	co_owner_role = frappe.db.get_value(
		"Has Role",
		{"parent": user, "role": "Seller Co-Owner", "parenttype": "User"},
		"name",
	)
	return bool(co_owner_role)


def _audit(action: str, name: str, decision: str, target: str, reason: str,
	severity: str = "LOW") -> None:
	try:
		from tradehub_core.audit import log_decision

		log_decision(
			actor=frappe.session.user or "System",
			action=action,
			decision=decision,
			rule_id=f"owner_transfer.{action.split('.')[-1]}",
			layer="L2",
			object_doctype="Owner Transfer Request",
			object_name=name,
			severity=severity,
			context={"reason": reason, "target_user": target},
		)
	except Exception as exc:
		frappe.log_error(f"owner_transfer audit failed: {exc}", "Owner Transfer")


def _log_role_change_safe(user: str, role: str, operation: str, reason: str) -> None:
	"""operation: 'promote_to_owner' | 'demote_from_owner' | 'tenant_suspend' | 'suspend'."""
	try:
		from tradehub_core.audit import log_role_change

		log_role_change(
			target_user=user,
			change_type=operation,
			changed_by=frappe.session.user or "System",
			reason=reason,
			after_roles=[role] if role else None,
		)
	except Exception as exc:
		frappe.log_error(f"_log_role_change_safe failed: {exc}", "Owner Transfer")
