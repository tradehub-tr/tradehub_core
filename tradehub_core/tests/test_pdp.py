"""Faz 1 — Birleşik PDP (authz.pdp.authorize) unit testleri.

Frappe stub'lanır → gerçek Frappe/DB gerektirmez; CI authz gate'inde koşar.

Kapsam:
  - Bilinmeyen verb → fail-closed DENY (L0)
  - RBAC allow / deny / exception (fail-closed)
  - Davranış garantisi: authorize().allow == frappe.has_permission(...)
  - resource çözümü (doc / dict / tuple / str / None)
  - Karar loglama modları (deny/all/none)
  - Decision alanları (decision_id, layer, trace)
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

# ── State ──
_HASPERM: dict = {}  # (doctype, ptype, name) -> bool | Exception
_HASPERM_DEFAULT = {"value": False}
_AUDIT_CALLS: list = []
_HASPERM_CALLS: list = []


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	def has_permission(doctype, ptype="read", doc=None, user=None, **kw):
		if doc is None:
			name = None
		elif isinstance(doc, str):
			name = doc  # docname
		elif isinstance(doc, dict):
			name = doc.get("name")
		else:
			name = getattr(doc, "name", None)
		_HASPERM_CALLS.append({"doctype": doctype, "ptype": ptype, "name": name, "user": user})
		key = (doctype, ptype, name)
		val = _HASPERM.get(key, _HASPERM_DEFAULT["value"])
		if isinstance(val, Exception):
			raise val
		return val

	frappe.has_permission = has_permission
	frappe.generate_hash = lambda length=12: "d" * length
	frappe.log_error = lambda *a, **kw: None
	frappe.session = SimpleNamespace(user="tester@x.com")


def _install_fake_audit() -> None:
	"""pdp._maybe_audit lazy `from tradehub_core.audit import log` yapıyor;
	sahte bir modül enjekte edip log_decision çağrılarını sayıyoruz."""
	pkg = sys.modules.get("tradehub_core.audit")
	if pkg is None:
		pkg = types.ModuleType("tradehub_core.audit")
		pkg.__path__ = []  # paket gibi davran
		sys.modules["tradehub_core.audit"] = pkg
	logmod = types.ModuleType("tradehub_core.audit.log")

	def log_decision(**kwargs):
		_AUDIT_CALLS.append(kwargs)
		return "ADL-STUB"

	logmod.log_decision = log_decision
	sys.modules["tradehub_core.audit.log"] = logmod
	pkg.log = logmod


_install_frappe_stub()
_install_fake_audit()

from tradehub_core.authz import pdp  # noqa: E402


def _reset():
	_HASPERM.clear()
	_HASPERM_DEFAULT["value"] = False
	_AUDIT_CALLS.clear()
	_HASPERM_CALLS.clear()
	_install_frappe_stub()
	_install_fake_audit()


class UnknownActionTests(unittest.TestCase):
	def setUp(self):
		_reset()

	def test_unknown_verb_denied(self):
		d = pdp.authorize("u@x", "frobnicate", "Listing")
		self.assertFalse(d.allow)
		self.assertEqual(d.reason, "unknown_action")
		self.assertEqual(d.layer, "L0.registry")

	def test_empty_action_denied(self):
		d = pdp.authorize("u@x", "", "Listing")
		self.assertFalse(d.allow)
		self.assertEqual(d.layer, "L0.registry")


class RbacLayerTests(unittest.TestCase):
	def setUp(self):
		_reset()

	def test_rbac_allow(self):
		_HASPERM[("Listing", "read", "LST-1")] = True
		d = pdp.authorize("u@x", "read", ("Listing", "LST-1"))
		self.assertTrue(d.allow)
		self.assertEqual(d.layer, "L3.rbac")
		self.assertEqual(d.reason, "rbac.allow")

	def test_rbac_deny_falls_to_default(self):
		_HASPERM[("Listing", "read", "LST-1")] = False
		d = pdp.authorize("u@x", "read", ("Listing", "LST-1"))
		self.assertFalse(d.allow)
		self.assertEqual(d.layer, "L4.default_deny")
		self.assertEqual(d.reason, "default_deny")

	def test_rbac_exception_fail_closed(self):
		_HASPERM[("Listing", "write", "LST-1")] = RuntimeError("db down")
		d = pdp.authorize("u@x", "write", ("Listing", "LST-1"))
		self.assertFalse(d.allow)  # fail-closed
		self.assertEqual(d.reason, "rbac_error")

	def test_verb_maps_to_ptype(self):
		# "edit" → ptype "write"
		_HASPERM[("Listing", "write", "LST-1")] = True
		pdp.authorize("u@x", "edit", ("Listing", "LST-1"))
		self.assertEqual(_HASPERM_CALLS[-1]["ptype"], "write")

	def test_no_doctype_fail_closed(self):
		d = pdp.authorize("u@x", "read", None)
		self.assertFalse(d.allow)
		self.assertEqual(d.reason, "no_doctype")


class BehaviorPreservationTests(unittest.TestCase):
	"""Faz 1 garantisi: L1 no-op + L2 pass-through → authorize == has_permission."""

	def setUp(self):
		_reset()

	def test_matches_has_permission_true(self):
		_HASPERM[("Order", "read", "ORD-1")] = True
		d = pdp.authorize("u@x", "read", ("Order", "ORD-1"))
		import frappe

		self.assertEqual(d.allow, frappe.has_permission("Order", "read", doc=SimpleNamespace(name="ORD-1")))

	def test_matches_has_permission_false(self):
		_HASPERM[("Order", "read", "ORD-2")] = False
		d = pdp.authorize("u@x", "read", ("Order", "ORD-2"))
		self.assertFalse(d.allow)


class ResourceResolutionTests(unittest.TestCase):
	def setUp(self):
		_reset()

	def test_doc_object(self):
		_HASPERM[("Listing", "read", "LST-9")] = True
		doc = SimpleNamespace(doctype="Listing", name="LST-9")
		d = pdp.authorize("u@x", "read", doc)
		self.assertTrue(d.allow)
		self.assertEqual(d.object_name, "LST-9")

	def test_dict_resource(self):
		_HASPERM[("Listing", "read", "LST-8")] = True
		d = pdp.authorize("u@x", "read", {"doctype": "Listing", "name": "LST-8"})
		self.assertTrue(d.allow)

	def test_str_doctype_level(self):
		_HASPERM[("Listing", "create", None)] = True
		d = pdp.authorize("u@x", "create", "Listing")
		self.assertTrue(d.allow)
		self.assertIsNone(d.object_name)


class AuditModeTests(unittest.TestCase):
	def setUp(self):
		_reset()

	def test_deny_mode_logs_only_denials(self):
		_HASPERM[("Listing", "read", "LST-1")] = True
		pdp.authorize("u@x", "read", ("Listing", "LST-1"), audit=pdp.AUDIT_DENY)
		self.assertEqual(len(_AUDIT_CALLS), 0)  # allow loglanmadı
		pdp.authorize("u@x", "read", ("Listing", "LST-2"), audit=pdp.AUDIT_DENY)  # deny
		self.assertEqual(len(_AUDIT_CALLS), 1)
		self.assertEqual(_AUDIT_CALLS[-1]["decision"], "DENY")

	def test_all_mode_logs_both(self):
		_HASPERM[("Listing", "read", "LST-1")] = True
		pdp.authorize("u@x", "read", ("Listing", "LST-1"), audit=pdp.AUDIT_ALL)
		self.assertEqual(len(_AUDIT_CALLS), 1)
		self.assertEqual(_AUDIT_CALLS[-1]["decision"], "ALLOW")

	def test_none_mode_silent(self):
		pdp.authorize("u@x", "read", ("Listing", "LST-1"), audit=pdp.AUDIT_NONE)
		self.assertEqual(len(_AUDIT_CALLS), 0)


class DecisionShapeTests(unittest.TestCase):
	def setUp(self):
		_reset()

	def test_decision_id_and_trace(self):
		_HASPERM[("Listing", "read", "LST-1")] = True
		d = pdp.authorize("u@x", "read", ("Listing", "LST-1"))
		self.assertTrue(d.decision_id)
		self.assertTrue(any(s["layer"] == "L3.rbac" for s in d.trace))
		self.assertTrue(bool(d))  # __bool__ == allow

	def test_default_principal_from_session(self):
		_HASPERM[("Listing", "read", "LST-1")] = True
		d = pdp.authorize("", "read", ("Listing", "LST-1"))
		self.assertEqual(d.actor, "tester@x.com")


class BreakGlassOverrideTests(unittest.TestCase):
	"""Faz 7 — aktif break-glass bir DENY'i ALLOW'a çevirir (L0.break_glass)."""

	def setUp(self):
		_reset()

	def test_deny_becomes_allow_when_active(self):
		_HASPERM[("Listing", "read", "LST-1")] = False  # RBAC deny
		import tradehub_core.authz.pdp as pdpmod

		orig = pdpmod.break_glass.is_active
		pdpmod.break_glass.is_active = lambda a: True
		pdpmod.break_glass.reason_for = lambda a: "incident"
		try:
			d = pdp.authorize("u@x", "read", ("Listing", "LST-1"))
			self.assertTrue(d.allow)
			self.assertEqual(d.layer, "L0.break_glass")
			self.assertEqual(d.reason, "break_glass_override")
		finally:
			pdpmod.break_glass.is_active = orig

	def test_no_override_when_inactive(self):
		_HASPERM[("Listing", "read", "LST-1")] = False
		d = pdp.authorize("u@x", "read", ("Listing", "LST-1"))
		self.assertFalse(d.allow)  # break-glass inaktif → deny kalır


class FieldLevelRegistryTests(unittest.TestCase):
	"""Faz 6 — alan-bazlı (field-level) registry çözümü."""

	def setUp(self):
		_reset()
		from tradehub_core.authz import registry

		self.reg = registry

	def test_field_action_resolves_object_and_relation(self):
		self.assertEqual(
			self.reg.field_target_for("Listing", "edit_price", "LST-9"),
			("listing_field:LST-9/PRICE", "can_edit"),
		)
		self.assertEqual(
			self.reg.field_target_for("Listing", "view_cost", "LST-9"),
			("listing_field:LST-9/COST", "can_view"),
		)

	def test_non_field_action_returns_none(self):
		self.assertIsNone(self.reg.field_target_for("Listing", "read", "LST-9"))
		self.assertIsNone(self.reg.field_target_for("Order", "approve", "ORD-1"))

	def test_field_action_needs_name(self):
		self.assertIsNone(self.reg.field_target_for("Listing", "edit_price", None))

	def test_field_verbs_map_to_ptype(self):
		self.assertEqual(self.reg.ptype_for("edit_price"), "write")
		self.assertEqual(self.reg.ptype_for("view_cost"), "read")


if __name__ == "__main__":
	unittest.main()
