# Copyright (c) 2026, TR TradeHub and contributors
import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tradehub_core.utils.field_commission import _initial_routing


def _ensure_user(email):
	if not frappe.db.exists("User", email):
		u = frappe.new_doc("User")
		u.email = email
		u.first_name = email.split("@")[0]
		u.insert(ignore_permissions=True)
	return email


def _make_team(team_name, leader, members, is_active=1):
	if frappe.db.exists("Sales Team", team_name):
		frappe.delete_doc("Sales Team", team_name, ignore_permissions=True, force=True)
	t = frappe.new_doc("Sales Team")
	t.team_name = team_name
	t.leader = leader
	t.is_active = is_active
	for m in members:
		t.append("members", {"agent": m})
	t.insert(ignore_permissions=True)
	return t


class TestSalesTeamRouting(FrappeTestCase):
	def setUp(self):
		self.leader = _ensure_user("lider_c@example.com")
		self.member = _ensure_user("uye_c@example.com")
		self.loner = _ensure_user("ekipsiz_c@example.com")

	def test_member_routes_to_leader_stage(self):
		_make_team("C-Test-Ekip-1", self.leader, [self.member])
		r = _initial_routing(self.member)
		self.assertEqual(r["status"], "Lider Onayı Bekliyor")
		self.assertEqual(r["team"], "C-Test-Ekip-1")
		self.assertEqual(r["team_leader"], self.leader)

	def test_leader_own_record_skips_leader_stage(self):
		_make_team("C-Test-Ekip-2", self.leader, [self.leader])
		r = _initial_routing(self.leader)
		self.assertEqual(r["status"], "Süperadmin Onayı Bekliyor")
		self.assertEqual(r["team_leader"], self.leader)

	def test_agent_without_team_skips_leader_stage(self):
		r = _initial_routing(self.loner)
		self.assertEqual(r["status"], "Süperadmin Onayı Bekliyor")
		self.assertIsNone(r["team"])
		self.assertIsNone(r["team_leader"])

	def test_member_cannot_join_second_active_team(self):
		_make_team("C-Test-Ekip-3", self.leader, [self.member])
		with self.assertRaises(frappe.ValidationError):
			_make_team("C-Test-Ekip-4", self.leader, [self.member])
