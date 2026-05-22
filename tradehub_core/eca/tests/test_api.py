"""ECA API endpoint testleri — sandbox condition runner."""

import json
import unittest
from unittest.mock import MagicMock, patch


class TestTestRuleWithSample(unittest.TestCase):
	"""test_rule_with_sample endpoint testleri.

	frappe.safe_eval, frappe.utils ve frappe.session.user mock'lanır; bu testler
	gerçek Frappe DB olmadan koşar (gerçek koşum: `bench --site dev.localhost
	run-tests --module tradehub_core.eca.tests.test_api`).
	"""

	def _mock_frappe(self, mock_frappe):
		mock_frappe.session = MagicMock()
		mock_frappe.session.user = "test@example.com"
		mock_frappe.utils = MagicMock()
		mock_frappe.utils.cint = lambda x: int(x) if x else 0
		mock_frappe.utils.flt = lambda x: float(x) if x else 0.0
		mock_frappe.utils.getdate = lambda x=None: None
		mock_frappe.utils.now_datetime = lambda: None
		mock_frappe.whitelist = lambda *a, **kw: lambda f: f
		mock_frappe.safe_eval = lambda expr, ctx: eval(expr, {"__builtins__": {}}, ctx)

	def test_empty_condition_returns_true(self):
		with patch("tradehub_core.eca.api.frappe") as mock_frappe:
			self._mock_frappe(mock_frappe)
			from tradehub_core.eca.api import test_rule_with_sample

			result = test_rule_with_sample(condition="", sample_doc_json="{}")
			self.assertTrue(result["result"])
			self.assertIsNone(result["error"])

	def test_simple_true_condition(self):
		with patch("tradehub_core.eca.api.frappe") as mock_frappe:
			self._mock_frappe(mock_frappe)
			from tradehub_core.eca.api import test_rule_with_sample

			doc = json.dumps({"base_price": 1500, "min_order_qty": 12})
			result = test_rule_with_sample(
				condition="cint(doc['min_order_qty']) >= 10",
				sample_doc_json=doc,
				owner_role="Seller",
			)
			self.assertTrue(result["result"])
			self.assertIsNone(result["error"])

	def test_simple_false_condition(self):
		with patch("tradehub_core.eca.api.frappe") as mock_frappe:
			self._mock_frappe(mock_frappe)
			from tradehub_core.eca.api import test_rule_with_sample

			doc = json.dumps({"base_price": 1500, "min_order_qty": 3})
			result = test_rule_with_sample(
				condition="cint(doc['min_order_qty']) >= 10",
				sample_doc_json=doc,
				owner_role="Seller",
			)
			self.assertFalse(result["result"])
			self.assertIsNone(result["error"])

	def test_invalid_json_returns_error(self):
		with patch("tradehub_core.eca.api.frappe") as mock_frappe:
			self._mock_frappe(mock_frappe)
			from tradehub_core.eca.api import test_rule_with_sample

			result = test_rule_with_sample(
				condition="True",
				sample_doc_json="{not valid json",
			)
			self.assertFalse(result["result"])
			self.assertIn("JSON", result["error"])

	def test_python_syntax_error_returns_error(self):
		with patch("tradehub_core.eca.api.frappe") as mock_frappe:
			self._mock_frappe(mock_frappe)
			from tradehub_core.eca.api import test_rule_with_sample

			result = test_rule_with_sample(
				condition="this is not python !!!",
				sample_doc_json="{}",
			)
			self.assertFalse(result["result"])
			self.assertIsNotNone(result["error"])

	def test_seller_filter_strips_admin_fields(self):
		with patch("tradehub_core.eca.api.frappe") as mock_frappe:
			self._mock_frappe(mock_frappe)
			from tradehub_core.eca.api import test_rule_with_sample

			doc = json.dumps(
				{
					"title": "Test",
					"admin_review_flag": 1,
				}
			)
			result = test_rule_with_sample(
				condition="doc.get('admin_review_flag', 0) == 0",
				sample_doc_json=doc,
				owner_role="Seller",
			)
			self.assertTrue(result["result"])


if __name__ == "__main__":
	unittest.main()
