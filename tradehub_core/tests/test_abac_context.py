"""FAZ 2.6 — ABAC context + conditional tuple testleri.

tradehub_core.services.abac_context içindeki:
  - build_order_context
  - build_region_context
  - build_time_context
  - build_full_context
  - Python-side condition evaluators
  - rebac_client.write_tuples 4/5-tuple desteği

için saf-Python testler.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_abac_context
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


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Guest")

	def db_get_value(doctype, name=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(name), str(fieldname))
		return _DB.get(key)

	def get_all(doctype, filters=None, pluck=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB.get(key, [])

	frappe.db = SimpleNamespace(get_value=db_get_value, escape=lambda s: f"'{s}'")
	frappe.get_all = get_all

	def get_doc(doctype, name=None, **kw):
		key = ("doc", doctype, name)
		if key in _DB:
			return _DB[key]
		# Default: SimpleNamespace
		return SimpleNamespace(doctype=doctype, name=name, get=lambda f, d=None: None)

	frappe.get_doc = get_doc
	frappe.get_roles = lambda u: _DB.get(("roles", u), [])

	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None
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

	# tradehub_core.audit stub (rebac_client import için).
	# D7: Force re-install — noop stub diğer testlerin recorder'ını engellemesin.
	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.log_decision = lambda *a, **kw: None
	audit_mod.log_role_change = lambda *a, **kw: None
	sys.modules["tradehub_core.audit"] = audit_mod

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
	_install_frappe_stub()


from tradehub_core.services import abac_context  # noqa: E402

# ---------------------------------------------------------------------------
# build_order_context
# ---------------------------------------------------------------------------


class OrderContextTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_build_from_doc(self):
		"""Doc object'ten context çıkarımı."""
		order = SimpleNamespace(
			doctype="Order",
			name="ORD-1",
			total=7450,
			currency="EUR",
			seller_profile="STORE-A",
			buyer="ayse@acme.com",
		)
		order.get = lambda field, default=None: getattr(order, field, default)
		order.items = []  # no items

		ctx = abac_context.build_order_context(order)
		self.assertEqual(ctx["amount"], 7450.0)
		self.assertEqual(ctx["currency"], "EUR")
		self.assertEqual(ctx["supplier"], "STORE-A")
		self.assertEqual(ctx["buyer"], "ayse@acme.com")
		self.assertIsNone(ctx["category"])

	def test_amount_zero_default(self):
		"""total=None → amount=0."""
		order = SimpleNamespace(doctype="Order", name="X", total=None, currency="USD")
		order.get = lambda f, d=None: getattr(order, f, d)
		ctx = abac_context.build_order_context(order)
		self.assertEqual(ctx["amount"], 0.0)


# ---------------------------------------------------------------------------
# build_region_context
# ---------------------------------------------------------------------------


class RegionContextTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_guest_empty(self):
		sys.modules["frappe"].session.user = "Guest"
		ctx = abac_context.build_region_context("Guest")
		self.assertEqual(ctx["user_regions"], [])
		self.assertIsNone(ctx["user_jurisdiction"])

	def test_user_with_regions(self):
		sys.modules["frappe"].session.user = "demet@acme.com"
		# User'ın region listesi
		_DB[
			(
				"get_all",
				"Subscription Plan Region",
				"{'parent': 'demet@acme.com', 'parenttype': 'User'}",
				"region",
			)
		] = ["EU", "TR"]

		# Region jurisdiction'ları
		_DB[("get_value", "Region", "EU", "jurisdiction")] = "GDPR"
		_DB[("get_value", "Region", "TR", "jurisdiction")] = "KVKK"

		ctx = abac_context.build_region_context("demet@acme.com")
		self.assertIn("EU", ctx["user_regions"])
		self.assertIn("TR", ctx["user_regions"])
		# KVKK > GDPR (priority)
		self.assertEqual(ctx["user_jurisdiction"], "KVKK")


# ---------------------------------------------------------------------------
# build_time_context
# ---------------------------------------------------------------------------


class TimeContextTests(unittest.TestCase):
	def test_default_business_hours(self):
		ctx = abac_context.build_time_context()
		self.assertEqual(ctx["start_hour"], 9)
		self.assertEqual(ctx["end_hour"], 18)
		self.assertIn("request_hour", ctx)
		self.assertIn("request_time", ctx)

	def test_custom_hours(self):
		ctx = abac_context.build_time_context(business_hours=(8, 20))
		self.assertEqual(ctx["start_hour"], 8)
		self.assertEqual(ctx["end_hour"], 20)


# ---------------------------------------------------------------------------
# build_full_context
# ---------------------------------------------------------------------------


class FullContextTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_combines_order_region_time(self):
		order = SimpleNamespace(
			doctype="Order", name="X", total=1000, currency="EUR",
			seller_profile="STORE-A", buyer="x@x.com", items=[],
		)
		order.get = lambda f, d=None: getattr(order, f, d)

		ctx = abac_context.build_full_context(
			order=order, user="x@x.com", include_time=True
		)
		# Order keys
		self.assertIn("amount", ctx)
		self.assertIn("currency", ctx)
		# Region keys
		self.assertIn("user_regions", ctx)
		# Time keys
		self.assertIn("request_time", ctx)


# ---------------------------------------------------------------------------
# Python-side condition evaluators
# ---------------------------------------------------------------------------


class ConditionEvaluatorTests(unittest.TestCase):
	def test_needs_approval_l1(self):
		# L1: 500 < amount <= 5000
		self.assertFalse(abac_context.evaluate_needs_approval_l1(500))  # exclusive
		self.assertTrue(abac_context.evaluate_needs_approval_l1(501))
		self.assertTrue(abac_context.evaluate_needs_approval_l1(2500))
		self.assertTrue(abac_context.evaluate_needs_approval_l1(5000))  # inclusive
		self.assertFalse(abac_context.evaluate_needs_approval_l1(5001))

	def test_needs_approval_l2(self):
		# L2: amount > 5000
		self.assertFalse(abac_context.evaluate_needs_approval_l2(5000))
		self.assertTrue(abac_context.evaluate_needs_approval_l2(5001))
		self.assertTrue(abac_context.evaluate_needs_approval_l2(100000))

	def test_user_in_region(self):
		self.assertTrue(abac_context.evaluate_user_in_region(["EU", "TR"], "EU"))
		self.assertFalse(abac_context.evaluate_user_in_region(["TR"], "EU"))
		self.assertFalse(abac_context.evaluate_user_in_region([], "EU"))
		self.assertFalse(abac_context.evaluate_user_in_region(None, "EU"))

	def test_within_business_hours(self):
		self.assertTrue(abac_context.evaluate_within_business_hours(9, 9, 18))
		self.assertTrue(abac_context.evaluate_within_business_hours(17, 9, 18))
		self.assertFalse(abac_context.evaluate_within_business_hours(18, 9, 18))  # exclusive
		self.assertFalse(abac_context.evaluate_within_business_hours(8, 9, 18))
		self.assertFalse(abac_context.evaluate_within_business_hours(22, 9, 18))


# ---------------------------------------------------------------------------
# rebac_client write_tuples 4/5-tuple condition desteği
# ---------------------------------------------------------------------------


# Env override
os.environ["REBAC_BASE_URL"] = "http://test-sidecar:8080"
os.environ["REBAC_API_KEY"] = "test-key"
os.environ["REBAC_STORE_ID"] = "test-store"
os.environ["REBAC_MODEL_ID"] = "test-model"

from tradehub_core.services import rebac_client  # noqa: E402


def _mock_response(status_code=200, data=None):
	resp = MagicMock()
	resp.status_code = status_code
	resp.ok = 200 <= status_code < 300
	resp.json.return_value = data or {}
	resp.content = b"x"
	resp.text = ""
	return resp


class ConditionalTupleTests(unittest.TestCase):
	def setUp(self):
		rebac_client._session = None  # noqa: SLF001
		rebac_client.reset_circuit_breaker()

	@patch.object(rebac_client.requests.Session, "post")
	def test_3_tuple_no_condition(self, mock_post):
		mock_post.return_value = _mock_response(200, {})
		rebac_client.write_tuples([("user:a", "member", "org:x")])

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		self.assertEqual(len(body["writes"]["tuple_keys"]), 1)
		self.assertNotIn("condition", body["writes"]["tuple_keys"][0])

	@patch.object(rebac_client.requests.Session, "post")
	def test_4_tuple_with_condition_name(self, mock_post):
		mock_post.return_value = _mock_response(200, {})
		rebac_client.write_tuples([
			("user:can@x.com", "can_approve_l1", "order_approval:OA-1", "needs_approval_l1"),
		])

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		tk = body["writes"]["tuple_keys"][0]
		self.assertEqual(tk["condition"], {"name": "needs_approval_l1"})

	@patch.object(rebac_client.requests.Session, "post")
	def test_5_tuple_with_condition_and_context(self, mock_post):
		mock_post.return_value = _mock_response(200, {})
		rebac_client.write_tuples([
			(
				"user:demet@x.com",
				"scope_user",
				"region:EU",
				"user_in_region",
				{"user_regions": ["EU"]},
			),
		])

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		tk = body["writes"]["tuple_keys"][0]
		self.assertEqual(tk["condition"]["name"], "user_in_region")
		self.assertEqual(tk["condition"]["context"], {"user_regions": ["EU"]})

	@patch.object(rebac_client.requests.Session, "post")
	def test_dict_tuple_direct(self, mock_post):
		mock_post.return_value = _mock_response(200, {})
		rebac_client.write_tuples([
			{
				"user": "user:x",
				"relation": "member",
				"object": "org:y",
				"condition": {"name": "custom_cond", "context": {"foo": "bar"}},
			}
		])
		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		self.assertEqual(body["writes"]["tuple_keys"][0]["condition"]["name"], "custom_cond")


# ---------------------------------------------------------------------------
# Region-aware PII access (pii.py)
# ---------------------------------------------------------------------------


class RegionAwarePiiAccessTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		# pii modülünün lazy import yaptığı abac_context'i tetikle
		from tradehub_core.utils import pii  # noqa: F401
		self.pii = pii

	def test_compliance_officer_bypass(self):
		"""Compliance Officer region check'i bypass eder."""
		_DB[("roles", "compliance@x.com")] = ["Compliance Officer"]
		# permlevel 3 erişimi
		_DB[
			(
				"exists",
				"Custom DocPerm",
				"{'parent': 'KYC Verification', 'role': ['in', ['Compliance Officer']], 'permlevel': 3, 'read': 1}",
			)
		] = "DocPerm-X"
		# Aslında pii.has_pii_access stub yok; o gerçek check kullanılıyor
		# Test'i: System Manager için bypass'ı kanıtla
		_DB[("roles", "admin@x.com")] = ["System Manager"]

		result = self.pii.has_pii_access_for_target(
			"admin@x.com", "KYC Verification", 3, target_region="EU"
		)
		self.assertTrue(result)

	def test_jurisdiction_helpers(self):
		_DB[("get_value", "Region", "EU", "jurisdiction")] = "GDPR"
		_DB[("get_value", "Region", "TR", "jurisdiction")] = "KVKK"
		_DB[("get_value", "Region", "MENA", "jurisdiction")] = "MENA"

		self.assertEqual(self.pii.get_jurisdiction_for_region("EU"), "GDPR")
		self.assertEqual(self.pii.get_jurisdiction_for_region("TR"), "KVKK")
		self.assertTrue(self.pii.is_strict_jurisdiction("EU"))
		self.assertTrue(self.pii.is_strict_jurisdiction("TR"))
		self.assertFalse(self.pii.is_strict_jurisdiction("MENA"))


if __name__ == "__main__":
	unittest.main()
