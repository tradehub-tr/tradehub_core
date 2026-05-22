"""FAZ 3.1 — Authorization Simulator unit tests.

12 senaryo:

  1. L0 deny (plan eksik feature)
  2. L0 skip (resource/action eşlemesi yok)
  3. L1 deny (cross-tenant)
  4. L1 skip (global resource)
  5. L1 system manager bypass
  6. L2 frappe role deny
  7. L2 rebac tuple deny
  8. L2 rebac sidecar unavailable → degraded
  9. L2 abac deny (amount tier dışı)
 10. L3 pii permlevel insufficient
 11. Full allow (happy path)
 12. Caller authorization — System Manager dışı + tenant owner değil → PermissionError
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


_DB: dict = {}
_AUDIT_LOGS: list[dict] = []
_USER_ROLES: dict[str, list[str]] = {}
_PERM_RESULTS: dict[tuple, bool] = {}


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Administrator")
	frappe.get_roles = lambda u: _USER_ROLES.get(u, ["System Manager"])

	def db_get_value(doctype, name=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(name), str(fieldname))
		return _DB.get(key)

	def get_all(doctype, filters=None, pluck=None, fields=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB.get(key, [])

	def get_doc(doctype, name=None):
		data = _DB.get(("get_doc", doctype, name), {})
		ns = SimpleNamespace(**data)
		ns.doctype = doctype
		ns.name = name
		return ns

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		commit=lambda: None,
	)
	frappe.get_all = get_all
	frappe.get_doc = get_doc

	def has_permission(doctype, ptype="read", doc=None, user=None):
		key = (user, doctype, ptype, doc)
		return _PERM_RESULTS.get(key, True)

	frappe.has_permission = has_permission

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s

	if not hasattr(frappe, "PermissionError"):
		class PermissionError(Exception):
			pass
		frappe.PermissionError = PermissionError
	if not hasattr(frappe, "ValidationError"):
		class ValidationError(Exception):
			pass
		frappe.ValidationError = ValidationError

	def _throw(msg, exc=Exception):
		if isinstance(exc, type):
			raise exc(msg)
		raise Exception(msg)

	frappe.throw = _throw

	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None
	if not hasattr(frappe, "logger"):
		frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None)

	def _enqueue(method, queue="short", **kwargs):
		pass

	frappe.enqueue = _enqueue

	# Audit module — D7: force re-install (no `if not in sys.modules` guard).
	audit_mod = types.ModuleType("tradehub_core.audit")

	def _log_decision(**kwargs):
		_AUDIT_LOGS.append(dict(kwargs))
		return "ADL-mock"

	audit_mod.log_decision = _log_decision
	audit_mod.log_role_change = lambda **kwargs: "RCL-mock"
	sys.modules["tradehub_core.audit"] = audit_mod

	if not hasattr(frappe, "whitelist"):
		def _whitelist(*args, **kwargs):
			def _decorator(fn):
				return fn
			if args and callable(args[0]):
				return args[0]
			return _decorator
		frappe.whitelist = _whitelist

	if not hasattr(frappe, "utils") or not hasattr(frappe.utils, "now_datetime"):
		frappe.utils = types.ModuleType("frappe.utils")
		from datetime import datetime, timedelta
		frappe.utils.cint = int
		frappe.utils.flt = float
		frappe.utils.now_datetime = lambda: datetime(2026, 5, 21, 12, 0, 0)
		frappe.utils.add_days = lambda dt, days: dt + timedelta(days=days)
		frappe.utils.get_url = lambda: "https://test.local"
		sys.modules["frappe.utils"] = frappe.utils


_install_frappe_stub()


def _reset_state():
	_DB.clear()
	_AUDIT_LOGS.clear()
	_USER_ROLES.clear()
	_PERM_RESULTS.clear()
	_install_frappe_stub()


import os  # noqa: E402

os.environ.setdefault("REBAC_BASE_URL", "http://test:8080")
os.environ.setdefault("REBAC_API_KEY", "test")
os.environ.setdefault("REBAC_STORE_ID", "test-store")
os.environ.setdefault("REBAC_MODEL_ID", "test-model")


from tradehub_core.services import authorization_simulator as sim  # noqa: E402


def _setup_actor(
	user: str,
	roles: list[str],
	tenant: str | None = None,
	plan: str | None = "Pro",
	regions: list[str] | None = None,
):
	_USER_ROLES[user] = roles

	# Tenant lookup via _get_seller_profile_for_user — we patch directly
	from tradehub_core.utils import tenant as tenant_utils

	tenant_utils._get_seller_profile_for_user = lambda u=None: (
		tenant if (u or "") == user else None
	)
	tenant_utils.is_tenant_admin = lambda user=None, tenant=None: (
		user == "owner@acme.com" and tenant is not None
	)

	# Regions stored in Subscription Plan Region child rows
	_DB[
		(
			"get_all",
			"Subscription Plan Region",
			f"{{'parent': '{user}', 'parenttype': 'User'}}",
			"region",
		)
	] = regions or []

	# Entitlement core hooks — patch at the module
	from tradehub_core.entitlement import core as ent_core

	ent_core.get_plan = lambda store: (plan if store == tenant else None)
	ent_core.get_capability_flags = lambda store: {"core_commerce": True}
	ent_core.get_active_subscription = lambda store: {"status": "Active", "plan": plan}


def _setup_resource(doctype: str, name: str, **fields):
	_DB[("get_doc", doctype, name)] = fields


def _make_caller_system_manager():
	"""Default caller is System Manager (bypasses caller auth check)."""
	frappe = sys.modules["frappe"]
	frappe.session.user = "Administrator"
	_USER_ROLES["Administrator"] = ["System Manager"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class _SimBase(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_make_caller_system_manager()

		# Always-true has_feature by default; override in specific tests
		from tradehub_core.entitlement import core as ent_core

		ent_core.has_feature = lambda store, key: True

		# Default ReBAC mock: always allow
		from tradehub_core.services import rebac_client as rc

		self._rc_check = rc.check
		rc.check = lambda **kwargs: True


class L0EntitlementTests(_SimBase):
	def test_l0_deny_when_feature_missing(self):
		_setup_actor("buyer@acme.com", ["Buyer Approver L1"], tenant="ACME", plan="Starter")
		_setup_resource("Order Approval", "OA-1", total=1500, seller_profile="ACME")

		# Plan = Starter, buyer_approval_workflow NOT in features
		from tradehub_core.entitlement import core as ent_core
		ent_core.has_feature = lambda store, key: key != "buyer_approval_workflow"

		res = sim.simulate("buyer@acme.com", "approve", "Order Approval", "OA-1")

		self.assertEqual(res["decision"], "DENY")
		self.assertEqual(res["first_deny"]["layer"], sim.LAYER_L0)
		self.assertIn("buyer_approval_workflow", res["first_deny"]["check"])

	def test_l0_skip_when_no_feature_mapping(self):
		_setup_actor("u@x.com", ["System Manager"], tenant="X")
		_setup_resource("Quote", "Q-1")

		res = sim.simulate("u@x.com", "read", "Quote", "Q-1")
		l0 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L0)
		self.assertEqual(l0["result"], "SKIP")


class L1TenantTests(_SimBase):
	def test_l1_deny_cross_tenant(self):
		_setup_actor("buyer@acme.com", ["Buyer Approver L1"], tenant="ACME")
		_setup_resource("Order Approval", "OA-X", total=1500, seller_profile="GLOBEX")

		res = sim.simulate("buyer@acme.com", "approve", "Order Approval", "OA-X")
		l1 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L1)
		self.assertEqual(l1["result"], "DENY")
		self.assertEqual(res["first_deny"]["check"], "tenant.mismatch")

	def test_l1_skip_for_global_resource(self):
		_setup_actor("u@x.com", ["Buyer Requisitioner"], tenant="X")
		_setup_resource("Order Approval", "OA-G")  # no tenant fields

		res = sim.simulate("u@x.com", "approve", "Order Approval", "OA-G")
		l1 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L1)
		self.assertEqual(l1["result"], "SKIP")

	def test_l1_system_manager_bypass(self):
		_setup_actor("admin@x.com", ["System Manager"], tenant="X")
		_setup_resource("Order Approval", "OA-Y", total=1500, seller_profile="OTHER")

		res = sim.simulate("admin@x.com", "approve", "Order Approval", "OA-Y")
		l1 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L1)
		self.assertEqual(l1["result"], "ALLOW")
		self.assertIn("bypass", l1["check"])


class L2FrappeRoleTests(_SimBase):
	def test_frappe_role_deny(self):
		_setup_actor("guest@acme.com", ["Guest"], tenant="ACME")
		_setup_resource("Order Approval", "OA-2", total=1500, seller_profile="ACME")

		_PERM_RESULTS[("guest@acme.com", "Order Approval", "submit", "OA-2")] = False

		res = sim.simulate("guest@acme.com", "approve", "Order Approval", "OA-2")
		l2_frappe = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L2_FRAPPE)
		self.assertEqual(l2_frappe["result"], "DENY")
		self.assertEqual(res["decision"], "DENY")


class L2ReBACTests(_SimBase):
	def test_rebac_tuple_deny(self):
		from tradehub_core.services import rebac_client as rc

		_setup_actor("buyer@acme.com", ["Buyer Approver L1"], tenant="ACME")
		_setup_resource("Order Approval", "OA-3", total=1500, seller_profile="ACME")

		rc.check = lambda **kwargs: False  # tuple yok

		res = sim.simulate("buyer@acme.com", "approve", "Order Approval", "OA-3")
		l2 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L2_REBAC)
		self.assertEqual(l2["result"], "DENY")

	def test_rebac_sidecar_unavailable(self):
		from tradehub_core.services import rebac_client as rc

		_setup_actor("buyer@acme.com", ["Buyer Approver L1"], tenant="ACME")
		_setup_resource("Order Approval", "OA-4", total=1500, seller_profile="ACME")

		def _raise(**kwargs):
			raise rc.ReBACUnavailable("circuit open")

		rc.check = _raise

		res = sim.simulate("buyer@acme.com", "approve", "Order Approval", "OA-4")
		l2 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L2_REBAC)
		self.assertEqual(l2["result"], "UNAVAILABLE")
		# DENY oluşmaz UNAVAILABLE'dan; ama sonraki layer'lar değerlendirilir
		# Decision UNAVAILABLE ≠ DENY → diğer layer'lar onayladığında ALLOW kalabilir


class L2ABACTests(_SimBase):
	def test_abac_deny_amount_out_of_tier(self):
		_setup_actor("buyer@acme.com", ["Buyer Approver L1"], tenant="ACME")
		_setup_resource("Order Approval", "OA-5", total=200, seller_profile="ACME")

		# amount=200 < 500 → needs_approval_l1 = False
		res = sim.simulate(
			"buyer@acme.com", "approve", "Order Approval", "OA-5",
			context={"amount": 200, "request_hour": 14},
		)
		l2 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L2_ABAC)
		self.assertEqual(l2["result"], "DENY")


class L3PIITests(_SimBase):
	def test_pii_permlevel_insufficient(self):
		_setup_actor("staff@acme.com", ["Buyer Requisitioner"], tenant="ACME")
		_setup_resource("Order Approval", "OA-6", total=1500, seller_profile="ACME")

		from tradehub_core.utils import pii as pii_utils

		pii_utils.get_pii_fieldnames = lambda dt, min_permlevel=1: ["tc_no", "phone"]
		pii_utils.get_user_max_permlevel = lambda u, dt: 0  # rol permlevel 0

		res = sim.simulate("staff@acme.com", "approve", "Order Approval", "OA-6")
		l3 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L3)
		self.assertEqual(l3["result"], "DENY")
		self.assertIn("permlevel", l3["check"])


class HappyPathTests(_SimBase):
	def test_full_allow(self):
		_setup_actor(
			"buyer@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["EU"],
		)
		_setup_resource(
			"Order Approval", "OA-7",
			total=1500, currency="EUR", seller_profile="ACME",
		)

		from tradehub_core.utils import pii as pii_utils

		pii_utils.get_pii_fieldnames = lambda dt, min_permlevel=1: []

		res = sim.simulate(
			"buyer@acme.com", "approve", "Order Approval", "OA-7",
			context={"amount": 1500, "request_hour": 14},
		)
		self.assertEqual(res["decision"], "ALLOW")
		self.assertIsNone(res["first_deny"])

	def test_audit_log_when_flag_true(self):
		_setup_actor("buyer@acme.com", ["Buyer Approver L1"], tenant="ACME", regions=["EU"])
		_setup_resource("Order Approval", "OA-8", total=1500, seller_profile="ACME")

		from tradehub_core.utils import pii as pii_utils
		pii_utils.get_pii_fieldnames = lambda dt, min_permlevel=1: []

		_AUDIT_LOGS.clear()

		res = sim.simulate(
			"buyer@acme.com", "approve", "Order Approval", "OA-8",
			context={"amount": 1500, "request_hour": 14},
			audit=True,
		)
		self.assertEqual(res["decision"], "ALLOW")
		self.assertEqual(len(_AUDIT_LOGS), 1)
		self.assertEqual(_AUDIT_LOGS[0]["rule_id"], "simulator.dry_run")


class CallerAuthorizationTests(_SimBase):
	def test_non_admin_non_owner_blocked(self):
		frappe = sys.modules["frappe"]
		frappe.session.user = "random@x.com"
		_USER_ROLES["random@x.com"] = ["Buyer Requisitioner"]

		_setup_actor("target@y.com", ["Buyer Approver L1"], tenant="Y")
		_setup_resource("Order Approval", "OA-9", total=1500, seller_profile="Y")

		with self.assertRaises(frappe.PermissionError):
			sim.simulate("target@y.com", "approve", "Order Approval", "OA-9")

	def test_tenant_owner_can_simulate_own_tenant(self):
		frappe = sys.modules["frappe"]
		frappe.session.user = "owner@acme.com"
		_USER_ROLES["owner@acme.com"] = ["Tenant Admin"]

		_setup_actor("target@acme.com", ["Buyer Approver L1"], tenant="ACME", regions=["EU"])
		_setup_resource("Order Approval", "OA-10", total=1500, seller_profile="ACME")

		from tradehub_core.utils import pii as pii_utils
		pii_utils.get_pii_fieldnames = lambda dt, min_permlevel=1: []

		# Should succeed without PermissionError
		res = sim.simulate(
			"target@acme.com", "approve", "Order Approval", "OA-10",
			context={"amount": 1500, "request_hour": 14},
		)
		self.assertEqual(res["decision"], "ALLOW")


class BatchTests(_SimBase):
	def test_batch_simulation_returns_list(self):
		_setup_actor("buyer@acme.com", ["Buyer Approver L1"], tenant="ACME", regions=["EU"])
		_setup_resource("Order Approval", "OA-A", total=1500, seller_profile="ACME")
		_setup_resource("Order Approval", "OA-B", total=200, seller_profile="ACME")

		from tradehub_core.utils import pii as pii_utils
		pii_utils.get_pii_fieldnames = lambda dt, min_permlevel=1: []

		results = sim.simulate_batch(
			"buyer@acme.com", "approve", "Order Approval", ["OA-A", "OA-B"],
			context={"request_hour": 14},
		)
		self.assertEqual(len(results), 2)
		# OA-A amount 1500 → ALLOW, OA-B amount 200 → DENY (abac)
		decisions = [r["decision"] for r in results]
		self.assertIn("ALLOW", decisions)
		self.assertIn("DENY", decisions)

	def test_batch_limit_enforced(self):
		_setup_actor("buyer@acme.com", ["Buyer Approver L1"], tenant="ACME")
		with self.assertRaises(Exception):
			sim.simulate_batch(
				"buyer@acme.com", "approve", "Order Approval",
				[f"OA-{i}" for i in range(sim.MAX_BATCH_SIZE + 1)],
			)


if __name__ == "__main__":
	unittest.main()
