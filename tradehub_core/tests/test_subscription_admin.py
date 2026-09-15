"""BE-6 — api/v1/subscription_admin testleri (stub-frappe deseni, AC-12).

list_attention_subscriptions:
  - Yetki: yalnız System Manager / Marketplace Admin — mağaza sahibi, alt
    kullanıcı ve rolsüz kullanıcı 403 alır; 403'te HİÇBİR veri sorgusu koşmaz.
  - cancellations: status='active' + cancel_at_period_end=1 satırları,
    current_period_end asc; diğer status/bayrak kombinasyonları DIŞARIDA.
  - dunning: status IN ('past_due','suspended') satırları (suspended_at dahil).
  - store_name: Admin Seller Profile.seller_name TEK batch sorguyla (N+1 yok);
    profili olmayan mağaza store kimliğine düşer.
  - reason_breakdown: yalnız cancellations bloğundan, yalnız GÖRÜLEN (>0)
    anahtarlar — allowlist'in sıfır kalan sebepleri yanıta girmez.
  - Boş durum: {"cancellations": [], "dunning": [], "reason_breakdown": {}} ve
    profil sorgusu hiç koşmaz.
  - get_all çağrıları limit 500 + current_period_end asc ile gider.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_subscription_admin
"""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _PermissionError(Exception):
	pass


class _ValidationError(Exception):
	pass


_STATE: dict = {}


def _reset_state() -> None:
	_STATE.update(
		{
			"roles": {"Marketplace Admin"},
			"subs": [],  # Store Subscription satırları (dict)
			"profiles": {},  # store -> seller_name (Admin Seller Profile)
			"get_all_calls": [],  # (doctype, filters, order_by, limit) kayıtları
		}
	)
	_rl_cache().reset()


class _CacheStub:
	"""Sahte frappe.cache — proje rate limiter'ının INCR/EXPIRE/TTL arayüzü."""

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

	`tradehub_core.api.rate_limit` modülünün `frappe` global'i İLK import'taki
	stub'a bağlı kalır — reset her zaman o objeye gitmeli (solo koşuda bu
	dosyanın stub'ı, kombine koşuda ilk import edenin stub'ı olabilir).
	"""
	rl = sys.modules.get("tradehub_core.api.rate_limit")
	cache = getattr(getattr(rl, "frappe", None), "cache", None)
	if cache is None:
		cache = getattr(sys.modules.get("frappe"), "cache", None) or _CacheStub()
	return cache


def _matches(row: dict, filters: dict | None) -> bool:
	for field, cond in (filters or {}).items():
		if isinstance(cond, (list, tuple)) and cond and cond[0] == "in":
			if row.get(field) not in cond[1]:
				return False
		elif row.get(field) != cond:
			return False
	return True


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
	frappe.session = SimpleNamespace(user="admin@test")
	frappe.get_roles = lambda u=None: list(_STATE["roles"])
	frappe.log_error = lambda *a, **k: None
	frappe.local = SimpleNamespace(request=None, response={})
	frappe.form_dict = {}
	# rate_limit decorator'ı frappe.cache() üzerinden atomik INCR yapar.
	frappe.cache = _CacheStub()

	def _only_for(roles, message=False):
		allowed = {roles} if isinstance(roles, str) else set(roles)
		if not allowed & set(_STATE["roles"]):
			raise _PermissionError(f"403: rol gerekli {sorted(allowed)}")

	frappe.only_for = _only_for

	def _get_all(doctype, filters=None, fields=None, order_by=None, limit_page_length=None, **kw):
		_STATE["get_all_calls"].append(
			{
				"doctype": doctype,
				"filters": filters,
				"order_by": order_by,
				"limit": limit_page_length,
			}
		)
		if doctype == "Store Subscription":
			rows = [dict(r) for r in _STATE["subs"] if _matches(r, filters)]
			if order_by:
				field, _sep, direction = order_by.partition(" ")
				rows.sort(key=lambda r: r.get(field), reverse=direction.strip() == "desc")
			if limit_page_length:
				rows = rows[:limit_page_length]
			return [{f: r.get(f) for f in (fields or r.keys())} for r in rows]
		if doctype == "Admin Seller Profile":
			wanted = (filters or {}).get("name", ["in", []])[1]
			return [
				{"name": store, "seller_name": _STATE["profiles"][store]}
				for store in wanted
				if store in _STATE["profiles"]
			]
		return []

	frappe.get_all = _get_all


_install_frappe_stub()
_reset_state()

from tradehub_core.api.v1 import subscription_admin as sa  # noqa: E402

_END_EARLY = datetime(2026, 9, 20, 0, 0, 0)
_END_LATE = datetime(2026, 10, 1, 0, 0, 0)
_REQUESTED_AT = datetime(2026, 9, 10, 12, 0, 0)
_SUSPENDED_AT = datetime(2026, 9, 12, 8, 0, 0)


def _sub(**overrides) -> dict:
	row = {
		"name": "STSUB-X",
		"store": "SELLER-A",
		"status": "active",
		"plan": "PRO",
		"cancel_at_period_end": 0,
		"cancellation_reason": None,
		"cancel_requested_at": None,
		"current_period_end": _END_LATE,
		"suspended_at": None,
	}
	row.update(overrides)
	return row


def _store_sub_calls() -> list[dict]:
	return [c for c in _STATE["get_all_calls"] if c["doctype"] == "Store Subscription"]


def _profile_calls() -> list[dict]:
	return [c for c in _STATE["get_all_calls"] if c["doctype"] == "Admin Seller Profile"]


class TestAuthorization(unittest.TestCase):
	"""AC-12 — superadmin-only: mağaza sahibi / alt kullanıcı / rolsüz → 403."""

	def setUp(self):
		_reset_state()
		_STATE["subs"] = [_sub(cancel_at_period_end=1, cancellation_reason="fiyat")]

	def _assert_denied(self):
		with self.assertRaises(_PermissionError):
			sa.list_attention_subscriptions()
		self.assertEqual(_STATE["get_all_calls"], [], "403'te hiçbir veri sorgusu koşmamalı")

	def test_seller_owner_denied(self):
		_STATE["roles"] = {"Seller Owner"}
		self._assert_denied()

	def test_sub_user_denied(self):
		_STATE["roles"] = {"Seller Staff"}
		self._assert_denied()

	def test_roleless_user_denied(self):
		_STATE["roles"] = set()
		self._assert_denied()

	def test_marketplace_admin_allowed(self):
		_STATE["roles"] = {"Marketplace Admin"}
		out = sa.list_attention_subscriptions()
		self.assertEqual(len(out["cancellations"]), 1)

	def test_system_manager_allowed(self):
		_STATE["roles"] = {"System Manager"}
		out = sa.list_attention_subscriptions()
		self.assertEqual(len(out["cancellations"]), 1)


class TestContent(unittest.TestCase):
	"""Üç blok içerik: filtreler, sıralama, alanlar, batch store_name (N+1 yok)."""

	def setUp(self):
		_reset_state()
		_STATE["subs"] = [
			# cancellations bloğu — kasıtlı olarak sıralama tersten seed'lenir.
			_sub(
				name="STSUB-A",
				store="SELLER-A",
				plan="PRO",
				cancel_at_period_end=1,
				cancellation_reason="fiyat",
				cancel_requested_at=_REQUESTED_AT,
				current_period_end=_END_LATE,
			),
			_sub(
				name="STSUB-B",
				store="SELLER-B",
				plan="BASIC",
				cancel_at_period_end=1,
				cancellation_reason="diger",
				cancel_requested_at=_REQUESTED_AT,
				current_period_end=_END_EARLY,
			),
			# DIŞARIDA kalması gerekenler:
			_sub(name="STSUB-C", store="SELLER-E", cancel_at_period_end=0),  # bayrak yok
			_sub(name="STSUB-F", store="SELLER-F", status="canceled", cancel_at_period_end=1),
			_sub(name="STSUB-G", store="SELLER-G", status="trial"),
			# dunning bloğu:
			_sub(
				name="STSUB-D",
				store="SELLER-C",
				plan="PRO",
				status="past_due",
				current_period_end=_END_EARLY,
			),
			_sub(
				name="STSUB-E",
				store="SELLER-D",
				plan="BASIC",
				status="suspended",
				current_period_end=_END_LATE,
				suspended_at=_SUSPENDED_AT,
			),
		]
		_STATE["profiles"] = {
			"SELLER-A": "Mağaza A",
			"SELLER-B": "Mağaza B",
			"SELLER-C": "Mağaza C",
			# SELLER-D bilinçli eksik → store kimliğine düşmeli.
		}

	def test_cancellations_block_sorted_and_shaped(self):
		out = sa.list_attention_subscriptions()
		self.assertEqual(
			out["cancellations"],
			[
				{
					"store": "SELLER-B",
					"store_name": "Mağaza B",
					"plan": "BASIC",
					"cancellation_reason": "diger",
					"cancel_requested_at": _REQUESTED_AT,
					"current_period_end": _END_EARLY,
				},
				{
					"store": "SELLER-A",
					"store_name": "Mağaza A",
					"plan": "PRO",
					"cancellation_reason": "fiyat",
					"cancel_requested_at": _REQUESTED_AT,
					"current_period_end": _END_LATE,
				},
			],
			"current_period_end asc + yalnız active+bayrak=1 satırlar",
		)

	def test_dunning_block_shaped_with_fallback_store_name(self):
		out = sa.list_attention_subscriptions()
		self.assertEqual(
			out["dunning"],
			[
				{
					"store": "SELLER-C",
					"store_name": "Mağaza C",
					"plan": "PRO",
					"status": "past_due",
					"current_period_end": _END_EARLY,
					"suspended_at": None,
				},
				{
					"store": "SELLER-D",
					"store_name": "SELLER-D",  # profili yok → store kimliğine düşer
					"plan": "BASIC",
					"status": "suspended",
					"current_period_end": _END_LATE,
					"suspended_at": _SUSPENDED_AT,
				},
			],
		)

	def test_store_names_fetched_in_single_batch(self):
		sa.list_attention_subscriptions()
		calls = _profile_calls()
		self.assertEqual(len(calls), 1, "store_name haritası TEK batch sorguyla gelmeli (N+1 yok)")
		wanted = set(calls[0]["filters"]["name"][1])
		self.assertEqual(
			wanted,
			{"SELLER-A", "SELLER-B", "SELLER-C", "SELLER-D"},
			"Batch, HER İKİ bloğun mağazalarını tek seferde kapsamalı",
		)

	def test_subscription_queries_bounded_and_ordered(self):
		sa.list_attention_subscriptions()
		calls = _store_sub_calls()
		self.assertEqual(len(calls), 2, "cancellations + dunning = 2 sorgu")
		for call in calls:
			self.assertEqual(call["limit"], 500)
			self.assertEqual(call["order_by"], "current_period_end asc")


class TestEmptyState(unittest.TestCase):
	"""Hiç dikkat satırı yokken üç blok da boş; profil sorgusu hiç koşmaz."""

	def setUp(self):
		_reset_state()
		_STATE["subs"] = [_sub(name="STSUB-OK", status="active", cancel_at_period_end=0)]
		_STATE["profiles"] = {"SELLER-A": "Mağaza A"}

	def test_empty_blocks(self):
		out = sa.list_attention_subscriptions()
		self.assertEqual(out, {"cancellations": [], "dunning": [], "reason_breakdown": {}})

	def test_no_profile_query_when_empty(self):
		sa.list_attention_subscriptions()
		self.assertEqual(_profile_calls(), [], "Boş listede batch profil sorgusu koşmamalı")


class TestReasonBreakdown(unittest.TestCase):
	"""Sebep sayaçları: yalnız cancellations'tan, yalnız GÖRÜLEN (>0) anahtarlar."""

	def setUp(self):
		_reset_state()
		_STATE["subs"] = [
			_sub(name="S1", store="SELLER-A", cancel_at_period_end=1, cancellation_reason="fiyat"),
			_sub(name="S2", store="SELLER-B", cancel_at_period_end=1, cancellation_reason="fiyat"),
			_sub(name="S3", store="SELLER-C", cancel_at_period_end=1, cancellation_reason="kapaniyor"),
			# dunning satırının sebebi (veri artığı olsa bile) SAYILMAZ:
			_sub(
				name="S4",
				store="SELLER-D",
				status="past_due",
				cancellation_reason="kullanmiyorum",
			),
			# reason'ı boş kalmış bozuk satır anahtar üretmez:
			_sub(name="S5", store="SELLER-E", cancel_at_period_end=1, cancellation_reason=None),
		]

	def test_only_positive_keys(self):
		out = sa.list_attention_subscriptions()
		self.assertEqual(out["reason_breakdown"], {"fiyat": 2, "kapaniyor": 1})
		self.assertNotIn("kullanmiyorum", out["reason_breakdown"], "dunning sebebi sayılmamalı")
		self.assertNotIn("diger", out["reason_breakdown"], "sıfır sayaçlı anahtar yanıta girmemeli")
		self.assertTrue(all(v > 0 for v in out["reason_breakdown"].values()))


if __name__ == "__main__":
	unittest.main()
