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
	def test_plan_percentage_resolves(self):
		plan = _Plan({"field_commission_type": "Yüzde", "field_commission_rate": 10, "monthly_price": 1000})
		res = _resolve_commission(_Deal({}), plan)
		self.assertEqual(res["commission_type"], "Yüzde")
		self.assertEqual(res["base_amount"], 1000)
		self.assertEqual(res["commission_rate"], 10)

	def test_plan_fixed_resolves(self):
		plan = _Plan({"field_commission_type": "Sabit Ücret", "field_commission_fixed_amount": 1200})
		res = _resolve_commission(_Deal({}), plan)
		self.assertEqual(res["commission_type"], "Sabit Ücret")
		self.assertEqual(res["commission_amount"], 1200)

	def test_no_commission_when_plan_unconfigured(self):
		plan = _Plan({"field_commission_type": None, "field_commission_rate": 0})
		res = _resolve_commission(_Deal({}), plan)
		self.assertIsNone(res)

	def test_quota_period_roundtrip(self):
		from tradehub_core.api.v1.field_commission import get_settings, update_settings

		frappe.set_user("Administrator")
		update_settings(quota_period="Çeyrek")
		self.assertEqual(get_settings()["quota_period"], "Çeyrek")
