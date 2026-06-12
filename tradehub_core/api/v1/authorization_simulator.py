# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.1 — Authorization Simulator whitelisted API endpoints.

Endpoints:
  - simulate(actor, action, resource_type, resource_name, context, audit)
  - simulate_batch(actor, action, resource_type, resource_names, ...)
  - get_simulator_metadata() → UI dropdown'ları için doctype/action listesi

Detay: docs/yetki/faz-3/00-faz-3-detayli-plan.md §3.1
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from tradehub_core.services import authorization_simulator as simulator

# H5 fix — simülatör keyfi actor için 4-katmanlı yetki kararlarını ifşa eden bir
# recon aracıdır; yalnız platform admin erişebilmeli.
_ADMIN_ROLES = frozenset({"System Manager", "Marketplace Admin", "Administrator"})


def _require_admin() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if not (roles & _ADMIN_ROLES):
		frappe.throw(_("Bu işlem için platform admin yetkisi gerekli"), exc=frappe.PermissionError)


@frappe.whitelist()
def simulate(
	actor: str,
	action: str,
	resource_type: str,
	resource_name: str | None = None,
	context: dict | str | None = None,
	audit: bool | int | str = False,
) -> dict:
	"""Dry-run 4-layer authorization simulation.

	`context` may arrive as JSON string from the frontend; we tolerate both.
	`audit` may arrive as "true"/"false" or 1/0.
	"""
	_require_admin()
	if not actor or not action or not resource_type:
		frappe.throw(_("actor, action ve resource_type zorunlu"), exc=frappe.ValidationError)

	ctx = _parse_context(context)
	audit_flag = _parse_bool(audit)

	return simulator.simulate(
		actor=actor,
		action=action,
		resource_type=resource_type,
		resource_name=resource_name,
		context=ctx,
		audit=audit_flag,
	)


@frappe.whitelist()
def simulate_batch(
	actor: str,
	action: str,
	resource_type: str,
	resource_names: list | str,
	context: dict | str | None = None,
	audit: bool | int | str = False,
) -> list[dict]:
	"""Batch simulation for many resources of the same type."""
	_require_admin()
	if isinstance(resource_names, str):
		try:
			resource_names = json.loads(resource_names)
		except json.JSONDecodeError:
			resource_names = [r.strip() for r in resource_names.split(",") if r.strip()]

	if not isinstance(resource_names, list):
		frappe.throw(_("resource_names liste olmalı"), exc=frappe.ValidationError)

	return simulator.simulate_batch(
		actor=actor,
		action=action,
		resource_type=resource_type,
		resource_names=resource_names,
		context=_parse_context(context),
		audit=_parse_bool(audit),
	)


@frappe.whitelist()
def get_simulator_metadata() -> dict:
	"""UI için statik metadata: desteklenen doctype + action eşlemeleri.

	`supported_doctypes` ReBAC kapsamı + PII/Frappe-only doctype'ları
	birleştirir. ReBAC kapsamında olmayan doctype'lar için L2.rebac_tuple
	SKIP olarak işaretlenir (simulator.py'da `_check_rebac_tuple` mantığı).
	"""
	rebac_doctypes = set(simulator._DOCTYPE_TO_REBAC_OBJECT.keys())  # noqa: SLF001
	# PII / Frappe-only doctype'lar — L0/L1/L3 katmanları test edilebilir
	additional = {
		"User Profile",
		"User",
		"Listing",
		"RFQ",
		"Quote",
		"Order Approval",
		"Approval Rule",
		"Cost Center",
		"Approved Supplier List",
		"PII Field Policy",
		"Authorization Anomaly Rule",
		"Role Delegation",
		"Owner Transfer Request",
	}
	return {
		"supported_doctypes": sorted(rebac_doctypes | additional),
		"supported_actions": sorted(set(simulator._ACTION_TO_PERM.keys())),  # noqa: SLF001
		"rebac_relations": {
			f"{k[0]}|{k[1]}": v
			for k, v in simulator._ACTION_TO_REBAC_RELATION.items()  # noqa: SLF001
		},
		"max_batch_size": simulator.MAX_BATCH_SIZE,
	}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_context(value) -> dict:
	if value is None or value == "":
		return {}
	if isinstance(value, dict):
		return value
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except json.JSONDecodeError:
			frappe.throw(_("context geçerli JSON olmalı"), exc=frappe.ValidationError)
		if not isinstance(parsed, dict):
			frappe.throw(_("context bir nesne olmalı"), exc=frappe.ValidationError)
		return parsed
	frappe.throw(_("context dict ya da JSON string olmalı"), exc=frappe.ValidationError)


def _parse_bool(value) -> bool:
	if isinstance(value, bool):
		return value
	if isinstance(value, int | float):
		return bool(value)
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return False
