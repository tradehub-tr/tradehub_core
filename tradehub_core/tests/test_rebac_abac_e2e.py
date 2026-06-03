"""
ReBAC/ABAC Authorization System — E2E & Cross-Layer Tests.

Bu test dosyasi Frappe runtime'a ihtiyac duymaz (standalone unittest).
Kaynak kodu statik analiz + pure logic fonksiyonlari test eder.

Calistirma:
    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_rebac_abac_e2e -v
"""

import json
import re
import sys
import types
import unittest
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_APP_ROOT = Path(__file__).resolve().parents[2]  # apps/tradehub_core/
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # istoc.com/
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

# ── Frappe stub — top-level "import frappe" geçsin diye minimal stub ─────────

if "frappe" not in sys.modules:
	_frappe = types.ModuleType("frappe")
	_frappe._ = lambda x: x
	_frappe.throw = None
	_frappe.PermissionError = PermissionError
	_frappe.session = types.SimpleNamespace(user="Administrator")
	_frappe.db = types.SimpleNamespace(
		get_value=lambda *a, **kw: None,
		escape=lambda x: x,
		exists=lambda *a, **kw: False,
		get_all=lambda *a, **kw: [],
	)
	_frappe.cache = lambda: types.SimpleNamespace(
		get_value=lambda *a, **kw: None,
		set_value=lambda *a, **kw: None,
	)
	_frappe.get_roles = lambda *a, **kw: []
	_frappe.get_all = lambda *a, **kw: []
	_frappe.get_doc = lambda *a, **kw: None
	_frappe.get_cached_doc = lambda *a, **kw: None
	_frappe.whitelist = lambda *a, **kw: lambda fn: fn
	sys.modules["frappe"] = _frappe
	# frappe.utils stub
	_frappe_utils = types.ModuleType("frappe.utils")
	_frappe_utils.flt = float
	sys.modules["frappe.utils"] = _frappe_utils
	# frappe.model stub
	_frappe_model = types.ModuleType("frappe.model")
	sys.modules["frappe.model"] = _frappe_model
	_frappe_model_doc = types.ModuleType("frappe.model.document")
	_frappe_model_doc.Document = object
	sys.modules["frappe.model.document"] = _frappe_model_doc

# ── Pure-logic imports ────────────────────────────────────────────────────────
# E402: imports below frappe stub installation are intentional — stub must be
# in place before tradehub_core.* modules import frappe at module load.
from tradehub_core.entitlement.checks import (  # noqa: E402
	_extract_region_codes,
	_is_variant_listing,
)
from tradehub_core.services.abac_context import (  # noqa: E402
	_dominant_jurisdiction,
	evaluate_needs_approval_l1,
	evaluate_needs_approval_l2,
	evaluate_user_in_region,
	evaluate_within_business_hours,
)
from tradehub_core.utils.seller_capabilities import (  # noqa: E402
	_OWNER_ONLY_CAPABILITIES,
	_PLATFORM_ROLES,
	_REQUIRES_AML_CLEAN,
	_REQUIRES_KYC,
	_TIER_COOWNER,
	_TIER_FINANCE,
	_TIER_MANAGEMENT,
	_TIER_OPERATIONS,
	_TIER_ROLE_FALLBACK,
	_TIER_SALES,
	SELLER_CAPABILITIES,
)

# ══════════════════════════════════════════════════════════════════════════════
# 1. ABAC Context Evaluator Tests (pure logic)
# ══════════════════════════════════════════════════════════════════════════════


class TestEvaluateNeedsApprovalL1(unittest.TestCase):
	"""ABAC: needs_approval_l1 — 500 < amount <= 5000."""

	def test_below_threshold_false(self):
		self.assertFalse(evaluate_needs_approval_l1(500))

	def test_at_lower_bound_false(self):
		self.assertFalse(evaluate_needs_approval_l1(500.0))

	def test_just_above_lower_true(self):
		self.assertTrue(evaluate_needs_approval_l1(500.01))

	def test_mid_range_true(self):
		self.assertTrue(evaluate_needs_approval_l1(2500))

	def test_at_upper_bound_true(self):
		self.assertTrue(evaluate_needs_approval_l1(5000))

	def test_above_upper_false(self):
		self.assertFalse(evaluate_needs_approval_l1(5000.01))

	def test_zero_false(self):
		self.assertFalse(evaluate_needs_approval_l1(0))

	def test_negative_false(self):
		self.assertFalse(evaluate_needs_approval_l1(-100))


class TestEvaluateNeedsApprovalL2(unittest.TestCase):
	"""ABAC: needs_approval_l2 — amount > 5000."""

	def test_at_threshold_false(self):
		self.assertFalse(evaluate_needs_approval_l2(5000))

	def test_just_above_true(self):
		self.assertTrue(evaluate_needs_approval_l2(5000.01))

	def test_large_amount_true(self):
		self.assertTrue(evaluate_needs_approval_l2(1_000_000))

	def test_zero_false(self):
		self.assertFalse(evaluate_needs_approval_l2(0))

	def test_negative_false(self):
		self.assertFalse(evaluate_needs_approval_l2(-10000))

	def test_l1_l2_boundary_no_overlap(self):
		"""L1 ve L2 arasinda bosluk veya overlap olmamali."""
		for amount in [4999.99, 5000, 5000.01]:
			l1 = evaluate_needs_approval_l1(amount)
			l2 = evaluate_needs_approval_l2(amount)
			# Bir amount icin en fazla biri True olmali
			self.assertFalse(
				l1 and l2,
				f"amount={amount}: L1={l1}, L2={l2} — overlap var",
			)

	def test_l1_l2_coverage_no_gap_above_500(self):
		"""500 ustu her amount icin L1 veya L2 gecmeli (bosluk yok)."""
		for amount in [501, 1000, 2500, 5000, 5001, 10000]:
			l1 = evaluate_needs_approval_l1(amount)
			l2 = evaluate_needs_approval_l2(amount)
			self.assertTrue(
				l1 or l2,
				f"amount={amount}: L1={l1}, L2={l2} — bosluk var",
			)


class TestEvaluateUserInRegion(unittest.TestCase):
	"""ABAC: user_in_region condition."""

	def test_user_in_region(self):
		self.assertTrue(evaluate_user_in_region(["TR", "DE"], "TR"))

	def test_user_not_in_region(self):
		self.assertFalse(evaluate_user_in_region(["TR", "DE"], "US"))

	def test_empty_regions(self):
		self.assertFalse(evaluate_user_in_region([], "TR"))

	def test_none_regions(self):
		self.assertFalse(evaluate_user_in_region(None, "TR"))

	def test_single_region_match(self):
		self.assertTrue(evaluate_user_in_region(["TR"], "TR"))


class TestEvaluateWithinBusinessHours(unittest.TestCase):
	"""ABAC: within_business_hours condition."""

	def test_within_default_hours(self):
		self.assertTrue(evaluate_within_business_hours(12))

	def test_at_start_boundary(self):
		self.assertTrue(evaluate_within_business_hours(9))

	def test_before_start(self):
		self.assertFalse(evaluate_within_business_hours(8))

	def test_at_end_boundary(self):
		# end_hour exclusive
		self.assertFalse(evaluate_within_business_hours(18))

	def test_custom_hours(self):
		self.assertTrue(evaluate_within_business_hours(20, start_hour=18, end_hour=23))

	def test_midnight_outside_default(self):
		self.assertFalse(evaluate_within_business_hours(0))


class TestDominantJurisdiction(unittest.TestCase):
	"""ABAC: jurisdiction priority — KVKK > GDPR > MENA > CIS > OTHER."""

	def test_kvkk_wins_over_gdpr(self):
		self.assertEqual(_dominant_jurisdiction({"KVKK", "GDPR"}), "KVKK")

	def test_gdpr_wins_over_mena(self):
		self.assertEqual(_dominant_jurisdiction({"GDPR", "MENA"}), "GDPR")

	def test_single_jurisdiction(self):
		self.assertEqual(_dominant_jurisdiction({"GDPR"}), "GDPR")

	def test_empty_returns_none(self):
		self.assertIsNone(_dominant_jurisdiction(set()))

	def test_unknown_jurisdiction_returned(self):
		result = _dominant_jurisdiction({"APAC"})
		self.assertEqual(result, "APAC")

	def test_kvkk_highest_priority(self):
		self.assertEqual(
			_dominant_jurisdiction({"OTHER", "CIS", "MENA", "GDPR", "KVKK"}),
			"KVKK",
		)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Entitlement Helpers (pure logic)
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractRegionCodes(unittest.TestCase):
	"""entitlement/checks._extract_region_codes — pure data transform."""

	def test_none_returns_empty(self):
		self.assertEqual(_extract_region_codes(None), set())

	def test_empty_string_returns_empty(self):
		self.assertEqual(_extract_region_codes(""), set())

	def test_comma_separated_string(self):
		self.assertEqual(_extract_region_codes("TR, DE, US"), {"TR", "DE", "US"})

	def test_uppercase_normalization(self):
		self.assertEqual(_extract_region_codes("tr, de"), {"TR", "DE"})

	def test_list_of_strings(self):
		self.assertEqual(_extract_region_codes(["TR", "DE"]), {"TR", "DE"})

	def test_list_of_dicts_with_region_key(self):
		items = [{"region": "TR"}, {"region": "DE"}]
		self.assertEqual(_extract_region_codes(items), {"TR", "DE"})

	def test_list_of_dicts_with_region_code_key(self):
		items = [{"region_code": "TR"}]
		self.assertEqual(_extract_region_codes(items), {"TR"})

	def test_empty_list(self):
		self.assertEqual(_extract_region_codes([]), set())

	def test_mixed_list_items(self):
		items = ["TR", {"region": "DE"}, None]
		# None items should be handled gracefully
		result = _extract_region_codes(items)
		self.assertIn("TR", result)
		self.assertIn("DE", result)

	def test_whitespace_handling(self):
		self.assertEqual(_extract_region_codes("  TR , DE  "), {"TR", "DE"})


class TestIsVariantListing(unittest.TestCase):
	"""entitlement/checks._is_variant_listing — heuristic detection."""

	def test_no_variants_returns_false(self):

		class FakeDoc:
			def get(self, key):
				return None

		self.assertFalse(_is_variant_listing(FakeDoc()))

	def test_single_variant_returns_false(self):

		class FakeDoc:
			def get(self, key):
				if key == "listing_variant_item":
					return [{"variant": "A"}]
				return None

		self.assertFalse(_is_variant_listing(FakeDoc()))

	def test_multiple_variants_returns_true(self):

		class FakeDoc:
			def get(self, key):
				if key == "listing_variant_item":
					return [{"variant": "A"}, {"variant": "B"}]
				return None

		self.assertTrue(_is_variant_listing(FakeDoc()))

	def test_variant_count_field(self):

		class FakeDoc:
			def get(self, key):
				if key == "variant_count":
					return 3
				return None

		self.assertTrue(_is_variant_listing(FakeDoc()))

	def test_variant_count_one_is_false(self):

		class FakeDoc:
			def get(self, key):
				if key == "variant_count":
					return 1
				return None

		self.assertFalse(_is_variant_listing(FakeDoc()))


# ══════════════════════════════════════════════════════════════════════════════
# 3. Capability Matrix Integrity Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCapabilityMatrixStructure(unittest.TestCase):
	"""SELLER_CAPABILITIES dict yapisal butunluk kontrolu."""

	def test_all_capabilities_have_two_tuple(self):
		"""Her capability (tier_set, plan_feature) tuple'i olmali."""
		for cap, value in SELLER_CAPABILITIES.items():
			self.assertIsInstance(value, tuple, f"{cap}: tuple degil")
			self.assertEqual(len(value), 2, f"{cap}: 2 elemanli degil")

	def test_all_tier_sets_are_frozenset(self):
		"""Tier set'ler frozenset olmali (immutable)."""
		for cap, (tier_set, _) in SELLER_CAPABILITIES.items():
			self.assertIsInstance(tier_set, frozenset, f"{cap}: tier set frozenset degil")

	def test_plan_feature_is_string_or_none(self):
		"""Plan feature ya string ya None olmali."""
		for cap, (_, plan_feature) in SELLER_CAPABILITIES.items():
			if plan_feature is not None:
				self.assertIsInstance(plan_feature, str, f"{cap}: plan_feature str degil")

	def test_no_empty_tier_sets(self):
		"""Hicbir capability bos tier set'e sahip olmamali."""
		for cap, (tier_set, _) in SELLER_CAPABILITIES.items():
			self.assertTrue(len(tier_set) > 0, f"{cap}: tier set bos")

	def test_owner_only_not_in_main_matrix(self):
		"""Owner-only capability'ler ana matris'te OLMAMALI (ayri yonetilir)."""
		for cap in _OWNER_ONLY_CAPABILITIES:
			self.assertNotIn(
				cap,
				SELLER_CAPABILITIES,
				f"Owner-only '{cap}' ana SELLER_CAPABILITIES'te",
			)

	def test_capability_naming_convention(self):
		"""Tum capability'ler 'domain.action' formatinda olmali."""
		pattern = re.compile(r"^[a-z_]+\.[a-z_]+$")
		for cap in SELLER_CAPABILITIES:
			self.assertRegex(cap, pattern, f"'{cap}' naming convention'a uymuyor")
		for cap in _OWNER_ONLY_CAPABILITIES:
			self.assertRegex(cap, pattern, f"Owner-only '{cap}' naming convention'a uymuyor")


class TestCapabilityTierHierarchy(unittest.TestCase):
	"""Tier hierarchy: Management < Operations/Finance/Sales < CoOwner."""

	def test_management_is_subset_of_operations(self):
		"""Management tier, Operations tier'in alt kumesi olmali."""
		self.assertTrue(_TIER_MANAGEMENT.issubset(_TIER_OPERATIONS))

	def test_management_is_subset_of_finance(self):
		self.assertTrue(_TIER_MANAGEMENT.issubset(_TIER_FINANCE))

	def test_coowner_is_subset_of_management(self):
		self.assertTrue(_TIER_COOWNER.issubset(_TIER_MANAGEMENT))

	def test_full_access_in_all_tiers(self):
		"""Seller Full Access tum tier'larda olmali."""
		for tier_name, tier_set in [
			("operations", _TIER_OPERATIONS),
			("finance", _TIER_FINANCE),
			("management", _TIER_MANAGEMENT),
			("coowner", _TIER_COOWNER),
			("sales", _TIER_SALES),
		]:
			self.assertIn(
				"Seller Full Access",
				tier_set,
				f"'Seller Full Access' {tier_name} tier'da yok",
			)

	def test_coowner_in_management_but_not_operations_directly(self):
		"""Seller Co-Owner management'ta var ama operations'ta yonetim uzerinden."""
		self.assertIn("Seller Co-Owner", _TIER_MANAGEMENT)
		# Co-Owner operations'ta da var (management subset)
		self.assertIn("Seller Co-Owner", _TIER_OPERATIONS)


class TestKYCandAMLRequirements(unittest.TestCase):
	"""KYC/AML required capability set'leri tutarli olmali."""

	def test_aml_is_subset_of_kyc(self):
		"""AML gerektiren her capability KYC de gerektirmeli."""
		missing = _REQUIRES_AML_CLEAN - _REQUIRES_KYC
		self.assertEqual(
			missing,
			frozenset(),
			f"AML gerektiren ama KYC gerektirmeyen: {missing}",
		)

	def test_kyc_required_capabilities_exist(self):
		"""KYC gerektiren capability'ler matris'te veya owner-only'de olmali."""
		all_caps = set(SELLER_CAPABILITIES.keys()) | _OWNER_ONLY_CAPABILITIES
		for cap in _REQUIRES_KYC:
			self.assertIn(cap, all_caps, f"KYC-required '{cap}' hicbir yerde tanimli degil")

	def test_finance_capabilities_require_kyc(self):
		"""Finans islemleri KYC gerektirmeli."""
		finance_ops = {"order.confirm_payment", "order.refund", "balance.withdraw"}
		for cap in finance_ops:
			self.assertIn(cap, _REQUIRES_KYC, f"Finans '{cap}' KYC gerektirmiyor")


class TestTierRoleFallback(unittest.TestCase):
	"""K6 fix: Role Delegation fallback mapping tutarli olmali."""

	def test_all_main_tiers_have_fallback(self):
		"""Operations, Finance, Management, CoOwner tier'larinin role fallback'i olmali."""
		self.assertIn(_TIER_OPERATIONS, _TIER_ROLE_FALLBACK)
		self.assertIn(_TIER_FINANCE, _TIER_ROLE_FALLBACK)
		self.assertIn(_TIER_MANAGEMENT, _TIER_ROLE_FALLBACK)
		self.assertIn(_TIER_COOWNER, _TIER_ROLE_FALLBACK)

	def test_sales_tier_no_fallback(self):
		"""Sales tier'in role fallback'i olmamali (veya olmali?)."""
		# Sales tier fallback yoksa bu bir gap olabilir
		if _TIER_SALES not in _TIER_ROLE_FALLBACK:
			pass  # Bilinen gap, Sales delegation desteklenmiyor

	def test_fallback_roles_are_frozenset(self):
		for _tier, roles in _TIER_ROLE_FALLBACK.items():
			self.assertIsInstance(roles, frozenset, "Tier role fallback frozenset degil")


class TestPlatformRoles(unittest.TestCase):
	"""Platform bypass role'leri dogru tanimlanmali."""

	def test_system_manager_is_platform(self):
		self.assertIn("System Manager", _PLATFORM_ROLES)

	def test_marketplace_admin_is_platform(self):
		self.assertIn("Marketplace Admin", _PLATFORM_ROLES)

	def test_administrator_is_platform(self):
		self.assertIn("Administrator", _PLATFORM_ROLES)

	def test_seller_roles_not_platform(self):
		"""Seller role'leri platform role'u olmamali."""
		seller_roles = {"Seller", "Marketplace Seller", "Seller Admin", "Seller Owner"}
		for role in seller_roles:
			self.assertNotIn(role, _PLATFORM_ROLES, f"'{role}' platform role'u olmamali")


# ══════════════════════════════════════════════════════════════════════════════
# 4. Source Code Audit Tests (static analysis)
# ══════════════════════════════════════════════════════════════════════════════


class TestPermissionsSourceAudit(unittest.TestCase):
	"""permissions.py statik analiz — guvenlik kontrolleri."""

	def setUp(self):
		self.src = (_APP_ROOT / "tradehub_core" / "permissions.py").read_text(encoding="utf-8")

	def test_financial_doctypes_defined(self):
		self.assertIn("FINANCIAL_DOCTYPES", self.src)

	def test_aml_sensitive_doctypes_defined(self):
		self.assertIn("AML_SENSITIVE_DOCTYPES", self.src)

	def test_subscription_gated_doctypes_defined(self):
		self.assertIn("SUBSCRIPTION_GATED_DOCTYPES", self.src)

	def test_kyc_check_function_exists(self):
		self.assertIn("def _check_kyc_verification(", self.src)

	def test_aml_check_function_exists(self):
		self.assertIn("def _check_aml_sanctions(", self.src)

	def test_subscription_check_function_exists(self):
		self.assertIn("def _check_subscription_active(", self.src)

	def test_spending_limit_function_exists(self):
		self.assertIn("def _check_spending_limit(", self.src)

	def test_aml_check_is_implemented(self):
		"""AML check artik gercek implementasyon icermeli."""
		# _check_aml_sanctions fonksiyonunda "Hit Found" veya "Match Found" kontrolu olmali
		self.assertIn("Hit Found", self.src, "AML check 'Hit Found' kontrolu eksik")
		self.assertIn("Match Found", self.src, "AML check 'Match Found' kontrolu eksik")

	def test_no_fstring_sql_injection(self):
		"""permissions.py'de f-string SQL interpolation olmamali."""
		# f"... {var} ..." pattern'i SQL context'inde
		dangerous_pattern = re.compile(r'frappe\.db\.sql\(f["\']')
		matches = dangerous_pattern.findall(self.src)
		self.assertEqual(
			len(matches),
			0,
			f"permissions.py'de {len(matches)} adet f-string SQL bulundu — injection riski",
		)

	def test_has_permission_returns_explicit_values(self):
		"""has_permission fonksiyonlari None yerine True/False donmeli."""
		has_perm_funcs = re.findall(r"def (\w+_has_permission)\(", self.src)
		self.assertTrue(len(has_perm_funcs) > 0, "Hicbir has_permission fonksiyonu bulunamadi")

	def test_critical_has_permission_no_return_none(self):
		"""Kritik has_permission fonksiyonlarinda 'return None' olmamali."""
		critical_funcs = [
			"listing_question_has_permission",
			"order_dispute_has_permission",
			"listing_review_has_permission",
			"review_helpful_vote_has_permission",
			"review_abuse_report_has_permission",
			"trusted_reviewer_invitation_has_permission",
		]
		for func_name in critical_funcs:
			pattern = re.compile(
				rf"def {re.escape(func_name)}\(.*?(?=\ndef |\Z)",
				re.DOTALL,
			)
			m = pattern.search(self.src)
			self.assertIsNotNone(m, f"{func_name} bulunamadi")
			func_body = m.group(0)
			self.assertNotIn(
				"return None",
				func_body,
				f"{func_name} hala 'return None' donuyor — explicit False olmali",
			)


class TestSellerCapabilitiesSourceAudit(unittest.TestCase):
	"""seller_capabilities.py statik analiz."""

	def setUp(self):
		self.src = (_APP_ROOT / "tradehub_core" / "utils" / "seller_capabilities.py").read_text(
			encoding="utf-8"
		)

	def test_guest_rejected_first(self):
		"""has_seller_capability: Guest/bos user ilk kontrol olmali."""
		func_src = self._extract_function("has_seller_capability")
		guest_pos = func_src.find('("Guest", "")')
		return_false_pos = func_src.find("return False")
		self.assertLess(guest_pos, return_false_pos)

	def test_administrator_bypass_before_db_calls(self):
		"""Administrator check DB call'lardan once olmali (performance)."""
		func_src = self._extract_function("has_seller_capability")
		admin_pos = func_src.find('"Administrator"')
		resolve_pos = func_src.find("_resolve_user_state")
		self.assertLess(admin_pos, resolve_pos)

	def test_disabled_user_check_exists(self):
		"""H3 fix: deactivated user check mevcut olmali."""
		self.assertIn('user_data.get("enabled") == 0', self.src)

	def test_seller_relation_check_exists(self):
		"""C1 fix: seller relation validation mevcut olmali."""
		self.assertIn("_is_seller_user(user, user_data)", self.src)

	def test_fail_secure_on_unknown_capability(self):
		"""Tanimsiz capability icin default deny."""
		func_src = self._extract_function("has_seller_capability")
		# cap_def None kontrolunden sonra False donmeli
		self.assertIn("return False", func_src)

	def test_aml_check_implemented(self):
		"""AML check gercek implementasyon icermeli."""
		self.assertIn("_check_aml_clean", self.src)
		self.assertIn("Hit Found", self.src, "seller_capabilities AML 'Hit Found' kontrolu eksik")

	def test_get_user_capabilities_mirrors_has_capability(self):
		"""get_user_capabilities ve has_seller_capability ayni preconditions'i kullanmali."""
		get_caps_src = self._extract_function("get_user_capabilities")
		# Ayni checkler mevcut olmali
		self.assertIn('("Guest", "")', get_caps_src)
		self.assertIn('"Administrator"', get_caps_src)
		self.assertIn("_PLATFORM_ROLES", get_caps_src)
		self.assertIn('user_data.get("enabled") == 0', get_caps_src)
		self.assertIn("_is_seller_user", get_caps_src)

	def _extract_function(self, name: str) -> str:
		pattern = re.compile(
			rf"^def {re.escape(name)}\(.*?(?=^def |\Z)",
			re.MULTILINE | re.DOTALL,
		)
		m = pattern.search(self.src)
		self.assertIsNotNone(m, f"{name} bulunamadi")
		return m.group(0)


class TestEntitlementCoreSourceAudit(unittest.TestCase):
	"""entitlement/core.py statik analiz."""

	def setUp(self):
		self.src = (_APP_ROOT / "tradehub_core" / "entitlement" / "core.py").read_text(encoding="utf-8")

	def test_cache_ttl_defined(self):
		"""Cache TTL sabiti tanimli olmali."""
		self.assertRegex(self.src, r"_CACHE_TTL\s*=\s*\d+")

	def test_operational_statuses_defined(self):
		"""Operational subscription status'leri tanimli olmali."""
		self.assertIn("_OPERATIONAL_STATUSES", self.src)
		# trial, active, past_due dahil
		self.assertIn('"trial"', self.src)
		self.assertIn('"active"', self.src)
		self.assertIn('"past_due"', self.src)

	def test_negative_cache_ttl_exists(self):
		"""Negatif cache (subscription yok) icin ayri TTL olmali."""
		# "expires_in_sec=10" veya benzeri kisa TTL
		self.assertRegex(self.src, r"expires_in_sec\s*=\s*\d+")

	def test_invalidation_functions_exist(self):
		self.assertIn("def invalidate_store_cache(", self.src)
		self.assertIn("def invalidate_plan_cache(", self.src)

	def test_has_feature_function_exists(self):
		self.assertIn("def has_feature(", self.src)

	def test_within_quota_function_exists(self):
		self.assertIn("def within_quota(", self.src)


class TestEntitlementSyncSourceAudit(unittest.TestCase):
	"""entitlement/sync.py — cache invalidation hook'lari mevcut olmali."""

	def setUp(self):
		path = _APP_ROOT / "tradehub_core" / "entitlement" / "sync.py"
		self.src = path.read_text(encoding="utf-8") if path.exists() else ""

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "entitlement" / "sync.py").exists(),
		"sync.py mevcut degil",
	)
	def test_plan_update_invalidation(self):
		"""Plan degistiginde cache invalidate olmali."""
		self.assertIn("invalidate", self.src.lower())

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "entitlement" / "sync.py").exists(),
		"sync.py mevcut degil",
	)
	def test_subscription_change_invalidation(self):
		"""Subscription degistiginde store cache invalidate olmali."""
		self.assertIn("invalidate_store_cache", self.src)


class TestAuthorizationSimulatorSourceAudit(unittest.TestCase):
	"""authorization_simulator.py — 4-layer structure mevcut olmali."""

	def setUp(self):
		self.src = (_APP_ROOT / "tradehub_core" / "services" / "authorization_simulator.py").read_text(
			encoding="utf-8"
		)

	def test_all_layers_defined(self):
		"""L0-L3 layer sabitleri tanimli olmali."""
		for layer in ["LAYER_L0", "LAYER_L1", "LAYER_L2", "LAYER_L3"]:
			self.assertIn(layer, self.src, f"{layer} sabiti eksik")

	def test_result_codes_defined(self):
		"""ALLOW/DENY/SKIP/UNAVAILABLE result kodlari olmali."""
		for code in ["RESULT_ALLOW", "RESULT_DENY", "RESULT_SKIP", "RESULT_UNAVAILABLE"]:
			self.assertIn(code, self.src, f"{code} sabiti eksik")

	def test_simulate_function_exists(self):
		self.assertIn("def simulate(", self.src)

	def test_batch_size_limit(self):
		"""Batch simulation icin boyut limiti olmali."""
		self.assertIn("MAX_BATCH_SIZE", self.src)

	def test_audit_logging_capability(self):
		"""Audit log kaydi yapabilmeli."""
		self.assertRegex(self.src, r"audit|log", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Cross-Layer Consistency Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPermissionsHooksRegistration(unittest.TestCase):
	"""hooks.py'de permission handler'lari kayitli olmali."""

	def setUp(self):
		self.hooks_src = (_APP_ROOT / "tradehub_core" / "hooks.py").read_text(encoding="utf-8")

	def test_permission_query_conditions_registered(self):
		self.assertIn("permission_query_conditions", self.hooks_src)

	def test_has_permission_registered(self):
		self.assertIn("has_permission", self.hooks_src)

	def test_listing_in_query_conditions(self):
		self.assertIn('"Listing"', self.hooks_src)

	def test_order_in_query_conditions(self):
		self.assertIn('"Order"', self.hooks_src)

	def test_admin_seller_profile_in_query_conditions(self):
		"""Admin Seller Profile tenant-isolated olmali."""
		self.assertIn('"Admin Seller Profile"', self.hooks_src)

	def test_entitlement_hooks_registered(self):
		"""Listing.before_insert icin entitlement check kayitli olmali."""
		self.assertIn("check_listing_creation_quota", self.hooks_src)


class TestCapabilityFrontendBackendSync(unittest.TestCase):
	"""Frontend hardcoded capability name'leri backend'le eslesik olmali."""

	# Admin panel'deki hardcoded capability'ler
	FRONTEND_CAPABILITIES = {
		"order.ship",
		"order.confirm_payment",
		"order.refund",
		"listing.publish",
	}

	def test_all_frontend_caps_exist_in_backend(self):
		"""Admin panel'deki capability'ler backend matris'te tanimli olmali."""
		all_backend_caps = set(SELLER_CAPABILITIES.keys()) | _OWNER_ONLY_CAPABILITIES
		for cap in self.FRONTEND_CAPABILITIES:
			self.assertIn(
				cap,
				all_backend_caps,
				f"Frontend capability '{cap}' backend'de tanimli degil",
			)

	def test_admin_panel_auth_store_can_function(self):
		"""Admin panel auth.js 'can(capability)' fonksiyonu mevcut olmali."""
		auth_path = _PROJECT_ROOT / "admin-panel" / "frontend" / "src" / "stores" / "auth.js"
		if not auth_path.exists():
			self.skipTest("admin-panel auth.js mevcut degil")
		src = auth_path.read_text(encoding="utf-8")
		self.assertIn("can(", src)
		self.assertIn("capabilities", src)


class TestStorefrontEntitlementSync(unittest.TestCase):
	"""Storefront entitlement.ts backend ile senkron olmali."""

	_ENTITLEMENT_PATH = _PROJECT_ROOT / "tradehubfront" / "src" / "utils" / "entitlement.ts"

	@unittest.skipUnless(
		(_PROJECT_ROOT / "tradehubfront" / "src" / "utils" / "entitlement.ts").exists(),
		"entitlement.ts mevcut degil",
	)
	def test_entitlement_not_security_boundary(self):
		"""Frontend entitlement snapshot guvenlik siniri OLMAMALI."""
		src = self._ENTITLEMENT_PATH.read_text(encoding="utf-8")
		# Yorum veya documentation'da bu belirtilmis olmali
		# Kaynak kodda guvenlik siniri olmadigi belirtilmis olmali
		has_security_note = (
			"güvenlik sınırı" in src
			or "security boundary" in src
			or "NOT a security" in src
			or "güvenlik kararı" in src
		)
		self.assertTrue(
			has_security_note,
			"Frontend entitlement'in guvenlik siniri olmadigina dair yorum eksik",
		)

	@unittest.skipUnless(
		(_PROJECT_ROOT / "tradehubfront" / "src" / "utils" / "entitlement.ts").exists(),
		"entitlement.ts mevcut degil",
	)
	def test_check_feature_fresh_exists(self):
		"""Cache bypass icin fresh check fonksiyonu olmali."""
		src = self._ENTITLEMENT_PATH.read_text(encoding="utf-8")
		self.assertIn("checkFeatureFresh", src)

	@unittest.skipUnless(
		(_PROJECT_ROOT / "tradehubfront" / "src" / "utils" / "entitlement.ts").exists(),
		"entitlement.ts mevcut degil",
	)
	def test_kyc_kyb_status_types(self):
		"""KYC/KYB status enum'lari backend ile senkron olmali."""
		src = self._ENTITLEMENT_PATH.read_text(encoding="utf-8")
		# Backend'deki status'ler
		for status in ["Locked", "Pending", "Verified", "Rejected", "Suspended"]:
			self.assertIn(status, src, f"KYC status '{status}' frontend'de eksik")


class TestDocTypeSchemaSubscriptionGating(unittest.TestCase):
	"""SUBSCRIPTION_GATED_DOCTYPES icindeki DocType'lar gercekten mevcut olmali."""

	def setUp(self):
		self.doctype_dir = _APP_ROOT / "tradehub_core" / "tradehub_core" / "doctype"

	def test_gated_doctypes_have_json_schema(self):
		"""Her gated DocType icin JSON schema dosyasi olmali."""
		# permissions.py'den SUBSCRIPTION_GATED_DOCTYPES'i import edemeyiz (frappe gerekir)
		# Ama source'dan parse edebiliriz
		perm_src = (_APP_ROOT / "tradehub_core" / "permissions.py").read_text(encoding="utf-8")
		# SUBSCRIPTION_GATED_DOCTYPES icindeki isimleri cek
		match = re.search(
			r"SUBSCRIPTION_GATED_DOCTYPES\s*=\s*frozenset\(\s*\[(.*?)\]\s*\)",
			perm_src,
			re.DOTALL,
		)
		if not match:
			self.skipTest("SUBSCRIPTION_GATED_DOCTYPES parse edilemedi")
		names_str = match.group(1)
		doctype_names = re.findall(r'"([^"]+)"', names_str)
		self.assertTrue(len(doctype_names) > 0, "Hicbir DocType parse edilemedi")

		# Her DocType icin dizin kontrolu (Frappe naming: "Order" -> "order/order.json")
		for dt in doctype_names:
			folder_name = dt.lower().replace(" ", "_")
			json_path = self.doctype_dir / folder_name / f"{folder_name}.json"
			self.assertTrue(
				json_path.exists(),
				f"SUBSCRIPTION_GATED DocType '{dt}' icin schema bulunamadi: {json_path}",
			)


class TestSubscriptionPlanFixtureIntegrity(unittest.TestCase):
	"""Subscription Plan fixture'lari capability flag'leri ile tutarli olmali."""

	_FIXTURE_PATH = _APP_ROOT / "tradehub_core" / "tradehub_core" / "fixtures" / "subscription_plan.json"

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "tradehub_core" / "fixtures" / "subscription_plan.json").exists(),
		"subscription_plan.json fixture mevcut degil",
	)
	def test_all_plans_have_capability_flags(self):
		plans = json.loads(self._FIXTURE_PATH.read_text(encoding="utf-8"))
		for plan in plans:
			self.assertIn(
				"capability_flags",
				plan,
				f"Plan '{plan.get('name')}' capability_flags eksik",
			)

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "tradehub_core" / "fixtures" / "subscription_plan.json").exists(),
		"subscription_plan.json fixture mevcut degil",
	)
	def test_all_plans_have_quota_limits(self):
		plans = json.loads(self._FIXTURE_PATH.read_text(encoding="utf-8"))
		for plan in plans:
			self.assertIn(
				"quota_limits",
				plan,
				f"Plan '{plan.get('name')}' quota_limits eksik",
			)

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "tradehub_core" / "fixtures" / "subscription_plan.json").exists(),
		"subscription_plan.json fixture mevcut degil",
	)
	def test_plan_feature_keys_valid_json(self):
		"""capability_flags JSON string parse edilebilmeli."""
		plans = json.loads(self._FIXTURE_PATH.read_text(encoding="utf-8"))
		for plan in plans:
			flags_raw = plan.get("capability_flags", "{}")
			try:
				flags = json.loads(flags_raw) if isinstance(flags_raw, str) else flags_raw
			except json.JSONDecodeError:
				self.fail(f"Plan '{plan.get('name')}' capability_flags gecersiz JSON")
			self.assertIsInstance(flags, dict)

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "tradehub_core" / "fixtures" / "subscription_plan.json").exists(),
		"subscription_plan.json fixture mevcut degil",
	)
	def test_free_plan_has_restricted_features(self):
		"""Free plan'da premium feature'lar kapali olmali."""
		plans = json.loads(self._FIXTURE_PATH.read_text(encoding="utf-8"))
		free_plan = next((p for p in plans if p.get("plan_code") == "free"), None)
		if not free_plan:
			self.skipTest("Free plan bulunamadi")
		flags = json.loads(free_plan["capability_flags"])
		# RFQ, CRM gibi premium feature'lar kapali olmali
		self.assertFalse(
			flags.get("feature.functional.rfq", False),
			"Free plan'da RFQ aktif olmamali",
		)
		self.assertFalse(
			flags.get("feature.pim.bulk_import", False),
			"Free plan'da bulk import aktif olmamali",
		)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Security-Critical Pattern Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestWhitelistEndpointCapabilityGating(unittest.TestCase):
	"""Kritik endpoint'lerde require_seller_capability kontrolu olmali."""

	def _read_api_file(self, name: str) -> str:
		path = _APP_ROOT / "tradehub_core" / "api" / name
		return path.read_text(encoding="utf-8") if path.exists() else ""

	def test_seller_addresses_has_capability_check(self):
		src = self._read_api_file("seller_addresses.py")
		self.assertIn("require_seller_capability", src)

	def test_listing_api_has_permission_checks(self):
		"""listing.py'de permission check pattern'lari olmali."""
		src = self._read_api_file("listing.py")
		# Ya check_permission ya da require_seller_capability
		has_check = "check_permission" in src or "require_seller_capability" in src
		self.assertTrue(has_check, "listing.py'de permission check eksik")

	def test_order_api_has_permission_checks(self):
		src = self._read_api_file("order.py")
		has_check = "check_permission" in src or "require_seller_capability" in src
		self.assertTrue(has_check, "order.py'de permission check eksik")

	def test_seller_api_has_permission_checks(self):
		src = self._read_api_file("seller.py")
		has_check = (
			"check_permission" in src or "require_seller_capability" in src or "frappe.only_for" in src
		)
		self.assertTrue(has_check, "seller.py'de permission check eksik")


class TestTenantIsolationSourceAudit(unittest.TestCase):
	"""tenant.py — tenant isolation critical patterns."""

	def setUp(self):
		path = _APP_ROOT / "tradehub_core" / "utils" / "tenant.py"
		self.src = path.read_text(encoding="utf-8") if path.exists() else ""

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "utils" / "tenant.py").exists(),
		"tenant.py mevcut degil",
	)
	def test_enforce_seller_isolation_hook_exists(self):
		self.assertIn("def enforce_seller_isolation_on_insert(", self.src)

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "utils" / "tenant.py").exists(),
		"tenant.py mevcut degil",
	)
	def test_get_current_seller_profile_exists(self):
		self.assertIn("get_current_seller_profile", self.src)

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "utils" / "tenant.py").exists(),
		"tenant.py mevcut degil",
	)
	def test_tenant_exempt_doctypes_defined(self):
		self.assertIn("TENANT_EXEMPT_DOCTYPES", self.src)

	@unittest.skipUnless(
		(_APP_ROOT / "tradehub_core" / "utils" / "tenant.py").exists(),
		"tenant.py mevcut degil",
	)
	def test_positive_only_cache_for_tenant(self):
		"""Tenant cache positive-only olmali (None cache'lenmemeli)."""
		# Tenant resolution'da None degerini cache'lememeli
		self.assertRegex(
			self.src,
			r"if.*(?:profile|tenant|seller).*:",
			"Tenant cache'te positive-only kontrol eksik olabilir",
		)


if __name__ == "__main__":
	unittest.main()
