# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.4 — Anomaly Dashboard API endpoint'leri."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from tradehub_core.services import anomaly_detector

_VIEW_ROLES = {"System Manager", "Administrator", "Compliance Officer"}


def _require_view_role() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if not (roles & _VIEW_ROLES):
		frappe.throw(
			_("Bu işlem için Compliance Officer veya System Manager yetkisi gerekli"),
			exc=frappe.PermissionError,
		)


@frappe.whitelist()
def list_alerts(
	status: str | None = "open",
	severity: str | None = None,
	limit: int = 100,
) -> list[dict]:
	_require_view_role()
	filters: dict = {}
	if status:
		filters["status"] = status
	if severity:
		filters["severity"] = severity

	return frappe.get_all(
		"Authorization Anomaly Alert",
		filters=filters,
		fields=[
			"name", "rule", "triggered_at", "status", "severity",
			"actor", "tenant", "event_count", "window_start", "window_end",
			"action_taken", "acknowledged_by", "acknowledged_at",
		],
		order_by="triggered_at desc",
		limit=int(limit),
	)


@frappe.whitelist()
def get_alert_detail(name: str) -> dict:
	_require_view_role()
	doc = frappe.get_doc("Authorization Anomaly Alert", name).as_dict()

	# Evidence log'ları fetch et
	evidence_ids = (doc.get("evidence_log_ids") or "").split(",")
	evidence_ids = [e.strip() for e in evidence_ids if e.strip()]
	evidence: list[dict] = []
	if evidence_ids:
		evidence = frappe.get_all(
			"Authorization Decision Log",
			filters={"name": ["in", evidence_ids]},
			fields=[
				"name",
				"creation",
				"actor",
				"action",
				"decision",
				"rule_id",
				"severity",
				"layer",
				"object_doctype",
				"object_name",
				"context",
			],
			order_by="creation desc",
		)
	doc["evidence"] = evidence
	return doc


@frappe.whitelist()
def acknowledge_alert(name: str, notes: str = "") -> dict:
	_require_view_role()
	doc = frappe.get_doc("Authorization Anomaly Alert", name)
	if doc.status not in {"open", "acknowledged"}:
		frappe.throw(_("Alert zaten kapatılmış: {0}").format(doc.status))

	doc.status = "acknowledged"
	doc.acknowledged_by = frappe.session.user
	doc.acknowledged_at = now_datetime()
	if notes:
		doc.resolution_notes = (doc.resolution_notes or "") + "\n" + notes
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status}


@frappe.whitelist()
def resolve_alert(name: str, notes: str = "", false_positive: bool | int = 0) -> dict:
	_require_view_role()
	doc = frappe.get_doc("Authorization Anomaly Alert", name)
	doc.status = "false_positive" if str(false_positive) in {"1", "true", "True"} else "resolved"
	doc.acknowledged_by = doc.acknowledged_by or frappe.session.user
	doc.acknowledged_at = doc.acknowledged_at or now_datetime()
	if notes:
		doc.resolution_notes = (doc.resolution_notes or "") + "\n" + notes
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status}


@frappe.whitelist()
def list_rules(is_active: int | None = None) -> list[dict]:
	_require_view_role()
	filters = {}
	if is_active is not None:
		filters["is_active"] = int(is_active)
	return frappe.get_all(
		"Authorization Anomaly Rule",
		filters=filters,
		fields=[
			"name", "rule_code", "rule_name", "detection_type",
			"threshold_count", "window_minutes", "severity_filter",
			"is_active", "cooldown_minutes",
			"action_notify", "action_suspend_actor", "action_disable_tenant",
		],
		order_by="rule_code",
	)


@frappe.whitelist()
def trigger_detection_now() -> dict:
	"""Manual trigger — schedule beklemeden çalıştır. System Manager only."""
	roles = set(frappe.get_roles(frappe.session.user))
	if "System Manager" not in roles:
		frappe.throw(_("Sadece System Manager bu işlemi yapabilir"), exc=frappe.PermissionError)
	return anomaly_detector.run_detection()
