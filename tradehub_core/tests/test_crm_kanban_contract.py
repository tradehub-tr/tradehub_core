"""CRM Kanban page endpoint contract tests (no Frappe runtime required)."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

_CALLS: list[dict] = []


def _install_stubs() -> None:
	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.whitelist = lambda *args, **kwargs: (
		args[0] if args and callable(args[0]) else lambda fn: fn
	)
	frappe.throw = lambda message: (_ for _ in ()).throw(ValueError(message))

	def get_list(doctype, **kwargs):
		_CALLS.append({"doctype": doctype, **kwargs})
		if kwargs.get("pluck") == "name":
			return [f"DEAL-{index}" for index in range(101)]
		return [
			{
				"name": "DEAL-101",
				"organization": "ORG-1",
				"status": "Won",
				"currency": "TRY",
				"deal_value": 1250,
				"expected_deal_value": 1000,
				"modified": "2026-07-25 12:00:00",
				"creation": "2026-07-20 12:00:00",
			}
		]

	frappe.get_list = get_list
	sys.modules["frappe"] = frappe

	permissions = types.ModuleType("tradehub_core.permissions")
	permissions._CRM_FULL_ACCESS_ROLES = frozenset()
	sys.modules["tradehub_core.permissions"] = permissions


_install_stubs()
from tradehub_core.api.v1 import crm_overrides  # noqa: E402


class TestCrmKanbanContract(unittest.TestCase):
	def setUp(self) -> None:
		_CALLS.clear()

	def test_page_is_permission_aware_capped_and_stably_ordered(self):
		result = crm_overrides.crm_get_kanban_page(
			"CRM Deal",
			status="Won",
			filters='[["organization", "=", "ORG-1"]]',
			limit_page_length="999",
			limit_start="-4",
			order_by="creation asc",
		)

		count_query, page_query = _CALLS
		self.assertEqual(count_query["doctype"], "CRM Deal")
		self.assertEqual(count_query["pluck"], "name")
		self.assertEqual(count_query["limit_page_length"], 0)
		self.assertEqual(
			count_query["filters"], [["organization", "=", "ORG-1"], ["status", "=", "Won"]],
		)
		self.assertEqual(page_query["start"], 0)
		self.assertEqual(page_query["page_length"], 100)
		self.assertEqual(page_query["order_by"], "creation asc, name asc")
		self.assertNotIn("email", page_query["fields"])
		self.assertEqual(result["total"], 101)
		self.assertTrue(result["has_more"])
		self.assertEqual(result["next_offset"], 100)
		self.assertEqual(result["status_field"], "status")
		self.assertEqual(result["items"][0]["order_token"], "2026-07-20 12:00:00|DEAL-101")

	def test_unknown_doctype_is_rejected(self):
		with self.assertRaises(ValueError):
			crm_overrides.crm_get_kanban_page("User")

