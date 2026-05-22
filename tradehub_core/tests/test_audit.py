"""FAZ 1.4 — Audit log helper unit testleri.

tradehub_core.audit.log içindeki:
  - log_decision (best-effort, audit_write flag)
  - log_role_change
  - log_override (justification zorunlu)
  - constants (DECISION_*, LAYER_*, SEVERITY_*)

için saf-Python testler. Frappe stub'lanır.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_audit
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_INSERTED_DOCS: list[dict] = []  # Audit'in yazdığı dummy doc'lar


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	# get_doc — bizim dummy mock document'ı döner
	class _DummyDoc:
		def __init__(self, data):
			self._data = dict(data)
			self.flags = SimpleNamespace(audit_write=False, audit_archive=False)
			self.name = None

		def insert(self, ignore_permissions=False, **kwargs):
			# audit_write flag set edilmiş olmalı (tek doğru yazma yolu)
			if not getattr(self.flags, "audit_write", False):
				raise Exception("Audit log doğrudan yazılamaz")
			self.name = f"{self._data.get('doctype', 'DOC')}-{len(_INSERTED_DOCS) + 1:06d}"
			self._data["name"] = self.name
			_INSERTED_DOCS.append(dict(self._data))
			return self

	frappe.get_doc = _DummyDoc

	# Session
	if not hasattr(frappe, "session"):
		frappe.session = SimpleNamespace(user="tester@x.com")
	else:
		frappe.session.user = "tester@x.com"

	# Roles + i18n + exceptions + log_error
	if not hasattr(frappe, "get_roles"):
		frappe.get_roles = lambda u: []
	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class PermissionError(Exception):
			pass

		frappe.PermissionError = PermissionError
	if not hasattr(frappe, "throw"):

		def _throw(msg, exc=Exception):
			raise exc(msg) if isinstance(exc, type) else Exception(msg)

		frappe.throw = _throw
	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None

	# DB minimal
	if not hasattr(frappe, "db"):
		frappe.db = SimpleNamespace(
			get_value=lambda *a, **kw: None,
			exists=lambda *a, **kw: False,
			escape=lambda s: f"'{s}'",
			count=lambda *a, **kw: 0,
			has_column=lambda *a, **kw: True,
		)

	# Utils
	if not hasattr(frappe, "utils") or not hasattr(frappe.utils, "now_datetime"):
		frappe.utils = types.ModuleType("frappe.utils")
		frappe.utils.cint = int
		frappe.utils.flt = float
		from datetime import datetime

		frappe.utils.now_datetime = lambda: datetime(2026, 5, 21, 12, 0, 0)
		frappe.utils.add_days = lambda dt, days: dt
		sys.modules["frappe.utils"] = frappe.utils


_install_frappe_stub()

from tradehub_core.audit import log as audit_log  # noqa: E402


def _reset_inserted():
	_INSERTED_DOCS.clear()
	_install_frappe_stub()


# ---------------------------------------------------------------------------
# log_decision
# ---------------------------------------------------------------------------


class LogDecisionTests(unittest.TestCase):
	def setUp(self):
		_reset_inserted()

	def test_minimal_call(self):
		"""En küçük çağrı: action + decision."""
		result = audit_log.log_decision(
			action="listing.create",
			decision=audit_log.DECISION_ALLOW,
		)
		self.assertIsNotNone(result)
		self.assertEqual(len(_INSERTED_DOCS), 1)
		doc = _INSERTED_DOCS[0]
		self.assertEqual(doc["doctype"], "Authorization Decision Log")
		self.assertEqual(doc["action"], "listing.create")
		self.assertEqual(doc["decision"], "ALLOW")

	def test_full_call(self):
		"""Tüm alanlar dolu."""
		result = audit_log.log_decision(
			actor="seller-a@x.com",
			action="order.approve",
			decision=audit_log.DECISION_DENY,
			rule_id="auth.b2b.approval_limit",
			layer=audit_log.LAYER_L2,
			object_doctype="Order",
			object_name="ORD-9382",
			tenant="STORE-A",
			region="EU",
			plan_code="pro",
			severity=audit_log.SEVERITY_HIGH,
			context={"amount": 7450, "limit": 5000},
		)
		self.assertIsNotNone(result)
		doc = _INSERTED_DOCS[0]
		self.assertEqual(doc["actor"], "seller-a@x.com")
		self.assertEqual(doc["rule_id"], "auth.b2b.approval_limit")
		self.assertEqual(doc["layer"], "L2")
		self.assertEqual(doc["severity"], "HIGH")
		# Context JSON serialize edilmiş olmalı
		ctx = json.loads(doc["context"])
		self.assertEqual(ctx["amount"], 7450)

	def test_actor_defaults_to_session_user(self):
		"""actor None ise session.user kullanılır."""
		audit_log.log_decision(action="x.y", decision="ALLOW")
		self.assertEqual(_INSERTED_DOCS[0]["actor"], "tester@x.com")

	def test_audit_write_flag_set(self):
		"""log_decision audit_write flag set ediyor mu (DocType validate'i bunu istiyor)."""
		audit_log.log_decision(action="x.y", decision="ALLOW")
		# _DummyDoc.insert audit_write True olmadan exception verir
		# Burada exception yok → flag set edildi.
		self.assertEqual(len(_INSERTED_DOCS), 1)

	def test_non_serializable_context_doesnt_break(self):
		"""Serializable olmayan context → default=str ile tolerasyon, log yazılır."""
		# object() default=str ile string'e çevrilir (audit kayıt yazımı bozulmamalı)
		audit_log.log_decision(
			action="x.y",
			decision="ALLOW",
			context={"obj": object()},
		)
		self.assertEqual(len(_INSERTED_DOCS), 1)
		# Log yazıldı; context string ya da None olabilir, kritik olan exception olmaması.


# ---------------------------------------------------------------------------
# log_role_change
# ---------------------------------------------------------------------------


class LogRoleChangeTests(unittest.TestCase):
	def setUp(self):
		_reset_inserted()

	def test_invite(self):
		audit_log.log_role_change(
			target_user="newuser@x.com",
			change_type="invite",
			after_roles=["Seller"],
			reason="onboarding",
		)
		doc = _INSERTED_DOCS[0]
		self.assertEqual(doc["doctype"], "Role Change Log")
		self.assertEqual(doc["change_type"], "invite")
		self.assertEqual(doc["target_user"], "newuser@x.com")

	def test_role_assign(self):
		audit_log.log_role_change(
			target_user="user@x.com",
			change_type="role_assign",
			before_roles=["Seller"],
			after_roles=["Seller", "Seller Finance"],
		)
		doc = _INSERTED_DOCS[0]
		self.assertEqual(doc["change_type"], "role_assign")
		self.assertIn("Seller Finance", json.loads(doc["after_roles"]))

	def test_temporary_assignment(self):
		audit_log.log_role_change(
			target_user="user@x.com",
			change_type="role_assign",
			after_roles=["Approver"],
			is_temporary=True,
			auto_revert_at="2026-06-01 00:00:00",
		)
		doc = _INSERTED_DOCS[0]
		self.assertEqual(doc["is_temporary"], 1)


# ---------------------------------------------------------------------------
# log_override
# ---------------------------------------------------------------------------


class LogOverrideTests(unittest.TestCase):
	def setUp(self):
		_reset_inserted()

	def test_minimal_call(self):
		result = audit_log.log_override(
			target_object="Order/ORD-001",
			override_action="force_approve",
			justification="Müşteri talebi üzerine acil onay.",
		)
		self.assertIsNotNone(result)
		doc = _INSERTED_DOCS[0]
		self.assertEqual(doc["doctype"], "Permission Override Log")
		self.assertEqual(doc["override_action"], "force_approve")

	def test_justification_required(self):
		"""Boş justification → ValueError."""
		with self.assertRaises(ValueError):
			audit_log.log_override(
				target_object="Order/ORD-001",
				override_action="force_approve",
				justification="",
			)

	def test_justification_whitespace_only(self):
		"""Sadece whitespace → ValueError."""
		with self.assertRaises(ValueError):
			audit_log.log_override(
				target_object="Order/ORD-001",
				override_action="force_approve",
				justification="   \n\t  ",
			)

	def test_default_decisions(self):
		"""original=DENY, final=ALLOW default."""
		audit_log.log_override(
			target_object="Order/ORD-001",
			override_action="force_approve",
			justification="Acil iş.",
		)
		doc = _INSERTED_DOCS[0]
		self.assertEqual(doc["original_decision"], "DENY")
		self.assertEqual(doc["final_decision"], "ALLOW")
		self.assertEqual(doc["severity"], "MEDIUM")  # default

	def test_critical_severity(self):
		audit_log.log_override(
			target_object="Admin Seller Profile/STORE-A",
			override_action="delete_locked",
			justification="GDPR right to erasure talebi #1234",
			severity="CRITICAL",
		)
		doc = _INSERTED_DOCS[0]
		self.assertEqual(doc["severity"], "CRITICAL")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class ConstantsTests(unittest.TestCase):
	def test_decisions(self):
		self.assertEqual(audit_log.DECISION_ALLOW, "ALLOW")
		self.assertEqual(audit_log.DECISION_DENY, "DENY")
		self.assertEqual(audit_log.DECISION_FIELD_MASKED, "FIELD_MASKED")
		self.assertEqual(audit_log.DECISION_ALLOW_PENDING, "ALLOW_PENDING")
		self.assertEqual(audit_log.DECISION_ERROR, "ERROR")

	def test_layers(self):
		self.assertEqual(audit_log.LAYER_L0, "L0")
		self.assertEqual(audit_log.LAYER_L1, "L1")
		self.assertEqual(audit_log.LAYER_L2, "L2")
		self.assertEqual(audit_log.LAYER_L3, "L3")

	def test_severities(self):
		self.assertEqual(audit_log.SEVERITY_LOW, "LOW")
		self.assertEqual(audit_log.SEVERITY_NORMAL, "NORMAL")
		self.assertEqual(audit_log.SEVERITY_HIGH, "HIGH")


# ---------------------------------------------------------------------------
# Best-effort behaviour
# ---------------------------------------------------------------------------


class BestEffortTests(unittest.TestCase):
	def setUp(self):
		_reset_inserted()

	def test_log_decision_swallows_db_error(self):
		"""DB hatası olsa bile log_decision exception fırlatmaz, None döner."""
		# get_doc'u hata fırlatacak şekilde değiştir
		frappe = sys.modules["frappe"]
		original = frappe.get_doc

		def _broken(*args, **kwargs):
			raise Exception("DB connection lost")

		frappe.get_doc = _broken
		try:
			result = audit_log.log_decision(action="x.y", decision="ALLOW")
			self.assertIsNone(result)
		finally:
			frappe.get_doc = original

	def test_log_role_change_swallows_db_error(self):
		frappe = sys.modules["frappe"]
		original = frappe.get_doc
		frappe.get_doc = lambda *a, **kw: (_ for _ in ()).throw(Exception("DB broken"))
		try:
			result = audit_log.log_role_change(target_user="x@x.com", change_type="invite")
			self.assertIsNone(result)
		finally:
			frappe.get_doc = original


if __name__ == "__main__":
	unittest.main()
