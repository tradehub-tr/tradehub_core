"""C6 + C7 — Sepet/sipariş fiyat manipülasyonu güvenlik testleri.

api/cart._compute_server_coupon_discount:
  - Geçersiz kupon → 0 (client coupon_discount yok sayılır)
  - percent/fixed indirim server'da koddan hesaplanır
  - indirim order_total'ı aşamaz (bedava sipariş engeli)
  - max_uses dolu / min_order sağlanmıyor → 0

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_cart_price_tampering
"""
from __future__ import annotations

import datetime
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


# Test kupon kayıtları: code → dict
_COUPONS: dict = {}


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.ValidationError = _ValidationError
	frappe._ = lambda s: s
	frappe.throw = lambda msg, exc=_ValidationError: (_ for _ in ()).throw(exc(msg)) if False else (_raise(exc, msg))

	def _get_value(doctype, filters=None, fieldname=None, as_dict=False, **kw):
		if doctype == "Coupon" and isinstance(filters, dict):
			code = filters.get("code")
			c = _COUPONS.get(code)
			if not c:
				return None
			if as_dict:
				return SimpleNamespace(**c)
			return c.get(fieldname)
		return None

	frappe.db = SimpleNamespace(get_value=_get_value)
	frappe.whitelist = lambda *a, **k: (a[0] if (a and callable(a[0])) else (lambda fn: fn))


def _raise(exc, msg):
	raise exc(msg)


_install_frappe_stub()
# Bu dosyanın frappe stub'ını sakla — testler birlikte koşulduğunda başka bir test
# sys.modules['frappe']'i değiştirse de hedef modülün frappe'sini buna geri bağlarız.
_FRAPPE_STUB = sys.modules["frappe"]

# cart.py geniş; importunu kolaylaştırmak için iç bağımlılıkları stub'la.
# NOT: `tradehub_core.api._input` STUB'LANMAZ — gerçek modül hafif (yalnız frappe.throw
# kullanır) ve başka testler (seller) `safe_float`'a ihtiyaç duyar; eksik stub sızıntısı
# import kırardı. Gerçek modül stub frappe altında sorunsuz import edilir.
for _mod, _attrs in {
	"tradehub_core.api.rate_limit": {"rate_limit": lambda *a, **k: (lambda fn: fn)},
	"tradehub_core.utils.auth_guards": {"require_verified_email": lambda fn: fn},
	"tradehub_core.utils.stock": {
		"deduct_stock_for_order": lambda *a, **k: None,
		"reserve_stock_for_order": lambda *a, **k: None,
	},
}.items():
	m = types.ModuleType(_mod)
	for k, v in _attrs.items():
		setattr(m, k, v)
	sys.modules[_mod] = m


def _try_import_cart():
	"""cart.py'yi bu dosyanın stub'ları aktifken bir kez import et."""
	try:
		from tradehub_core.api import cart as cart_mod

		return cart_mod
	except Exception:
		return None


# Modül seviyesinde TEK SEFER import et (bu dosyanın stub'ları aktifken). Lazy/setUp
# içinde re-import edilirse, başka bir testin contaminated frappe'siyle import patlar
# ve test skip olur. Bu referansı sakla; setUp yalnızca frappe'yi geri bağlar.
_CART_MOD = _try_import_cart()


class TestCouponServerSide(unittest.TestCase):
	def setUp(self):
		_COUPONS.clear()
		self.cart = _CART_MOD
		if self.cart is None or not hasattr(self.cart, "_compute_server_coupon_discount"):
			self.skipTest("cart modülü stub ortamında import edilemedi")
		# İzolasyon: cart başka bir testin frappe stub'ına bağlı kalmış olabilir
		# (modül cache). Kendi stub'ımıza geri bağla ki get_value _COUPONS'u görsün.
		self.cart.frappe = _FRAPPE_STUB

	def test_no_coupon_returns_zero(self):
		self.assertEqual(self.cart._compute_server_coupon_discount(None, 100), 0.0)

	def test_invalid_coupon_returns_zero(self):
		self.assertEqual(self.cart._compute_server_coupon_discount("NOPE", 100), 0.0)

	def test_fixed_discount_computed_server_side(self):
		_COUPONS["SAVE10"] = {
			"name": "c1", "coupon_type": "fixed", "value": 10, "min_order": 0,
			"max_uses": 0, "used_count": 0, "expires_at": None,
		}
		self.assertEqual(self.cart._compute_server_coupon_discount("save10", 100), 10.0)

	def test_percent_discount_computed_server_side(self):
		_COUPONS["P20"] = {
			"name": "c2", "coupon_type": "percent", "value": 20, "min_order": 0,
			"max_uses": 0, "used_count": 0, "expires_at": None,
		}
		self.assertEqual(self.cart._compute_server_coupon_discount("p20", 100), 20.0)

	def test_discount_clamped_to_order_total(self):
		# Bedava sipariş istismarı: value order_total'dan büyük → clamp.
		_COUPONS["HUGE"] = {
			"name": "c3", "coupon_type": "fixed", "value": 999999, "min_order": 0,
			"max_uses": 0, "used_count": 0, "expires_at": None,
		}
		self.assertEqual(self.cart._compute_server_coupon_discount("huge", 50), 50.0)

	def test_maxed_out_coupon_returns_zero(self):
		_COUPONS["DONE"] = {
			"name": "c4", "coupon_type": "fixed", "value": 10, "min_order": 0,
			"max_uses": 5, "used_count": 5, "expires_at": None,
		}
		self.assertEqual(self.cart._compute_server_coupon_discount("done", 100), 0.0)

	def test_min_order_not_met_returns_zero(self):
		_COUPONS["MIN"] = {
			"name": "c5", "coupon_type": "fixed", "value": 10, "min_order": 200,
			"max_uses": 0, "used_count": 0, "expires_at": None,
		}
		self.assertEqual(self.cart._compute_server_coupon_discount("min", 100), 0.0)

	def test_expired_coupon_returns_zero(self):
		_COUPONS["OLD"] = {
			"name": "c6", "coupon_type": "fixed", "value": 10, "min_order": 0,
			"max_uses": 0, "used_count": 0, "expires_at": datetime.date(2000, 1, 1),
		}
		self.assertEqual(self.cart._compute_server_coupon_discount("old", 100), 0.0)


if __name__ == "__main__":
	unittest.main()
