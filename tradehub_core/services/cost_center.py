"""FAZ 3.3 — Cost Center bütçe servisi.

Alıcı şirketin departmanal harcama izleme ve onay gating'i:

  - get_tree(tenant) → cost center ağacı
  - get_monthly_spend(cost_center, year, month) → toplam onaylı/teslim edilmiş order
  - validate_budget(cost_center, amount) → ok | over_budget
  - validate_order_cost_center(order_doc) → Order.before_insert hook

Karar matrisi:
  - Order'da cost_center yok ve tenant'ın aktif cost center'ı var → DENY (no_cost_center)
  - cost_center kapalı (is_active=0) → DENY (inactive_cost_center)
  - cost_center'ın aylık bütçesi var ve aşıldı → DENY (over_budget) severity=HIGH
  - Diğer → ALLOW
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import frappe
from frappe import _

BYPASS_ROLES = frozenset({"System Manager", "Administrator", "Compliance Officer"})


@dataclass
class BudgetDecision:
	decision: str  # ALLOW | DENY
	reason: str = ""
	cost_center: str | None = None
	current_spend: float = 0.0
	budget: float = 0.0
	remaining: float = 0.0


def get_tree(tenant: str | None = None) -> list[dict]:
	"""Return active cost centers as flat list with parent links.

	tenant=None → tüm tenant'lar (Super Admin için).
	UI bunu tree'ye dönüştürür (nested set lft/rgt verisini de döner).
	"""
	filters: dict = {"is_active": 1}
	if tenant:
		filters["tenant"] = tenant
	rows = frappe.get_all(
		"Cost Center",
		filters=filters,
		fields=[
			"name",
			"cost_center_code",
			"cost_center_name",
			"parent_cost_center",
			"linked_organization",
			"monthly_budget",
			"currency",
			"budget_period",
			"is_group",
			"tenant",
		],
		order_by="lft",
	)
	return rows


def get_monthly_spend(cost_center: str, year: int, month: int) -> float:
	"""Sum of completed/in-progress orders for the given month."""
	from calendar import monthrange

	start = datetime(year, month, 1).date()
	last_day = monthrange(year, month)[1]
	end = datetime(year, month, last_day).date()

	# Order'lar cost_center custom field'a sahip; iptal edilenler hariç
	total = frappe.db.get_value(
		"Order",
		{
			"cost_center": cost_center,
			"order_date": ["between", [start, end]],
			"status": ["not in", ["Cancelled", "Rejected"]],
		},
		"SUM(total)",
	)
	return float(total or 0)


def validate_budget(
	cost_center: str,
	amount: float,
	at_date: datetime | None = None,
) -> BudgetDecision:
	"""Pure decision — does not audit. Use for UI preflight."""
	if not cost_center:
		return BudgetDecision(decision="ALLOW", reason="no_cost_center")

	cc = frappe.db.get_value(
		"Cost Center",
		cost_center,
		["is_active", "monthly_budget", "currency", "budget_period"],
		as_dict=True,
	)
	if not cc:
		return BudgetDecision(
			decision="DENY",
			reason=_("Cost center {0} bulunamadı").format(cost_center),
			cost_center=cost_center,
		)
	if not cc.is_active:
		return BudgetDecision(
			decision="DENY",
			reason=_("Cost center pasif: {0}").format(cost_center),
			cost_center=cost_center,
		)
	if not cc.monthly_budget or cc.monthly_budget <= 0:
		return BudgetDecision(
			decision="ALLOW",
			reason="no_budget_limit",
			cost_center=cost_center,
		)

	now = at_date or datetime.now()
	current = get_monthly_spend(cost_center, now.year, now.month)
	projected = current + float(amount or 0)
	budget = float(cc.monthly_budget)

	if projected > budget:
		return BudgetDecision(
			decision="DENY",
			reason=_("Bütçe aşıldı: mevcut {0} + yeni {1} > limit {2}").format(current, amount, budget),
			cost_center=cost_center,
			current_spend=current,
			budget=budget,
			remaining=max(0, budget - current),
		)

	return BudgetDecision(
		decision="ALLOW",
		reason="within_budget",
		cost_center=cost_center,
		current_spend=current,
		budget=budget,
		remaining=budget - projected,
	)


def validate_order_cost_center(doc, method=None) -> None:
	"""Order.before_insert hook."""
	if doc.doctype != "Order":
		return

	user = frappe.session.user
	roles = set(frappe.get_roles(user)) if user else set()
	if roles & BYPASS_ROLES:
		_audit(user, doc, "ALLOW", "bypass_role", severity="LOW")
		return

	cost_center = getattr(doc, "cost_center", None)
	tenant = _resolve_buyer_tenant(doc)

	# Tenant'ın hiç cost center'ı yok → atla (geçiş aşaması)
	has_any_cc = bool(frappe.db.get_value("Cost Center", {"tenant": tenant, "is_active": 1}, "name"))
	if not has_any_cc:
		return

	if not cost_center:
		_audit(user, doc, "DENY", "no_cost_center", severity="LOW", rule_id="procurement.no_cost_center")
		frappe.throw(
			_("Bu tenant için cost center zorunlu — order'a cost_center seçin"),
			exc=frappe.ValidationError,
		)

	amount = float(getattr(doc, "total", 0) or 0)
	decision = validate_budget(cost_center, amount)

	if decision.decision == "DENY":
		severity = "HIGH" if "Bütçe" in decision.reason else "MEDIUM"
		_audit(
			user,
			doc,
			"DENY",
			decision.reason,
			severity=severity,
			rule_id="procurement.over_budget" if severity == "HIGH" else "procurement.cost_center_invalid",
		)
		frappe.throw(decision.reason, exc=frappe.PermissionError)
	else:
		_audit(user, doc, "ALLOW", decision.reason, severity="LOW", rule_id="procurement.cost_center_ok")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_buyer_tenant(order_doc) -> str | None:
	buyer = getattr(order_doc, "buyer", None)
	if not buyer:
		return None
	# has_column guard: tradehub_buyer_tenant custom field olmayabilir; olmayan
	# kolona get_value 1054 fırlatır → atlayıp var olan kolona düş.
	for fieldname in ("tradehub_buyer_tenant", "tradehub_tenant"):
		if not frappe.db.has_column("User", fieldname):
			continue
		val = frappe.db.get_value("User", buyer, fieldname)
		if val:
			return val
	return None


def _audit(
	user: str,
	order_doc,
	decision: str,
	reason: str,
	severity: str = "LOW",
	rule_id: str = "procurement.cost_center_check",
) -> None:
	try:
		from tradehub_core.audit import log_decision

		log_decision(
			actor=user,
			action="order.create",
			object_doctype="Order",
			object_name=getattr(order_doc, "name", "*"),
			decision=decision,
			rule_id=rule_id,
			layer="L2",
			severity=severity,
			context={
				"reason": reason,
				"cost_center": getattr(order_doc, "cost_center", None),
				"amount": float(getattr(order_doc, "total", 0) or 0),
			},
		)
	except Exception as exc:
		frappe.log_error(f"cost_center audit failed: {exc}", "Cost Center")
