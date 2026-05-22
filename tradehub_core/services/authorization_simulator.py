"""FAZ 3.1 — Yetki Simülatörü.

Süper Admin ve Tenant Owner'ların "X kullanıcısı Y eylemini Z kaynağa yapabilir mi?"
sorusunu canlı olarak sorabileceği 4-katmanlı dry-run servisi.

Mimari:

    L0 Entitlement   →   plan / feature / quota
    L1 Tenant         →   actor.tenant == resource.tenant
    L2 Authorization →   Frappe role + ReBAC tuple + ABAC condition
    L3 Field/PII     →   permlevel + region jurisdiction

Sonuç: ALLOW / DENY + adım adım `decision_trace`.

Default'ta hiçbir doc yazılmaz, audit log oluşturulmaz. `audit=True` ile
forensics modunda gerçek `Authorization Decision Log` üretilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _

from tradehub_core import audit as audit_mod
from tradehub_core.entitlement import core as ent_core
from tradehub_core.entitlement.core import EntitlementError
from tradehub_core.services import abac_context, rebac_client
from tradehub_core.utils import pii as pii_utils
from tradehub_core.utils import tenant as tenant_utils

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LAYER_L0 = "L0.entitlement"
LAYER_L1 = "L1.tenant"
LAYER_L2_FRAPPE = "L2.frappe_role"
LAYER_L2_REBAC = "L2.rebac_tuple"
LAYER_L2_ABAC = "L2.abac_condition"
LAYER_L3 = "L3.field_pii"

RESULT_ALLOW = "ALLOW"
RESULT_DENY = "DENY"
RESULT_SKIP = "SKIP"
RESULT_UNAVAILABLE = "UNAVAILABLE"

# Action → minimum Frappe permission mapping (heuristic)
_ACTION_TO_PERM = {
	"read": "read",
	"view": "read",
	"list": "read",
	"write": "write",
	"update": "write",
	"create": "create",
	"insert": "create",
	"delete": "delete",
	"submit": "submit",
	"cancel": "cancel",
	"approve": "submit",
	"reject": "submit",
}

# Action → ReBAC relation (model.fga ile birebir; tanımlı olmayan relation kullanılmaz)
_ACTION_TO_REBAC_RELATION = {
	("Order Approval", "approve"): "can_approve_l1",
	("Order Approval", "approve_l1"): "can_approve_l1",
	("Order Approval", "approve_l2"): "can_approve_l2",
	("Order Approval", "reject"): "can_approve_l1",
	("Order Approval", "read"): "current_approver",
	("Order", "read"): "can_view",
	("Order", "view"): "can_view",
	("Order", "approve"): "can_approve",
	("Order", "submit"): "can_approve",
	("Admin Seller Profile", "read"): "can_view",
	("Admin Seller Profile", "view"): "can_view",
	("CRM Organization", "read"): "can_view",
	("CRM Organization", "view"): "can_view",
	("CRM Organization", "create"): "can_create_order",
	("Listing", "write"): "can_edit",
	("Listing", "update"): "can_edit",
	("Listing", "read"): "can_view",
}

# Doctype → ReBAC object type (sadece model.fga'da tanımlı tipler)
_DOCTYPE_TO_REBAC_OBJECT = {
	"Order Approval": "order_approval",
	"Order": "order",
	"Admin Seller Profile": "store",
	"CRM Organization": "buyer_org",
	"Listing": "listing",
}

# Max resources per batch call
MAX_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TraceStep:
	"""A single decision step in the trace."""

	layer: str
	check: str
	result: str  # ALLOW | DENY | SKIP | UNAVAILABLE
	detail: str = ""
	meta: dict[str, Any] = field(default_factory=dict)

	def to_dict(self) -> dict[str, Any]:
		return {
			"layer": self.layer,
			"check": self.check,
			"result": self.result,
			"detail": self.detail,
			"meta": self.meta,
		}


@dataclass
class SimulationResult:
	"""Aggregated simulator output."""

	decision: str
	trace: list[TraceStep] = field(default_factory=list)
	first_deny: TraceStep | None = None
	actor_snapshot: dict[str, Any] = field(default_factory=dict)
	resource_snapshot: dict[str, Any] = field(default_factory=dict)

	def to_dict(self) -> dict[str, Any]:
		return {
			"decision": self.decision,
			"trace": [t.to_dict() for t in self.trace],
			"first_deny": self.first_deny.to_dict() if self.first_deny else None,
			"actor_snapshot": self.actor_snapshot,
			"resource_snapshot": self.resource_snapshot,
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def simulate(
	actor: str,
	action: str,
	resource_type: str,
	resource_name: str | None = None,
	context: dict[str, Any] | None = None,
	audit: bool = False,
) -> dict[str, Any]:
	"""Run the 4-layer simulation.

	Parameters
	----------
	actor : str
		User name (e.g. "staff@acme.com")
	action : str
		read | write | create | delete | submit | approve | ...
	resource_type : str
		DocType name (e.g. "Order Approval")
	resource_name : str, optional
		Specific document name; None for type-only check
	context : dict, optional
		ABAC context overrides {amount, currency, region, request_hour, ...}
	audit : bool
		If True, persist an `Authorization Decision Log` entry (rule_id=simulator.dry_run).

	Returns the result dict (see SimulationResult.to_dict).
	"""

	context = context or {}

	# Caller authorization — only System Manager or tenant owner can simulate
	_assert_caller_can_simulate(actor)

	result = SimulationResult(decision=RESULT_ALLOW)

	# Build snapshots (fast — no permission writes)
	result.actor_snapshot = _snapshot_actor(actor)
	result.resource_snapshot = _snapshot_resource(resource_type, resource_name)

	# L0 — Entitlement
	step = _check_entitlement(
		actor=actor,
		resource_type=resource_type,
		action=action,
		actor_snapshot=result.actor_snapshot,
	)
	_record(result, step)

	# L1 — Tenant isolation
	step = _check_tenant_isolation(
		actor_snapshot=result.actor_snapshot,
		resource_snapshot=result.resource_snapshot,
	)
	_record(result, step)

	# L2 — Authorization (3 sub-checks)
	step = _check_frappe_role(
		actor=actor, action=action, resource_type=resource_type, resource_name=resource_name
	)
	_record(result, step)

	step = _check_rebac_tuple(
		actor=actor,
		action=action,
		resource_type=resource_type,
		resource_name=resource_name,
		context=context,
	)
	_record(result, step)

	step = _check_abac_conditions(
		action=action,
		resource_snapshot=result.resource_snapshot,
		actor_snapshot=result.actor_snapshot,
		context=context,
	)
	_record(result, step)

	# L3 — Field/PII
	step = _check_field_pii(
		actor=actor,
		actor_snapshot=result.actor_snapshot,
		resource_type=resource_type,
		resource_name=resource_name,
		context=context,
	)
	_record(result, step)

	# Optional audit
	if audit:
		_write_audit(
			actor=actor,
			action=action,
			resource_type=resource_type,
			resource_name=resource_name,
			result=result,
		)

	return result.to_dict()


def simulate_batch(
	actor: str,
	action: str,
	resource_type: str,
	resource_names: list[str],
	context: dict[str, Any] | None = None,
	audit: bool = False,
) -> list[dict[str, Any]]:
	"""Run simulate() for multiple resources of the same type.

	Returns a list aligned with `resource_names`.
	Raises if batch exceeds MAX_BATCH_SIZE.
	"""

	if len(resource_names) > MAX_BATCH_SIZE:
		frappe.throw(
			_("Batch simülasyon limiti aşıldı (max {0})").format(MAX_BATCH_SIZE),
			exc=frappe.ValidationError,
		)

	results = []
	for name in resource_names:
		results.append(
			simulate(
				actor=actor,
				action=action,
				resource_type=resource_type,
				resource_name=name,
				context=context,
				audit=audit,
			)
		)
	return results


# ---------------------------------------------------------------------------
# Layer 0 — Entitlement
# ---------------------------------------------------------------------------


def _check_entitlement(
	actor: str,
	resource_type: str,
	action: str,
	actor_snapshot: dict[str, Any],
) -> TraceStep:
	"""Plan/feature/quota check against the actor's tenant."""

	tenant = actor_snapshot.get("tenant")
	if not tenant:
		return TraceStep(
			layer=LAYER_L0,
			check="entitlement.no_tenant",
			result=RESULT_SKIP,
			detail=_("Kullanıcı bir mağazaya (tenant) bağlı değil — entitlement atlandı"),
		)

	feature_key = _resource_action_to_feature(resource_type, action)
	if not feature_key:
		return TraceStep(
			layer=LAYER_L0,
			check="entitlement.no_feature_mapping",
			result=RESULT_SKIP,
			detail=_("{0}+{1} için feature anahtarı tanımlı değil").format(resource_type, action),
		)

	try:
		allowed = ent_core.has_feature(tenant, feature_key)
	except EntitlementError as exc:
		return TraceStep(
			layer=LAYER_L0,
			check=f"entitlement.has_feature({feature_key})",
			result=RESULT_DENY,
			detail=str(exc),
		)

	plan = actor_snapshot.get("plan")
	return TraceStep(
		layer=LAYER_L0,
		check=f"entitlement.has_feature({feature_key})",
		result=RESULT_ALLOW if allowed else RESULT_DENY,
		detail=_("Plan: {0}").format(plan or "—"),
		meta={"plan": plan, "feature": feature_key},
	)


def _resource_action_to_feature(resource_type: str, action: str) -> str | None:
	"""Heuristic mapping. Extend as plans evolve."""

	mapping = {
		("Order Approval", "approve"): "buyer_approval_workflow",
		("Order Approval", "approve_l2"): "buyer_approval_l2",
		("Order", "create"): "core_commerce",
		("RFQ", "create"): "rfq_module",
		("Buyer Sub User Invite", "create"): "buyer_team_management",
	}
	return mapping.get((resource_type, action))


# ---------------------------------------------------------------------------
# Layer 1 — Tenant isolation
# ---------------------------------------------------------------------------


def _check_tenant_isolation(
	actor_snapshot: dict[str, Any],
	resource_snapshot: dict[str, Any],
) -> TraceStep:
	"""Actor and resource must share the tenant (unless resource is global)."""

	actor_tenant = actor_snapshot.get("tenant")
	resource_tenant = resource_snapshot.get("tenant")

	if resource_tenant is None:
		return TraceStep(
			layer=LAYER_L1,
			check="tenant.global_resource",
			result=RESULT_SKIP,
			detail=_("Kaynak global (tenant-bağımsız) — izolasyon atlandı"),
		)

	if actor_tenant and actor_tenant == resource_tenant:
		return TraceStep(
			layer=LAYER_L1,
			check="tenant.match",
			result=RESULT_ALLOW,
			detail=_("Aktör ve kaynak aynı mağazada ({0})").format(actor_tenant),
			meta={"tenant": actor_tenant},
		)

	# System Manager bypass for diagnostics is intentional — gets ALLOW with note
	if "System Manager" in actor_snapshot.get("roles", []):
		return TraceStep(
			layer=LAYER_L1,
			check="tenant.system_manager_bypass",
			result=RESULT_ALLOW,
			detail=_("System Manager — tenant izolasyonu uygulanmaz"),
		)

	return TraceStep(
		layer=LAYER_L1,
		check="tenant.mismatch",
		result=RESULT_DENY,
		detail=_("Aktör {0}, kaynak {1} — farklı mağazalar").format(actor_tenant or "(yok)", resource_tenant),
		meta={"actor_tenant": actor_tenant, "resource_tenant": resource_tenant},
	)


# ---------------------------------------------------------------------------
# Layer 2 — Frappe role check
# ---------------------------------------------------------------------------


def _check_frappe_role(
	actor: str,
	action: str,
	resource_type: str,
	resource_name: str | None,
) -> TraceStep:
	"""Use Frappe's has_permission to evaluate the role-side gate."""

	ptype = _ACTION_TO_PERM.get(action.lower(), "read")

	try:
		if resource_name:
			allowed = frappe.has_permission(doctype=resource_type, ptype=ptype, doc=resource_name, user=actor)
		else:
			allowed = frappe.has_permission(doctype=resource_type, ptype=ptype, user=actor)
	except Exception as exc:
		return TraceStep(
			layer=LAYER_L2_FRAPPE,
			check=f"frappe.has_permission({ptype})",
			result=RESULT_UNAVAILABLE,
			detail=_("Frappe permission değerlendirmesi hata verdi: {0}").format(exc),
		)

	return TraceStep(
		layer=LAYER_L2_FRAPPE,
		check=f"frappe.has_permission({ptype})",
		result=RESULT_ALLOW if allowed else RESULT_DENY,
		detail=_("DocType: {0}, ptype: {1}").format(resource_type, ptype),
		meta={"ptype": ptype, "doctype": resource_type},
	)


# ---------------------------------------------------------------------------
# Layer 2 — ReBAC tuple check
# ---------------------------------------------------------------------------


def _check_rebac_tuple(
	actor: str,
	action: str,
	resource_type: str,
	resource_name: str | None,
	context: dict[str, Any],
) -> TraceStep:
	"""Translate (doctype, action) → ReBAC relation, then call OpenFGA."""

	relation = _ACTION_TO_REBAC_RELATION.get((resource_type, action.lower()))
	rebac_object_type = _DOCTYPE_TO_REBAC_OBJECT.get(resource_type)

	# O1: Reject action — Order Approval'da current_level'a göre relation seç.
	# Statik mapping reject → can_approve_l1 idi; L2 stage reject simülasyonu
	# yanlış kontrol yapıyordu (L1 condition'da amount > 5000 fail).
	if resource_type == "Order Approval" and action.lower() == "reject" and resource_name:
		try:
			current_level = frappe.db.get_value("Order Approval", resource_name, "current_level")
			if int(current_level or 1) == 2:
				relation = "can_approve_l2"
			else:
				relation = "can_approve_l1"
		except Exception:
			# Lookup hatası — varsayılan mapping ile devam
			pass

	if not relation or not rebac_object_type or not resource_name:
		return TraceStep(
			layer=LAYER_L2_REBAC,
			check="rebac.not_applicable",
			result=RESULT_SKIP,
			detail=_("Bu kaynak/eylem ReBAC kapsamında değil"),
		)

	user_obj = f"user:{actor}"
	resource_obj = f"{rebac_object_type}:{resource_name}"

	try:
		allowed = rebac_client.check(
			user=user_obj, relation=relation, object=resource_obj, context=context or None
		)
	except rebac_client.ReBACUnavailable:
		return TraceStep(
			layer=LAYER_L2_REBAC,
			check=f"rebac.{relation}@{resource_obj}",
			result=RESULT_UNAVAILABLE,
			detail=_("ReBAC sidecar erişilemez — fail-closed mod"),
		)
	except Exception as exc:
		return TraceStep(
			layer=LAYER_L2_REBAC,
			check=f"rebac.{relation}@{resource_obj}",
			result=RESULT_UNAVAILABLE,
			detail=_("ReBAC değerlendirme hatası: {0}").format(exc),
		)

	return TraceStep(
		layer=LAYER_L2_REBAC,
		check=f"rebac.{relation}@{resource_obj}",
		result=RESULT_ALLOW if allowed else RESULT_DENY,
		detail=_("İlişki: {0}, kaynak: {1}").format(relation, resource_obj),
		meta={"user": user_obj, "relation": relation, "object": resource_obj},
	)


# ---------------------------------------------------------------------------
# Layer 2 — ABAC conditions
# ---------------------------------------------------------------------------


def _check_abac_conditions(
	action: str,
	resource_snapshot: dict[str, Any],
	actor_snapshot: dict[str, Any],
	context: dict[str, Any],
) -> TraceStep:
	"""Evaluate amount/region/time conditions inline (Python-side fallback)."""

	resource_type = resource_snapshot.get("doctype")
	# O2: ABAC koşulları Order Approval **ve** Order üzerinde approve* action'ları
	# için aktif. Order üzerinde approve simülasyonunda eski versiyon SKIP edip
	# amount-tier kontrolünü atlıyordu — ReBAC simulator'da forensik kayıp.
	if resource_type not in {"Order Approval", "Order"} or action.lower() not in {
		"approve",
		"approve_l1",
		"approve_l2",
	}:
		return TraceStep(
			layer=LAYER_L2_ABAC,
			check="abac.not_applicable",
			result=RESULT_SKIP,
			detail=_("ABAC koşulları bu eylem için tanımlı değil"),
		)

	# Amount kaynağı doctype'a göre değişir:
	#   - Order Approval: `amount` field'ı tutar
	#   - Order: `total` field'ı tutar
	resource_fields = resource_snapshot.get("fields", {})
	if context.get("amount") is not None:
		amount_raw = context["amount"]
	elif resource_type == "Order Approval":
		amount_raw = resource_fields.get("amount") or resource_fields.get("total") or 0
	else:  # Order
		amount_raw = resource_fields.get("total") or resource_fields.get("amount") or 0
	amount = float(amount_raw or 0)
	current_hour = int(context.get("request_hour", abac_context.build_time_context().get("request_hour", 12)))
	user_regions = actor_snapshot.get("regions", [])
	target_region = context.get("target_region") or resource_snapshot.get("region")

	conditions = []

	# Amount tier — generic action `approve` için amount'a göre tier seç:
	#   amount > 5000 → L2 condition (CFO onayı şart)
	#   amount <= 5000 → L1 condition (200 gibi alt-eşiklerde de L1 fail =>
	#                     "onaylanmaması gereken bir order için onay simülasyonu"
	#                     DENY döner; defansif davranış)
	action_lower = action.lower()
	if action_lower == "approve":
		if amount > 5000:
			ok = abac_context.evaluate_needs_approval_l2(amount)
			conditions.append(("needs_approval_l2", ok, f"amount={amount} (>5000 — L2)"))
		else:
			ok = abac_context.evaluate_needs_approval_l1(amount)
			conditions.append(("needs_approval_l1", ok, f"amount={amount} (<=5000 — L1)"))
	elif action_lower == "approve_l1":
		ok = abac_context.evaluate_needs_approval_l1(amount)
		conditions.append(("needs_approval_l1", ok, f"amount={amount}"))
	elif action_lower == "approve_l2":
		ok = abac_context.evaluate_needs_approval_l2(amount)
		conditions.append(("needs_approval_l2", ok, f"amount={amount}"))

	# Region (only if target_region provided)
	if target_region:
		ok = abac_context.evaluate_user_in_region(user_regions, target_region)
		conditions.append(("user_in_region", ok, f"regions={user_regions}, target={target_region}"))

	# Business hours advisory — `all_pass`'a dahil edilmez (yorum uygulandı).
	# Trace'te bilgi amaçlı görünür ama overall karara dahil değildir.
	bh_ok = abac_context.evaluate_within_business_hours(current_hour, 9, 18)

	all_pass = all(ok for _, ok, _ in conditions)
	failed = [c for c, ok, _ in conditions if not ok]
	# Advisory satırı trace'in sonuna ekle (DENY üretmez)
	conditions.append(
		(
			"within_business_hours",
			bh_ok,
			f"hour={current_hour} (advisory — karara dahil değil)",
		)
	)

	return TraceStep(
		layer=LAYER_L2_ABAC,
		check="abac.conditions",
		result=RESULT_ALLOW if all_pass else RESULT_DENY,
		detail=("Tüm koşullar sağlandı" if all_pass else _("Başarısız: {0}").format(", ".join(failed))),
		meta={"conditions": [{"name": c, "passed": ok, "detail": d} for c, ok, d in conditions]},
	)


# ---------------------------------------------------------------------------
# Layer 3 — Field/PII
# ---------------------------------------------------------------------------


def _check_field_pii(
	actor: str,
	actor_snapshot: dict[str, Any],
	resource_type: str,
	resource_name: str | None,
	context: dict[str, Any],
) -> TraceStep:
	"""Check whether actor can see PII fields on this doctype."""

	pii_fields = pii_utils.get_pii_fieldnames(resource_type, min_permlevel=1)
	if not pii_fields:
		return TraceStep(
			layer=LAYER_L3,
			check="pii.not_applicable",
			result=RESULT_SKIP,
			detail=_("Bu DocType'ta korumalı PII alanı yok"),
		)

	max_lvl = pii_utils.get_user_max_permlevel(actor, resource_type)
	if max_lvl < 1:
		return TraceStep(
			layer=LAYER_L3,
			check="pii.permlevel_insufficient",
			result=RESULT_DENY,
			detail=_("Kullanıcı permlevel {0}, PII permlevel >= 1 gerekli").format(max_lvl),
			meta={"permlevel": max_lvl, "pii_fields": pii_fields},
		)

	# Region jurisdiction check (when context has target_region)
	target_region = context.get("target_region")
	if target_region and pii_utils.is_strict_jurisdiction(target_region):
		user_regions = actor_snapshot.get("regions", [])
		if target_region not in user_regions:
			return TraceStep(
				layer=LAYER_L3,
				check="pii.jurisdiction_mismatch",
				result=RESULT_DENY,
				detail=_("Kaynak {0} ({1}) jurisdiction'ında, kullanıcı bölgeleri {2}").format(
					target_region, pii_utils.get_jurisdiction_for_region(target_region), user_regions
				),
				meta={"target_region": target_region, "user_regions": user_regions},
			)

	return TraceStep(
		layer=LAYER_L3,
		check="pii.allowed",
		result=RESULT_ALLOW,
		detail=_("Permlevel {0}, PII alan sayısı: {1}").format(max_lvl, len(pii_fields)),
		meta={"permlevel": max_lvl, "pii_field_count": len(pii_fields)},
	)


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _snapshot_actor(user: str) -> dict[str, Any]:
	"""Lightweight projection of the actor — used in UI + decision logic."""

	try:
		roles = frappe.get_roles(user)
	except Exception:
		roles = []

	tenant: str | None = None
	try:
		tenant = tenant_utils._get_seller_profile_for_user(user)  # noqa: SLF001
	except Exception:
		tenant = None

	regions: list[str] = []
	try:
		region_rows = frappe.get_all(
			"Subscription Plan Region",
			filters={"parent": user, "parenttype": "User"},
			pluck="region",
		)
		regions = list(region_rows or [])
	except Exception:
		regions = []

	plan: str | None = None
	caps: dict[str, Any] = {}
	if tenant:
		try:
			plan = ent_core.get_plan(tenant)
		except Exception:
			plan = None
		try:
			caps = ent_core.get_capability_flags(tenant) or {}
		except Exception:
			caps = {}

	subscription: dict | None = None
	if tenant:
		try:
			subscription = ent_core.get_active_subscription(tenant)
		except Exception:
			subscription = None

	return {
		"user": user,
		"roles": roles,
		"tenant": tenant,
		"plan": plan,
		"regions": regions,
		"capability_flags": caps,
		"subscription_status": (subscription or {}).get("status"),
	}


def _snapshot_resource(resource_type: str, resource_name: str | None) -> dict[str, Any]:
	"""Lightweight projection of the resource — fields that decisions depend on."""

	snap: dict[str, Any] = {"doctype": resource_type, "name": resource_name}
	if not resource_name:
		return snap

	try:
		doc = frappe.get_doc(resource_type, resource_name)
	except Exception:
		return snap

	tenant = None
	for fieldname in ("seller_profile", "admin_seller", "tradehub_tenant", "tenant"):
		val = getattr(doc, fieldname, None)
		if val:
			tenant = val
			break
	snap["tenant"] = tenant

	# Common transactional fields
	for fieldname in ("total", "amount", "currency", "status", "region", "buyer", "seller"):
		val = getattr(doc, fieldname, None)
		if val is not None:
			snap.setdefault("fields", {})[fieldname] = val

	return snap


# ---------------------------------------------------------------------------
# Caller authorization
# ---------------------------------------------------------------------------


def _assert_caller_can_simulate(target_actor: str) -> None:
	"""System Manager OR Tenant Owner of target_actor's tenant."""

	caller = frappe.session.user
	roles = frappe.get_roles(caller) if caller else []

	if "System Manager" in roles or "Administrator" in roles:
		return

	# Tenant owner check: caller is owner of the tenant the target_actor belongs to
	target_tenant: str | None = None
	try:
		target_tenant = tenant_utils._get_seller_profile_for_user(target_actor)  # noqa: SLF001
	except Exception:
		target_tenant = None

	if target_tenant:
		try:
			is_admin = tenant_utils.is_tenant_admin(user=caller, tenant=target_tenant)
		except Exception:
			is_admin = False
		if is_admin:
			return

	frappe.throw(
		_("Yetki simülatörünü çağırmak için System Manager veya kendi mağazanızın Owner'ı olmalısınız"),
		exc=frappe.PermissionError,
	)


# ---------------------------------------------------------------------------
# Recording + audit
# ---------------------------------------------------------------------------


def _record(result: SimulationResult, step: TraceStep) -> None:
	"""Append a step; if DENY, capture as first_deny and flip the decision."""

	result.trace.append(step)

	if step.result == RESULT_DENY:
		if result.first_deny is None:
			result.first_deny = step
		result.decision = RESULT_DENY


def _write_audit(
	actor: str,
	action: str,
	resource_type: str,
	resource_name: str | None,
	result: SimulationResult,
) -> None:
	"""Forensics mode — persist the simulator outcome."""

	try:
		reason = result.first_deny.detail if result.first_deny else _("Tüm katmanlar onayladı")
		audit_mod.log_decision(
			actor=actor,
			action=f"simulate.{action}",
			decision=result.decision,
			rule_id="simulator.dry_run",
			layer="L2",
			object_doctype=resource_type,
			object_name=resource_name or "*",
			tenant=result.actor_snapshot.get("tenant"),
			plan_code=result.actor_snapshot.get("plan"),
			severity="LOW",
			context={
				"reason": reason,
				"trace": [t.to_dict() for t in result.trace],
				"actor_snapshot": result.actor_snapshot,
				"resource_snapshot": result.resource_snapshot,
			},
		)
	except Exception as exc:
		# Audit best-effort — never block the simulator response
		frappe.log_error(f"authorization_simulator audit write failed: {exc}", "Authorization Simulator")
