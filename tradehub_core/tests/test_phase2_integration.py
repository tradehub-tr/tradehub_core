"""FAZ 2.7 — Phase 2 cross-cutting integration tests.

Faz 2'nin tüm bileşenlerinin birbirine bağlandığı senaryolar:

  1. ReBAC client + tuple sync + audit log chain
  2. Organization hierarchy → buyer org tuple sync
  3. Approval workflow + ABAC condition tuple
  4. PII access + region context entegrasyonu
  5. Circuit breaker + fail-closed davranış
  6. Plan-rol kelepçesi + B2B alıcı kombinasyonu

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_phase2_integration
"""

from __future__ import annotations

import json
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_DB: dict = {}
_ENQUEUED: list = []
_AUDIT_LOGS: list[dict] = []


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Administrator")
	frappe.get_roles = lambda u: _DB.get(("roles", u), ["System Manager"])

	def db_get_value(doctype, name=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(name), str(fieldname))
		return _DB.get(key)

	def get_all(doctype, filters=None, pluck=None, fields=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB.get(key, [])

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		commit=lambda: None,
	)
	frappe.get_all = get_all
	frappe.get_doc = lambda *a, **kw: SimpleNamespace()

	def _enqueue(method, queue="short", **kwargs):
		_ENQUEUED.append({"method": method, **kwargs})

	frappe.enqueue = _enqueue

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class PermissionError(Exception):
			pass

		frappe.PermissionError = PermissionError
	if not hasattr(frappe, "throw"):

		def _throw(msg, exc=Exception):
			raise (exc(msg) if isinstance(exc, type) else Exception(msg))

		frappe.throw = _throw
	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None
	if not hasattr(frappe, "logger"):
		frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None)

	# Audit log_decision — _AUDIT_LOGS'a yazar.
	# D7: Force re-install (önceki test'in stub'ı varsa override) — cross-test
	# pollution sorununu kapatır. Eski `if not in sys.modules` guard'ı testler
	# birlikte çalıştırıldığında stub'ı ilkinkine kilitliyordu.
	audit_mod = types.ModuleType("tradehub_core.audit")

	def _log_decision(**kwargs):
		_AUDIT_LOGS.append(dict(kwargs))
		return "ADL-mock"

	audit_mod.log_decision = _log_decision
	audit_mod.log_role_change = lambda **kwargs: "RCL-mock"
	sys.modules["tradehub_core.audit"] = audit_mod

	# whitelist no-op decorator
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
	_ENQUEUED.clear()
	_AUDIT_LOGS.clear()
	_install_frappe_stub()


# Env override for rebac_client
os.environ["REBAC_BASE_URL"] = "http://test:8080"
os.environ["REBAC_API_KEY"] = "test"
os.environ["REBAC_STORE_ID"] = "test-store"
os.environ["REBAC_MODEL_ID"] = "test-model"


def _mock_response(status_code=200, data=None):
	resp = MagicMock()
	resp.status_code = status_code
	resp.ok = 200 <= status_code < 300
	resp.json.return_value = data or {}
	resp.content = b"x"
	resp.text = ""
	return resp


from tradehub_core.services import (  # noqa: E402
	abac_context,
	rebac_client,
	tuple_sync,  # noqa: E402
)
from tradehub_core.utils import organization_hierarchy as oh  # noqa: E402

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class ReBACTupleSyncChainTests(unittest.TestCase):
	"""User insert → tuple_sync → rebac_client.write_tuples (mock HTTP)."""

	def setUp(self):
		_reset_state()
		rebac_client._session = None  # noqa: SLF001
		rebac_client.reset_circuit_breaker()

	def test_buyer_user_insert_triggers_correct_tuples(self):
		"""Buyer user create → buyer_org tuple'ları async write'a giden enqueue listesinde."""
		doc = SimpleNamespace(
			doctype="User",
			name="ayse@acme.com",
			tradehub_tenant=None,
			tradehub_parent_organization="acme",
		)
		doc.get = lambda f, d=None: getattr(doc, f, d)
		# K4: role_profile_name string match yerine roles list bazlı
		_DB[("roles", "ayse@acme.com")] = ["Buyer Procurement"]

		tuple_sync.on_user_insert(doc)

		# Enqueue çağrısı yapılmış olmalı
		self.assertEqual(len(_ENQUEUED), 1)
		tuples = _ENQUEUED[0]["tuples"]
		# Member + requisitioner
		self.assertIn(("user:ayse@acme.com", "member", "buyer_org:acme"), tuples)
		self.assertIn(("user:ayse@acme.com", "requisitioner", "buyer_org:acme"), tuples)

	@patch.object(rebac_client.requests.Session, "post")
	def test_seller_owner_full_relationship_chain(self, mock_post):
		"""Owner user → store/owner + store/member tuple HTTP'ye gönderilmeli."""
		mock_post.return_value = _mock_response(200, {})

		# Direct write_tuples (sync) test
		result = rebac_client.write_tuples(
			[
				("user:mehmet@x.com", "owner", "store:STORE-A"),
				("user:mehmet@x.com", "member", "store:STORE-A"),
			]
		)
		self.assertTrue(result)

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		self.assertEqual(len(body["writes"]["tuple_keys"]), 2)


class OrgHierarchyTupleSyncTests(unittest.TestCase):
	"""Organization → group hierarchy tuple sync."""

	def setUp(self):
		_reset_state()

	def test_org_with_parent_creates_group_hierarchy(self):
		doc = SimpleNamespace(
			doctype="CRM Organization",
			name="acme-istanbul",
			tradehub_parent_org="acme-root",
			tradehub_org_admin="mehmet@acme.com",
		)
		doc.get = lambda f, d=None: getattr(doc, f, d)

		tuple_sync.on_organization_insert(doc)

		self.assertEqual(len(_ENQUEUED), 1)
		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("group:acme-istanbul", "parent", "group:acme-root"), tuples)
		self.assertIn(("user:mehmet@acme.com", "admin", "buyer_org:acme-istanbul"), tuples)

	def test_org_cycle_check_blocks_invalid_save(self):
		"""validate_no_cycle: 3-cycle attempt → ValidationError."""
		_DB[("parent", "acme-c")] = "acme-b"
		_DB[("parent", "acme-b")] = "acme-a"

		# Mock get_value: parent zinciri
		original_get_value = sys.modules["frappe"].db.get_value

		def _patched_get_value(doctype, name, fieldname=None, **kw):
			if doctype == "CRM Organization" and fieldname == "tradehub_parent_org":
				return _DB.get(("parent", name))
			return original_get_value(doctype, name, fieldname, **kw)

		sys.modules["frappe"].db.get_value = _patched_get_value

		doc = SimpleNamespace(name="acme-a", tradehub_parent_org="acme-c")
		doc.get = lambda f, d=None: getattr(doc, f, d)

		with self.assertRaises(Exception) as ctx:
			oh.validate_no_cycle(doc)
		self.assertIn("döngü", str(ctx.exception))


class ConditionalTupleABACChainTests(unittest.TestCase):
	"""Approval tuple ABAC condition'ı ile yazılıyor."""

	def setUp(self):
		_reset_state()
		rebac_client._session = None  # noqa: SLF001
		rebac_client.reset_circuit_breaker()

	@patch.object(rebac_client.requests.Session, "post")
	def test_approval_tuples_with_l1_l2_conditions(self, mock_post):
		"""L1/L2 approver tuple'ları condition'lı."""
		mock_post.return_value = _mock_response(200, {})

		# Approval workflow'un yazacağı tuple'lar
		tuples = [
			("order:ORD-1", "target_order", "order_approval:OA-1"),
			("user:can@acme.com", "can_approve_l1", "order_approval:OA-1", "needs_approval_l1"),
			("user:demet@acme.com", "can_approve_l2", "order_approval:OA-1", "needs_approval_l2"),
		]
		rebac_client.write_tuples(tuples)

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		tks = body["writes"]["tuple_keys"]

		# 3-tuple → no condition
		target_tuple = next(t for t in tks if t["relation"] == "target_order")
		self.assertNotIn("condition", target_tuple)

		# 4-tuple → condition name only
		l1_tuple = next(t for t in tks if t["relation"] == "can_approve_l1")
		self.assertEqual(l1_tuple["condition"], {"name": "needs_approval_l1"})

		l2_tuple = next(t for t in tks if t["relation"] == "can_approve_l2")
		self.assertEqual(l2_tuple["condition"], {"name": "needs_approval_l2"})

	@patch.object(rebac_client.requests.Session, "post")
	def test_check_passes_context_to_openfga(self, mock_post):
		"""check() ABAC context'i payload'a koyar."""
		mock_post.return_value = _mock_response(200, {"allowed": True})

		rebac_client.check(
			user="user:can@acme.com",
			relation="can_approve_l1",
			object="order_approval:OA-1",
			context={"amount": 3000, "currency": "EUR"},
		)

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		self.assertEqual(body["context"], {"amount": 3000, "currency": "EUR"})


class CircuitBreakerFailClosedTests(unittest.TestCase):
	"""Sidecar down → fail-closed davranış + HIGH severity audit log."""

	def setUp(self):
		_reset_state()
		rebac_client._session = None  # noqa: SLF001
		rebac_client.reset_circuit_breaker()

	@patch.object(rebac_client.requests.Session, "post")
	def test_sidecar_unavailable_logs_high_severity(self, mock_post):
		"""ReBACUnavailable durumunda HIGH severity log + DENY return."""
		# Circuit breaker'ı manuel olarak aç
		import time

		rebac_client._circuit_breaker._fail_count = 99  # noqa: SLF001
		rebac_client._circuit_breaker._opened_at = time.time()  # noqa: SLF001

		result = rebac_client.check(user="user:any", relation="any", object="any:thing")
		self.assertFalse(result)  # fail-closed

		# HIGH severity audit log yazılmış olmalı
		high_logs = [
			log
			for log in _AUDIT_LOGS
			if log.get("severity") == "HIGH" and log.get("rule_id") == "rebac.unavailable"
		]
		self.assertGreaterEqual(len(high_logs), 1)


class FullContextBuilderTests(unittest.TestCase):
	"""abac_context.build_full_context — order + region + time entegrasyonu."""

	def setUp(self):
		_reset_state()

	def test_full_context_for_b2b_order(self):
		"""B2B order için tam context — amount + region + jurisdiction."""
		order = SimpleNamespace(
			doctype="Order",
			name="ORD-B2B-1",
			total=7450,
			currency="EUR",
			seller_profile="STORE-A",
			buyer="demet@acme.com",
			items=[],
		)
		order.get = lambda f, d=None: getattr(order, f, d)

		# Demet'in region'ları
		_DB[
			(
				"get_all",
				"Subscription Plan Region",
				"{'parent': 'demet@acme.com', 'parenttype': 'User'}",
				"region",
			)
		] = ["EU"]
		_DB[("get_value", "Region", "EU", "None")] = None
		_DB[("get_value", "Region", "EU", "jurisdiction")] = "GDPR"

		ctx = abac_context.build_full_context(order=order, user="demet@acme.com", include_time=True)

		# Order fields
		self.assertEqual(ctx["amount"], 7450.0)
		self.assertEqual(ctx["currency"], "EUR")
		# Region fields
		self.assertIn("EU", ctx["user_regions"])
		self.assertEqual(ctx["user_jurisdiction"], "GDPR")
		# Time fields
		self.assertIn("request_hour", ctx)
		self.assertIn("start_hour", ctx)


class PythonEvaluatorFallbackTests(unittest.TestCase):
	"""Sidecar offline → Python-side evaluator UI gating için."""

	def test_l1_conditions(self):
		# 500 < amount <= 5000
		self.assertFalse(abac_context.evaluate_needs_approval_l1(500))
		self.assertTrue(abac_context.evaluate_needs_approval_l1(501))
		self.assertTrue(abac_context.evaluate_needs_approval_l1(5000))
		self.assertFalse(abac_context.evaluate_needs_approval_l1(5001))

	def test_l2_conditions(self):
		# amount > 5000
		self.assertFalse(abac_context.evaluate_needs_approval_l2(5000))
		self.assertTrue(abac_context.evaluate_needs_approval_l2(7500))

	def test_region_check(self):
		self.assertTrue(abac_context.evaluate_user_in_region(["EU", "TR"], "EU"))
		self.assertFalse(abac_context.evaluate_user_in_region(["TR"], "EU"))

	def test_business_hours(self):
		# 09:00 - 18:00
		self.assertTrue(abac_context.evaluate_within_business_hours(9, 9, 18))
		self.assertTrue(abac_context.evaluate_within_business_hours(17, 9, 18))
		self.assertFalse(abac_context.evaluate_within_business_hours(18, 9, 18))


class CompositeHierarchyABACTests(unittest.TestCase):
	"""Org hierarchy + ABAC condition birleşimi — Demet (CFO) İstanbul → Pazarlama'nın order'ını onaylar mı?"""

	def setUp(self):
		_reset_state()

	def test_hierarchy_resolution(self):
		"""3-derinlik hiyerarşi: pazarlama → istanbul → root."""
		_DB[("parent", "acme-pazarlama")] = "acme-istanbul"
		_DB[("parent", "acme-istanbul")] = "acme-root"
		_DB[("parent", "acme-root")] = None

		# Mock get_value zinciri
		original_get_value = sys.modules["frappe"].db.get_value

		def _patched(doctype, name, fieldname=None, **kw):
			if doctype == "CRM Organization" and fieldname == "tradehub_parent_org":
				return _DB.get(("parent", name))
			return original_get_value(doctype, name, fieldname, **kw)

		sys.modules["frappe"].db.get_value = _patched

		ancestors = oh.get_ancestors("acme-pazarlama")
		self.assertEqual(ancestors, ["acme-istanbul", "acme-root"])

		self.assertEqual(oh.get_depth("acme-pazarlama"), 2)
		self.assertEqual(oh.get_root("acme-pazarlama"), "acme-root")


if __name__ == "__main__":
	unittest.main()
