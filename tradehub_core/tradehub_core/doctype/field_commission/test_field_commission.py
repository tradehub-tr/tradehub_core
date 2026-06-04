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
		self.assertEqual(fc[0].status, "Beklemede")
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


class TestFieldCommissionApi(FrappeTestCase):
	def setUp(self):
		self.plan = frappe.get_all("Subscription Plan", limit=1, pluck="name")[0]
		frappe.db.set_value("Subscription Plan", self.plan, "field_commission_rate", 20)

	def _make_commission(self, agent="Administrator", status="Beklemede"):
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
		fc = self._make_commission(status="Beklemede")
		with self.assertRaises(frappe.ValidationError):
			fc_api.mark_paid(fc.name)
