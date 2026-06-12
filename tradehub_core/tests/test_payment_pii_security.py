"""H10 — verify_supplier_account banka PII enumerasyonu engeli.

api/payment.verify_supplier_account artık yalnız boolean `verified` döner;
seller_name/bank_name/iban/account_holder gibi PII DÖNMEZ.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_payment_pii_security
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _ValidationError(Exception):
	pass


class _PermissionError(Exception):
	pass


_KNOWN_IBANS = {"TR000000000000000000000001"}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.ValidationError = _ValidationError
	frappe.PermissionError = _PermissionError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: (a[0] if (a and callable(a[0])) else (lambda fn: fn))
	frappe.session = SimpleNamespace(user="buyer@test")
	frappe.get_roles = lambda u=None: ["Buyer"]

	def _exists(doctype, filters=None):
		if doctype == "Admin Seller Profile" and isinstance(filters, dict):
			return filters.get("iban") in _KNOWN_IBANS
		return False

	frappe.db = SimpleNamespace(exists=_exists, get_value=lambda *a, **k: None)

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: None
	sys.modules["frappe.utils"] = utils


_install_frappe_stub()
_FRAPPE_STUB = sys.modules["frappe"]

# payment.py importu için bağımlılık stub'ları (minimal)
for _mod, _attrs in {
	"tradehub_core.api.rate_limit": {"rate_limit": lambda *a, **k: (lambda fn: fn)},
	"tradehub_core.api._pagination": {
		"normalize_pagination": lambda p=1, ps=20, *a, **k: (int(p or 1), int(ps or 20), None)
	},
}.items():
	m = types.ModuleType(_mod)
	for k, v in _attrs.items():
		setattr(m, k, v)
	sys.modules.setdefault(_mod, m)


def _import_payment():
	try:
		from tradehub_core.api import payment as pay

		return pay
	except Exception:
		return None


_PAY = _import_payment()


class TestVerifySupplierAccount(unittest.TestCase):
	def setUp(self):
		if _PAY is None or not hasattr(_PAY, "verify_supplier_account"):
			self.skipTest("payment modülü stub ortamında import edilemedi")
		_PAY.frappe = _FRAPPE_STUB
		# _require_buyer'ı no-op'la (rol kontrolü bu testin konusu değil)
		_PAY._require_buyer = lambda: "buyer@test"

	_PII_KEYS = {"seller_name", "bank_name", "iban", "account_holder"}

	def test_known_iban_verified_without_pii(self):
		out = _PAY.verify_supplier_account("TR00 0000 0000 0000 0000 0000 01")
		self.assertTrue(out.get("verified"))
		leaked = self._PII_KEYS & set(out.keys())
		self.assertEqual(leaked, set(), f"PII sızdı: {leaked}")

	def test_unknown_iban_not_verified_without_pii(self):
		out = _PAY.verify_supplier_account("TR99 9999 9999")
		self.assertFalse(out.get("verified"))
		leaked = self._PII_KEYS & set(out.keys())
		self.assertEqual(leaked, set(), f"PII sızdı: {leaked}")


if __name__ == "__main__":
	unittest.main()
