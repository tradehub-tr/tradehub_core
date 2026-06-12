"""C4 — list_my_inquiries tenant izolasyonu testi.

api/seller.list_my_inquiries'in `get_all`/`count` çağrılarına çağıranın kendi
`seller` profilini filtre olarak geçtiğini doğrular (cross-tenant sızıntı engeli).

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_seller_inquiry_isolation
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


class _DoesNotExistError(Exception):
	pass


_CAPTURED = {"get_all_filters": None, "count_filters": None}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError
	frappe.DoesNotExistError = _DoesNotExistError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: a[0] if (a and callable(a[0])) else (lambda fn: fn)
	frappe.session = SimpleNamespace(user="seller-a@test")

	def _get_all(doctype, filters=None, **kw):
		_CAPTURED["get_all_filters"] = dict(filters or {})
		return []

	def _count(doctype, filters=None, **kw):
		_CAPTURED["count_filters"] = dict(filters or {})
		return 0

	# db.get_value("Admin Seller Profile", {"user": ...}, "name") → profile adı
	def _get_value(doctype, filters=None, fieldname=None, **kw):
		if doctype == "Admin Seller Profile":
			return "SELLER-A-PROFILE"
		return None

	frappe.get_all = _get_all
	frappe.db = SimpleNamespace(count=_count, get_value=_get_value)
	frappe.has_permission = lambda *a, **k: True


_install_frappe_stub()

# seller.py geniş bir modül; importu kolaylaştırmak için eksik bağımlılıkları stub'la.
for _mod in ("tradehub_core.utils.tenant",):
	if _mod not in sys.modules:
		m = types.ModuleType(_mod)
		m._get_seller_profile_for_user = lambda user: "SELLER-A-PROFILE"
		sys.modules[_mod] = m

from tradehub_core.api import seller  # noqa: E402


class TestInquiryIsolation(unittest.TestCase):
	def test_list_my_inquiries_filters_by_own_seller(self):
		seller.list_my_inquiries(status="all", page=1, page_size=20)
		self.assertEqual(
			_CAPTURED["get_all_filters"].get("seller"),
			"SELLER-A-PROFILE",
			"get_all çağrısı seller filtresi içermeli (cross-tenant guard)",
		)
		self.assertEqual(
			_CAPTURED["count_filters"].get("seller"),
			"SELLER-A-PROFILE",
			"count çağrısı da seller filtresi içermeli",
		)


if __name__ == "__main__":
	unittest.main()
