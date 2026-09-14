"""identity.py session-bazlı rate-limit kilidi (stub-frappe deseni).

Bağlam: Frappe v15 `frappe.rate_limiter.rate_limit(key="user")` kimliği
SESSION user'dan DEĞİL, form_dict'teki 'user' parametresinden okur — istemci
her çağrıda `user=<rastgele>` göndererek yeni bucket açıp limiti tamamen
atlatabiliyordu. identity.py'daki 7 uç proje-içi session-bazlı decorator'a
(`tradehub_core.api.rate_limit`, kimlik=frappe.session.user) geçirildi;
bu testler o davranışı kilitler:

  - verify_email_otp (OTP brute-force guard'ı, ÖNCELİKLİ): form_dict spoof
    bucket'ı DEĞİŞTİRMEZ + 10/600s limit aşımında TooManyRequestsError (429).
  - Kalan 6 uç için sözleşme testleri: her uç session-user kovasına doğru
    scope + doğru pencereyle sayar ve max_calls aşımında 429 fırlatır;
    form_dict'e basılan 'user' hiçbir uçta yeni kova açmaz.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_identity_rate_limit

(Kombine koşu bilinen stub çakışması nedeniyle modül başına ayrı süreçte koşulur.)
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


class _AuthenticationError(Exception):
	pass


class _DoesNotExistError(Exception):
	pass


class _DuplicateEntryError(Exception):
	pass


class _FrappeTooManyRequestsError(Exception):
	pass


_STATE: dict = {}


def _reset_state() -> None:
	_STATE.clear()
	_STATE.update(
		{
			"user": "owner@test",
			"response": {},
		}
	)
	cache = _rl_cache()
	if hasattr(cache, "reset"):
		cache.reset()


class _CacheStub:
	"""Sahte frappe.cache — rate limiter'ın INCR/EXPIRE/TTL sayaçlarını tutar.

	Sayaçlar instance üstünde: kombine koşuda (birden fazla stub test modülü
	aynı süreçte) rate_limit modülü İLK import'taki frappe stub'ına bağlı kalır;
	reset/okuma her zaman `_rl_cache()` üzerinden o objeye gider.
	"""

	def __init__(self):
		self.counts: dict[str, int] = {}
		self.expires: dict[str, int] = {}

	def reset(self):
		self.counts.clear()
		self.expires.clear()

	def __call__(self):
		return self

	def make_key(self, key):
		return f"test|{key}"

	def incr(self, key):
		self.counts[key] = self.counts.get(key, 0) + 1
		return self.counts[key]

	def expire(self, key, ttl):
		self.expires[key] = ttl

	def ttl(self, key):
		return self.expires.get(key, 600)

	def get_value(self, *a, **k):
		# identity.py OTP okuması da buradan geçer — None = "kod yok" (404 yolu).
		return None

	def set_value(self, *a, **k):
		return None

	def delete_value(self, *a, **k):
		return None


def _rl_cache() -> _CacheStub:
	"""Rate limiter'ın GERÇEKTE kullandığı cache objesi (bkz. _CacheStub docstring)."""
	rl = sys.modules.get("tradehub_core.api.rate_limit")
	cache = getattr(getattr(rl, "frappe", None), "cache", None)
	if cache is None:
		# Stub henüz kurulmadıysa (modül-üstü ilk _reset_state) no-op obje döner.
		cache = getattr(sys.modules.get("frappe"), "cache", None) or _CacheStub()
	return cache


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe

	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError
	frappe.AuthenticationError = _AuthenticationError
	frappe.DoesNotExistError = _DoesNotExistError
	frappe.DuplicateEntryError = _DuplicateEntryError
	frappe.TooManyRequestsError = _FrappeTooManyRequestsError
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: a[0] if (a and callable(a[0])) else (lambda fn: fn)
	frappe.session = SimpleNamespace(user="owner@test")
	frappe.local = SimpleNamespace(response=_STATE.setdefault("response", {}), request=None)
	frappe.log_error = lambda *a, **k: None
	frappe.logger = lambda *a, **k: SimpleNamespace(info=lambda *x, **y: None, warning=lambda *x, **y: None)
	frappe.get_traceback = lambda: ""
	frappe.generate_hash = lambda length=32: "x" * length
	frappe.sendmail = lambda **kw: None
	frappe.sessions = SimpleNamespace(clear_sessions=lambda u: None)
	# frappe.cache hem attribute hem callable (frappe.cache()) kullanılıyor —
	# proje rate limiter'ı INCR/EXPIRE/TTL çağırır, identity.py OTP'yi
	# get_value ile okur. Sayaçlar cache objesinin üstünde.
	frappe.cache = _CacheStub()
	# Saldırgan istemcinin gönderebildiği form input'u — proje decorator'ı bunu
	# ASLA okumamalı (frappe.rate_limiter key="user" bug'ının kilidi).
	frappe.form_dict = {}

	def _get_value(doctype, filters=None, fieldname=None, as_dict=False, **kw):
		if doctype == "User Profile" and fieldname == "email_verified":
			# resend_verification_email erken (yan etkisiz) dönsün — bu testler
			# yalnız decorator sözleşmesini kilitler, mail akışını değil.
			return 1
		return None

	frappe.db = SimpleNamespace(
		get_value=_get_value,
		set_value=lambda *a, **k: None,
		exists=lambda *a, **k: None,
		sql=lambda *a, **k: [],
		commit=lambda: None,
		count=lambda *a, **k: 0,
		delete=lambda *a, **k: None,
		has_column=lambda *a, **k: False,
	)
	frappe.get_doc = lambda *a, **k: SimpleNamespace(name=None)
	frappe.get_all = lambda *a, **k: []
	frappe.get_roles = lambda u=None: []

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: "2026-09-14 12:00:00"
	utils.add_days = lambda d, n: d
	utils.get_datetime = lambda d=None: d
	utils.getdate = lambda d=None: d
	utils.cint = lambda v: int(v or 0)
	sys.modules["frappe.utils"] = utils
	frappe.utils = utils

	password_mod = types.ModuleType("frappe.utils.password")
	password_mod.check_password = lambda user, pwd: None
	password_mod.update_password = lambda *a, **k: None
	sys.modules["frappe.utils.password"] = password_mod

	rl = types.ModuleType("frappe.rate_limiter")
	rl.rate_limit = lambda **kw: lambda fn: fn
	sys.modules["frappe.rate_limiter"] = rl

	# tradehub_core iç bağımlılık stub'ları (identity.py module-level import'ları)
	auth_mod = types.ModuleType("tradehub_core.api.v1.auth")
	auth_mod._generate_member_id = lambda email, creation: "M-00001"
	sys.modules["tradehub_core.api.v1.auth"] = auth_mod

	seo_mod = types.ModuleType("tradehub_core.seo.site_url")
	seo_mod.storefront_url = lambda: "http://test.localhost"
	sys.modules["tradehub_core.seo.site_url"] = seo_mod

	guards_mod = types.ModuleType("tradehub_core.utils.auth_guards")
	guards_mod.require_verified_email = lambda fn: fn
	sys.modules["tradehub_core.utils.auth_guards"] = guards_mod

	phone_mod = types.ModuleType("tradehub_core.utils.phone")
	phone_mod.canonicalize_phone = lambda p: p
	sys.modules["tradehub_core.utils.phone"] = phone_mod

	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.log_decision = lambda **kw: None
	sys.modules["tradehub_core.audit"] = audit_mod


_reset_state()
_install_frappe_stub()

import frappe  # noqa: E402  (stub)

from tradehub_core.api.rate_limit import TooManyRequestsError  # noqa: E402
from tradehub_core.api.v1 import identity  # noqa: E402

# Endpoint gövdesinin (stub ortamında beklenen şekilde) fırlattığı hatalar —
# rate-limit sayacı gövdeden ÖNCE arttığı için sözleşme testinde yutulur.
_BODY_ERRORS = (
	_ValidationError,
	_AuthenticationError,
	_DoesNotExistError,
	_DuplicateEntryError,
	_PermissionError,
	_FrappeTooManyRequestsError,
)


def _spoof_form_dict(value: str) -> None:
	# Saldırgan simülasyonu: hem son yüklenen stub'a hem rate limiter'ın
	# gerçekte bağlı olduğu frappe objesine basılır — decorator OKUMAMALI.
	frappe.form_dict = {"user": value}
	rl = sys.modules.get("tradehub_core.api.rate_limit")
	if rl is not None:
		rl.frappe.form_dict = {"user": value}


def _call_swallowing_body_errors(fn, *args, **kwargs) -> None:
	try:
		fn(*args, **kwargs)
	except _BODY_ERRORS:
		pass


class _Base(unittest.TestCase):
	def setUp(self):
		_reset_state()
		frappe.session.user = _STATE["user"]
		frappe.local.response = _STATE["response"]
		_spoof_form_dict("attacker-bucket-0")


class TestVerifyEmailOtpRateLimit(_Base):
	"""ÖNCELİKLİ: verify_email_otp OTP brute-force guard'ı (10/600s, session-bazlı)."""

	def test_spoofed_form_dict_user_does_not_change_bucket(self):
		_spoof_form_dict("attacker-bucket-1")
		_call_swallowing_body_errors(identity.verify_email_otp, code="000000")
		_spoof_form_dict("attacker-bucket-2")
		_call_swallowing_body_errors(identity.verify_email_otp, code="000000")

		keys = [k for k in _rl_cache().counts if "verify_email_otp" in k]
		self.assertEqual(len(keys), 1, "Farklı form_dict 'user' değerleri TEK bucket'ta saymalı")
		self.assertIn("owner@test", keys[0], "Kova kimliği session user'dan türemeli")
		self.assertNotIn("attacker-bucket", keys[0])
		self.assertEqual(_rl_cache().counts[keys[0]], 2, "Her iki çağrı aynı sayaca yazılmalı")

	def test_limit_exhaustion_raises_429_even_with_fresh_spoof(self):
		for _ in range(10):
			_call_swallowing_body_errors(identity.verify_email_otp, code="000000")
		# 11. çağrı: form_dict'e yeni 'user' basmak da kurtarmamalı.
		_spoof_form_dict("fresh-bucket-please")
		with self.assertRaises(TooManyRequestsError):
			identity.verify_email_otp(code="000000")

	def test_window_is_600_seconds(self):
		_call_swallowing_body_errors(identity.verify_email_otp, code="000000")
		cache = _rl_cache()
		key = next(k for k in cache.counts if "verify_email_otp" in k)
		self.assertEqual(cache.expires.get(key), 600)


class TestSessionRateLimitContract(_Base):
	"""Kalan 6 uç: decorator uygulanmış, scope/limit/pencere doğru, kova session-bazlı.

	Gövde davranışı burada test EDİLMEZ — her uç stub ortamında erken guard'ına
	çarpar (yan etkisiz); sayaç gövdeden önce arttığı için sözleşme ölçülebilir.
	"""

	# (fonksiyon adı, çağrı kwargs, scope, max_calls, window_seconds)
	CONTRACT = [
		("update_profile_image", {}, "update_profile_image", 10, 300),
		("change_email", {"new_email": "new@test.example", "password": "p"}, "change_email", 10, 3600),
		("request_email_change", {"new_email": "", "password": "p"}, "request_email_change", 20, 3600),
		("confirm_email_change", {"code": "000000"}, "confirm_email_change", 10, 600),
		("resend_verification_email", {}, "resend_verification_email", 3, 3600),
		("change_phone", {"phone": "", "password": "p"}, "change_phone", 5, 300),
	]

	def test_bucket_is_session_user_not_form_dict(self):
		for fn_name, kwargs, scope, _max_calls, window in self.CONTRACT:
			with self.subTest(endpoint=fn_name):
				_reset_state()
				_spoof_form_dict(f"attacker-{fn_name}")
				_call_swallowing_body_errors(getattr(identity, fn_name), **kwargs)

				cache = _rl_cache()
				keys = [k for k in cache.counts if scope in k]
				self.assertEqual(len(keys), 1, f"{fn_name}: tek session kovası beklenirdi")
				self.assertIn("owner@test", keys[0], f"{fn_name}: kova session user'dan türemeli")
				self.assertNotIn("attacker-", keys[0], f"{fn_name}: form_dict kovaya sızmamalı")
				self.assertEqual(cache.expires.get(keys[0]), window, f"{fn_name}: pencere korunmalı")

	def test_limit_exhaustion_raises_429_per_endpoint(self):
		for fn_name, kwargs, _scope, max_calls, _window in self.CONTRACT:
			with self.subTest(endpoint=fn_name):
				_reset_state()
				fn = getattr(identity, fn_name)
				for _ in range(max_calls):
					_call_swallowing_body_errors(fn, **kwargs)
				# Limit doldu: yeni form_dict 'user' basmak da kurtarmamalı.
				_spoof_form_dict("fresh-bucket-please")
				with self.assertRaises(TooManyRequestsError):
					fn(**kwargs)


if __name__ == "__main__":
	unittest.main()
