"""FAZ 3.3 — Supplier whitelist + Cost Center testleri.

Senaryolar:
  Supplier:
    1. No whitelist → ALLOW
    2. Supplier listede değil → DENY
    3. Supplier listede, amount limit aşıldı → DENY
    4. Min order aşağıda → DENY
    5. Allowed category dışında → DENY
    6. Compliance Officer bypass
    7. Happy path → ALLOW
    8. Cache invalidation

  Cost Center:
    9. No cost center → ALLOW (geçiş)
   10. Cost center bulunamadı → DENY
   11. Cost center inactive → DENY
   12. Bütçe limit yok → ALLOW
   13. Bütçe aşıldı → DENY
   14. Within budget → ALLOW

  cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_procurement
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_DB: dict = {}
_AUDIT_LOGS: list[dict] = []
_USER_ROLES: dict[str, list[str]] = {}
_CACHE: dict = {}
_SPEND: dict = {}


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Administrator")
	frappe.get_roles = lambda u: _USER_ROLES.get(u, [])

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(filters), str(fieldname))
		val = _DB.get(key)
		# Support as_dict
		if isinstance(fieldname, list) and val is not None and kwargs.get("as_dict"):
			return SimpleNamespace(**val) if isinstance(val, dict) else val
		return val

	def get_all(doctype, filters=None, pluck=None, fields=None, order_by=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB.get(key, [])

	def get_doc(doctype, name=None):
		data = _DB.get(("get_doc", doctype, name), {})
		ns = SimpleNamespace(**data)
		ns.doctype = doctype
		ns.name = name
		raw = data.get("suppliers", [])
		ns.suppliers = [SimpleNamespace(**(r if isinstance(r, dict) else r.__dict__)) for r in raw]
		return ns

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=lambda *a, **kw: True,
		escape=lambda s: f"'{s}'",
		commit=lambda: None,
	)
	frappe.get_all = get_all
	frappe.get_doc = get_doc

	frappe.cache = SimpleNamespace(
		get_value=lambda k: _CACHE.get(k),
		set_value=lambda k, v, **kw: _CACHE.__setitem__(k, v),
		delete_value=lambda k: _CACHE.pop(k, None),
	)

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class PermissionError(Exception):
			pass

		frappe.PermissionError = PermissionError
	if not hasattr(frappe, "ValidationError"):

		class ValidationError(Exception):
			pass

		frappe.ValidationError = ValidationError

	def _throw(msg, exc=Exception):
		if isinstance(exc, type):
			raise exc(msg)
		raise Exception(msg)

	frappe.throw = _throw
	frappe.log_error = lambda *a, **kw: None
	frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None)

	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.log_decision = lambda **kw: _AUDIT_LOGS.append(dict(kw)) or "ADL"
	audit_mod.log_role_change = lambda **kw: "RCL"
	sys.modules["tradehub_core.audit"] = audit_mod

	if not hasattr(frappe, "whitelist"):

		def _w(*a, **kw):
			if a and callable(a[0]):
				return a[0]
			return lambda fn: fn

		frappe.whitelist = _w


_install_frappe_stub()


def _reset_state():
	_DB.clear()
	_AUDIT_LOGS.clear()
	_USER_ROLES.clear()
	_CACHE.clear()
	_SPEND.clear()
	_install_frappe_stub()


os.environ.setdefault("REBAC_BASE_URL", "http://test:8080")
os.environ.setdefault("REBAC_API_KEY", "test")
os.environ.setdefault("REBAC_STORE_ID", "test-store")
os.environ.setdefault("REBAC_MODEL_ID", "test-model")


from tradehub_core.services import cost_center as cc_service  # noqa: E402
from tradehub_core.services import supplier_whitelist as sw_service  # noqa: E402


def _seed_whitelist(tenant: str, suppliers: list[dict], list_name: str = "Default"):
	policy_name = f"ASL-{tenant}-001"
	_DB[
		(
			"get_value",
			"Approved Supplier List",
			f"{{'tenant': '{tenant}', 'is_default': 1, 'is_active': 1}}",
			"name",
		)
	] = policy_name
	_DB[("get_doc", "Approved Supplier List", policy_name)] = {
		"tenant": tenant,
		"list_name": list_name,
		"effective_from": None,
		"effective_to": None,
		"suppliers": [{**s, "is_active": s.get("is_active", 1)} for s in suppliers],
	}


def _seed_cost_center(name: str, **fields):
	_DB[
		("get_value", "Cost Center", name, "['is_active', 'monthly_budget', 'currency', 'budget_period']")
	] = fields
	# Backward compat — single field reads
	for k, v in fields.items():
		_DB[("get_value", "Cost Center", name, k)] = v


# ---------------------------------------------------------------------------
# Supplier whitelist tests
# ---------------------------------------------------------------------------


class SupplierWhitelistTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_no_whitelist_allows(self):
		res = sw_service.is_supplier_approved("ACME", "SUPP-A", amount=1000)
		self.assertEqual(res.decision, "ALLOW")
		self.assertEqual(res.reason, "no_whitelist")

	def test_supplier_not_in_list_denies(self):
		_seed_whitelist(
			"ACME",
			[{"supplier": "SUPP-A", "min_order_amount": 0, "max_order_amount": 0, "allowed_categories": ""}],
		)
		res = sw_service.is_supplier_approved("ACME", "SUPP-B", amount=1000)
		self.assertEqual(res.decision, "DENY")
		self.assertIn("onaylı listede değil", res.reason)

	def test_max_amount_exceeded_denies(self):
		_seed_whitelist(
			"ACME",
			[
				{
					"supplier": "SUPP-A",
					"min_order_amount": 0,
					"max_order_amount": 500,
					"allowed_categories": "",
				}
			],
		)
		res = sw_service.is_supplier_approved("ACME", "SUPP-A", amount=1000)
		self.assertEqual(res.decision, "DENY")
		self.assertIn("maksimumu", res.reason)

	def test_min_amount_below_denies(self):
		_seed_whitelist(
			"ACME",
			[
				{
					"supplier": "SUPP-A",
					"min_order_amount": 1000,
					"max_order_amount": 0,
					"allowed_categories": "",
				}
			],
		)
		res = sw_service.is_supplier_approved("ACME", "SUPP-A", amount=500)
		self.assertEqual(res.decision, "DENY")
		self.assertIn("minimumun", res.reason)

	def test_category_filter_denies(self):
		_seed_whitelist(
			"ACME",
			[
				{
					"supplier": "SUPP-A",
					"min_order_amount": 0,
					"max_order_amount": 0,
					"allowed_categories": "office,it",
				}
			],
		)
		res = sw_service.is_supplier_approved("ACME", "SUPP-A", amount=500, categories=["furniture"])
		self.assertEqual(res.decision, "DENY")
		self.assertIn("kategorileri", res.reason)

	def test_category_match_allows(self):
		_seed_whitelist(
			"ACME",
			[
				{
					"supplier": "SUPP-A",
					"min_order_amount": 0,
					"max_order_amount": 0,
					"allowed_categories": "office,it",
				}
			],
		)
		res = sw_service.is_supplier_approved("ACME", "SUPP-A", amount=500, categories=["office"])
		self.assertEqual(res.decision, "ALLOW")

	def test_happy_path(self):
		_seed_whitelist(
			"ACME",
			[
				{
					"supplier": "SUPP-A",
					"min_order_amount": 100,
					"max_order_amount": 5000,
					"allowed_categories": "",
				}
			],
		)
		res = sw_service.is_supplier_approved("ACME", "SUPP-A", amount=2500)
		self.assertEqual(res.decision, "ALLOW")
		self.assertEqual(res.reason, "approved")

	def test_cache_invalidation(self):
		_seed_whitelist(
			"ACME",
			[{"supplier": "SUPP-A", "min_order_amount": 0, "max_order_amount": 0, "allowed_categories": ""}],
		)
		# Populate cache
		sw_service.get_default_list("ACME")
		self.assertIn("supplier_whitelist:ACME", _CACHE)
		sw_service.invalidate_cache("ACME")
		self.assertNotIn("supplier_whitelist:ACME", _CACHE)


# ---------------------------------------------------------------------------
# Cost center tests
# ---------------------------------------------------------------------------


class CostCenterTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		# Patch get_monthly_spend to read from _SPEND
		cc_service.get_monthly_spend = lambda cc, y, m: float(_SPEND.get(cc, 0))

	def test_no_cost_center_allows(self):
		res = cc_service.validate_budget("", amount=100)
		self.assertEqual(res.decision, "ALLOW")
		self.assertEqual(res.reason, "no_cost_center")

	def test_cost_center_not_found_denies(self):
		res = cc_service.validate_budget("CC-X-MISSING", amount=100)
		self.assertEqual(res.decision, "DENY")
		self.assertIn("bulunamadı", res.reason)

	def test_inactive_cost_center_denies(self):
		_seed_cost_center("CC-1", is_active=0, monthly_budget=1000, currency="EUR", budget_period="monthly")
		# Provide as_dict-compatible return: stub her field için ayrı read yapar
		# is_active=0 yapmamız gerekiyor — direct as_dict çağrısı yerine, model'in nasıl çağırdığını destekleyelim
		# cost_center service: frappe.db.get_value("Cost Center", name, ["is_active", ...], as_dict=True)
		# Stub'umuz as_dict desteklemiyor — manuel patch
		import frappe as _f

		_f.db.get_value = lambda dt, name, fl=None, **kw: (
			SimpleNamespace(is_active=0, monthly_budget=1000, currency="EUR", budget_period="monthly")
			if dt == "Cost Center"
			else None
		)

		res = cc_service.validate_budget("CC-1", amount=100)
		self.assertEqual(res.decision, "DENY")
		self.assertIn("pasif", res.reason)

	def test_no_budget_limit_allows(self):
		import frappe as _f

		_f.db.get_value = lambda dt, name, fl=None, **kw: (
			SimpleNamespace(is_active=1, monthly_budget=0, currency="EUR", budget_period="monthly")
			if dt == "Cost Center"
			else None
		)

		res = cc_service.validate_budget("CC-2", amount=100)
		self.assertEqual(res.decision, "ALLOW")
		self.assertEqual(res.reason, "no_budget_limit")

	def test_budget_exceeded_denies(self):
		import frappe as _f

		_f.db.get_value = lambda dt, name, fl=None, **kw: (
			SimpleNamespace(is_active=1, monthly_budget=1000, currency="EUR", budget_period="monthly")
			if dt == "Cost Center"
			else None
		)
		_SPEND["CC-3"] = 800

		res = cc_service.validate_budget("CC-3", amount=300)
		# 800 + 300 = 1100 > 1000
		self.assertEqual(res.decision, "DENY")
		self.assertIn("Bütçe", res.reason)

	def test_within_budget_allows(self):
		import frappe as _f

		_f.db.get_value = lambda dt, name, fl=None, **kw: (
			SimpleNamespace(is_active=1, monthly_budget=1000, currency="EUR", budget_period="monthly")
			if dt == "Cost Center"
			else None
		)
		_SPEND["CC-4"] = 200

		res = cc_service.validate_budget("CC-4", amount=300)
		# 200 + 300 = 500 < 1000
		self.assertEqual(res.decision, "ALLOW")
		self.assertEqual(res.current_spend, 200)
		self.assertEqual(res.remaining, 500)


if __name__ == "__main__":
	unittest.main()
