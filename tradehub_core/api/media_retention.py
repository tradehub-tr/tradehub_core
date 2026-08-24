"""Media retention dry-run raporu ve tek kullanımlık insan onayı API'si."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from tradehub_core.media import audit as media_audit
from tradehub_core.media.pipeline.storage import retention

ALLOWED_ROLES = frozenset({"Media Superadmin"})


def _require_superadmin() -> None:
	user = frappe.session.user
	if user == "Administrator":
		return
	if not (set(frappe.get_roles(user)) & ALLOWED_ROLES):
		frappe.throw(_("Bu işlem yalnızca Media Superadmin rolüne açıktır."), frappe.PermissionError)


@frappe.whitelist()
def approve_maintenance_report(report_name: str, approve: int = 1, reason: str = "") -> dict[str, Any]:
	"""Kuru koşum adaylarını aynı politika hash'i için bir kez onayla/reddet."""
	_require_superadmin()
	doc = frappe.get_doc(retention.MEDIA_MAINTENANCE_REPORT, report_name)
	if not int(doc.dry_run or 0) or doc.status != "completed":
		frappe.throw(_("Yalnız başarıyla tamamlanmış kuru koşum raporu onaylanabilir."))
	if doc.approval_status != "pending":
		frappe.throw(_("Bu rapor için karar daha önce verilmiş."))
	if frappe.utils.get_datetime(doc.expires_at) < frappe.utils.now_datetime():
		frappe.throw(_("Bu kuru koşum raporunun onay süresi dolmuş."))
	decision = "approved" if int(approve or 0) else "rejected"
	frappe.db.set_value(
		retention.MEDIA_MAINTENANCE_REPORT,
		doc.name,
		{
			"approval_status": decision,
			"approved_by": frappe.session.user,
			"approved_at": frappe.utils.now_datetime(),
			"approval_reason": str(reason or "")[:1000],
		},
		update_modified=False,
	)
	media_audit.log_media_event(
		action=media_audit.ACTION_RETENTION_APPROVAL,
		allowed=decision == "approved",
		reason=str(reason or decision),
		commit=False,
		context={
			"report": doc.name,
			"job_type": doc.job_type,
			"policy_hash": doc.policy_hash,
			"candidates": int(doc.candidates or 0),
			"bytes_candidate": int(doc.bytes_candidate or 0),
		},
	)
	return {"ok": True, "report": doc.name, "approval_status": decision}


@frappe.whitelist()
def run_maintenance_dry_run(job_type: str = "combined", limit: int = 0) -> dict[str, Any]:
	"""Onay öncesi raporu açıkça üret; hiçbir yıkıcı yolu çağırmaz."""
	_require_superadmin()
	policy = retention.configured_policy()
	if job_type == "originals":
		section = retention.sweep_originals(policy=policy, dry_run=True, limit=int(limit or 0))
		report = {
			"generated_at": frappe.utils.now(),
			"dry_run": True,
			"policy": policy.to_dict(),
			"sections": [section.to_dict()],
			"totals": retention._totals(section),
		}
	elif job_type == "derivatives":
		section = retention.sweep_derivatives(policy=policy, dry_run=True, limit=int(limit or 0))
		report = {
			"generated_at": frappe.utils.now(),
			"dry_run": True,
			"policy": policy.to_dict(),
			"sections": [section.to_dict()],
			"totals": retention._totals(section),
		}
	elif job_type == "soft_delete":
		report = retention.purge_soft_deleted_renditions(dry_run=True, limit=int(limit or 0))
	else:
		job_type = "combined"
		report = retention.run_maintenance(policy=policy, dry_run=True, limit=int(limit or 0))
	report_name = retention.persist_maintenance_report(report, job_type=job_type, policy=policy)
	return {"ok": True, "report": report_name, "result": report}
