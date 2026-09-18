# Copyright (c) 2026, TR TradeHub and contributors
"""Satış Ekibi yönetim API'si — admin panelden ekip kur / üye ekle / rol ata."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.v1 import sales_team as api

LEADER_ROLE = "Saha Ekip Lideri"
AGENT_ROLE = "Saha Pazarlama"


def _ensure_user(email: str) -> str:
	if not frappe.db.exists("User", email):
		u = frappe.new_doc("User")
		u.email = email
		u.first_name = email.split("@")[0]
		u.user_type = "System User"
		u.insert(ignore_permissions=True)
	return email


def _has_role(user: str, role: str) -> bool:
	return role in frappe.get_roles(user)


def _drop_team(name: str) -> None:
	if frappe.db.exists("Sales Team", name):
		frappe.delete_doc("Sales Team", name, ignore_permissions=True, force=True)


class TestSalesTeamApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.leader = _ensure_user("st_lider@example.com")
		self.m1 = _ensure_user("st_uye1@example.com")
		self.m2 = _ensure_user("st_uye2@example.com")
		for n in ("ST-Api-Ekip", "ST-Api-Ekip-2", "ST-Api-Yeni-Ad"):
			_drop_team(n)

	def tearDown(self):
		frappe.set_user("Administrator")
		for n in ("ST-Api-Ekip", "ST-Api-Ekip-2", "ST-Api-Yeni-Ad"):
			_drop_team(n)

	def test_create_team_assigns_roles(self):
		out = api.save_sales_team(
			team_name="ST-Api-Ekip", leader=self.leader, members=[self.m1, self.m2], is_active=1
		)
		self.assertEqual(out["name"], "ST-Api-Ekip")
		self.assertEqual(out["leader"], self.leader)
		self.assertEqual({m["agent"] for m in out["members"]}, {self.m1, self.m2})
		self.assertTrue(_has_role(self.leader, LEADER_ROLE))
		self.assertTrue(_has_role(self.m1, AGENT_ROLE))
		self.assertTrue(_has_role(self.m2, AGENT_ROLE))

	def test_members_accept_json_string(self):
		out = api.save_sales_team(
			team_name="ST-Api-Ekip", leader=self.leader, members=frappe.as_json([self.m1]), is_active=1
		)
		self.assertEqual([m["agent"] for m in out["members"]], [self.m1])

	def test_update_replaces_members_and_renames(self):
		api.save_sales_team(team_name="ST-Api-Ekip", leader=self.leader, members=[self.m1], is_active=1)
		out = api.save_sales_team(
			name="ST-Api-Ekip",
			team_name="ST-Api-Yeni-Ad",
			leader=self.leader,
			members=[self.m2],
			is_active=0,
		)
		self.assertEqual(out["name"], "ST-Api-Yeni-Ad")
		self.assertEqual([m["agent"] for m in out["members"]], [self.m2])
		self.assertEqual(out["is_active"], 0)
		self.assertFalse(frappe.db.exists("Sales Team", "ST-Api-Ekip"))

	def test_duplicate_active_member_rejected(self):
		api.save_sales_team(team_name="ST-Api-Ekip", leader=self.leader, members=[self.m1], is_active=1)
		with self.assertRaises(frappe.ValidationError):
			api.save_sales_team(team_name="ST-Api-Ekip-2", leader=self.leader, members=[self.m1], is_active=1)

	def test_list_returns_members_with_names(self):
		api.save_sales_team(team_name="ST-Api-Ekip", leader=self.leader, members=[self.m1], is_active=1)
		rows = api.list_sales_teams()
		row = next(r for r in rows if r["name"] == "ST-Api-Ekip")
		self.assertEqual(row["leader"], self.leader)
		self.assertEqual(row["members"][0]["agent"], self.m1)
		self.assertIn("full_name", row["members"][0])

	def test_search_users_by_email_fragment(self):
		rows = api.search_users(q="st_uye1")
		self.assertTrue(any(r["name"] == self.m1 for r in rows))
		self.assertFalse(any(r["name"] in ("Administrator", "Guest") for r in rows))

	def test_delete_team(self):
		api.save_sales_team(team_name="ST-Api-Ekip", leader=self.leader, members=[], is_active=1)
		api.delete_sales_team(name="ST-Api-Ekip")
		self.assertFalse(frappe.db.exists("Sales Team", "ST-Api-Ekip"))

	def test_non_admin_forbidden(self):
		frappe.set_user(self.m1)
		with self.assertRaises(frappe.PermissionError):
			api.list_sales_teams()
		with self.assertRaises(frappe.PermissionError):
			api.save_sales_team(team_name="ST-Api-Ekip", leader=self.leader, members=[], is_active=1)
