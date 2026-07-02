"""Faz 2 — Guardrail katmanı (L1 hard_deny + L2 guardrail) unit testleri.

permissions ve entitlement SAHTE modüllerle enjekte edilir → gerçek Frappe/DB
gerektirmez; CI authz gate'inde koşar.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

# ── Kontrol edilebilir state ──
_S = {
	"privileged": {},  # user -> bool
	"tenant": {},  # user -> store name | None
	"kyc_ok": True,
	"aml_ok": True,
	"sub_ok": True,
	"features": {},  # feature -> bool
}


def _install_stubs() -> None:
	# minimal frappe (pdp/import 'import frappe' için)
	if "frappe" not in sys.modules:
		f = types.ModuleType("frappe")
		f.log_error = lambda *a, **k: None
		f.session = types.SimpleNamespace(user="x@x")
		f.generate_hash = lambda length=12: "d" * length
		sys.modules["frappe"] = f

	# sahte permissions
	perm = types.ModuleType("tradehub_core.permissions")
	perm.SUBSCRIPTION_GATED_DOCTYPES = frozenset(
		{"Listing", "Order", "Admin Seller Profile", "Seller Inquiry"}
	)
	perm._is_platform_full_access = lambda user, ptype=None: _S["privileged"].get(user, False)
	perm._get_seller_profile_name = lambda user: _S["tenant"].get(user)
	perm._check_kyc_verification = lambda user, doctype: _S["kyc_ok"]
	perm._check_aml_sanctions = lambda user, doctype: _S["aml_ok"]
	perm._check_subscription_active = lambda tenant, doctype, ptype: _S["sub_ok"]
	sys.modules["tradehub_core.permissions"] = perm

	# sahte entitlement
	ent = types.ModuleType("tradehub_core.entitlement")
	ent.has_feature = lambda store, feature: _S["features"].get(feature, False)
	sys.modules["tradehub_core.entitlement"] = ent


_install_stubs()

from tradehub_core.authz import guardrail  # noqa: E402


def _reset():
	_S["privileged"] = {}
	_S["tenant"] = {"seller@x": "STORE-A"}
	_S["kyc_ok"] = True
	_S["aml_ok"] = True
	_S["sub_ok"] = True
	_S["features"] = {}
	_install_stubs()


class HardDenyTests(unittest.TestCase):
	def setUp(self):
		_reset()

	def test_kyc_missing_denies(self):
		_S["kyc_ok"] = False
		r = guardrail.hard_deny("seller@x", "read", "Seller Balance", None, None, {})
		self.assertTrue(r.deny)
		self.assertEqual(r.reason, "kyc_required")

	def test_aml_hit_denies(self):
		_S["aml_ok"] = False
		r = guardrail.hard_deny("seller@x", "read", "Payment Intent", None, None, {})
		self.assertTrue(r.deny)
		self.assertEqual(r.reason, "aml_blocked")

	def test_subscription_suspended_write_denies(self):
		_S["sub_ok"] = False
		r = guardrail.hard_deny("seller@x", "create", "Listing", None, None, {})
		self.assertTrue(r.deny)
		self.assertEqual(r.reason, "subscription_suspended")

	def test_subscription_suspended_read_allows(self):
		# read gate'lenmez — suspended satıcı hâlâ okuyabilir (audit)
		_S["sub_ok"] = False
		r = guardrail.hard_deny("seller@x", "read", "Listing", None, None, {})
		self.assertFalse(r.deny)

	def test_subscription_suspended_non_gated_allows(self):
		_S["sub_ok"] = False
		r = guardrail.hard_deny("seller@x", "create", "CRM Lead", None, None, {})
		self.assertFalse(r.deny)

	def test_no_tenant_skips_subscription(self):
		# store tenant yoksa subscription değerlendirilemez → allow
		_S["sub_ok"] = False
		_S["tenant"] = {}
		r = guardrail.hard_deny("seller@x", "create", "Listing", None, None, {})
		self.assertFalse(r.deny)

	def test_administrator_bypass(self):
		_S["kyc_ok"] = False
		_S["sub_ok"] = False
		r = guardrail.hard_deny("Administrator", "create", "Seller Balance", None, None, {})
		self.assertFalse(r.deny)

	def test_platform_full_access_bypass(self):
		_S["privileged"]["admin@x"] = True
		_S["kyc_ok"] = False
		r = guardrail.hard_deny("admin@x", "read", "Seller Balance", None, None, {})
		self.assertFalse(r.deny)

	def test_all_pass_allows(self):
		r = guardrail.hard_deny("seller@x", "create", "Listing", None, None, {})
		self.assertFalse(r.deny)

	def test_no_doctype_allows(self):
		r = guardrail.hard_deny("seller@x", "read", None, None, None, {})
		self.assertFalse(r.deny)


class GuardrailFeatureTests(unittest.TestCase):
	def setUp(self):
		_reset()

	def test_feature_not_in_plan_denies(self):
		# ("Order","create") → "core_commerce" (registry)
		_S["features"] = {"core_commerce": False}
		r = guardrail.guardrail("seller@x", "create", "Order", None, None, {})
		self.assertTrue(r.deny)
		self.assertEqual(r.reason, "feature_not_in_plan")

	def test_feature_in_plan_allows(self):
		_S["features"] = {"core_commerce": True}
		r = guardrail.guardrail("seller@x", "create", "Order", None, None, {})
		self.assertFalse(r.deny)

	def test_non_feature_gated_action_allows(self):
		# ("Listing","read") feature-gated değil
		r = guardrail.guardrail("seller@x", "read", "Listing", None, None, {})
		self.assertFalse(r.deny)

	def test_no_store_tenant_skips(self):
		_S["tenant"] = {}
		_S["features"] = {"core_commerce": False}
		r = guardrail.guardrail("seller@x", "create", "Order", None, None, {})
		self.assertFalse(r.deny)  # değerlendirilemez → base RBAC'a bırak

	def test_administrator_bypass(self):
		_S["features"] = {"core_commerce": False}
		r = guardrail.guardrail("Administrator", "create", "Order", None, None, {})
		self.assertFalse(r.deny)


if __name__ == "__main__":
	unittest.main()
