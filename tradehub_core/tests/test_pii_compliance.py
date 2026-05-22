"""FAZ 3.2 — PII Compliance engine testleri.

Senaryolar:
  1. No policy → ALLOW
  2. Permlevel insufficient → DENY
  3. Compliance Officer bypass → ALLOW
  4. KVKK last_4 → MASK
  5. GDPR block → DENY
  6. Cross-border block + user.region != target → DENY
  7. Cross-border block + user.region == target → MASK/ALLOW
  8. No matching jurisdiction rule → ALLOW
  9. Mask strategy "none" → ALLOW (no mask)
 10. Cache invalidation
 11. Audit log integration (default audit=True)
 12. Audit disabled mode (audit=False) — no decision log

  cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_pii_compliance
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


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Administrator")
	frappe.get_roles = lambda u: _USER_ROLES.get(u, [])

	def db_get_value(doctype, name_or_filters=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(name_or_filters), str(fieldname))
		return _DB.get(key)

	def get_all(doctype, filters=None, pluck=None, fields=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB.get(key, [])

	def get_doc(doctype, name=None):
		data = _DB.get(("get_doc", doctype, name), {})
		ns = SimpleNamespace(**data)
		ns.doctype = doctype
		ns.name = name
		# jurisdiction_rules as list of SimpleNamespace
		raw_rules = data.get("jurisdiction_rules", [])
		ns.jurisdiction_rules = [
			SimpleNamespace(**r) if isinstance(r, dict) else r for r in raw_rules
		]
		return ns

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=lambda *a, **kw: True,
		escape=lambda s: f"'{s}'",
		commit=lambda: None,
	)
	frappe.get_all = get_all
	frappe.get_doc = get_doc

	# Cache stub
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

	# audit module
	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.log_decision = lambda **kw: (_AUDIT_LOGS.append(dict(kw)) or "ADL")
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
	_install_frappe_stub()


os.environ.setdefault("REBAC_BASE_URL", "http://test:8080")
os.environ.setdefault("REBAC_API_KEY", "test")
os.environ.setdefault("REBAC_STORE_ID", "test-store")
os.environ.setdefault("REBAC_MODEL_ID", "test-model")


from tradehub_core.utils import pii_compliance as pii_comp  # noqa: E402


def _seed_policy(
	doctype: str,
	fieldname: str,
	permlevel: int,
	rules: list[dict],
	is_active: bool = True,
):
	"""Insert a policy lookup into the stub."""
	policy_name = f"PIIPOL-{doctype}-{fieldname}"
	# Policy lookup by (doctype, fieldname) filters
	_DB[
		("get_value", "PII Field Policy", f"{{'ref_doctype': '{doctype}', 'fieldname': '{fieldname}', 'is_active': 1}}", "name")
	] = policy_name if is_active else None

	# Full doc fetch
	_DB[("get_doc", "PII Field Policy", policy_name)] = {
		"ref_doctype": doctype,
		"fieldname": fieldname,
		"pii_category": "other",
		"permlevel": permlevel,
		"is_active": is_active,
		"jurisdiction_rules": rules,
		"description": "",
		"legal_basis": "",
	}


def _seed_region(region: str, jurisdiction: str):
	_DB[("get_value", "Region", region, "jurisdiction")] = jurisdiction


def _seed_user(user: str, roles: list[str], regions: list[str] | None = None):
	_USER_ROLES[user] = roles
	# pii_base.has_pii_access checks role-doctype-permlevel; we patch directly
	from tradehub_core.utils import pii as pii_base

	pii_base.has_pii_access = lambda u, dt, lvl: bool(roles)  # any role → True

	_DB[
		(
			"get_all",
			"Subscription Plan Region",
			f"{{'parent': '{user}', 'parenttype': 'User'}}",
			"region",
		)
	] = regions or []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class NoPolicyTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_seed_user("ahmet@x.com", ["Buyer Requisitioner"])

	def test_no_policy_returns_allow(self):
		res = pii_comp.evaluate_pii_access(
			"ahmet@x.com", "Some DocType", "some_field", target_region="EU"
		)
		self.assertEqual(res.decision, "ALLOW")
		self.assertEqual(res.reason, "no_policy")


class PermlevelTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_seed_region("EU", "GDPR")
		_seed_policy("User Profile", "tc_no", 2, [
			{"jurisdiction": "GDPR", "mask_strategy": "last_4", "cross_border_block": 0, "require_consent": 0},
		])

	def test_permlevel_insufficient_denies(self):
		_seed_user("guest@x.com", [])
		# pii_base.has_pii_access patch'i artık False döner (boş roles)

		res = pii_comp.evaluate_pii_access(
			"guest@x.com", "User Profile", "tc_no", target_region="EU"
		)
		self.assertEqual(res.decision, "DENY")
		self.assertIn("Permlevel", res.reason)


class BypassTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_seed_region("EU", "GDPR")
		_seed_policy("User Profile", "tc_no", 2, [
			{"jurisdiction": "GDPR", "mask_strategy": "block", "cross_border_block": 1, "require_consent": 0},
		])

	def test_compliance_officer_bypasses(self):
		_seed_user("co@firm.com", ["Compliance Officer"])

		res = pii_comp.evaluate_pii_access(
			"co@firm.com", "User Profile", "tc_no", target_region="EU"
		)
		self.assertEqual(res.decision, "ALLOW")
		self.assertEqual(res.reason, "bypass_role")

	def test_system_manager_bypasses(self):
		_seed_user("admin@x.com", ["System Manager"])
		res = pii_comp.evaluate_pii_access(
			"admin@x.com", "User Profile", "tc_no", target_region="EU"
		)
		self.assertEqual(res.decision, "ALLOW")


class JurisdictionRuleTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_seed_region("TR", "KVKK")
		_seed_region("DE", "GDPR")
		_seed_region("EG", "MENA")

	def test_kvkk_last_4_masks(self):
		_seed_policy("User Profile", "tc_no", 2, [
			{"jurisdiction": "KVKK", "mask_strategy": "last_4", "cross_border_block": 0, "require_consent": 0},
		])
		_seed_user("user@tr.com", ["Buyer Requisitioner"], regions=["TR"])
		res = pii_comp.evaluate_pii_access(
			"user@tr.com", "User Profile", "tc_no", target_region="TR"
		)
		self.assertEqual(res.decision, "MASK")
		self.assertEqual(res.mask_strategy, "last_4")

	def test_gdpr_block_denies(self):
		_seed_policy("User Profile", "medical_info", 3, [
			{"jurisdiction": "GDPR", "mask_strategy": "block", "cross_border_block": 0, "require_consent": 1},
		])
		_seed_user("doctor@de.com", ["Buyer Requisitioner"], regions=["DE"])
		res = pii_comp.evaluate_pii_access(
			"doctor@de.com", "User Profile", "medical_info", target_region="DE"
		)
		self.assertEqual(res.decision, "DENY")
		self.assertEqual(res.mask_strategy, "block")

	def test_no_matching_rule_allows(self):
		_seed_policy("User Profile", "tc_no", 2, [
			{"jurisdiction": "KVKK", "mask_strategy": "last_4", "cross_border_block": 0, "require_consent": 0},
		])
		_seed_user("user@eg.com", ["Buyer Requisitioner"], regions=["EG"])
		# Target = EG (MENA), policy only has KVKK rule
		res = pii_comp.evaluate_pii_access(
			"user@eg.com", "User Profile", "tc_no", target_region="EG"
		)
		self.assertEqual(res.decision, "ALLOW")
		self.assertIn("no_rule_for_jurisdiction", res.reason)

	def test_mask_strategy_none_allows(self):
		_seed_policy("User Profile", "email", 1, [
			{"jurisdiction": "OTHER", "mask_strategy": "none", "cross_border_block": 0, "require_consent": 0},
		])
		_seed_region("US", "OTHER")
		_seed_user("user@us.com", ["Buyer Requisitioner"], regions=["US"])
		res = pii_comp.evaluate_pii_access(
			"user@us.com", "User Profile", "email", target_region="US"
		)
		self.assertEqual(res.decision, "ALLOW")
		self.assertEqual(res.mask_strategy, "none")


class CrossBorderTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_seed_region("DE", "GDPR")
		_seed_policy("User Profile", "tc_no", 2, [
			{"jurisdiction": "GDPR", "mask_strategy": "last_4", "cross_border_block": 1, "require_consent": 0},
		])

	def test_cross_border_block_denies(self):
		# User region=TR, target region=DE (GDPR), cross-border-block=1
		_seed_user("user@tr.com", ["Buyer Requisitioner"], regions=["TR"])
		res = pii_comp.evaluate_pii_access(
			"user@tr.com", "User Profile", "tc_no", target_region="DE"
		)
		self.assertEqual(res.decision, "DENY")
		self.assertIn("Cross-border", res.reason)

	def test_cross_border_allowed_when_same_region(self):
		_seed_user("user@de.com", ["Buyer Requisitioner"], regions=["DE"])
		res = pii_comp.evaluate_pii_access(
			"user@de.com", "User Profile", "tc_no", target_region="DE"
		)
		# Cross-border-block satisfied (same region), strategy=last_4 → MASK
		self.assertEqual(res.decision, "MASK")
		self.assertEqual(res.mask_strategy, "last_4")


class CacheTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_invalidation_clears_cache_key(self):
		_seed_policy("User Profile", "iban", 2, [
			{"jurisdiction": "KVKK", "mask_strategy": "iban", "cross_border_block": 0, "require_consent": 0},
		])
		pii_comp.get_field_policy("User Profile", "iban")
		# Cache populated
		self.assertIn("pii_policy:User Profile:iban", _CACHE)

		pii_comp.invalidate_policy_cache("User Profile", "iban")
		self.assertNotIn("pii_policy:User Profile:iban", _CACHE)


class AuditTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_seed_region("TR", "KVKK")
		_seed_policy("User Profile", "phone", 1, [
			{"jurisdiction": "KVKK", "mask_strategy": "last_4", "cross_border_block": 0, "require_consent": 0},
		])
		_seed_user("user@tr.com", ["Buyer Requisitioner"], regions=["TR"])

	def test_audit_default_writes_log(self):
		pii_comp.evaluate_pii_access(
			"user@tr.com", "User Profile", "phone", target_region="TR"
		)
		self.assertEqual(len(_AUDIT_LOGS), 1)
		self.assertEqual(_AUDIT_LOGS[0]["rule_id"], "pii.access.mask")
		self.assertEqual(_AUDIT_LOGS[0]["severity"], "LOW")

	def test_audit_false_skips_log(self):
		pii_comp.evaluate_pii_access(
			"user@tr.com", "User Profile", "phone", target_region="TR", audit=False
		)
		self.assertEqual(len(_AUDIT_LOGS), 0)

	def test_deny_logs_medium_severity(self):
		_seed_policy("User Profile", "medical_info", 3, [
			{"jurisdiction": "KVKK", "mask_strategy": "block", "cross_border_block": 0, "require_consent": 1},
		])
		_seed_user("user2@tr.com", ["Buyer Requisitioner"], regions=["TR"])

		pii_comp.evaluate_pii_access(
			"user2@tr.com", "User Profile", "medical_info", target_region="TR"
		)
		deny_logs = [log for log in _AUDIT_LOGS if log["decision"] == "DENY"]
		self.assertEqual(len(deny_logs), 1)
		self.assertEqual(deny_logs[0]["severity"], "MEDIUM")
		self.assertEqual(deny_logs[0]["rule_id"], "pii.access.deny")


if __name__ == "__main__":
	unittest.main()
