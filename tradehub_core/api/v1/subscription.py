"""Faz E.3 — Self-service Subscription Plan upgrade/downgrade.

Owner (`tradehub_is_owner=1`) veya platform admin tenant'ın aktif Store
Subscription'ının `plan` field'ını değiştirebilir. Plan değişimi sonrası:
  1. Subscription Plan capability/quota'ları yeni planın değerlerine geçer
  2. Eski plan'da desteklenen sub-user role profile'lar yeni plan'da
     desteklenmiyorsa `apply_role_downgrade_for_plan_change` ile sub-user
     downgrade chain'i uygulanır
  3. Entitlement + permission cache flush edilir
  4. ADL'ye HIGH severity audit log yazılır (rule: auth.subscription_change)

Şu an placeholder — gerçek billing/payment akışı entegrasyonu yapılmadı; sadece
plan değişimi + role sync + audit. Trial üretiyorsa caller `start_trial=True`
ile çağırır (`status=trial`, `trial_end` plan.trial_days üzerinden).
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

from tradehub_core.audit import log_decision

_ALLOWED_TARGET_STATUS = frozenset({"active", "trial"})


def _resolve_tenant_for_caller() -> str:
	"""Caller'ın yönetebileceği tenant'ı çöz.

	Platform admin (System Manager / Marketplace Admin) → tenant parametresi
	zorunlu (aksi durumda hangi store'u yöneteceğini bilmez).
	Seller Owner → User.tradehub_tenant'tan otomatik resolve.
	Diğer → PermissionError.
	"""
	user = frappe.session.user
	if user in ("Guest", ""):
		frappe.throw(_("Yetki gerekli."), frappe.PermissionError)

	roles = set(frappe.get_roles(user))
	if {"System Manager", "Marketplace Admin"} & roles:
		return ""  # Caller tenant parametresini geçirmeli

	user_data = frappe.db.get_value("User", user, ["tradehub_tenant", "tradehub_is_owner"], as_dict=True)
	if not user_data or not user_data.tradehub_is_owner:
		frappe.throw(
			_("Sadece mağaza sahibi veya platform admin plan değiştirebilir."),
			frappe.PermissionError,
		)
	tenant = user_data.tradehub_tenant
	if not tenant:
		frappe.throw(_("Mağaza bulunamadı."), frappe.PermissionError)
	return tenant


@frappe.whitelist(methods=["POST"])
def upgrade_subscription_plan(
	new_plan: str,
	tenant: str | None = None,
	start_trial: bool | int | str = False,
	reason: str = "",
) -> dict[str, Any]:
	"""Self-service plan değişimi (upgrade/downgrade/trial başlatma).

	Args:
	    new_plan: Subscription Plan.name (örn. "PRO", "ENTERPRISE")
	    tenant: Platform admin için zorunlu (Admin Seller Profile.name). Owner
	        çağırıyorsa otomatik resolve.
	    start_trial: True ise `status=trial`, `trial_end = now + plan.trial_days`.
	        False (default) → `status=active`, immediate billing period start.
	    reason: Audit context'e yazılır (max 200 char).

	Returns:
	    {old_plan, new_plan, role_sync, audit_id}
	"""
	caller_tenant = _resolve_tenant_for_caller()
	tenant = (tenant or caller_tenant or "").strip()
	if not tenant:
		frappe.throw(_("tenant parametresi gerekli."), frappe.ValidationError)
	if caller_tenant and caller_tenant != tenant:
		# Owner sadece kendi tenant'ı için işlem yapabilir
		frappe.throw(_("Başka mağaza için plan değiştiremezsiniz."), frappe.PermissionError)

	if not frappe.db.exists("Admin Seller Profile", tenant):
		frappe.throw(_("Mağaza bulunamadı: {0}").format(tenant))
	if not frappe.db.exists("Subscription Plan", new_plan):
		frappe.throw(_("Plan bulunamadı: {0}").format(new_plan))

	plan_doc = frappe.get_doc("Subscription Plan", new_plan)
	if not plan_doc.is_active:
		frappe.throw(
			_("'{0}' planı aktif değil; seçilemez.").format(new_plan),
			frappe.ValidationError,
		)

	start_trial_bool = str(start_trial).strip().lower() in ("1", "true", "yes")

	# Mevcut aktif/trial Store Subscription
	existing = frappe.db.get_value(
		"Store Subscription",
		{"store": tenant, "status": ["in", list(_ALLOWED_TARGET_STATUS)]},
		["name", "plan", "status"],
		as_dict=True,
	)

	old_plan = existing.plan if existing else None
	target_status = "trial" if start_trial_bool else "active"

	if existing:
		sub_doc = frappe.get_doc("Store Subscription", existing.name)
		sub_doc.plan = new_plan
		sub_doc.status = target_status
		if start_trial_bool:
			trial_days = int(plan_doc.get("trial_days") or 0)
			if trial_days > 0:
				sub_doc.trial_end = add_days(now_datetime(), trial_days)
		sub_doc.current_period_start = now_datetime()
		sub_doc.flags.ignore_permissions = True
		sub_doc.save(ignore_permissions=True)
	else:
		sub_doc = frappe.new_doc("Store Subscription")
		sub_doc.store = tenant
		sub_doc.plan = new_plan
		sub_doc.status = target_status
		sub_doc.started_at = now_datetime()
		sub_doc.current_period_start = now_datetime()
		if start_trial_bool:
			trial_days = int(plan_doc.get("trial_days") or 0)
			if trial_days > 0:
				sub_doc.trial_end = add_days(now_datetime(), trial_days)
		sub_doc.flags.ignore_permissions = True
		sub_doc.insert(ignore_permissions=True)

	# Plan değiştiyse sub-user role profile downgrade chain'ini çalıştır
	role_sync: dict[str, Any] = {"downgraded": [], "deactivated": [], "unchanged": []}
	if old_plan and old_plan != new_plan:
		try:
			from tradehub_core.services.subscription_downgrade import (
				apply_role_downgrade_for_plan_change,
			)

			role_sync = apply_role_downgrade_for_plan_change(tenant, new_plan)
		except Exception as exc:
			frappe.log_error(
				f"plan upgrade role sync failed: tenant={tenant} plan={new_plan}: {exc}",
				"subscription.upgrade",
			)

	# Cache flush — entitlement layer
	try:
		frappe.cache().delete_keys("tradehub:entitlement:")
		frappe.cache().delete_keys("tradehub:pricing:public")
	except Exception:
		frappe.log_error("cache flush failed in upgrade", "subscription.upgrade")

	frappe.db.commit()

	# Audit — HIGH severity (subscription change is owner-only capability)
	log_decision(
		action="subscription.upgrade",
		decision="ALLOW",
		rule_id="auth.subscription_change",
		layer="L0",
		object_doctype="Store Subscription",
		object_name=sub_doc.name,
		tenant=tenant,
		plan_code=new_plan,
		severity="HIGH",
		context={
			"old_plan": old_plan,
			"new_plan": new_plan,
			"status": target_status,
			"started_trial": start_trial_bool,
			"reason": (reason or "")[:200],
			"role_sync_summary": {
				"downgraded": len(role_sync.get("downgraded", [])),
				"deactivated": len(role_sync.get("deactivated", [])),
				"unchanged": len(role_sync.get("unchanged", [])),
			},
		},
	)

	return {
		"old_plan": old_plan,
		"new_plan": new_plan,
		"status": target_status,
		"subscription": sub_doc.name,
		"role_sync": role_sync,
	}
