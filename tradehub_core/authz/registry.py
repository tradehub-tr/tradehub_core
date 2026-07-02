"""Yetkilendirme action registry — TEK KAYNAK (single source of truth).

PDP (`authz.pdp`) ve authorization simülatörü (`services.authorization_simulator`)
AYNI map'leri kullanmalı; aksi halde simülatör gerçek karardan sapar (#F3).
Yeni action/relation/feature buraya eklenir; iki taraf da otomatik tutarlı kalır.

Kural: bir verb `VERB_TO_PTYPE`'ta yoksa PDP fail-closed DENY verir (bilinmeyen
action = reddet).
"""

from __future__ import annotations

# Action verb → Frappe permission type (ptype). Bilinmeyen verb → DENY.
VERB_TO_PTYPE: dict[str, str] = {
	"read": "read",
	"view": "read",
	"list": "read",
	"report": "report",
	"write": "write",
	"update": "write",
	"edit": "write",
	"create": "create",
	"insert": "create",
	"delete": "delete",
	"submit": "submit",
	"cancel": "cancel",
	"amend": "amend",
	"approve": "submit",
	"reject": "submit",
	# Faz 6 — alan-bazlı (field-level) fiiller. RBAC katmanı için ptype (write/read).
	"edit_price": "write",
	"edit_description": "write",
	"edit_cost": "write",
	"view_cost": "read",
}

# Faz 6 — Alan-bazlı izin (Airbnb type:id:part). (Doctype, verb) → (PART, relation).
# Object listing_field:<name>:<PART> olarak kurulur (bkz. field_target_for).
FIELD_ACTIONS: dict[tuple[str, str], tuple[str, str]] = {
	("Listing", "edit_price"): ("PRICE", "can_edit"),
	("Listing", "edit_description"): ("DESCRIPTION", "can_edit"),
	("Listing", "edit_cost"): ("COST", "can_edit"),
	("Listing", "view_cost"): ("COST", "can_view"),
}
_FIELD_OBJECT_TYPE: dict[str, str] = {"Listing": "listing_field"}


def field_target_for(doctype: str, verb: str, name: str | None) -> tuple[str, str] | None:
	"""Alan-bazlı action ise (object_str, relation) döner; değilse None.

	Örn. ("Listing", "edit_price", "LST-9") → ("listing_field:LST-9:PRICE", "can_edit").
	"""
	spec = FIELD_ACTIONS.get((doctype, (verb or "").lower()))
	if not spec or not name:
		return None
	ftype = _FIELD_OBJECT_TYPE.get(doctype)
	if not ftype:
		return None
	part, relation = spec
	# Ayraç '/': OpenFGA object formatı 'type:id'; id içinde ':' GEÇERSİZ, '/' geçerli.
	return (f"{ftype}:{name}/{part}", relation)

# (Doctype, verb) → ReBAC relation (model.fga ile birebir; tanımsız relation kullanılmaz).
ACTION_TO_REBAC_RELATION: dict[tuple[str, str], str] = {
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

# Doctype → ReBAC object type (sadece model.fga'da tanımlı tipler).
DOCTYPE_TO_REBAC_OBJECT: dict[str, str] = {
	"Order Approval": "order_approval",
	"Order": "order",
	"Admin Seller Profile": "store",
	"CRM Organization": "buyer_org",
	"Listing": "listing",
}

# (Doctype, verb) → guardrail feature key (plan/abonelik kapısı — Faz 2).
ACTION_TO_FEATURE: dict[tuple[str, str], str] = {
	("Order Approval", "approve"): "buyer_approval_workflow",
	("Order Approval", "approve_l2"): "buyer_approval_l2",
	("Order", "create"): "core_commerce",
	("RFQ", "create"): "rfq_module",
	("Buyer Sub User Invite", "create"): "buyer_team_management",
}


def ptype_for(verb: str) -> str | None:
	"""Verb → ptype; bilinmiyorsa None (çağıran fail-closed DENY vermeli)."""
	return VERB_TO_PTYPE.get(verb.lower())


def rebac_relation_for(doctype: str, verb: str) -> str | None:
	return ACTION_TO_REBAC_RELATION.get((doctype, verb.lower()))


def rebac_object_for(doctype: str) -> str | None:
	return DOCTYPE_TO_REBAC_OBJECT.get(doctype)


def feature_for(doctype: str, verb: str) -> str | None:
	return ACTION_TO_FEATURE.get((doctype, verb.lower()))
