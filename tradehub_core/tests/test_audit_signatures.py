"""HOTFIX regression — audit fonksiyon imzalarının gerçek log_decision ve
log_role_change imzalarıyla uyumlu olduğunu doğrular.

Önceki test'lerdeki mock'lar `**kw` kabul ediyordu, bu yüzden imza
uyumsuzluğu (resource_type, reason, meta gibi yanlış kwarg'lar) sessizce
geçiyordu. Production'da TypeError fırlıyor ve audit kaydı oluşmuyordu.

Bu test gerçek `log_decision` ve `log_role_change` signature'larını taklit
eden katı kwargs kontrolüyle servislerin çağrılarını doğrular.
"""

from __future__ import annotations

import inspect
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_DECISION_CALLS: list[dict] = []
_ROLE_CHANGE_CALLS: list[dict] = []
_OVERRIDE_CALLS: list[dict] = []


# Gerçek log_decision imzasının kabul ettiği kwargs (audit/log.py)
_ALLOWED_DECISION_KWARGS = {
	"actor", "action", "decision", "rule_id", "layer",
	"object_doctype", "object_name", "tenant", "region", "plan_code",
	"severity", "context", "actor_role", "request_id", "ip_address", "user_agent",
}

_ALLOWED_ROLE_CHANGE_KWARGS = {
	"target_user", "change_type", "changed_by", "tenant",
	"before_roles", "after_roles", "before_role_profiles", "after_role_profiles",
	"reason", "is_temporary", "auto_revert_at",
}

_ALLOWED_OVERRIDE_KWARGS = {
	"target_object", "override_action", "justification",
	"admin_user", "original_decision", "final_decision", "severity", "approved_by",
}


def _strict_log_decision(**kwargs) -> str:
	if "action" not in kwargs:
		raise TypeError("log_decision: 'action' required")
	if "decision" not in kwargs:
		raise TypeError("log_decision: 'decision' required")
	extra = set(kwargs) - _ALLOWED_DECISION_KWARGS
	if extra:
		raise TypeError(f"log_decision unexpected kwargs: {extra}")
	_DECISION_CALLS.append(dict(kwargs))
	return "ADL-MOCK"


def _strict_log_role_change(**kwargs) -> str:
	if "target_user" not in kwargs:
		raise TypeError("log_role_change: 'target_user' required")
	if "change_type" not in kwargs:
		raise TypeError("log_role_change: 'change_type' required")
	extra = set(kwargs) - _ALLOWED_ROLE_CHANGE_KWARGS
	if extra:
		raise TypeError(f"log_role_change unexpected kwargs: {extra}")
	_ROLE_CHANGE_CALLS.append(dict(kwargs))
	return "RCL-MOCK"


def _strict_log_override(**kwargs) -> str:
	if "target_object" not in kwargs:
		raise TypeError("log_override: 'target_object' required")
	if "justification" not in kwargs or not kwargs["justification"].strip():
		raise ValueError("log_override: justification required")
	extra = set(kwargs) - _ALLOWED_OVERRIDE_KWARGS
	if extra:
		raise TypeError(f"log_override unexpected kwargs: {extra}")
	_OVERRIDE_CALLS.append(dict(kwargs))
	return "POL-MOCK"


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe") or types.ModuleType("frappe")
	sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="admin@x.com")
	frappe.get_roles = lambda u: ["System Manager"]
	frappe.db = SimpleNamespace(
		get_value=lambda *a, **kw: None,
		exists=lambda *a, **kw: True,
		set_value=lambda *a, **kw: None,
		commit=lambda: None,
		has_column=lambda *a, **kw: True,
	)
	frappe.get_all = lambda *a, **kw: []
	frappe.get_doc = lambda *a, **kw: SimpleNamespace(name="DOC", doctype="X")
	frappe.new_doc = lambda dt: SimpleNamespace(doctype=dt, save=lambda *a, **kw: None, insert=lambda *a, **kw: None)
	frappe.throw = lambda msg, exc=Exception: (_ for _ in ()).throw(exc(msg) if isinstance(exc, type) else Exception(msg))
	frappe.log_error = lambda *a, **kw: None
	frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None)
	frappe._ = lambda s: s
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.ValidationError = type("ValidationError", (Exception,), {})

	# frappe.utils alt-modülü (delegation_service ve diğerleri import ediyor)
	from datetime import datetime, timedelta

	utils_mod = types.ModuleType("frappe.utils")
	utils_mod.now_datetime = lambda: datetime(2026, 5, 21, 14, 0, 0)
	utils_mod.add_days = lambda dt, days: dt + timedelta(days=days)
	utils_mod.cint = int
	utils_mod.flt = float
	utils_mod.get_url = lambda: "https://test.local"
	frappe.utils = utils_mod
	sys.modules["frappe.utils"] = utils_mod

	# Strict audit stubs — yanlış kwarg verirsen TypeError
	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.log_decision = _strict_log_decision
	audit_mod.log_role_change = _strict_log_role_change
	audit_mod.log_override = _strict_log_override
	sys.modules["tradehub_core.audit"] = audit_mod


_install_frappe_stub()


def _reset():
	_DECISION_CALLS.clear()
	_ROLE_CHANGE_CALLS.clear()
	_OVERRIDE_CALLS.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class OwnerTransferAuditTests(unittest.TestCase):
	def setUp(self):
		_reset()
		from tradehub_core.services import owner_transfer
		self.mod = owner_transfer

	def test_audit_signature_ok(self):
		"""HOTFIX-1: owner_transfer._audit gerçek log_decision imzasıyla uyumlu mu?"""
		self.mod._audit(
			action="owner_transfer.complete",
			name="OTR-1",
			decision="ALLOW",
			target="new@owner.com",
			reason="founder leaving",
			severity="HIGH",
		)
		self.assertEqual(len(_DECISION_CALLS), 1)
		call = _DECISION_CALLS[0]
		self.assertEqual(call["decision"], "ALLOW")
		self.assertEqual(call["object_doctype"], "Owner Transfer Request")
		self.assertEqual(call["object_name"], "OTR-1")
		self.assertEqual(call["rule_id"], "owner_transfer.complete")
		self.assertIn("target_user", call["context"])

	def test_log_role_change_signature_ok(self):
		"""HOTFIX-1: _log_role_change_safe target_user/change_type doğru kwarg."""
		self.mod._log_role_change_safe(
			user="new@owner.com",
			role="Seller Owner",
			operation="promote_to_owner",
			reason="otr:OTR-1",
		)
		self.assertEqual(len(_ROLE_CHANGE_CALLS), 1)
		call = _ROLE_CHANGE_CALLS[0]
		self.assertEqual(call["target_user"], "new@owner.com")
		self.assertEqual(call["change_type"], "promote_to_owner")
		self.assertEqual(call["after_roles"], ["Seller Owner"])


class DelegationAuditTests(unittest.TestCase):
	def setUp(self):
		_reset()
		from tradehub_core.services import delegation_service
		self.mod = delegation_service

	def test_audit_signature_ok(self):
		self.mod._audit(
			action="delegation.activate",
			name="RD-1",
			decision="ALLOW",
			target="vekil@acme.com",
			reason="vacation",
		)
		self.assertEqual(len(_DECISION_CALLS), 1)
		call = _DECISION_CALLS[0]
		self.assertEqual(call["object_doctype"], "Role Delegation")
		self.assertEqual(call["rule_id"], "delegation.activate")

	def test_log_role_change_signature_ok(self):
		self.mod._log_role_change_safe(
			user="vekil@acme.com",
			role="Buyer Approver L1",
			operation="delegate_assign",
			reason="delegation:RD-1",
		)
		self.assertEqual(len(_ROLE_CHANGE_CALLS), 1)
		call = _ROLE_CHANGE_CALLS[0]
		self.assertEqual(call["change_type"], "delegate_assign")
		self.assertTrue(call["is_temporary"])


class AnomalyActionsAuditTests(unittest.TestCase):
	def setUp(self):
		_reset()
		from tradehub_core.services import anomaly_actions
		self.mod = anomaly_actions

	def test_log_role_change_signature_ok(self):
		self.mod._log_role_change_safe(
			user="bad@x.com",
			action="suspend",
			reason="anomaly:CROSS_TENANT_PROBE",
		)
		self.assertEqual(len(_ROLE_CHANGE_CALLS), 1)
		self.assertEqual(_ROLE_CHANGE_CALLS[0]["change_type"], "suspend")


class SimulatorAuditTests(unittest.TestCase):
	def setUp(self):
		_reset()
		from tradehub_core.services import authorization_simulator
		self.mod = authorization_simulator

	def test_write_audit_signature_ok(self):
		"""HOTFIX-1: _write_audit log_decision imzasıyla uyumlu mu?"""
		result = self.mod.SimulationResult(decision="ALLOW")
		result.actor_snapshot = {"tenant": "ACME", "plan": "Pro"}
		result.resource_snapshot = {"doctype": "Order", "name": "ORD-1"}
		result.trace = [self.mod.TraceStep(layer="L0", check="ent", result="ALLOW")]

		self.mod._write_audit(
			actor="actor@x.com",
			action="read",
			resource_type="Order",
			resource_name="ORD-1",
			result=result,
		)
		self.assertEqual(len(_DECISION_CALLS), 1)
		call = _DECISION_CALLS[0]
		self.assertEqual(call["action"], "simulate.read")
		self.assertEqual(call["object_doctype"], "Order")
		self.assertEqual(call["object_name"], "ORD-1")
		self.assertEqual(call["rule_id"], "simulator.dry_run")
		self.assertEqual(call["tenant"], "ACME")
		self.assertEqual(call["plan_code"], "Pro")
		self.assertIn("trace", call["context"])


class ApprovalWorkflowAuditTests(unittest.TestCase):
	def setUp(self):
		_reset()
		from tradehub_core.services import approval_workflow
		self.mod = approval_workflow

	def test_log_admin_override_signature_ok(self):
		"""HOTFIX-6: System Manager bypass log_override'a uygun çağrı."""
		approval = SimpleNamespace(name="OA-1")
		self.mod._log_admin_override(
			approval=approval,
			admin_user="admin@x.com",
			action="approve",
			level=1,
			reason="emergency",
		)
		self.assertEqual(len(_OVERRIDE_CALLS), 1)
		call = _OVERRIDE_CALLS[0]
		self.assertEqual(call["target_object"], "Order Approval/OA-1")
		self.assertEqual(call["override_action"], "approval.approve.admin_bypass")
		self.assertEqual(call["admin_user"], "admin@x.com")
		self.assertEqual(call["severity"], "HIGH")
		self.assertTrue(call["justification"].strip())


class OrderApprovalHooksAuditTests(unittest.TestCase):
	def setUp(self):
		_reset()
		from tradehub_core.services import order_approval_hooks
		self.mod = order_approval_hooks

	def test_admin_bypass_logged(self):
		"""HOTFIX-6: admin order create → log_override HIGH severity (impersonation)."""
		order = SimpleNamespace(name="ORD-1")
		self.mod._log_admin_bypass(
			order_doc=order,
			admin_user="admin@x.com",
			buyer="real_buyer@y.com",  # impersonation
		)
		self.assertEqual(len(_OVERRIDE_CALLS), 1)
		call = _OVERRIDE_CALLS[0]
		self.assertEqual(call["target_object"], "Order/ORD-1")
		self.assertEqual(call["severity"], "HIGH")
		self.assertIn("on behalf of buyer", call["justification"])

	def test_admin_own_purchase_low_severity(self):
		order = SimpleNamespace(name="ORD-2")
		self.mod._log_admin_bypass(
			order_doc=order,
			admin_user="admin@x.com",
			buyer="admin@x.com",  # own purchase
		)
		self.assertEqual(len(_OVERRIDE_CALLS), 1)
		self.assertEqual(_OVERRIDE_CALLS[0]["severity"], "LOW")


class SignatureCompatibilityTests(unittest.TestCase):
	"""Servislerin gerçek audit imzasıyla uyumlu olduğunu inspect.signature ile doğrular.

	Test sırası önemli: stub modüllerin önüne geçmek için audit/log.py'i
	doğrudan dosyadan import eder.
	"""

	def test_log_decision_signature(self):
		# Gerçek audit/log.py modülünü doğrudan dosyadan yükle (stub'ı atla)
		import importlib.util

		spec = importlib.util.spec_from_file_location(
			"_real_audit_log",
			str(_APP_ROOT / "tradehub_core/audit/log.py"),
		)
		mod = importlib.util.module_from_spec(spec)
		# log.py içinde frappe import var; stub frappe'imiz yeterli
		try:
			spec.loader.exec_module(mod)
		except Exception:
			self.skipTest("audit/log.py modül yüklenemedi (stub uyumsuzluğu)")
			return

		sig = inspect.signature(mod.log_decision)
		params = set(sig.parameters.keys())
		required_for_hotfixes = {
			"actor", "action", "decision", "rule_id", "layer",
			"object_doctype", "object_name", "severity", "context",
		}
		missing = required_for_hotfixes - params
		self.assertFalse(missing, f"log_decision eksik kwargs: {missing}")

		sig2 = inspect.signature(mod.log_role_change)
		params2 = set(sig2.parameters.keys())
		required2 = {"target_user", "change_type", "changed_by", "after_roles", "reason"}
		missing2 = required2 - params2
		self.assertFalse(missing2, f"log_role_change eksik kwargs: {missing2}")

		sig3 = inspect.signature(mod.log_override)
		params3 = set(sig3.parameters.keys())
		required3 = {"target_object", "override_action", "justification", "admin_user", "severity"}
		missing3 = required3 - params3
		self.assertFalse(missing3, f"log_override eksik kwargs: {missing3}")


if __name__ == "__main__":
	unittest.main()
