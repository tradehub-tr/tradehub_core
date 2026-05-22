"""FAZ 2.3 — rebac_client unit testleri.

tradehub_core.services.rebac_client içindeki:
  - check (mock HTTP, allow/deny/fail-closed)
  - list_objects (mock HTTP, prefix stripping)
  - write_tuples / delete_tuples
  - Circuit breaker (5 fail → open, 30 sn recovery)
  - AuthZEN wrapper

için saf-Python testler. requests modülü mock'lanır.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_rebac_client
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


# ---------------------------------------------------------------------------
# Frappe stub (audit log için minimum)
# ---------------------------------------------------------------------------


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None

	# Audit log_decision boş stub (test_rebac_client'da audit kontrol etmiyoruz).
	# D7: Force re-install — noop stub diğer testlerin recorder'ını engellemesin.
	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.log_decision = lambda *a, **kw: None
	audit_mod.log_role_change = lambda *a, **kw: None
	sys.modules["tradehub_core.audit"] = audit_mod


_install_frappe_stub()


# Env'i test için override
os.environ["REBAC_BASE_URL"] = "http://test-sidecar:8080"
os.environ["REBAC_API_KEY"] = "test-key"
os.environ["REBAC_STORE_ID"] = "test-store-01"
os.environ["REBAC_MODEL_ID"] = "test-model-01"

from tradehub_core.services import rebac_client  # noqa: E402


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
	"""Mock requests.Response."""
	resp = MagicMock()
	resp.status_code = status_code
	resp.ok = 200 <= status_code < 300
	resp.json.return_value = json_data or {}
	resp.content = b"x" if json_data else b""
	resp.text = str(json_data) if json_data else ""
	return resp


def _reset_state():
	"""Test başında session + circuit breaker reset."""
	rebac_client._session = None  # noqa: SLF001
	rebac_client.reset_circuit_breaker()


# ---------------------------------------------------------------------------
# check() tests
# ---------------------------------------------------------------------------


class CheckTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	@patch.object(rebac_client.requests.Session, "post")
	def test_check_allow(self, mock_post):
		mock_post.return_value = _mock_response(200, {"allowed": True})
		result = rebac_client.check("user:ayse@x.com", "member", "buyer_org:acme")
		self.assertTrue(result)

	@patch.object(rebac_client.requests.Session, "post")
	def test_check_deny(self, mock_post):
		mock_post.return_value = _mock_response(200, {"allowed": False})
		result = rebac_client.check("user:rando@x.com", "member", "buyer_org:acme")
		self.assertFalse(result)

	@patch.object(rebac_client.requests.Session, "post")
	def test_check_with_context(self, mock_post):
		mock_post.return_value = _mock_response(200, {"allowed": True})
		rebac_client.check(
			"user:can@x.com",
			"can_approve_l1",
			"order_approval:OA-001",
			context={"amount": 1500},
		)
		# Çağrıda context geçti mi?
		call_args = mock_post.call_args
		# call_args[1]['data'] JSON string; parse et
		import json

		body = json.loads(call_args.kwargs.get("data", "{}"))
		self.assertEqual(body.get("context"), {"amount": 1500})

	@patch.object(rebac_client.requests.Session, "post")
	def test_check_4xx_fail_closed(self, mock_post):
		"""4xx (auth fail vb.) → fail-closed (False)."""
		mock_post.return_value = _mock_response(401, {"code": "auth_failed"})
		result = rebac_client.check("user:x@x.com", "member", "org:y")
		self.assertFalse(result)

	@patch.object(rebac_client.requests.Session, "post")
	def test_check_network_error_fail_closed(self, mock_post):
		mock_post.side_effect = rebac_client.requests.exceptions.ConnectionError("network")
		result = rebac_client.check("user:x@x.com", "member", "org:y")
		self.assertFalse(result)


# ---------------------------------------------------------------------------
# list_objects() tests
# ---------------------------------------------------------------------------


class ListObjectsTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	@patch.object(rebac_client.requests.Session, "post")
	def test_list_objects_strips_prefix(self, mock_post):
		mock_post.return_value = _mock_response(200, {"objects": ["order:ORD-9382", "order:ORD-9401"]})
		result = rebac_client.list_objects("order", "can_view", "user:ayse@x.com")
		self.assertEqual(result, ["ORD-9382", "ORD-9401"])

	@patch.object(rebac_client.requests.Session, "post")
	def test_list_objects_empty(self, mock_post):
		mock_post.return_value = _mock_response(200, {"objects": []})
		result = rebac_client.list_objects("order", "can_view", "user:lonely@x.com")
		self.assertEqual(result, [])

	@patch.object(rebac_client.requests.Session, "post")
	def test_list_objects_fail_closed_empty(self, mock_post):
		mock_post.side_effect = rebac_client.requests.exceptions.Timeout("slow")
		result = rebac_client.list_objects("order", "can_view", "user:x@x.com")
		self.assertEqual(result, [])  # Fail-closed: boş liste


# ---------------------------------------------------------------------------
# write_tuples / delete_tuples
# ---------------------------------------------------------------------------


class WriteDeleteTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	@patch.object(rebac_client.requests.Session, "post")
	def test_write_tuples_success(self, mock_post):
		mock_post.return_value = _mock_response(200, {})
		result = rebac_client.write_tuples([("user:ayse@x.com", "member", "buyer_org:acme")])
		self.assertTrue(result)
		# Payload kontrolü
		import json

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		self.assertEqual(len(body["writes"]["tuple_keys"]), 1)
		self.assertEqual(body["writes"]["tuple_keys"][0]["relation"], "member")

	@patch.object(rebac_client.requests.Session, "post")
	def test_write_tuples_empty_list_skips(self, mock_post):
		"""Boş liste → HTTP çağrısı YAPILMAMALI."""
		result = rebac_client.write_tuples([])
		self.assertTrue(result)
		mock_post.assert_not_called()

	@patch.object(rebac_client.requests.Session, "post")
	def test_delete_tuples_success(self, mock_post):
		mock_post.return_value = _mock_response(200, {})
		result = rebac_client.delete_tuples([("user:ayse@x.com", "member", "buyer_org:acme")])
		self.assertTrue(result)
		import json

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		self.assertIn("deletes", body)


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitBreakerTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	@patch.object(rebac_client.requests.Session, "post")
	def test_circuit_opens_after_threshold(self, mock_post):
		"""5 ardışık fail → circuit OPEN, sonraki check fail-closed."""
		mock_post.side_effect = rebac_client.requests.exceptions.ConnectionError("err")

		# 5 fail (her biri retry'lar dahil) → CB fail counter +5
		for _ in range(5):
			rebac_client.check("user:x@x.com", "member", "org:y")

		# Circuit açık olmalı
		self.assertTrue(rebac_client._circuit_breaker.is_open())

	@patch.object(rebac_client.requests.Session, "post")
	def test_circuit_breaker_blocks_request(self, mock_post):
		"""Circuit açıkken HTTP çağrısı YAPILMAMALI."""
		# Manuel olarak CB'yi aç
		rebac_client._circuit_breaker._fail_count = 99  # noqa: SLF001
		rebac_client._circuit_breaker._opened_at = __import__("time").time()  # noqa: SLF001

		result = rebac_client.check("user:x@x.com", "member", "org:y")
		self.assertFalse(result)  # Fail-closed
		mock_post.assert_not_called()  # HTTP çağrılmadı

	def test_reset_circuit_breaker(self):
		"""reset_circuit_breaker() helper'ı CB'yi kapatır."""
		rebac_client._circuit_breaker._fail_count = 99  # noqa: SLF001
		rebac_client._circuit_breaker._opened_at = __import__("time").time()  # noqa: SLF001
		rebac_client.reset_circuit_breaker()
		self.assertFalse(rebac_client._circuit_breaker.is_open())


# ---------------------------------------------------------------------------
# Config errors
# ---------------------------------------------------------------------------


class ConfigErrorTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	@patch.object(rebac_client, "_REBAC_STORE_ID", "")
	def test_missing_store_id_raises(self):
		"""STORE_ID boşsa _call() ConfigError fırlatır."""
		with self.assertRaises(rebac_client.ReBACConfigError):
			rebac_client._call("POST", "/test", {})


# ---------------------------------------------------------------------------
# AuthZEN wrapper
# ---------------------------------------------------------------------------


class AuthZENWrapperTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	@patch.object(rebac_client.requests.Session, "post")
	def test_authzen_check_translates_correctly(self, mock_post):
		"""AuthZEN payload → OpenFGA native API."""
		mock_post.return_value = _mock_response(200, {"allowed": True})

		result = rebac_client.authzen_check(
			subject={"type": "user", "id": "ayse@x.com"},
			action={"name": "can_view"},
			resource={"type": "order", "id": "ORD-9382"},
		)
		self.assertTrue(result)

		# OpenFGA payload kontrolü
		import json

		body = json.loads(mock_post.call_args.kwargs.get("data", "{}"))
		self.assertEqual(body["tuple_key"]["user"], "user:ayse@x.com")
		self.assertEqual(body["tuple_key"]["relation"], "can_view")
		self.assertEqual(body["tuple_key"]["object"], "order:ORD-9382")


if __name__ == "__main__":
	unittest.main()
