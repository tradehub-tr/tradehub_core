"""H6/H7 — Buyer team rol profili allowlist testi.

api/v1/buyer_team._assert_buyer_role_profile:
  - Var olmayan profil reddedilir
  - 'Buyer' ile başlamayan profil reddedilir (Seller/admin profilleri)
  - 'Buyer' adıyla başlasa bile power-role içeren profil reddedilir
  - Temiz buyer profili kabul edilir

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_buyer_team_role_security
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


class _PermissionError(Exception):
	pass


class _ValidationError(Exception):
	pass


# Role Profile DB: name → roles list
_PROFILES = {
	"Buyer Full Access": ["Buyer", "Buyer Admin"],
	"Buyer Operations": ["Buyer"],
	"Buyer Evil": ["Buyer", "System Manager"],  # isim bypass denemesi
	"Seller Full Access": ["Marketplace Seller", "Seller Owner"],
}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: (a[0] if (a and callable(a[0])) else (lambda fn: fn))
	frappe.session = SimpleNamespace(user="buyeradmin@test")
	frappe.exists = None

	def _exists(doctype, name=None):
		return name in _PROFILES if doctype == "Role Profile" else False

	def _get_doc(doctype, name=None):
		roles = [SimpleNamespace(role=r) for r in _PROFILES.get(name, [])]
		return SimpleNamespace(name=name, roles=roles)

	frappe.db = SimpleNamespace(exists=_exists, get_value=lambda *a, **k: None)
	frappe.get_doc = _get_doc

	# buyer_team importu için ağır bağımlılıkları stub'la
	for mod, attrs in {
		"frappe.utils": {"add_days": lambda *a, **k: None, "now_datetime": lambda: None},
		"tradehub_core.entitlement": {
			"has_feature": lambda *a, **k: True,
			"check_feature_or_throw": lambda *a, **k: None,
			"check_quota_or_throw": lambda *a, **k: None,
		},
		"tradehub_core.utils.tenant": {"get_current_seller_profile": lambda: None},
	}.items():
		m = types.ModuleType(mod)
		for k, v in attrs.items():
			setattr(m, k, v)
		sys.modules[mod] = m


_install_frappe_stub()
_FRAPPE_STUB = sys.modules["frappe"]

# İzolasyon: başka bir test `tradehub_core.audit`'i eksik stub'lamış olabilir
# (log_role_change yok). Gerçek modül minimal frappe stub'ı altında temiz import edilir.
for _m in ("tradehub_core.audit",):
	sys.modules.pop(_m, None)

from tradehub_core.api.v1 import buyer_team as bt  # noqa: E402


class TestBuyerRoleProfileAllowlist(unittest.TestCase):
	def setUp(self):
		bt.frappe = _FRAPPE_STUB

	def test_nonexistent_profile_rejected(self):
		with self.assertRaises(_ValidationError):
			bt._assert_buyer_role_profile("Nope Profile")

	def test_non_buyer_profile_rejected(self):
		with self.assertRaises(_PermissionError):
			bt._assert_buyer_role_profile("Seller Full Access")

	def test_buyer_named_profile_with_power_role_rejected(self):
		# İsim 'Buyer' ile başlasa bile System Manager içeriyorsa reddedilmeli.
		with self.assertRaises(_PermissionError):
			bt._assert_buyer_role_profile("Buyer Evil")

	def test_clean_buyer_profile_accepted(self):
		bt._assert_buyer_role_profile("Buyer Full Access")
		bt._assert_buyer_role_profile("Buyer Operations")

	def test_empty_rejected(self):
		with self.assertRaises(_ValidationError):
			bt._assert_buyer_role_profile("")


if __name__ == "__main__":
	unittest.main()
