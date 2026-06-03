# Copyright (c) 2026, TR TradeHub and contributors
import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.tradehub_core.utils.field_commission import _resolve_commission


class _Plan(dict):
	"""plan_doc.get(...) arayüzünü taklit eden basit sözlük."""

	def get(self, key, default=None):
		return super().get(key, default)


class _Deal(dict):
	def get(self, key, default=None):
		return super().get(key, default)


class TestFieldCommissionSettings(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("Field Commission Settings", "global_per_sale_amount", 0)

	def test_plan_percentage_wins_over_global(self):
		frappe.db.set_single_value("Field Commission Settings", "global_per_sale_amount", 5000)
		plan = _Plan({"field_commission_type": "Yüzde", "field_commission_rate": 10, "monthly_price": 1000})
		deal = _Deal({})
		res = _resolve_commission(deal, plan)
		self.assertEqual(res["commission_type"], "Yüzde")
		self.assertEqual(res["base_amount"], 1000)
		self.assertEqual(res["commission_rate"], 10)

	def test_plan_fixed_wins_over_global(self):
		frappe.db.set_single_value("Field Commission Settings", "global_per_sale_amount", 5000)
		plan = _Plan({"field_commission_type": "Sabit Ücret", "field_commission_fixed_amount": 1200})
		res = _resolve_commission(_Deal({}), plan)
		self.assertEqual(res["commission_type"], "Sabit Ücret")
		self.assertEqual(res["commission_amount"], 1200)

	def test_global_fallback_when_plan_unconfigured(self):
		frappe.db.set_single_value("Field Commission Settings", "global_per_sale_amount", 5000)
		plan = _Plan({"field_commission_type": None, "field_commission_rate": 0})
		res = _resolve_commission(_Deal({}), plan)
		self.assertEqual(res["commission_type"], "Sabit Ücret")
		self.assertEqual(res["base_amount"], 0)
		self.assertEqual(res["commission_amount"], 5000)

	def test_no_commission_when_nothing_configured(self):
		plan = _Plan({"field_commission_type": None, "field_commission_rate": 0})
		res = _resolve_commission(_Deal({}), plan)
		self.assertIsNone(res)

	def test_update_and_get_settings_roundtrip(self):
		from tradehub_core.api.v1.field_commission import get_settings, update_settings

		frappe.set_user("Administrator")
		update_settings(global_per_sale_amount=7500)
		self.assertEqual(get_settings()["global_per_sale_amount"], 7500)
