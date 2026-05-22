# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.2 — Compliance + PII Mask Matrix endpoint'leri.

Endpoints:
  - get_field_policies(doctype) → UI matrix için tüm PII Field Policy'leri
  - upsert_field_policy(...) → Compliance Officer / System Manager yetkili
  - delete_field_policy(name)
  - simulate_pii_access(user, doctype, fieldname, target_region) → dry-run
  - export_pii_access_report(start_date, end_date, user_filter) → GDPR Article 30

Detay: docs/yetki/faz-3/02-faz-3-2-detayli-plan.md
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from tradehub_core.utils import pii_compliance

_WRITE_ROLES = {"System Manager", "Administrator", "Compliance Officer"}


def _require_compliance_role() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if not (roles & _WRITE_ROLES):
		frappe.throw(
			_("Bu işlem için Compliance Officer veya System Manager yetkisi gerekli"),
			exc=frappe.PermissionError,
		)


@frappe.whitelist()
def get_field_policies(doctype: str | None = None) -> list[dict]:
	"""Aktif PII Field Policy'lerin listesi. doctype filtresi opsiyonel."""
	filters: dict = {"is_active": 1}
	if doctype:
		filters["ref_doctype"] = doctype

	policies = frappe.get_all(
		"PII Field Policy",
		filters=filters,
		fields=[
			"name",
			"ref_doctype",
			"fieldname",
			"pii_category",
			"permlevel",
			"is_active",
			"description",
			"legal_basis",
		],
		order_by="ref_doctype, fieldname",
	)

	for p in policies:
		rules = frappe.get_all(
			"PII Jurisdiction Rule",
			filters={"parent": p["name"], "parenttype": "PII Field Policy"},
			fields=["jurisdiction", "mask_strategy", "cross_border_block", "require_consent"],
		)
		p["jurisdiction_rules"] = rules

	return policies


@frappe.whitelist()
def upsert_field_policy(
	ref_doctype: str,
	fieldname: str,
	pii_category: str = "other",
	permlevel: int = 1,
	is_active: bool | int = 1,
	jurisdiction_rules: list | str | None = None,
	description: str = "",
	legal_basis: str = "",
) -> dict:
	"""Create or update a PII Field Policy. Idempotent on (ref_doctype, fieldname)."""
	_require_compliance_role()

	if isinstance(jurisdiction_rules, str):
		try:
			jurisdiction_rules = json.loads(jurisdiction_rules)
		except json.JSONDecodeError:
			frappe.throw(_("jurisdiction_rules geçerli JSON olmalı"), exc=frappe.ValidationError)
	jurisdiction_rules = jurisdiction_rules or []

	existing = frappe.db.get_value(
		"PII Field Policy",
		{"ref_doctype": ref_doctype, "fieldname": fieldname},
		"name",
	)

	if existing:
		doc = frappe.get_doc("PII Field Policy", existing)
	else:
		doc = frappe.new_doc("PII Field Policy")
		doc.ref_doctype = ref_doctype
		doc.fieldname = fieldname

	doc.pii_category = pii_category
	doc.permlevel = int(permlevel)
	doc.is_active = 1 if str(is_active) in {"1", "True", "true", "yes"} else 0
	doc.description = description
	doc.legal_basis = legal_basis

	# Replace child rows
	doc.set("jurisdiction_rules", [])
	for r in jurisdiction_rules:
		if not isinstance(r, dict):
			continue
		doc.append(
			"jurisdiction_rules",
			{
				"jurisdiction": r.get("jurisdiction"),
				"mask_strategy": r.get("mask_strategy", "none"),
				"cross_border_block": 1 if r.get("cross_border_block") else 0,
				"require_consent": 1 if r.get("require_consent") else 0,
			},
		)

	doc.save()
	frappe.db.commit()

	pii_compliance.invalidate_policy_cache(ref_doctype, fieldname)
	return {"ok": True, "name": doc.name, "created": not existing}


@frappe.whitelist()
def delete_field_policy(name: str) -> dict:
	_require_compliance_role()

	doctype, fieldname = (
		frappe.db.get_value("PII Field Policy", name, ["ref_doctype", "fieldname"]) or (None, None)
	)
	frappe.delete_doc("PII Field Policy", name, ignore_permissions=False)
	frappe.db.commit()

	if doctype and fieldname:
		pii_compliance.invalidate_policy_cache(doctype, fieldname)
	return {"ok": True}


@frappe.whitelist()
def simulate_pii_access(
	user: str,
	doctype: str,
	fieldname: str,
	target_region: str | None = None,
) -> dict:
	"""Dry-run evaluator — UI panelinden test edilir, audit log YAZILMAZ."""
	_require_compliance_role()
	decision = pii_compliance.evaluate_pii_access(
		user=user,
		doctype=doctype,
		fieldname=fieldname,
		target_region=target_region,
		audit=False,
	)
	return decision.to_dict()


@frappe.whitelist()
def export_pii_access_report(
	start_date: str,
	end_date: str,
	user_filter: str | None = None,
) -> list[dict]:
	"""GDPR Article 30 — Records of Processing.

	Authorization Decision Log'tan pii.* kayıtlarını çeker.
	"""
	_require_compliance_role()

	filters: dict = {
		"creation": ["between", [start_date, end_date]],
		"rule_id": ["like", "pii.%"],
	}
	if user_filter:
		filters["actor"] = user_filter

	rows = frappe.get_all(
		"Authorization Decision Log",
		filters=filters,
		fields=[
			"name",
			"creation",
			"actor",
			"action",
			"resource_type",
			"resource_name",
			"decision",
			"rule_id",
			"severity",
			"reason",
		],
		order_by="creation desc",
		limit=10000,
	)
	return rows


@frappe.whitelist()
def get_compliance_metadata() -> dict:
	"""UI helper — sabitler."""
	return {
		"mask_strategies": list(pii_compliance.MASK_STRATEGIES),
		"jurisdictions": list(pii_compliance.JURISDICTIONS),
		"pii_categories": [
			"identity",
			"financial",
			"contact",
			"health",
			"location",
			"other",
		],
	}
