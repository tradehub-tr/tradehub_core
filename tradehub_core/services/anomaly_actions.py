"""FAZ 3.4 — Anomali aksiyonları.

Üç tip aksiyon:
  - notify_super_admins(alert_name, rule, group) → email + platform notification
  - suspend_actor(user, reason) → User.enabled = 0 + Role Change Log
  - disable_tenant(tenant, reason) → Admin Seller Profile.status="Suspended"

Hepsi best-effort; bir aksiyon başarısız olursa diğeri etkilenmez.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

# D5: Anomaly bildirimleri sadece System Manager'a değil; forensik triage'ı
# yapacak rollerin tamamına gitsin. Compliance Officer'ın varlık sebebi bu.
_ANOMALY_NOTIFY_ROLES = (
	"System Manager",
	"Marketplace Admin",
	"Platform Super Admin",
	"Platform Admin",
	"Compliance Officer",
)


def notify_super_admins(alert_name: str, rule: dict, group: Any) -> None:
	"""Send Frappe Notification + email to all platform-admin users.

	D5: Genişletilmiş alıcı listesi — `_ANOMALY_NOTIFY_ROLES`. Duplicate
	user'lar (birden fazla role taşıyanlar) set ile teklenir.
	"""
	admin_set: set[str] = set()
	for role in _ANOMALY_NOTIFY_ROLES:
		rows = (
			frappe.get_all(
				"Has Role",
				filters={"role": role, "parenttype": "User"},
				pluck="parent",
			)
			or []
		)
		admin_set.update(rows)
	admins = sorted(admin_set)

	subject = _("[Anomaly] {0}").format(rule.get("rule_name") or rule.get("rule_code"))
	body = _(
		"Anomali tetiklendi: {0}\nWindow: {1} → {2}\nOlay sayısı: {3}\nActor: {4}\nTenant: {5}\nAlert ID: {6}"
	).format(
		rule.get("rule_code"),
		group.window_start,
		group.window_end,
		group.count,
		group.actor or "(çoklu)",
		group.tenant or "(çoklu)",
		alert_name,
	)

	# Platform Notification (in-app)
	for admin in admins:
		try:
			notif = (
				frappe.new_doc("Notification Log")
				if frappe.db.exists("DocType", "Notification Log")
				else None
			)
			if notif:
				notif.for_user = admin
				notif.subject = subject
				notif.email_content = body
				notif.document_type = "Authorization Anomaly Alert"
				notif.document_name = alert_name
				notif.insert(ignore_permissions=True)
		except Exception as exc:
			frappe.log_error(
				f"notify_super_admins notification failed for {admin}: {exc}",
				"Anomaly Actions",
			)

	# Email (best-effort, sadece email_id set olanlar)
	try:
		recipients = [u for u in admins if frappe.db.get_value("User", u, "email")]
		if recipients:
			frappe.sendmail(
				recipients=recipients,
				subject=subject,
				message=body.replace("\n", "<br/>"),
				now=False,  # queue
			)
	except Exception as exc:
		frappe.log_error(f"notify_super_admins email failed: {exc}", "Anomaly Actions")


def suspend_actor(user: str, reason: str = "") -> None:
	"""Pasifleştir + Role Change Log."""
	if not user:
		return
	if not frappe.db.exists("User", user):
		return

	try:
		frappe.db.set_value("User", user, "enabled", 0)
		_log_role_change_safe(
			user=user,
			action="suspend",
			reason=reason,
		)
	except Exception as exc:
		frappe.log_error(f"suspend_actor failed for {user}: {exc}", "Anomaly Actions")


def disable_tenant(tenant: str, reason: str = "") -> None:
	"""Admin Seller Profile.status = Suspended."""
	if not tenant or not frappe.db.exists("Admin Seller Profile", tenant):
		return
	try:
		frappe.db.set_value("Admin Seller Profile", tenant, "status", "Suspended")
		_log_role_change_safe(
			user=tenant,
			action="tenant_suspend",
			reason=reason,
		)
	except Exception as exc:
		frappe.log_error(f"disable_tenant failed for {tenant}: {exc}", "Anomaly Actions")


def _log_role_change_safe(user: str, action: str, reason: str) -> None:
	"""Best-effort Role Change Log. action: 'suspend' | 'tenant_suspend'."""
	try:
		from tradehub_core.audit import log_role_change

		log_role_change(
			target_user=user,
			change_type=action,
			changed_by=frappe.session.user or "System",
			reason=reason,
		)
	except Exception as exc:
		frappe.log_error(f"_log_role_change_safe failed: {exc}", "Anomaly Actions")
