"""#D1 — ABAC deny-only overlay enforcement testleri.

`permissions.py` içindeki `_abac_deny` helper'ının 4 ABAC kapısını
(KYC / AML / abonelik-write / harcama-limiti) OR-birleştirdiğini ve kayıtlı
per-doctype handler'ların (`listing`, `order`, `admin_seller_profile`,
`seller_balance`, `seller_inquiry`, `seller_category`, `seller_gallery_image`)
bir kapı DENY ettiğinde `False` döndürdüğünü doğrular.

Not: `_check_*` primitifleri burada PATCH'lenir — onların iç mantığı
`test_abac_context` / entitlement testlerinde ayrıca kapsanır. Bu modül
2026-07-02 raporundaki #D1 bulgusunun (ABAC kapıları register edilmemiş ölü
kod) kapatıldığını, yani WIRING'i test eder.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_abac_gate_enforcement
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


def _install_frappe_stub() -> None:
	"""permissions.py + utils/tenant.py import'u için minimal frappe stub."""
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.db = SimpleNamespace(
		get_value=lambda *a, **kw: None,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		has_column=lambda *a, **kw: False,
	)
	frappe.session = SimpleNamespace(user="Guest")
	frappe.local = SimpleNamespace()
	frappe.get_roles = lambda u: []
	frappe.get_all = lambda *a, **kw: []

	_cache_store: dict = {}

	class _CacheStub:
		def get_value(self, key):
			return _cache_store.get(key)

		def set_value(self, key, value, expires_in_sec=None):
			_cache_store[key] = value

		def delete_value(self, key):
			_cache_store.pop(key, None)

	frappe.cache = lambda: _CacheStub()
	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None
	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class _PermissionError(Exception):
			pass

		frappe.PermissionError = _PermissionError

	# frappe.utils.flt (permissions.py top-level import)
	futils = sys.modules.get("frappe.utils")
	if futils is None:
		futils = types.ModuleType("frappe.utils")
		sys.modules["frappe.utils"] = futils
	futils.flt = lambda v, precision=None: float(v or 0)
	frappe.utils = futils


_install_frappe_stub()

from tradehub_core import permissions  # noqa: E402

# Deny gate uygulanan tüm kayıtlı handler'lar + doctype'ları.
_GATED_HANDLERS = [
	("listing_has_permission", "Listing"),
	("order_has_permission", "Order"),
	("admin_seller_profile_has_permission", "Admin Seller Profile"),
	("seller_balance_has_permission", "Seller Balance"),
	("seller_inquiry_has_permission", "Seller Inquiry"),
	("seller_category_has_permission", "Seller Category"),
	("seller_gallery_image_has_permission", "Seller Gallery Image"),
]


class TestAbacDenyComposition(unittest.TestCase):
	"""_abac_deny 4 kapıyı OR-birleştirir: herhangi biri deny → True."""

	def _all_allow(self):
		"""4 _check_* de allow (True/pass) döndürecek şekilde patch context."""
		return (
			patch.object(permissions, "_get_seller_profile_name", return_value="SEL-1"),
			patch.object(permissions, "_check_kyc_verification", return_value=True),
			patch.object(permissions, "_check_aml_sanctions", return_value=True),
			patch.object(permissions, "_check_subscription_active", return_value=True),
			patch.object(permissions, "_check_spending_limit", return_value=True),
		)

	def test_all_pass_no_deny(self):
		ctx = self._all_allow()
		with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4]:
			self.assertFalse(permissions._abac_deny({}, "write", "u", "Listing"))

	def test_kyc_deny(self):
		ctx = self._all_allow()
		with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], patch.object(
			permissions, "_check_kyc_verification", return_value=False
		):
			self.assertTrue(permissions._abac_deny({}, "read", "u", "Seller Balance"))

	def test_aml_deny(self):
		ctx = self._all_allow()
		with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], patch.object(
			permissions, "_check_aml_sanctions", return_value=False
		):
			self.assertTrue(permissions._abac_deny({}, "read", "u", "Seller Balance"))

	def test_subscription_deny(self):
		ctx = self._all_allow()
		with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], patch.object(
			permissions, "_check_subscription_active", return_value=False
		):
			self.assertTrue(permissions._abac_deny({}, "write", "u", "Listing"))

	def test_spending_deny_only_on_write(self):
		ctx = self._all_allow()
		# read'de spending kapısı devreye girmez → deny YOK.
		with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], patch.object(
			permissions, "_check_spending_limit", return_value=False
		):
			self.assertFalse(permissions._abac_deny({}, "read", "u", "Order"))
		ctx = self._all_allow()
		with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], patch.object(
			permissions, "_check_spending_limit", return_value=False
		):
			self.assertTrue(permissions._abac_deny({}, "write", "u", "Order"))


class TestHandlersRespectDeny(unittest.TestCase):
	"""Kayıtlı handler'lar _abac_deny True dönünce False (deny) döndürmeli."""

	def test_handler_denies_when_abac_denies(self):
		for fn_name, doctype in _GATED_HANDLERS:
			handler = getattr(permissions, fn_name)
			with patch.object(
				permissions, "_is_platform_full_access", return_value=False
			), patch.object(permissions, "_abac_deny", return_value=True) as mock_deny:
				doc = SimpleNamespace(
					doctype=doctype, name="X", seller="SEL-1", seller_profile="SEL-1",
					parent="SEL-1", buyer="b", owner="u",
				)
				result = handler(doc, "write", "seller@test.local")
				self.assertFalse(
					result, f"{fn_name}: ABAC deny iken handler False döndürmeli"
				)
				mock_deny.assert_called_once()

	def test_admin_bypasses_gate(self):
		"""Administrator ABAC gate'e girmeden True almalı (gate çağrılmamalı)."""
		for fn_name, _doctype in _GATED_HANDLERS:
			handler = getattr(permissions, fn_name)
			with patch.object(permissions, "_abac_deny", return_value=True) as mock_deny:
				result = handler(SimpleNamespace(name="X"), "write", "Administrator")
				self.assertTrue(result, f"{fn_name}: Administrator gate'i bypass etmeli")
				mock_deny.assert_not_called()


class TestAbacDenyReadPassthrough(unittest.TestCase):
	"""Abonelik kapısı yalnız destructive op'ları gate'ler — read serbest."""

	def test_read_not_subscription_gated(self):
		# GERÇEK _check_subscription_active çalışır; entitlement modülü sahte
		# enjekte edilir (suspended → is_subscription_operational False).
		fake_entitlement = types.ModuleType("tradehub_core.entitlement")
		fake_entitlement.is_subscription_operational = lambda store: False
		with patch.dict(sys.modules, {"tradehub_core.entitlement": fake_entitlement}), \
			patch.object(permissions, "_get_seller_profile_name", return_value="SEL-1"), \
			patch.object(permissions, "_check_kyc_verification", return_value=True), \
			patch.object(permissions, "_check_aml_sanctions", return_value=True), \
			patch.object(permissions, "_check_spending_limit", return_value=True):
			# read → _check_subscription_active ptype guard'ı entitlement'a hiç
			# gitmeden True döner (gate skip) → deny YOK.
			self.assertFalse(permissions._abac_deny({}, "read", "u", "Listing"))
			# write → suspended abonelik → deny.
			self.assertTrue(permissions._abac_deny({}, "write", "u", "Listing"))


if __name__ == "__main__":
	unittest.main()
