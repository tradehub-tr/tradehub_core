"""BE-2 — api/v1/subscription_payment testleri (stub-frappe deseni).

create_bank_transfer_request (AC-5 + E4):
  - Bekleyen talep, plan+cycle AYNI olsa bile güncel plan fiyatından farklıysa
    amount/currency tazelenir (bayat 5.990€ → 7.188€) ve yanıta additive
    `amount_updated: true` eklenir.
  - Fiyat aynıysa: doc'a dokunulmaz, `amount_updated` yanıtta HİÇ yer almaz —
    mevcut yanıt alan seti birebir korunur.
  - Currency değişimi de tazeleme sayılır (risk kaydı: para birimi birlikte
    güncellenir).
  - Plan/cycle değişiminde mevcut güncelleme davranışı korunur; tutar da
    değiştiyse amount_updated true, iki plan aynı fiyattaysa alan eklenmez
    (E4: sinyal "tutar güncellendiyse").

list_my_subscription_payments (AC-6):
  - Owner-only çift katman: alt kullanıcı (tradehub_is_owner=0), platform-admin
    boş-tenant yolu ve guest → 403 (sorgu HİÇ çalışmaz, DENY audit yazılır).
  - Sorgu store=tenant filtresi + requested_at desc + limit 100 ile gider.
  - Cross-tenant: filtre katmanı gevşese bile store'u eşleşmeyen satır yanıta
    SIZMAZ (defense-in-depth ikinci katman).
  - Alan seti sözleşmeyle birebir: name, plan, billing_cycle, amount, currency,
    reference_code, status, requested_at, confirmed_at, rejection_reason
    (store yanıtta YOK).
  - Rate limit kovası session user'a bağlı (proje decorator'ı, scope ayrı).

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_subscription_payment_requests
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


_NOW = datetime(2026, 9, 15, 12, 0, 0)

_STATE: dict = {}


def _reset_state() -> None:
	_STATE.update(
		{
			"user": "owner@test",
			"roles": {"Seller Owner"},
			"is_owner": 1,
			"tenant": "SELLER-A",
			"seller_status": "Active",
			# Subscription Plan kayıtları (name → dict)
			"plans": {
				"PRO": {
					"name": "PRO",
					"is_active": 1,
					"monthly_price": 599,
					"yearly_price": 7188,
					"currency": "EUR",
				},
				"BASIC": {
					"name": "BASIC",
					"is_active": 1,
					"monthly_price": 99,
					"yearly_price": 990,
					"currency": "EUR",
				},
			},
			# Mevcut pending Subscription Payment satırı (dict) veya None
			"pending_payment": None,
			# list_my_subscription_payments için get_all dönüşü
			"payment_rows": [],
			"get_all_calls": [],  # (doctype, kwargs)
			"saved": [],  # (op, doctype)
			"last_payment_doc": None,
			"notifications": [],
			"audits": [],
			"commits": 0,
		}
	)
	frappe = sys.modules.get("frappe")
	if frappe is not None:
		frappe.session.user = "owner@test"
	_rl_cache().reset()


def _pending(**overrides) -> dict:
	row = {
		"name": "SUBPAY-1",
		"store": "SELLER-A",
		"plan": "PRO",
		"billing_cycle": "yearly",
		"amount": 5990.0,
		"currency": "EUR",
		"status": "pending",
		"reference_code": "REF-001",
	}
	row.update(overrides)
	return row


def _history_row(**overrides) -> dict:
	row = {
		"name": "SUBPAY-9",
		"store": "SELLER-A",
		"plan": "PRO",
		"billing_cycle": "yearly",
		"amount": 7188.0,
		"currency": "EUR",
		"reference_code": "REF-009",
		"status": "confirmed",
		"requested_at": _NOW - timedelta(days=30),
		"confirmed_at": _NOW - timedelta(days=29),
		"rejection_reason": None,
	}
	row.update(overrides)
	return row


class _NSDict(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)


class _Doc(SimpleNamespace):
	def get(self, k, default=None):
		return getattr(self, k, default)

	def save(self, *a, **k):
		_STATE["saved"].append(("save", getattr(self, "_doctype", "?")))

	def insert(self, *a, **k):
		# Gerçek insert name + autoname reference_code atar — stub sabitler.
		self.name = "SUBPAY-NEW"
		if not getattr(self, "reference_code", None):
			self.reference_code = "REF-NEW"
		_STATE["saved"].append(("insert", getattr(self, "_doctype", "?")))


class _CacheStub:
	"""Sahte frappe.cache — rate limiter'ın INCR/EXPIRE/TTL sayaçlarını tutar."""

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
	"""Rate limiter'ın GERÇEKTE bağlı olduğu cache objesi (kombine koşu emniyeti).

	`tradehub_core.api.rate_limit` modülünün `frappe` global'i, modülün ilk
	import edildiği andaki stub'a bağlıdır — reset/okuma sys.modules üzerinden
	o bağlanmış objeye gitmeli (test_subscription_cancellation ile aynı desen).
	"""
	rl = sys.modules.get("tradehub_core.api.rate_limit")
	cache = getattr(getattr(rl, "frappe", None), "cache", None)
	if cache is None:
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
		if doctype == "Admin Seller Profile":
			return _STATE["seller_status"]
		if doctype == "Subscription Payment":
			# create_bank_transfer_request'in pending lookup'ı (filters dict).
			pending = _STATE["pending_payment"]
			if pending and isinstance(name, dict):
				if name.get("store") == pending["store"] and name.get("status") == pending["status"]:
					return pending["name"]
			return None
		return None

	def _commit():
		_STATE["commits"] += 1

	frappe.db = SimpleNamespace(
		get_value=_get_value,
		exists=lambda doctype, name=None: name in _STATE["plans"] if doctype == "Subscription Plan" else True,
		commit=_commit,
	)

	def _get_doc(doctype, name=None):
		if doctype == "Subscription Plan":
			return _NSDict(**_STATE["plans"][name])
		if doctype == "Subscription Payment":
			pending = _STATE["pending_payment"] or {}
			d = _Doc(_doctype=doctype, flags=SimpleNamespace(), **pending)
			_STATE["last_payment_doc"] = d
			return d
		return _Doc(_doctype=doctype, name=name, flags=SimpleNamespace())

	frappe.get_doc = _get_doc

	def _new_doc(doctype):
		d = _Doc(_doctype=doctype, flags=SimpleNamespace(), reference_code=None)
		if doctype == "Subscription Payment":
			_STATE["last_payment_doc"] = d
		return d

	frappe.new_doc = _new_doc

	def _get_all(doctype, **kwargs):
		if doctype == "Subscription Payment":
			_STATE["get_all_calls"].append((doctype, kwargs))
			fields = kwargs.get("fields") or []
			# Stub filtre UYGULAMAZ (bilinçli): endpoint'in defense-in-depth
			# ikinci katmanı "filtre gevşedi" senaryosunda test edilebilsin.
			return [{k: r.get(k) for k in fields} for r in _STATE["payment_rows"]]
		return []  # Has Role (admin bildirimi) vb.

	frappe.get_all = _get_all
	frappe.get_cached_doc = lambda doctype: _NSDict(
		subscription_bank_name="Test Bank",
		subscription_account_holder="İstoç AŞ",
		subscription_iban="TR00 0000",
		subscription_payment_instructions="Açıklamaya referans kodu yazın",
	)

	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: _NOW
	utils.add_days = lambda d, n: d + timedelta(days=n)
	utils.add_months = lambda d, n: d + timedelta(days=30 * n)  # subscription.py importu için yeter
	utils.add_years = lambda d, n: d + timedelta(days=365 * n)
	utils.getdate = lambda d=None: d.date() if isinstance(d, datetime) else d
	utils.cint = lambda v: int(v or 0)
	# subscription.py (BE-1 devir dalı) modül seviyesinde get_datetime import ediyor.
	utils.get_datetime = lambda d=None: d if isinstance(d, datetime) else datetime.fromisoformat(str(d))
	sys.modules["frappe.utils"] = utils

	# frappe.cache hem attribute hem callable (frappe.cache()) kullanılıyor.
	frappe.cache = _CacheStub()
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

# Kombine koşu emniyeti: bu modüller daha önce BAŞKA bir stub ile import
# edildiyse bayat frappe bağlanmış olur — bizim stub'la yeniden yüklenir
# (rate_limit bilinçli pop edilmez; sayaçlara _rl_cache üzerinden gidilir).
for _mod in (
	"tradehub_core.api.v1.subscription_payment",
	"tradehub_core.api.v1.subscription_cancellation",
	"tradehub_core.api.v1.subscription",
):
	sys.modules.pop(_mod, None)

from tradehub_core.api.v1 import subscription_payment as sp  # noqa: E402

# Sözleşme: mevcut create_bank_transfer_request yanıt alanları (E4 öncesi).
_BASE_VIEW_KEYS = {"payment", "status", "plan", "billing_cycle", "amount", "currency", "reference_code", "bank"}

_CONTRACT_LIST_FIELDS = {
	"name",
	"plan",
	"billing_cycle",
	"amount",
	"currency",
	"reference_code",
	"status",
	"requested_at",
	"confirmed_at",
	"rejection_reason",
}


def _as_owner() -> None:
	_STATE["roles"] = {"Seller Owner"}
	_STATE["is_owner"] = 1


def _as_sub_user() -> None:
	_STATE["roles"] = {"Seller Staff"}
	_STATE["is_owner"] = 0


def _as_platform_admin() -> None:
	_STATE["roles"] = {"System Manager"}
	_STATE["is_owner"] = 0


def _as_guest() -> None:
	sys.modules["frappe"].session.user = "Guest"


class TestAmountRefresh(unittest.TestCase):
	"""AC-5 + E4 — bekleyen talep tutar tazeleme + additive amount_updated sinyali."""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["pending_payment"] = _pending(amount=5990.0)  # bayat fiyat (plan: 7188)

	def test_stale_amount_refreshed_same_plan_and_cycle(self):
		out = sp.create_bank_transfer_request(plan="PRO", billing_cycle="yearly")
		doc = _STATE["last_payment_doc"]
		self.assertEqual(doc.amount, 7188.0, "Tutar güncel plan fiyatına tazelenmeli")
		self.assertEqual(doc.currency, "EUR")
		self.assertEqual(doc.plan, "PRO")
		self.assertEqual(doc.billing_cycle, "yearly")
		self.assertEqual(_STATE["saved"], [("save", "Subscription Payment")])
		self.assertEqual(_STATE["commits"], 1)
		self.assertEqual(out["amount"], 7188.0, "Yanıt güncel tutarı dönmeli")
		self.assertIs(out.get("amount_updated"), True, "E4: bu çağrıda tutar güncellendi sinyali")
		self.assertEqual(set(out.keys()), _BASE_VIEW_KEYS | {"amount_updated"})

	def test_same_price_no_update_and_no_signal(self):
		_STATE["pending_payment"] = _pending(amount=7188.0)
		out = sp.create_bank_transfer_request(plan="PRO", billing_cycle="yearly")
		self.assertEqual(_STATE["saved"], [], "Fiyat aynıysa doc'a dokunulmamalı")
		self.assertEqual(_STATE["commits"], 0)
		self.assertNotIn("amount_updated", out, "Tutar değişmediyse alan HİÇ eklenmez")
		self.assertEqual(set(out.keys()), _BASE_VIEW_KEYS, "Mevcut yanıt alan seti birebir korunmalı")
		self.assertEqual(out["amount"], 7188.0)
		self.assertEqual(out["reference_code"], "REF-001", "Referans kodu değişmemeli")

	def test_currency_change_counts_as_stale(self):
		# Tutar sayısal olarak aynı ama plan para birimi değişmiş (risk kaydı).
		_STATE["plans"]["PRO"]["currency"] = "TRY"
		_STATE["pending_payment"] = _pending(amount=7188.0, currency="EUR")
		out = sp.create_bank_transfer_request(plan="PRO", billing_cycle="yearly")
		doc = _STATE["last_payment_doc"]
		self.assertEqual(doc.currency, "TRY", "Para birimi birlikte güncellenmeli")
		self.assertEqual(_STATE["saved"], [("save", "Subscription Payment")])
		self.assertIs(out.get("amount_updated"), True)

	def test_plan_change_still_updates_with_signal_when_amount_differs(self):
		# Mevcut davranış korunur: plan değişimi güncelleme tetikler; tutar da
		# değiştiği için E4 sinyali eklenir.
		_STATE["pending_payment"] = _pending(plan="BASIC", amount=990.0)
		out = sp.create_bank_transfer_request(plan="PRO", billing_cycle="yearly")
		doc = _STATE["last_payment_doc"]
		self.assertEqual(doc.plan, "PRO")
		self.assertEqual(doc.amount, 7188.0)
		self.assertEqual(_STATE["saved"], [("save", "Subscription Payment")])
		self.assertIs(out.get("amount_updated"), True)

	def test_plan_change_same_price_updates_without_signal(self):
		# İki plan aynı fiyattaysa: güncelleme olur ama "tutar güncellendi"
		# sinyali YANLIŞ olurdu — E4 yalnız tutar değişimini işaretler.
		_STATE["plans"]["BASIC"]["yearly_price"] = 7188
		_STATE["pending_payment"] = _pending(plan="BASIC", amount=7188.0)
		out = sp.create_bank_transfer_request(plan="PRO", billing_cycle="yearly")
		self.assertEqual(_STATE["saved"], [("save", "Subscription Payment")], "Plan değişimi kaydedilmeli")
		self.assertNotIn("amount_updated", out)

	def test_no_pending_creates_new_request(self):
		# Regresyon: pending yokken mevcut oluşturma akışı değişmedi.
		_STATE["pending_payment"] = None
		out = sp.create_bank_transfer_request(plan="PRO", billing_cycle="yearly")
		self.assertEqual(_STATE["saved"], [("insert", "Subscription Payment")])
		self.assertEqual(set(out.keys()), _BASE_VIEW_KEYS)
		self.assertEqual(out["amount"], 7188.0)


class TestListAuthorization(unittest.TestCase):
	"""AC-6 — owner-only çift katman: 403 alt kullanıcı / platform admin / guest."""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["payment_rows"] = [_history_row()]

	def _assert_denied_without_query(self):
		self.assertEqual(_STATE["get_all_calls"], [], "403'te sorgu HİÇ çalışmamalı")
		denies = [a for a in _STATE["audits"] if a.get("decision") == "DENY"]
		self.assertEqual(len(denies), 1, "Yetkisiz deneme DENY audit'i yazmalı")

	def test_sub_user_denied(self):
		_as_sub_user()
		with self.assertRaises(_PermissionError) as ctx:
			sp.list_my_subscription_payments()
		self.assertIn("Sadece mağaza sahibi ödeme geçmişini görüntüleyebilir.", str(ctx.exception))
		self._assert_denied_without_query()

	def test_platform_admin_empty_tenant_path_denied(self):
		# _resolve_tenant_for_caller admin için "" döner — owner-only uçta 403
		# (admin geçmişi Desk'ten list_subscription_payments ile görür).
		_as_platform_admin()
		with self.assertRaises(_PermissionError):
			sp.list_my_subscription_payments()
		self._assert_denied_without_query()

	def test_guest_denied(self):
		_as_guest()
		with self.assertRaises(_PermissionError):
			sp.list_my_subscription_payments()
		self.assertEqual(_STATE["get_all_calls"], [])


class TestListScopingAndContract(unittest.TestCase):
	"""AC-6 — store filtresi, cross-tenant sızıntı, alan seti + sıralama sözleşmesi."""

	def setUp(self):
		_reset_state()
		_as_owner()
		_STATE["payment_rows"] = [
			_history_row(
				name="SUBPAY-3",
				status="pending",
				requested_at=_NOW - timedelta(days=1),
				confirmed_at=None,
			),
			_history_row(name="SUBPAY-2", requested_at=_NOW - timedelta(days=10)),
			_history_row(
				name="SUBPAY-1",
				status="rejected",
				requested_at=_NOW - timedelta(days=40),
				confirmed_at=None,
				rejection_reason="Havale bulunamadı",
			),
		]

	def test_query_uses_tenant_filter_ordering_and_limit(self):
		sp.list_my_subscription_payments()
		self.assertEqual(len(_STATE["get_all_calls"]), 1)
		doctype, kwargs = _STATE["get_all_calls"][0]
		self.assertEqual(doctype, "Subscription Payment")
		self.assertEqual(kwargs["filters"], {"store": "SELLER-A"}, "1. katman: store=tenant filtresi")
		self.assertEqual(kwargs["order_by"], "requested_at desc")
		self.assertEqual(kwargs["limit_page_length"], 100)
		self.assertEqual(set(kwargs["fields"]), _CONTRACT_LIST_FIELDS | {"store"})

	def test_cross_tenant_row_never_leaks(self):
		# Stub filtre uygulamaz — filtre katmanı gevşedi senaryosu: yabancı
		# mağazanın satırı 2. katmanda (store doğrulaması) düşmeli.
		_STATE["payment_rows"].insert(0, _history_row(name="SUBPAY-EVIL", store="SELLER-B"))
		rows = sp.list_my_subscription_payments()
		self.assertEqual([r["name"] for r in rows], ["SUBPAY-3", "SUBPAY-2", "SUBPAY-1"])
		self.assertNotIn("SUBPAY-EVIL", [r["name"] for r in rows])

	def test_rows_expose_exact_contract_field_set(self):
		rows = sp.list_my_subscription_payments()
		self.assertEqual(len(rows), 3)
		for r in rows:
			self.assertEqual(set(r.keys()), _CONTRACT_LIST_FIELDS, "store yanıtta YER ALMAZ")
		# Sıralama sorgudan geldiği gibi korunur (requested_at desc).
		self.assertEqual([r["name"] for r in rows], ["SUBPAY-3", "SUBPAY-2", "SUBPAY-1"])
		pending = rows[0]
		self.assertEqual(pending["status"], "pending")
		self.assertIsNone(pending["confirmed_at"])
		rejected = rows[2]
		self.assertEqual(rejected["rejection_reason"], "Havale bulunamadı")

	def test_rate_limit_bucket_is_session_scoped(self):
		sp.list_my_subscription_payments()
		sp.list_my_subscription_payments()
		keys = [k for k in _rl_cache().counts if "list_my_subscription_payments" in k]
		self.assertEqual(len(keys), 1, "Uç kendi scope'unda tek kovada saymalı")
		self.assertIn("owner@test", keys[0], "Kova kimliği session user'dan türemeli")
		self.assertEqual(_rl_cache().counts[keys[0]], 2)


if __name__ == "__main__":
	unittest.main()
