"""FAZ 3.2 — PII Compliance Engine.

Multi-jurisdiction PII access kontrolü:

  evaluate_pii_access(user, doctype, fieldname, target_region)
    → {decision: ALLOW|MASK|DENY, mask_strategy: ..., reason: ...}

  apply_pii_masking(doc, user) → doc'un PII alanlarını yerinde maskele
  invalidate_policy_cache(doctype, fieldname) → on_update/on_trash'tan çağrılır

Karar matrisi (her field için):
  1. PII Field Policy var mı? Yoksa → ALLOW (PII tanımı yok)
  2. is_active=0 → ALLOW
  3. has_pii_access(user, doctype, permlevel) False → DENY (permlevel insufficient)
  4. Compliance Officer / System Manager → ALLOW (bypass, audit edilir)
  5. target_region için PII Jurisdiction Rule:
        mask_strategy=block → DENY
        mask_strategy=full → MASK (full)
        cross_border_block=1 ve user.region ∉ {target_region} → DENY
        diğer → MASK (strategy ile)
  6. Eşleşen rule yoksa → ALLOW

Audit:
  Her evaluate_pii_access çağrısı Authorization Decision Log'a yazılır
  (default; `audit=False` ile kapatılabilir).

Detay: docs/yetki/faz-3/02-faz-3-2-detayli-plan.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _

from tradehub_core.utils import pii as pii_base

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DECISION_ALLOW = "ALLOW"
DECISION_MASK = "MASK"
DECISION_DENY = "DENY"

# Strategy → human-readable label (UI için)
MASK_STRATEGIES = (
	"none",
	"full",
	"last_4",
	"first_3",
	"email",
	"iban",
	"block",
)

JURISDICTIONS = ("KVKK", "GDPR", "MENA", "CIS", "OTHER")

BYPASS_ROLES = frozenset({"System Manager", "Administrator", "Compliance Officer"})

_CACHE_PREFIX = "pii_policy:"
_CACHE_TTL = 600  # 10 dk


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PIIDecision:
	"""Outcome of evaluate_pii_access."""

	decision: str  # ALLOW | MASK | DENY
	mask_strategy: str = "none"
	reason: str = ""
	policy_name: str | None = None
	matched_rule: dict[str, Any] = field(default_factory=dict)

	def to_dict(self) -> dict[str, Any]:
		return {
			"decision": self.decision,
			"mask_strategy": self.mask_strategy,
			"reason": self.reason,
			"policy_name": self.policy_name,
			"matched_rule": self.matched_rule,
		}


# ---------------------------------------------------------------------------
# Policy lookup (cached)
# ---------------------------------------------------------------------------


def get_field_policy(doctype: str, fieldname: str) -> dict[str, Any] | None:
	"""Return active PII Field Policy as dict, or None if not configured.

	Cached for 10 min; invalidated by on_update/on_trash of the policy doctype.
	"""

	cache_key = f"{_CACHE_PREFIX}{doctype}:{fieldname}"
	cached = frappe.cache.get_value(cache_key)
	if cached is not None:
		return cached if cached else None  # cached=={} represents "no policy"

	policy_name = frappe.db.get_value(
		"PII Field Policy",
		{"ref_doctype": doctype, "fieldname": fieldname, "is_active": 1},
		"name",
	)
	if not policy_name:
		frappe.cache.set_value(cache_key, {}, expires_in_sec=_CACHE_TTL)
		return None

	doc = frappe.get_doc("PII Field Policy", policy_name)

	rules: list[dict[str, Any]] = []
	for r in doc.jurisdiction_rules or []:
		rules.append(
			{
				"jurisdiction": r.jurisdiction,
				"mask_strategy": r.mask_strategy,
				"cross_border_block": bool(getattr(r, "cross_border_block", 0)),
				"require_consent": bool(getattr(r, "require_consent", 0)),
			}
		)

	policy = {
		"name": doc.name,
		"ref_doctype": doc.ref_doctype,
		"fieldname": doc.fieldname,
		"pii_category": doc.pii_category,
		"permlevel": int(doc.permlevel or 1),
		"is_active": bool(doc.is_active),
		"rules": rules,
		"description": doc.description,
		"legal_basis": doc.legal_basis,
	}
	frappe.cache.set_value(cache_key, policy, expires_in_sec=_CACHE_TTL)
	return policy


def invalidate_policy_cache(doctype: str, fieldname: str) -> None:
	frappe.cache.delete_value(f"{_CACHE_PREFIX}{doctype}:{fieldname}")


def _find_rule(policy: dict, jurisdiction: str | None) -> dict | None:
	if not jurisdiction:
		return None
	for r in policy.get("rules") or []:
		if r["jurisdiction"] == jurisdiction:
			return r
	return None


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


def evaluate_pii_access(
	user: str | None,
	doctype: str,
	fieldname: str,
	target_region: str | None = None,
	audit: bool = True,
) -> PIIDecision:
	"""Compute ALLOW/MASK/DENY for a (user, doctype, fieldname, region) tuple.

	Side effects: writes to Authorization Decision Log unless `audit=False`.
	"""

	user = user or frappe.session.user

	policy = get_field_policy(doctype, fieldname)
	if not policy:
		decision = PIIDecision(decision=DECISION_ALLOW, reason="no_policy")
		_audit(user, doctype, fieldname, target_region, decision, audit)
		return decision

	# 1. permlevel gate
	if not pii_base.has_pii_access(user, doctype, policy["permlevel"]):
		decision = PIIDecision(
			decision=DECISION_DENY,
			reason=_("Permlevel yetersiz (gerekli >= {0})").format(policy["permlevel"]),
			policy_name=policy["name"],
		)
		_audit(user, doctype, fieldname, target_region, decision, audit)
		return decision

	# 2. bypass roles
	roles = set(frappe.get_roles(user)) if user else set()
	if roles & BYPASS_ROLES:
		decision = PIIDecision(
			decision=DECISION_ALLOW,
			reason="bypass_role",
			policy_name=policy["name"],
		)
		_audit(user, doctype, fieldname, target_region, decision, audit)
		return decision

	# 3. jurisdiction rule
	jurisdiction = pii_base.get_jurisdiction_for_region(target_region) if target_region else None
	rule = _find_rule(policy, jurisdiction)

	if not rule:
		# No rule for this jurisdiction → policy active but no constraint → ALLOW
		decision = PIIDecision(
			decision=DECISION_ALLOW,
			reason=f"no_rule_for_jurisdiction:{jurisdiction or 'unknown'}",
			policy_name=policy["name"],
		)
		_audit(user, doctype, fieldname, target_region, decision, audit)
		return decision

	# 3a. cross-border block
	if rule.get("cross_border_block"):
		user_regions = _user_regions(user)
		if target_region and target_region not in user_regions:
			decision = PIIDecision(
				decision=DECISION_DENY,
				reason=_("Cross-border erişim engelli (target={0}, user_regions={1})").format(
					target_region, list(user_regions)
				),
				policy_name=policy["name"],
				matched_rule=rule,
			)
			_audit(user, doctype, fieldname, target_region, decision, audit)
			return decision

	# 3b. mask strategy
	strategy = rule.get("mask_strategy") or "none"

	if strategy == "block":
		decision = PIIDecision(
			decision=DECISION_DENY,
			mask_strategy="block",
			reason=_("Jurisdiction kuralı: erişim blok ({0})").format(jurisdiction),
			policy_name=policy["name"],
			matched_rule=rule,
		)
	elif strategy == "none":
		decision = PIIDecision(
			decision=DECISION_ALLOW,
			mask_strategy="none",
			reason="open_under_jurisdiction",
			policy_name=policy["name"],
			matched_rule=rule,
		)
	else:
		decision = PIIDecision(
			decision=DECISION_MASK,
			mask_strategy=strategy,
			reason=_("Jurisdiction kuralı: {0} stratejisi").format(strategy),
			policy_name=policy["name"],
			matched_rule=rule,
		)

	_audit(user, doctype, fieldname, target_region, decision, audit)
	return decision


def apply_pii_masking(doc, user: str | None = None) -> dict[str, str]:
	"""In-place mask all PII fields on `doc` based on policies.

	Returns a map of fieldname → applied mask_strategy (for diagnostics).
	"""

	user = user or frappe.session.user
	if not user or user == "Guest":
		return {}

	doctype = doc.doctype if hasattr(doc, "doctype") else type(doc).__name__
	target_region = _resource_region(doc)

	applied: dict[str, str] = {}

	# All fields with a policy (not just permlevel-tagged)
	policies = frappe.get_all(
		"PII Field Policy",
		filters={"ref_doctype": doctype, "is_active": 1},
		pluck="fieldname",
	)

	for fieldname in policies:
		decision = evaluate_pii_access(
			user=user,
			doctype=doctype,
			fieldname=fieldname,
			target_region=target_region,
			audit=False,  # avoid log spam during bulk masking
		)
		if decision.decision == DECISION_MASK:
			value = getattr(doc, fieldname, None)
			if value is not None:
				setattr(doc, fieldname, pii_base.mask_value(value, _strategy_to_kind(decision.mask_strategy)))
				applied[fieldname] = decision.mask_strategy
		elif decision.decision == DECISION_DENY:
			# Strip the value entirely
			setattr(doc, fieldname, None)
			applied[fieldname] = "denied"

	return applied


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_regions(user: str) -> set[str]:
	rows = (
		frappe.get_all(
			"Subscription Plan Region",
			filters={"parent": user, "parenttype": "User"},
			pluck="region",
		)
		or []
	)
	return set(rows)


def _resource_region(doc) -> str | None:
	for fieldname in ("region", "target_region", "buyer_region", "customer_region"):
		val = getattr(doc, fieldname, None)
		if val:
			return val
	return None


def _strategy_to_kind(strategy: str) -> str:
	"""Map our jurisdiction strategy to pii_base.mask_value kind."""
	mapping = {
		"last_4": "tax_id",  # last_4 maskeleme
		"first_3": "identity",
		"email": "email",
		"iban": "iban",
		"full": "generic",
	}
	return mapping.get(strategy, "generic")


def _audit(
	user: str,
	doctype: str,
	fieldname: str,
	target_region: str | None,
	decision: PIIDecision,
	enabled: bool,
) -> None:
	"""Best-effort audit. Failures must NOT crash PII evaluation."""
	if not enabled:
		return

	severity_map = {DECISION_ALLOW: "LOW", DECISION_MASK: "LOW", DECISION_DENY: "MEDIUM"}
	rule_id_map = {
		DECISION_ALLOW: "pii.access.allow",
		DECISION_MASK: "pii.access.mask",
		DECISION_DENY: "pii.access.deny",
	}

	try:
		from tradehub_core.audit import log_decision

		log_decision(
			actor=user,
			action="pii.read",
			resource_type=doctype,
			resource_name=fieldname,
			decision=decision.decision,
			rule_id=rule_id_map[decision.decision],
			severity=severity_map[decision.decision],
			reason=decision.reason,
			meta={
				"policy_name": decision.policy_name,
				"target_region": target_region,
				"matched_rule": decision.matched_rule,
				"mask_strategy": decision.mask_strategy,
			},
		)
	except Exception as exc:
		frappe.log_error(f"pii_compliance audit failed: {exc}", "PII Compliance")
