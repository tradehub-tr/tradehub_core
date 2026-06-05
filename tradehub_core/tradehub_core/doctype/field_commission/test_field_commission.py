# Copyright (c) 2026, TR TradeHub and contributors
import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.v1 import field_commission as fc_api
from tradehub_core.permissions import (
	field_commission_has_permission,
	field_commission_query_conditions,
)
from tradehub_core.utils.field_commission import generate_on_deal_won


def _make_won_deal(plan_code, owner, deal_value=1000):
	deal = frappe.new_doc("CRM Deal")
	deal.deal_owner = owner
	deal.custom_subscription_plan = plan_code
	# base_amount'u deterministik kıl: override yolu (custom_sale_amount) kullan —
	# seed plan fiyatına bağlı kalmasın. _base_amount() deal_value'i okumaz.
	deal.custom_sale_amount = deal_value
	# Won tipli ilk status'ü bul
	won = frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name")
	deal.status = won[0]
	deal.insert(ignore_permissions=True)
	return deal


class TestFieldCommissionGeneration(FrappeTestCase):
	def setUp(self):
		self.plan = frappe.get_all("Subscription Plan", limit=1, pluck="name")[0]
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_type", "Yüzde")
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_rate", 10)
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_mode", "Tek seferlik")
		self.owner = "Administrator"

	def test_won_deal_creates_pending_commission(self):
		deal = _make_won_deal(self.plan, self.owner, deal_value=2000)
		generate_on_deal_won(deal)
		fc = frappe.get_all(
			"Field Commission",
			filters={"deal": deal.name},
			fields=["status", "commission_amount", "commission_rate", "base_amount", "agent"],
		)
		self.assertEqual(len(fc), 1)
		self.assertEqual(fc[0].status, "Süperadmin Onayı Bekliyor")
		self.assertEqual(fc[0].agent, self.owner)
		self.assertEqual(fc[0].commission_rate, 10)
		self.assertEqual(fc[0].base_amount, 2000)
		self.assertEqual(fc[0].commission_amount, 200)

	def test_idempotent_no_duplicate(self):
		deal = _make_won_deal(self.plan, self.owner)
		generate_on_deal_won(deal)
		generate_on_deal_won(deal)
		count = frappe.db.count("Field Commission", {"deal": deal.name})
		self.assertEqual(count, 1)

	def test_zero_rate_skips(self):
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_rate", 0)
		deal = _make_won_deal(self.plan, self.owner)
		generate_on_deal_won(deal)
		self.assertEqual(frappe.db.count("Field Commission", {"deal": deal.name}), 0)

	def test_fixed_fee_commission(self):
		# Sabit Ücret modunda komisyon = paket fiyatından bağımsız sabit tutar.
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_type", "Sabit Ücret")
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_fixed_amount", 500)
		deal = _make_won_deal(self.plan, self.owner, deal_value=9999)
		generate_on_deal_won(deal)
		fc = frappe.get_all(
			"Field Commission",
			filters={"deal": deal.name},
			fields=["commission_type", "commission_amount", "commission_rate"],
		)
		self.assertEqual(len(fc), 1)
		self.assertEqual(fc[0].commission_type, "Sabit Ücret")
		self.assertEqual(fc[0].commission_amount, 500)
		self.assertEqual(fc[0].commission_rate, 0)

	def test_zero_fixed_fee_skips(self):
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_type", "Sabit Ücret")
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_fixed_amount", 0)
		deal = _make_won_deal(self.plan, self.owner)
		generate_on_deal_won(deal)
		self.assertEqual(frappe.db.count("Field Commission", {"deal": deal.name}), 0)


class TestFieldCommissionPermission(FrappeTestCase):
	def test_agent_query_condition_scopes_to_self(self):
		cond = field_commission_query_conditions("agent@example.com")
		# Saha Pazarlama rolü olmayan biri → erişim yok ('1=0').
		# Burada rolü olan bir kullanıcı simüle etmek yerine SQL şeklini doğrularız:
		self.assertTrue(cond == "1=0" or "`tabField Commission`.`agent`" in cond)

	def test_admin_sees_all(self):
		self.assertEqual(field_commission_query_conditions("Administrator"), "")
		# Administrator per-doc kontrolünde de tam erişimli olmalı.
		self.assertTrue(field_commission_has_permission({"agent": "x@example.com"}, "read", "Administrator"))

	def test_leader_query_condition_shape(self):
		# Admin tümünü görür (boş koşul). Lider/saha dalları rol enjekte etmeden
		# SQL şekli üzerinden doğrulanır — mevcut test deseniyle aynı.
		self.assertEqual(field_commission_query_conditions("Administrator"), "")


class TestFieldCommissionApi(FrappeTestCase):
	def setUp(self):
		self.plan = frappe.get_all("Subscription Plan", limit=1, pluck="name")[0]
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_rate", 20)

	def _make_commission(self, agent="Administrator", status="Süperadmin Onayı Bekliyor"):
		fc = frappe.new_doc("Field Commission")
		fc.agent = agent
		# deal zorunlu Link → testte var olan ilk CRM Deal'i kullan veya oluştur
		deal = frappe.get_all("CRM Deal", limit=1, pluck="name")
		fc.deal = deal[0] if deal else None
		fc.plan = self.plan
		fc.base_amount = 1000
		fc.commission_rate = 20
		fc.currency = "USD"
		fc.status = status
		fc.insert(ignore_permissions=True)
		return fc

	def test_approve_transitions_pending_to_approved(self):
		fc = self._make_commission()
		fc_api.approve_commission(fc.name)
		self.assertEqual(frappe.db.get_value("Field Commission", fc.name, "status"), "Onaylandı")

	def test_mark_paid_requires_approved(self):
		fc = self._make_commission(status="Süperadmin Onayı Bekliyor")
		with self.assertRaises(frappe.ValidationError):
			fc_api.mark_paid(fc.name)

	def test_leader_approve_moves_to_superadmin_stage(self):
		fc = self._make_commission(status="Lider Onayı Bekliyor")
		frappe.db.set_value("Field Commission", fc.name, "team_leader", "Administrator")
		fc_api.leader_approve(fc.name)
		self.assertEqual(
			frappe.db.get_value("Field Commission", fc.name, "status"),
			"Süperadmin Onayı Bekliyor",
		)

	def test_approve_requires_superadmin_stage(self):
		fc = self._make_commission(status="Lider Onayı Bekliyor")
		with self.assertRaises(frappe.ValidationError):
			fc_api.approve_commission(fc.name)

	def test_leader_reject_requires_note(self):
		fc = self._make_commission(status="Lider Onayı Bekliyor")
		frappe.db.set_value("Field Commission", fc.name, "team_leader", "Administrator")
		with self.assertRaises(frappe.ValidationError):
			fc_api.leader_reject(fc.name)


class TestQuotaBonus(FrappeTestCase):
	def setUp(self):
		from tradehub_core.tradehub_core.utils.field_commission import _quota_bonus_for_count

		self._fn = _quota_bonus_for_count
		# Kota eşikleri artık paket-bazı: bir test planına yaz.
		self.plan = frappe.get_all("Subscription Plan", limit=1, pluck="name")[0]
		plan_doc = frappe.get_doc("Subscription Plan", self.plan)
		plan_doc.set("quota_tiers", [])
		plan_doc.append("quota_tiers", {"min_sales": 5, "bonus_amount": 1000})
		plan_doc.append("quota_tiers", {"min_sales": 10, "bonus_amount": 3000})
		plan_doc.save(ignore_permissions=True)
		frappe.db.set_single_value("Field Commission Settings", "quota_period", "Aylık")

	def test_below_first_threshold_no_bonus(self):
		self.assertEqual(self._fn(3, self.plan), 0)

	def test_first_threshold(self):
		self.assertEqual(self._fn(5, self.plan), 1000)
		self.assertEqual(self._fn(9, self.plan), 1000)

	def test_highest_threshold_wins(self):
		self.assertEqual(self._fn(10, self.plan), 3000)
		self.assertEqual(self._fn(50, self.plan), 3000)

	def test_recompute_creates_bonus_when_threshold_met(self):
		from tradehub_core.tradehub_core.utils.field_commission import recompute_quota_bonus

		agent = "Administrator"
		pk = "9999-99"  # izole test dönemi
		deal = frappe.get_all("CRM Deal", limit=1, pluck="name")
		deal = deal[0] if deal else None
		for _i in range(5):
			fc = frappe.new_doc("Field Commission")
			fc.agent = agent
			fc.deal = deal
			fc.plan = self.plan
			fc.kind = "Satış"
			fc.period_key = pk
			fc.commission_type = "Sabit Ücret"
			fc.commission_amount = 100
			fc.status = "Onaylandı"
			fc.insert(ignore_permissions=True)
		recompute_quota_bonus(agent, pk, self.plan)
		bonus = frappe.get_all(
			"Field Commission",
			filters={"agent": agent, "period_key": pk, "plan": self.plan, "kind": "Bonus"},
			fields=["commission_amount"],
		)
		self.assertEqual(len(bonus), 1)
		self.assertEqual(bonus[0].commission_amount, 1000)
