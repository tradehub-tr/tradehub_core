"""BE-2 — api/v1/subscription_cancellation testleri (stub-frappe deseni).

request_cancellation:
  - AC-4: alt kullanıcı (tradehub_is_owner=0) → 403; platform admin boş-tenant
    yolu REDDEDİLİR (403); cross-tenant (Store Subscription.store != tenant) → 403.
  - R3: trial'da iptal → 417 (ödeme yok, trial_end otomatik sonlandırır).
  - Geçersiz reason / 500+ karakter not / current_period_end boş → 417.
  - Başarı: status 'active' KALIR, bayrak + cancellation alanları yazılır,
    audit (HIGH) + Platform Notification üretilir (AC-5, AC-11).
  - İdempotent: 2. çağrı already_scheduled=True + YAN ETKİSİZ (AC-6).

revoke_cancellation:
  - Başarı: bayrak 0'lanır + cancellation alanları temizlenir (AC-6).
  - İptal planlı değilken → 417.

BE-3 — cancel_requested_at (AC-8):
  - request doc'a now damgası yazar + yanıta additive cancel_requested_at ekler.
  - İdempotent tekrar çağrı damgayı DEĞİŞTİRMEZ — erken dönüş yolu DB'deki
    mevcut (ilk talep) değeri döner.
  - revoke damgayı diğer cancellation alanlarıyla birlikte temizler + yanıtına
    cancel_requested_at: None ekler.

Güvenlik denetimi ekleri:
  - Deny audit: alt kullanıcı ("not_owner") ve platform-admin boş-tenant yolu
    ("platform_admin_path") 403'ten ÖNCE DENY (HIGH) audit'i yazar.
  - Rate limit session-bazlı: kova kimliği frappe.session.user'dan türer —
    form_dict'e `user=<rastgele>` basmak bucket'ı DEĞİŞTİRMEZ (frappe
    rate_limiter key="user" bypass'ının kilidi); limit aşımı 429 fırlatır.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_subscription_cancellation
"""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _PermissionError(Exception):
	pass


class _ValidationError(Exception):
	pass


_NOW = datetime(2026, 9, 8, 12, 0, 0)
_PERIOD_END = datetime(2026, 10, 1, 0, 0, 0)
# BE-3: idempotency vakası için İLK talebin (DB'deki mevcut) damgası — _NOW'dan farklı.
_EARLIER_REQUESTED_AT = datetime(2026, 9, 1, 9, 30, 0)

_STATE: dict = {}


def _reset_state() -> None:
	_STATE.update(
		{
			"user": "owner@test",
			"roles": {"Seller Owner"},
			"is_owner": 1,
			"tenant": "SELLER-A",
			# Mevcut Store Subscription satırı (dict) veya None
			"existing_sub": None,
			"saved": [],  # (op, doctype, status)
			"last_sub_doc": None,
			"notifications": [],  # notify(**kwargs) kayıtları
			"audits": [],  # log_decision(**kwargs) kayıtları
			"commits": 0,
		}
	)
	_rl_cache().reset()


def _active_sub(**overrides) -> dict:
	sub = {
		"name": "STSUB-1",
		"store": "SELLER-A",
		"status": "active",
		"plan": "PRO",
		"current_period_end": _PERIOD_END,
		"cancel_at_period_end": 0,
		"cancel_requested_at": None,
	}
	sub.update(overrides)
	return sub


class _NSDict(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)


class _Doc(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)

	def save(self, *a, **k):
		_STATE["saved"].append(("save", getattr(self, "_doctype", "?"), getattr(self, "status", None)))

	def insert(self, *a, **k):
		_STATE["saved"].append(("insert", getattr(self, "_doctype", "?"), getattr(self, "status", None)))


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
		return self.expires.get(key, 300)

	def get_value(self, *a, **k):
		return None

	def set_value(self, *a, **k):
		return None

	def delete_value(self, *a, **k):
		return None


def _rl_cache() -> _CacheStub:
	"""Rate limiter'ın GERÇEKTE kullandığı cache objesi.

	`tradehub_core.api.rate_limit` modülünün `frappe` global'i, modülün ilk
	import edildiği andaki stub'a bağlıdır — sayaç reset'i ve assertion'lar
	sys.modules üzerinden o bağlanmış objeye gitmeli (solo koşuda bu dosyanın
	stub'ı, kombine koşuda ilk import edenin stub'ı olabilir).
	"""
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
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError):
		raise exc(msg)

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: a[0] if (a and callable(a[0])) else (lambda fn: fn)
	frappe.session = SimpleNamespace(user="owner@test")
	frappe.get_roles = lambda u=None: list(_STATE["roles"])
	frappe.log_error = lambda *a, **k: None

	def _get_value(doctype, name=None, fieldname=None, as_dict=False, **kw):
		if doctype == "User":
			return _NSDict(tradehub_tenant=_STATE["tenant"], tradehub_is_owner=_STATE["is_owner"])
		if doctype == "Store Subscription":
			sub = _STATE["existing_sub"]
			return _NSDict(**sub) if sub else None
		return None

	def _commit():
		_STATE["commits"] += 1

	frappe.db = SimpleNamespace(get_value=_get_value, exists=lambda *a, **k: True, commit=_commit)

	def _get_doc(doctype, name=None):
		d = _Doc(_doctype=doctype, name=name, flags=SimpleNamespace())
		if doctype == "Store Subscription":
			_STATE["last_sub_doc"] = d
		return d

	frappe.get_doc = _get_doc

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: _NOW
	utils.add_days = lambda d, n: d + timedelta(days=n)
	utils.add_months = lambda d, n: d + timedelta(days=30 * n)  # subscription.py importu için yeter
	utils.add_years = lambda d, n: d + timedelta(days=365 * n)
	utils.get_datetime = lambda d: d if isinstance(d, datetime) else datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
	utils.getdate = lambda d=None: d.date() if isinstance(d, datetime) else d
	utils.cint = lambda v: int(v or 0)
	sys.modules["frappe.utils"] = utils

	rate_limiter = types.ModuleType("frappe.rate_limiter")
	rate_limiter.rate_limit = lambda **k: lambda fn: fn
	sys.modules["frappe.rate_limiter"] = rate_limiter

	# Proje-içi rate limiter (tradehub_core.api.rate_limit) GERÇEK modül olarak
	# import edilir — kova kimliğinin session-bazlı olduğunu kilitlemek için
	# frappe.cache INCR/EXPIRE çağrıları cache objesinin üstünde sayılır.
	# frappe.cache hem attribute hem callable (frappe.cache()) kullanılıyor.
	frappe.cache = _CacheStub()
	# Saldırgan istemcinin gönderebildiği form input'u — proje decorator'ı bunu
	# ASLA okumamalı (frappe.rate_limiter key="user" bug'ının kilidi).
	frappe.form_dict = {}
	frappe.local = SimpleNamespace(request=None, response={})

	audit = types.ModuleType("tradehub_core.audit")

	def _log_decision(*a, **k):
		_STATE["audits"].append(k)
		return "AUDIT-1"

	audit.log_decision = _log_decision
	sys.modules["tradehub_core.audit"] = audit

	notify_mod = types.ModuleType("tradehub_core.utils.notify")

	def _notify(**k):
		_STATE["notifications"].append(k)
		return "NOTIF-1"

	notify_mod.notify = _notify
	sys.modules["tradehub_core.utils.notify"] = notify_mod


_install_frappe_stub()
_reset_state()

from tradehub_core.api.v1 import subscription_cancellation as sc  # noqa: E402


def _as_owner() -> None:
	_STATE["roles"] = {"Seller Owner"}
	_STATE["is_owner"] = 1


def _as_sub_user() -> None:
	_STATE["roles"] = {"Seller Staff"}
	_STATE["is_owner"] = 0


def _as_platform_admin() -> None:
	_STATE["roles"] = {"System Manager"}
	_STATE["is_owner"] = 0


class TestAuthorization(unittest.TestCase):
	"""AC-4 — owner-only çift katman: 403 alt kullanıcı / platform admin / cross-tenant."""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["existing_sub"] = _active_sub()

	def test_sub_user_cannot_request(self):
		_as_sub_user()
		with self.assertRaises(_PermissionError):
			sc.request_cancellation(reason="fiyat")
		self.assertEqual(_STATE["saved"], [], "403'te doc değişmemeli")

	def test_sub_user_cannot_revoke(self):
		_as_sub_user()
		_STATE["existing_sub"]["cancel_at_period_end"] = 1
		with self.assertRaises(_PermissionError):
			sc.revoke_cancellation()
		self.assertEqual(_STATE["saved"], [])

	def test_platform_admin_empty_tenant_path_rejected(self):
		# _resolve_tenant_for_caller admin için "" döner — bu uçlarda 403 (Desk'ten yapılır).
		_as_platform_admin()
		with self.assertRaises(_PermissionError):
			sc.request_cancellation(reason="fiyat")
		self.assertEqual(_STATE["saved"], [])

	def test_cross_tenant_request_denied(self):
		_STATE["existing_sub"]["store"] = "SELLER-B"
		with self.assertRaises(_PermissionError):
			sc.request_cancellation(reason="fiyat")
		self.assertEqual(_STATE["saved"], [], "Cross-tenant denemesi doc'a dokunmamalı")
		denies = [a for a in _STATE["audits"] if a.get("decision") == "DENY"]
		self.assertEqual(len(denies), 1, "Cross-tenant denemesi DENY audit'i yazmalı")
		self.assertEqual(denies[0]["rule_id"], "auth.subscription_cancellation")

	def test_cross_tenant_revoke_denied(self):
		_STATE["existing_sub"].update({"store": "SELLER-B", "cancel_at_period_end": 1})
		with self.assertRaises(_PermissionError):
			sc.revoke_cancellation()
		self.assertEqual(_STATE["saved"], [])


class TestRequestGuards(unittest.TestCase):
	"""417 guard'ları — trial (R3), geçersiz reason, uzun not, dönem bilgisi eksik."""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["existing_sub"] = _active_sub()

	def test_trial_cannot_cancel(self):
		# R3 — trial'da iptal aksiyonu yok; API de 417 döner (Apple demo hesabı riski).
		_STATE["existing_sub"]["status"] = "trial"
		with self.assertRaises(_ValidationError):
			sc.request_cancellation(reason="fiyat")
		self.assertEqual(_STATE["saved"], [])

	def test_invalid_reason_rejected(self):
		with self.assertRaises(_ValidationError):
			sc.request_cancellation(reason="baska_sebep")
		self.assertEqual(_STATE["saved"], [])

	def test_empty_reason_rejected(self):
		with self.assertRaises(_ValidationError):
			sc.request_cancellation(reason="")

	def test_note_over_500_chars_rejected(self):
		with self.assertRaises(_ValidationError):
			sc.request_cancellation(reason="diger", note="x" * 501)
		self.assertEqual(_STATE["saved"], [])

	def test_missing_period_end_rejected(self):
		# BE-1 backfill önkoşulu: current_period_end boşsa iptal planlanamaz.
		_STATE["existing_sub"]["current_period_end"] = None
		with self.assertRaises(_ValidationError):
			sc.request_cancellation(reason="fiyat")
		self.assertEqual(_STATE["saved"], [])


class TestRequestSuccess(unittest.TestCase):
	"""AC-5 + AC-6 + AC-11 — başarı yanıtı, yazılan alanlar, idempotency."""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["existing_sub"] = _active_sub()

	def test_success_sets_flag_without_status_change(self):
		out = sc.request_cancellation(reason="fiyat", note="pahalı geldi")
		self.assertEqual(
			out,
			{
				"ok": True,
				"subscription": "STSUB-1",
				"status": "active",
				"cancel_at_period_end": 1,
				"effective_end": _PERIOD_END,
				"plan": "PRO",
				"already_scheduled": False,
				"cancel_requested_at": _NOW,
			},
		)
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.cancel_at_period_end, 1)
		self.assertEqual(doc.cancellation_reason, "fiyat")
		self.assertEqual(doc.cancellation_note, "pahalı geldi")
		self.assertEqual(doc.cancel_requested_by, "owner@test")
		self.assertEqual(doc.cancel_requested_at, _NOW, "BE-3: talep anı doc'a yazılmalı")
		self.assertIsNone(doc.get("status"), "Status'a DOKUNULMAMALI — state machine devreye girmemeli")
		self.assertEqual(_STATE["saved"], [("save", "Store Subscription", None)])
		self.assertEqual(_STATE["commits"], 1)

	def test_success_writes_audit_and_notification(self):
		sc.request_cancellation(reason="kapaniyor")
		self.assertEqual(len(_STATE["audits"]), 1)
		audit = _STATE["audits"][0]
		self.assertEqual(audit["decision"], "ALLOW")
		self.assertEqual(audit["severity"], "HIGH")
		self.assertEqual(audit["rule_id"], "auth.subscription_cancellation")
		self.assertEqual(audit["tenant"], "SELLER-A")
		self.assertEqual(len(_STATE["notifications"]), 1)
		notif = _STATE["notifications"][0]
		self.assertEqual(notif["type"], "system")
		self.assertIn(str(_PERIOD_END), notif["message"], "Bildirim bitiş tarihini içermeli")
		self.assertIn("Geri Al", notif["message"], "Bildirim geri alma yolunu içermeli")

	def test_second_call_is_idempotent_and_side_effect_free(self):
		_STATE["existing_sub"].update(
			{"cancel_at_period_end": 1, "cancel_requested_at": _EARLIER_REQUESTED_AT}
		)
		out = sc.request_cancellation(reason="fiyat")
		self.assertTrue(out["already_scheduled"])
		self.assertEqual(out["cancel_at_period_end"], 1)
		self.assertEqual(out["effective_end"], _PERIOD_END)
		self.assertEqual(_STATE["saved"], [], "İdempotent tekrar çağrı doc yazmamalı")
		self.assertEqual(_STATE["notifications"], [], "İdempotent tekrar çağrı bildirim atmamalı")
		self.assertEqual(_STATE["audits"], [], "İdempotent tekrar çağrı audit üretmemeli")

	def test_idempotent_call_preserves_original_cancel_requested_at(self):
		"""BE-3 / AC-8: tekrar çağrı tarihi DEĞİŞTİRMEZ — erken dönüş yolunda yanıt
		DB'deki mevcut damgayı (ilk talep anını) döner, now'ı değil."""
		_STATE["existing_sub"].update(
			{"cancel_at_period_end": 1, "cancel_requested_at": _EARLIER_REQUESTED_AT}
		)
		out = sc.request_cancellation(reason="fiyat")
		self.assertEqual(out["cancel_requested_at"], _EARLIER_REQUESTED_AT)
		self.assertNotEqual(out["cancel_requested_at"], _NOW)
		self.assertEqual(_STATE["saved"], [], "Erken dönüş yolunda damga yeniden yazılmamalı")


class TestRevoke(unittest.TestCase):
	"""AC-6 — geri alma: bayrak 0 + alan temizliği; planlı iptal yoksa 417."""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["existing_sub"] = _active_sub(
			cancel_at_period_end=1, cancel_requested_at=_EARLIER_REQUESTED_AT
		)

	def test_revoke_success_clears_flag_and_fields(self):
		out = sc.revoke_cancellation()
		self.assertEqual(
			out,
			{
				"ok": True,
				"subscription": "STSUB-1",
				"status": "active",
				"cancel_at_period_end": 0,
				"current_period_end": _PERIOD_END,
				"plan": "PRO",
				"cancel_requested_at": None,
			},
		)
		doc = _STATE["last_sub_doc"]
		self.assertEqual(doc.cancel_at_period_end, 0)
		self.assertIsNone(doc.cancellation_reason)
		self.assertIsNone(doc.cancellation_note)
		self.assertIsNone(doc.cancel_requested_by)
		self.assertIsNone(doc.cancel_requested_at, "BE-3: revoke damgayı da temizlemeli")
		self.assertEqual(_STATE["saved"], [("save", "Store Subscription", None)])
		self.assertEqual(len(_STATE["audits"]), 1)
		self.assertEqual(_STATE["audits"][0]["decision"], "ALLOW")
		self.assertEqual(len(_STATE["notifications"]), 1)

	def test_revoke_without_scheduled_cancellation_rejected(self):
		_STATE["existing_sub"]["cancel_at_period_end"] = 0
		with self.assertRaises(_ValidationError):
			sc.revoke_cancellation()
		self.assertEqual(_STATE["saved"], [])
		self.assertEqual(_STATE["notifications"], [])


class TestDenyAudit(unittest.TestCase):
	"""Güvenlik denetimi: yetkisiz denemeler 403'ten ÖNCE DENY audit'i yazmalı."""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["existing_sub"] = _active_sub()

	def _single_deny(self) -> dict:
		denies = [a for a in _STATE["audits"] if a.get("decision") == "DENY"]
		self.assertEqual(len(denies), 1, "Tam 1 DENY audit'i yazılmalı")
		return denies[0]

	def test_sub_user_deny_audited_as_not_owner(self):
		_as_sub_user()
		with self.assertRaises(_PermissionError):
			sc.request_cancellation(reason="fiyat")
		deny = self._single_deny()
		self.assertEqual(deny["severity"], "HIGH")
		self.assertEqual(deny["rule_id"], "auth.subscription_cancellation")
		self.assertEqual(deny["context"], {"denied": "not_owner"})

	def test_platform_admin_deny_audited_as_platform_admin_path(self):
		_as_platform_admin()
		with self.assertRaises(_PermissionError):
			sc.request_cancellation(reason="fiyat")
		deny = self._single_deny()
		self.assertEqual(deny["severity"], "HIGH")
		self.assertEqual(deny["context"], {"denied": "platform_admin_path"})

	def test_revoke_deny_audited_too(self):
		_as_sub_user()
		_STATE["existing_sub"]["cancel_at_period_end"] = 1
		with self.assertRaises(_PermissionError):
			sc.revoke_cancellation()
		deny = self._single_deny()
		self.assertEqual(deny["context"], {"denied": "not_owner"})


class TestRateLimitSessionIdentity(unittest.TestCase):
	"""MAJOR fix kilidi: rate-limit kovası SESSION user'a bağlı.

	Frappe v15 `rate_limit(key="user")` form_dict'teki 'user' parametresini
	okur — istemci her istekte `user=<rastgele>` göndererek yeni bucket açıp
	limiti atlayabilirdi. Proje decorator'ı (tradehub_core.api.rate_limit)
	kimliği frappe.session.user'dan türetir; bu testler o davranışı kilitler.
	"""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["existing_sub"] = _active_sub()

	def _bucket_keys(self) -> list[str]:
		return list(_rl_cache().counts.keys())

	def _spoof_form_dict(self, value: str) -> None:
		# Saldırgan simülasyonu: hem son yüklenen stub'a hem rate limiter'ın
		# gerçekte bağlı olduğu frappe objesine basılır — decorator OKUMAMALI.
		sys.modules["frappe"].form_dict = {"user": value}
		rl = sys.modules.get("tradehub_core.api.rate_limit")
		if rl is not None:
			rl.frappe.form_dict = {"user": value}

	def test_spoofed_form_dict_user_does_not_change_bucket(self):
		self._spoof_form_dict("attacker-bucket-1")
		sc.request_cancellation(reason="fiyat")
		self._spoof_form_dict("attacker-bucket-2")
		_STATE["existing_sub"]["cancel_at_period_end"] = 1  # idempotent yol, yan etkisiz
		sc.request_cancellation(reason="fiyat")

		keys = self._bucket_keys()
		self.assertEqual(len(keys), 1, "Farklı form_dict 'user' değerleri TEK bucket'ta saymalı")
		self.assertIn("owner@test", keys[0], "Kova kimliği session user'dan türemeli")
		self.assertNotIn("attacker-bucket", keys[0])
		self.assertEqual(_rl_cache().counts[keys[0]], 2, "Her iki çağrı aynı sayaca yazılmalı")

	def test_limit_exhaustion_raises_429_for_session_user(self):
		from tradehub_core.api.rate_limit import TooManyRequestsError

		_STATE["existing_sub"]["cancel_at_period_end"] = 1  # idempotent, yan etkisiz yol
		for _ in range(5):
			sc.request_cancellation(reason="fiyat")
		# 6. çağrı: form_dict'e yeni 'user' basmak da kurtarmamalı.
		self._spoof_form_dict("fresh-bucket-please")
		with self.assertRaises(TooManyRequestsError):
			sc.request_cancellation(reason="fiyat")

	def test_endpoints_use_separate_scopes_but_same_identity(self):
		_STATE["existing_sub"]["cancel_at_period_end"] = 1
		sc.request_cancellation(reason="fiyat")
		sc.revoke_cancellation()
		keys = sorted(self._bucket_keys())
		self.assertEqual(len(keys), 2)
		self.assertTrue(all("owner@test" in k for k in keys))
		self.assertTrue(any("request_cancellation" in k for k in keys))
		self.assertTrue(any("revoke_cancellation" in k for k in keys))


if __name__ == "__main__":
	unittest.main()
