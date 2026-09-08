"""BE-5 — Hesap silme backend'i (AC-12/AC-13).

api/v1/identity:
  - get_account_deletion_preview: Guest → 403; owner → mağaza/abonelik/alt
    kullanıcı özeti + grace_days=15 + Türkçe sonuç maddeleri; owner değilse
    mağazasız sade önizleme.
  - delete_account: mağaza sahibiyse Store Subscription → 'canceled'
    (cancellation_reason='account_deleted', state machine üzerinden save),
    bekleyen Subscription Payment → 'rejected'; owner değilse aboneliğe
    dokunulmaz; mevcut soft-delete davranışı korunur.

privacy/account_deletion:
  - _anonymize_store_subscription: cancellation_note/cancel_requested_by PII
    temizliği; şema migrate edilmemişse sessiz no-op.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_account_deletion_backend
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


_STATE: dict = {}


def _reset_state() -> None:
	_STATE.clear()
	_STATE.update(
		{
			"user": "owner@test",
			"is_owner": 1,
			"tenant": "SEL-00001",
			"company_name": "Test Mağaza",
			"user_profile": "owner@test",
			"seller_profile": "SEL-00001",
			"subscription": {
				"name": "STSUB-2026-00001",
				"plan": "PRO",
				"status": "active",
				"current_period_end": "2026-10-01 00:00:00",
			},
			"sub_user_count": 2,
			"pending_payments": ["SUBPAY-001"],
			"has_columns": {"cancel_requested_by", "cancellation_note"},
			"subs_by_canceller": ["STSUB-2026-00001"],
			# kayıt defterleri
			"set_values": [],
			"saved_subs": [],
			"deleted": [],
			"sessions_cleared": [],
			"sent_mails": [],
			"audit": [],
			"response": {},
		}
	)
	# Rate-limit sayaçları her testte sıfır başlasın (3/saat limiti taşmasın).
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
		return self.expires.get(key, 3600)

	def get_value(self, *a, **k):
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


class _SubscriptionDoc(SimpleNamespace):
	def save(self, *a, **k):
		_STATE["saved_subs"].append(
			{
				"name": self.name,
				"status": self.status,
				"cancellation_reason": getattr(self, "cancellation_reason", None),
				"ignore_permissions": bool(k.get("ignore_permissions")),
			}
		)


def _install_frappe_stub() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe

	frappe.PermissionError = _PermissionError
	frappe.ValidationError = _ValidationError
	frappe.AuthenticationError = _AuthenticationError
	frappe.DuplicateEntryError = type("_Dup", (Exception,), {})
	frappe.DoesNotExistError = type("_DNE", (Exception,), {})
	frappe.TooManyRequestsError = type("_TMR", (Exception,), {})
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: a[0] if (a and callable(a[0])) else (lambda fn: fn)
	frappe.session = SimpleNamespace(user="owner@test")
	frappe.local = SimpleNamespace(response=_STATE.setdefault("response", {}), request=None)
	frappe.log_error = lambda *a, **k: None
	frappe.logger = lambda *a, **k: SimpleNamespace(info=lambda *x, **y: None)
	frappe.get_traceback = lambda: ""
	frappe.generate_hash = lambda length=32: "x" * length
	frappe.sendmail = lambda **kw: _STATE["sent_mails"].append(kw)
	frappe.sessions = SimpleNamespace(clear_sessions=lambda u: _STATE["sessions_cleared"].append(u))
	# frappe.cache hem attribute hem callable (frappe.cache()) kullanılıyor —
	# proje rate limiter'ı (tradehub_core.api.rate_limit, artık delete_account +
	# preview'da GERÇEK modül) INCR/EXPIRE/TTL çağırır. Sayaçlar cache objesinin
	# üstünde; her testte `_rl_cache().reset()` ile sıfırlanır (limit testler
	# arasında taşmasın).
	frappe.cache = _CacheStub()
	frappe.form_dict = {}

	def _get_value(doctype, filters=None, fieldname=None, as_dict=False, **kw):
		if doctype == "User" and fieldname == ["tradehub_tenant", "tradehub_is_owner"]:
			return SimpleNamespace(tradehub_tenant=_STATE["tenant"], tradehub_is_owner=_STATE["is_owner"])
		if doctype == "User Profile":
			return _STATE.get("user_profile")
		if doctype == "Admin Seller Profile":
			if isinstance(filters, dict):
				return _STATE.get("seller_profile")
			return SimpleNamespace(company_name=_STATE.get("company_name"), seller_name=None)
		if doctype == "Store Subscription":
			sub = _STATE.get("subscription")
			if not sub:
				return None
			if fieldname == "name":
				return sub["name"]
			return SimpleNamespace(
				plan=sub["plan"], status=sub["status"], current_period_end=sub["current_period_end"]
			)
		return None

	def _set_value(doctype, name, field, value=None, **kw):
		_STATE["set_values"].append((doctype, name, field, value))

	def _get_doc(doctype, name=None):
		if doctype == "User":
			return SimpleNamespace(full_name="Test User")
		if doctype == "Store Subscription":
			sub = _STATE["subscription"]
			return _SubscriptionDoc(name=name, status=sub["status"], cancellation_reason=None)
		return SimpleNamespace(name=name)

	def _get_all(doctype, filters=None, pluck=None, **kw):
		if doctype == "Subscription Payment":
			return list(_STATE.get("pending_payments", []))
		if doctype == "Store Subscription":
			return list(_STATE.get("subs_by_canceller", []))
		return []

	frappe.db = SimpleNamespace(
		get_value=_get_value,
		set_value=_set_value,
		count=lambda doctype, filters=None: _STATE.get("sub_user_count", 0),
		delete=lambda doctype, filters=None: _STATE["deleted"].append((doctype, filters)),
		commit=lambda: None,
		has_column=lambda doctype, column: column in _STATE.get("has_columns", set()),
		exists=lambda *a, **k: None,
		sql=lambda *a, **k: [],
	)
	frappe.get_doc = _get_doc
	frappe.get_all = _get_all

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: "2026-09-08 12:00:00"
	utils.add_days = lambda d, n: d
	utils.add_months = lambda d, n: d
	utils.add_years = lambda d, n: d
	utils.get_datetime = lambda d=None: d
	utils.getdate = lambda d=None: d
	utils.cint = lambda v: int(v or 0)
	sys.modules["frappe.utils"] = utils
	frappe.utils = utils

	password_mod = types.ModuleType("frappe.utils.password")

	def _check_password(user, pwd):
		if not _STATE.get("password_ok", True):
			raise _AuthenticationError("wrong password")

	password_mod.check_password = _check_password
	password_mod.update_password = lambda *a, **k: None
	sys.modules["frappe.utils.password"] = password_mod

	rl = types.ModuleType("frappe.rate_limiter")
	rl.rate_limit = lambda **kw: lambda fn: fn
	sys.modules["frappe.rate_limiter"] = rl

	model_mod = types.ModuleType("frappe.model")
	doc_mod = types.ModuleType("frappe.model.document")

	class _Document:
		pass

	doc_mod.Document = _Document
	sys.modules["frappe.model"] = model_mod
	sys.modules["frappe.model.document"] = doc_mod

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
	audit_mod.log_decision = lambda **kw: _STATE["audit"].append(kw)
	sys.modules["tradehub_core.audit"] = audit_mod


_reset_state()
_install_frappe_stub()

import frappe  # noqa: E402  (stub)

from tradehub_core.api.v1 import identity  # noqa: E402
from tradehub_core.privacy import account_deletion  # noqa: E402


class _Base(unittest.TestCase):
	def setUp(self):
		_reset_state()
		frappe.session.user = _STATE["user"]
		frappe.local.response = _STATE["response"]


class TestDeletionPreview(_Base):
	def test_guest_403(self):
		frappe.session.user = "Guest"
		with self.assertRaises(_PermissionError):
			identity.get_account_deletion_preview()
		self.assertEqual(frappe.local.response.get("http_status_code"), 403)

	def test_owner_full_preview(self):
		out = identity.get_account_deletion_preview()
		self.assertTrue(out["has_store"])
		self.assertEqual(out["store_name"], "Test Mağaza")
		self.assertEqual(
			out["active_subscription"],
			{"plan": "PRO", "status": "active", "current_period_end": "2026-10-01 00:00:00"},
		)
		self.assertEqual(out["sub_user_count"], 2)
		self.assertEqual(out["grace_days"], 15)
		joined = " ".join(out["consequences"])
		self.assertIn("Test Mağaza", joined)
		self.assertIn("iade yapılmaz", joined)
		self.assertIn("15 gün", joined)
		self.assertIn("alt kullanıcı", joined)

	def test_trial_preview_wording(self):
		_STATE["subscription"]["status"] = "trial"
		out = identity.get_account_deletion_preview()
		joined = " ".join(out["consequences"])
		self.assertIn("ücret alınmaz", joined)
		self.assertNotIn("iade yapılmaz", joined)

	def test_non_owner_preview(self):
		_STATE["is_owner"] = 0
		out = identity.get_account_deletion_preview()
		self.assertFalse(out["has_store"])
		self.assertIsNone(out["store_name"])
		self.assertIsNone(out["active_subscription"])
		self.assertEqual(out["sub_user_count"], 0)
		self.assertEqual(out["grace_days"], 15)
		self.assertGreaterEqual(len(out["consequences"]), 2)


class TestDeleteAccountOwner(_Base):
	def test_owner_delete_cancels_subscription(self):
		identity.delete_account(password="Secret123")
		self.assertEqual(len(_STATE["saved_subs"]), 1)
		saved = _STATE["saved_subs"][0]
		self.assertEqual(saved["status"], "canceled")
		self.assertEqual(saved["cancellation_reason"], "account_deleted")
		self.assertTrue(saved["ignore_permissions"])

	def test_owner_delete_rejects_pending_payments(self):
		identity.delete_account(password="Secret123")
		rejected = [sv for sv in _STATE["set_values"] if sv[0] == "Subscription Payment"]
		self.assertEqual(len(rejected), 1)
		self.assertEqual(rejected[0][1], "SUBPAY-001")
		self.assertEqual(rejected[0][2], {"status": "rejected", "rejection_reason": "account_deleted"})

	def test_owner_delete_audit_context(self):
		identity.delete_account(password="Secret123")
		self.assertEqual(len(_STATE["audit"]), 1)
		ctx = _STATE["audit"][0]["context"]
		self.assertEqual(ctx["subscription_canceled"], "STSUB-2026-00001")
		self.assertEqual(ctx["previous_subscription_status"], "active")
		self.assertEqual(ctx["pending_payments_rejected"], 1)

	def test_owner_trial_subscription_also_canceled(self):
		# trial→canceled geçişi mevcut geçiş tablosunda — silme trial'ı da kapatır
		_STATE["subscription"]["status"] = "trial"
		identity.delete_account(password="Secret123")
		self.assertEqual(_STATE["saved_subs"][0]["status"], "canceled")
		self.assertEqual(_STATE["audit"][0]["context"]["previous_subscription_status"], "trial")

	def test_existing_soft_delete_behavior_preserved(self):
		identity.delete_account(password="Secret123")
		sets = _STATE["set_values"]
		self.assertIn(("User", "owner@test", "enabled", 0), sets)
		self.assertIn(("User Profile", "owner@test", "status", "Deactivated"), sets)
		self.assertIn(("Admin Seller Profile", "SEL-00001", "status", "Suspended"), sets)
		self.assertTrue(any(sv[:3] == ("User", "owner@test", "deletion_requested_on") for sv in sets))
		self.assertEqual(_STATE["sessions_cleared"], ["owner@test"])
		self.assertIn(("Mobile API Token", {"user": "owner@test"}), _STATE["deleted"])


class TestDeleteAccountNonOwner(_Base):
	def test_non_owner_delete_leaves_subscription_alone(self):
		_STATE["is_owner"] = 0
		_STATE["seller_profile"] = None
		identity.delete_account(password="Secret123")
		self.assertEqual(_STATE["saved_subs"], [])
		self.assertEqual([sv for sv in _STATE["set_values"] if sv[0] == "Subscription Payment"], [])
		ctx = _STATE["audit"][0]["context"]
		self.assertIsNone(ctx["subscription_canceled"])
		self.assertEqual(ctx["pending_payments_rejected"], 0)
		# temel soft-delete davranışı yine çalışır
		self.assertIn(("User", "owner@test", "enabled", 0), _STATE["set_values"])


class TestStateMachineAssumption(unittest.TestCase):
	def test_canceled_reachable_from_active_and_trial(self):
		"""BE-5 'X→canceled' yönüne dayanır — gerçek geçiş tablosunda mevcut olmalı."""
		from tradehub_core.tradehub_core.doctype.store_subscription import store_subscription

		self.assertIn("canceled", store_subscription._VALID_TRANSITIONS["active"])
		self.assertIn("canceled", store_subscription._VALID_TRANSITIONS["trial"])


class TestSessionRateLimit(_Base):
	"""Güvenlik denetimi kilidi: delete_account + preview limiti SESSION-bazlı.

	frappe.rate_limiter key="user" form_dict'ten okunuyordu (bypass); proje
	decorator'ı kimliği frappe.session.user'dan türetir — parola brute-force
	guard'ı (3/saat) form input'uyla atlatılamaz.
	"""

	def _spoof_form_dict(self, value: str) -> None:
		# Saldırgan simülasyonu: hem son yüklenen stub'a hem rate limiter'ın
		# gerçekte bağlı olduğu frappe objesine basılır — decorator OKUMAMALI.
		frappe.form_dict = {"user": value}
		rl = sys.modules.get("tradehub_core.api.rate_limit")
		if rl is not None:
			rl.frappe.form_dict = {"user": value}

	def test_delete_account_bucket_is_session_user(self):
		self._spoof_form_dict("attacker-bucket-1")
		identity.delete_account(password="Secret123")
		self._spoof_form_dict("attacker-bucket-2")
		identity.delete_account(password="Secret123")
		keys = [k for k in _rl_cache().counts if "delete_account" in k]
		self.assertEqual(len(keys), 1, "Farklı form_dict 'user' değerleri TEK bucket'ta saymalı")
		self.assertIn("owner@test", keys[0])
		self.assertEqual(_rl_cache().counts[keys[0]], 2)

	def test_delete_account_fourth_call_hits_429(self):
		from tradehub_core.api.rate_limit import TooManyRequestsError

		for _ in range(3):
			identity.delete_account(password="Secret123")
		self._spoof_form_dict("fresh-bucket-please")
		with self.assertRaises(TooManyRequestsError):
			identity.delete_account(password="Secret123")

	def test_preview_rate_limited_per_session(self):
		identity.get_account_deletion_preview()
		keys = [k for k in _rl_cache().counts if "account_deletion_preview" in k]
		self.assertEqual(len(keys), 1, "Preview ucu da session-bazlı sayaç yazmalı")
		self.assertIn("owner@test", keys[0])


class TestPrivacyAnonymization(_Base):
	def test_cancellation_fields_anonymized(self):
		account_deletion._anonymize_store_subscription("owner@test")
		writes = [sv for sv in _STATE["set_values"] if sv[0] == "Store Subscription"]
		self.assertEqual(len(writes), 1)
		self.assertEqual(writes[0][1], "STSUB-2026-00001")
		self.assertEqual(writes[0][2], {"cancel_requested_by": None, "cancellation_note": None})

	def test_old_schema_silently_skipped(self):
		_STATE["has_columns"] = set()  # BE-1 migrate edilmemiş
		account_deletion._anonymize_store_subscription("owner@test")
		self.assertEqual([sv for sv in _STATE["set_values"] if sv[0] == "Store Subscription"], [])

	def test_note_column_missing_only_link_cleared(self):
		_STATE["has_columns"] = {"cancel_requested_by"}
		account_deletion._anonymize_store_subscription("owner@test")
		writes = [sv for sv in _STATE["set_values"] if sv[0] == "Store Subscription"]
		self.assertEqual(writes[0][2], {"cancel_requested_by": None})


if __name__ == "__main__":
	unittest.main()
