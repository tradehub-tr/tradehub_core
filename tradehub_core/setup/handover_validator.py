"""FAZ 3.6 — Production handover validator.

Tüm yetki sistemi bileşenlerinin production-ready olduğunu doğrular.

Endpoint:
  GET /api/method/tradehub_core.setup.handover_validator.validate_production_readiness

Returns:
  {
    "ok": bool,
    "summary": {"pass": N, "fail": M, "warn": K},
    "checks": [{"name": "...", "status": "PASS|FAIL|WARN", "detail": "..."}],
  }

System Manager only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _


@dataclass
class Check:
	name: str
	status: str  # PASS | FAIL | WARN
	detail: str = ""

	def to_dict(self) -> dict[str, str]:
		return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class ValidationReport:
	checks: list[Check] = field(default_factory=list)

	def add(self, name: str, status: str, detail: str = "") -> None:
		self.checks.append(Check(name=name, status=status, detail=detail))

	def summary(self) -> dict[str, Any]:
		counts = {"PASS": 0, "FAIL": 0, "WARN": 0}
		for c in self.checks:
			counts[c.status] = counts.get(c.status, 0) + 1
		ok = counts["FAIL"] == 0
		return {
			"ok": ok,
			"summary": {
				"pass": counts["PASS"],
				"fail": counts["FAIL"],
				"warn": counts["WARN"],
			},
			"checks": [c.to_dict() for c in self.checks],
		}


@frappe.whitelist()
def validate_production_readiness() -> dict[str, Any]:
	"""Production öncesi tüm yetki sistemi check'leri."""
	roles = set(frappe.get_roles(frappe.session.user))
	if "System Manager" not in roles and "Administrator" not in roles:
		frappe.throw(
			_("Sadece System Manager bu validator'ı çağırabilir"),
			exc=frappe.PermissionError,
		)

	r = ValidationReport()

	_check_doctypes(r)
	_check_roles(r)
	_check_default_seeds(r)
	_check_scheduler(r)
	_check_hooks(r)
	_check_sidecar(r)
	_check_audit_log_accessible(r)

	return r.summary()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


_REQUIRED_DOCTYPES = [
	"Subscription Plan",
	"Region",
	"Feature Catalog",
	"Authorization Decision Log",
	"Role Change Log",
	"Permission Override Log",
	"Store Subscription",
	"Seller Sub User Invite",
	"Buyer Sub User Invite",
	"Approval Rule",
	"Order Approval",
	"Order Approval Log",
	"PII Field Policy",
	"PII Jurisdiction Rule",
	"Cost Center",
	"Approved Supplier List",
	"Approved Supplier Entry",
	"Authorization Anomaly Rule",
	"Authorization Anomaly Alert",
	"Role Delegation",
	"Owner Transfer Request",
]


def _check_doctypes(r: ValidationReport) -> None:
	missing: list[str] = []
	for dt in _REQUIRED_DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			missing.append(dt)

	if missing:
		r.add(
			"doctypes",
			"FAIL",
			f"Eksik doctype'lar: {', '.join(missing)}",
		)
	else:
		r.add("doctypes", "PASS", f"{len(_REQUIRED_DOCTYPES)} required doctype mevcut")


_REQUIRED_ROLES = [
	"Seller Owner",
	"Seller Co-Owner",
	"Seller Admin",
	"Buyer",
	"Buyer Approver L1",
	"Buyer Approver L2",
	"Compliance Officer",
]


def _check_roles(r: ValidationReport) -> None:
	missing: list[str] = []
	for role in _REQUIRED_ROLES:
		if not frappe.db.exists("Role", role):
			missing.append(role)

	if missing:
		r.add("roles", "FAIL", f"Eksik roller: {', '.join(missing)}")
	else:
		r.add("roles", "PASS", f"{len(_REQUIRED_ROLES)} required rol mevcut")


def _check_default_seeds(r: ValidationReport) -> None:
	# Subscription Plans
	plan_count = frappe.db.count("Subscription Plan", {"is_active": 1})
	if plan_count < 3:
		r.add("subscription_plans", "WARN", f"Sadece {plan_count} aktif plan var (önerilen >= 3)")
	else:
		r.add("subscription_plans", "PASS", f"{plan_count} aktif plan")

	# Regions
	region_count = frappe.db.count("Region", {"is_active": 1})
	if region_count < 4:
		r.add("regions", "WARN", f"{region_count} aktif region (önerilen >= 4: TR/EU/MENA/CIS)")
	else:
		r.add("regions", "PASS", f"{region_count} aktif region")

	# PII Field Policies
	pii_count = frappe.db.count("PII Field Policy", {"is_active": 1})
	if pii_count == 0:
		r.add("pii_policies", "FAIL", "Hiç PII Field Policy yok — seed patch çalışmamış")
	elif pii_count < 6:
		r.add("pii_policies", "WARN", f"{pii_count} PII policy (önerilen >= 6)")
	else:
		r.add("pii_policies", "PASS", f"{pii_count} aktif PII policy")

	# Anomaly Rules
	anomaly_count = frappe.db.count("Authorization Anomaly Rule", {"is_active": 1})
	if anomaly_count < 5:
		r.add("anomaly_rules", "WARN", f"{anomaly_count} aktif rule (önerilen 5 default)")
	else:
		r.add("anomaly_rules", "PASS", f"{anomaly_count} aktif anomaly rule")


def _check_scheduler(r: ValidationReport) -> None:
	"""hooks.py'daki kritik scheduler entry'leri runtime'da var mı?"""
	try:
		from tradehub_core import hooks as _hooks
	except Exception as exc:
		r.add("hooks_module", "FAIL", f"hooks.py import edilemedi: {exc}")
		return

	expected_hourly = [
		"tradehub_core.services.anomaly_detector.run_detection",
		"tradehub_core.services.delegation_service.expire_overdue_delegations",
	]
	expected_daily = [
		"tradehub_core.services.rebac_drift_detection.scan_drift",
	]

	hourly = _hooks.scheduler_events.get("hourly", [])
	missing_hourly = [e for e in expected_hourly if e not in hourly]
	if missing_hourly:
		r.add("scheduler_hourly", "FAIL", f"Eksik hourly entry: {missing_hourly}")
	else:
		r.add("scheduler_hourly", "PASS", "hourly scheduler entry'leri kayıtlı")

	daily = _hooks.scheduler_events.get("daily", [])
	missing_daily = [e for e in expected_daily if e not in daily]
	if missing_daily:
		r.add("scheduler_daily", "FAIL", f"Eksik daily entry: {missing_daily}")
	else:
		r.add("scheduler_daily", "PASS", "daily scheduler entry'leri kayıtlı")


def _check_hooks(r: ValidationReport) -> None:
	"""doc_events Order ve User için kritik hook'lar mevcut mu?"""
	try:
		from tradehub_core import hooks as _hooks

		order_hooks = _hooks.doc_events.get("Order", {})
		expected_in_before = [
			"tradehub_core.services.supplier_whitelist.validate_order_supplier",
			"tradehub_core.services.cost_center.validate_order_cost_center",
		]
		before_insert = order_hooks.get("before_insert", [])
		if isinstance(before_insert, str):
			before_insert = [before_insert]

		missing = [h for h in expected_in_before if h not in before_insert]
		if missing:
			r.add("order_hooks", "FAIL", f"Order.before_insert eksik: {missing}")
		else:
			r.add("order_hooks", "PASS", "Order procurement hook'ları kayıtlı")
	except Exception as exc:
		r.add("hooks_runtime", "WARN", f"hooks kontrolünde hata: {exc}")


def _check_sidecar(r: ValidationReport) -> None:
	try:
		from tradehub_core.services import rebac_client

		ok = rebac_client.healthz()
		if ok:
			r.add("rebac_sidecar", "PASS", "OpenFGA sidecar canlı")
		else:
			r.add("rebac_sidecar", "WARN", "Sidecar healthz fail — B2B flow degraded")
	except Exception as exc:
		r.add("rebac_sidecar", "WARN", f"Sidecar kontrolü: {exc}")


def _check_audit_log_accessible(r: ValidationReport) -> None:
	try:
		recent = frappe.db.count("Authorization Decision Log")
		if recent == 0:
			r.add("audit_log", "WARN", "Audit log boş — sistem henüz log üretmemiş olabilir")
		else:
			r.add("audit_log", "PASS", f"Audit log erişilebilir ({recent} kayıt)")
	except Exception as exc:
		r.add("audit_log", "FAIL", f"Audit log read fail: {exc}")
