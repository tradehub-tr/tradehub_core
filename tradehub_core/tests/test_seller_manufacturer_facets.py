"""Manufacturer facet kuruluş yılı sayımı için saf regresyon testleri.

Run:
    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_seller_manufacturer_facets
"""

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	frappe.ValidationError = type("ValidationError", (Exception,), {})
	frappe.whitelist = lambda **_kwargs: lambda func: func
	frappe._ = lambda message: message
	sys.modules["frappe"] = frappe

	frappe_utils = types.ModuleType("frappe.utils")
	frappe_utils.getdate = lambda value: value
	frappe_utils.nowdate = lambda: "2026-07-25"
	sys.modules["frappe.utils"] = frappe_utils


_install_frappe_stub()

from tradehub_core.api.seller import _is_founded_year_at_most  # noqa: E402


class TestManufacturerFacetFoundedYear(unittest.TestCase):
	def test_accepts_string_null_and_numeric_founded_year_values(self):
		cutoff = 2015
		values = ["2010", None, 2015, 2018]

		matches = [value for value in values if _is_founded_year_at_most(value, cutoff)]

		self.assertEqual(matches, ["2010", 2015])

