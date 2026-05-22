# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 2.3 — OpenFGA Sidecar HTTP Client.

Frappe backend'inin Faz 2.2'de deploy edilen ReBAC sidecar ile konuştuğu
HTTP wrapper. AuthZEN-uyumlu wrapper sayesinde gelecekte SpiceDB'ye geçiş
basit kalır.

Mimari kararlar:
  - Connection pooling (requests.Session)
  - Retry: 3 deneme, exponential backoff (0.5, 1, 2 sn)
  - Timeout: 2 sn connect + 3 sn read
  - Circuit breaker: 5 ardışık fail → 30 sn devre dışı, FAIL-CLOSED
  - DENY kararları audit log'a yazılır (sample-based; her ALLOW log'lanmaz)

Public API:
  - check(user, relation, object, context=None) → bool
  - list_objects(type, relation, user, context=None) → list[str]
  - write_tuples(tuples) → bool
  - delete_tuples(tuples) → bool

Detay: docs/yetki/faz-2/01-tasarim-kararlari.md §4
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import frappe
import requests

# ---------------------------------------------------------------------------
# Config (env'den okunur)
# ---------------------------------------------------------------------------

_REBAC_BASE_URL = os.getenv("REBAC_BASE_URL", "http://rebac-sidecar:8080")
_REBAC_API_KEY = os.getenv("REBAC_API_KEY", "")
_REBAC_STORE_ID = os.getenv("REBAC_STORE_ID", "")
_REBAC_MODEL_ID = os.getenv("REBAC_MODEL_ID", "")

# Timeouts (saniye)
_CONNECT_TIMEOUT = 2.0
_READ_TIMEOUT = 3.0

# Retry
_MAX_RETRIES = 3
_RETRY_BACKOFF = [0.5, 1.0, 2.0]

# Circuit breaker — ardışık 5 fail → 30 sn devre dışı
_CB_FAIL_THRESHOLD = 5
_CB_RECOVERY_SECONDS = 30


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ReBACError(Exception):
	"""Genel ReBAC sidecar hatası."""

	pass


class ReBACUnavailable(ReBACError):
	"""Sidecar erişilemez (circuit open veya HTTP fail)."""

	pass


class ReBACConfigError(ReBACError):
	"""STORE_ID / API_KEY eksik."""

	pass


# ---------------------------------------------------------------------------
# Circuit Breaker (thread-safe)
# ---------------------------------------------------------------------------


class _CircuitBreaker:
	"""Basit circuit breaker — N ardışık fail → T saniye devre dışı."""

	def __init__(self, threshold: int = _CB_FAIL_THRESHOLD, recovery: int = _CB_RECOVERY_SECONDS):
		self.threshold = threshold
		self.recovery = recovery
		self._fail_count = 0
		self._opened_at: float | None = None
		self._lock = threading.Lock()

	def is_open(self) -> bool:
		"""Circuit açık mı (istek reddedilmeli)?"""
		with self._lock:
			if self._opened_at is None:
				return False
			# Recovery süresi geçti mi?
			if time.time() - self._opened_at > self.recovery:
				# Half-open: bir istek denenebilir
				self._opened_at = None
				self._fail_count = 0
				return False
			return True

	def record_success(self) -> None:
		with self._lock:
			self._fail_count = 0
			self._opened_at = None

	def record_failure(self) -> None:
		with self._lock:
			self._fail_count += 1
			if self._fail_count >= self.threshold:
				self._opened_at = time.time()


_circuit_breaker = _CircuitBreaker()


# ---------------------------------------------------------------------------
# Session (connection pooling)
# ---------------------------------------------------------------------------

_session: requests.Session | None = None
_session_lock = threading.Lock()


def _get_session() -> requests.Session:
	"""requests.Session singleton (connection pool)."""
	global _session
	if _session is None:
		with _session_lock:
			if _session is None:
				s = requests.Session()
				s.headers.update(
					{
						"Authorization": f"Bearer {_REBAC_API_KEY}",
						"Content-Type": "application/json",
					}
				)
				adapter = requests.adapters.HTTPAdapter(
					pool_connections=10,
					pool_maxsize=20,
					max_retries=0,  # Manuel retry yapıyoruz
				)
				s.mount("http://", adapter)
				s.mount("https://", adapter)
				_session = s
	return _session


# ---------------------------------------------------------------------------
# Low-level HTTP wrapper (retry + circuit breaker + audit)
# ---------------------------------------------------------------------------


def _call(method: str, endpoint: str, payload: dict | None = None) -> dict:
	"""ReBAC sidecar'a HTTP çağrısı yap.

	Args:
	    method: GET / POST
	    endpoint: '/stores/<id>/check' gibi
	    payload: POST body (dict)

	Returns:
	    Response JSON

	Raises:
	    ReBACConfigError: REBAC_STORE_ID eksik
	    ReBACUnavailable: Circuit open veya HTTP fail
	"""
	if not _REBAC_STORE_ID:
		raise ReBACConfigError(
			"REBAC_STORE_ID env değişkeni boş. 'make rebac-model-deploy' çalıştır."
		)

	if _circuit_breaker.is_open():
		raise ReBACUnavailable("ReBAC sidecar circuit breaker OPEN (fail-closed)")

	url = f"{_REBAC_BASE_URL}{endpoint}"
	session = _get_session()
	last_err: Exception | None = None

	for attempt in range(_MAX_RETRIES):
		try:
			if method == "POST":
				resp = session.post(
					url,
					data=json.dumps(payload or {}),
					timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
				)
			else:
				resp = session.get(url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))

			# 5xx → retry; 4xx → exception (config/data hatası)
			if 500 <= resp.status_code < 600:
				last_err = ReBACError(f"5xx from sidecar: {resp.status_code}")
				time.sleep(_RETRY_BACKOFF[attempt])
				continue

			if not resp.ok:
				# 4xx — retry yok, hemen exception
				_circuit_breaker.record_failure()
				raise ReBACError(
					f"ReBAC sidecar {resp.status_code}: {resp.text[:200]}"
				)

			_circuit_breaker.record_success()
			return resp.json() if resp.content else {}

		except requests.exceptions.RequestException as e:
			last_err = e
			if attempt < _MAX_RETRIES - 1:
				time.sleep(_RETRY_BACKOFF[attempt])

	# Tüm retry'lar başarısız
	_circuit_breaker.record_failure()
	raise ReBACUnavailable(f"ReBAC sidecar erişilemez: {last_err}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check(
	user: str,
	relation: str,
	object: str,
	context: dict[str, Any] | None = None,
) -> bool:
	"""Bir ilişkinin var olup olmadığını kontrol et.

	Args:
	    user: 'user:ayse@x.com' veya 'group:acme-marketing#member'
	    relation: 'member', 'can_view', 'can_approve_l1', ...
	    object: 'buyer_org:acme', 'order:ORD-9382', ...
	    context: ABAC condition input'ları (örn. {"amount": 7450})

	Returns:
	    True: izinli, False: değil veya hata (fail-closed)
	"""
	payload: dict[str, Any] = {
		"tuple_key": {"user": user, "relation": relation, "object": object},
	}
	if _REBAC_MODEL_ID:
		payload["authorization_model_id"] = _REBAC_MODEL_ID
	if context:
		payload["context"] = context

	try:
		result = _call("POST", f"/stores/{_REBAC_STORE_ID}/check", payload)
		allowed = bool(result.get("allowed", False))

		# DENY audit log (best-effort, sadece DENY için sample)
		if not allowed:
			_log_decision_safely(
				action=f"rebac.check.{relation}",
				decision="DENY",
				rule_id=f"rebac.{relation}",
				actor=user,
				object_repr=object,
				context=context,
			)

		return allowed

	except ReBACUnavailable:
		# Fail-closed: sidecar yoksa veya circuit open → DENY
		_log_decision_safely(
			action=f"rebac.check.{relation}",
			decision="DENY",
			rule_id="rebac.unavailable",
			actor=user,
			object_repr=object,
			severity="HIGH",
		)
		return False
	except ReBACError as e:
		frappe.log_error(f"ReBAC check failed: {e}", "rebac_client.check")
		return False


def list_objects(
	type: str,
	relation: str,
	user: str,
	context: dict[str, Any] | None = None,
) -> list[str]:
	"""Bir kullanıcının verilen ilişkide görebildiği tüm object'leri döner.

	Args:
	    type: 'order', 'listing', 'buyer_org', ...
	    relation: 'can_view', 'can_approve', ...
	    user: 'user:ayse@x.com'
	    context: ABAC input

	Returns:
	    Object ID listesi (örn. ['ORD-9382', 'ORD-9401']) — type prefix soyulmuş
	"""
	payload: dict[str, Any] = {
		"type": type,
		"relation": relation,
		"user": user,
	}
	if _REBAC_MODEL_ID:
		payload["authorization_model_id"] = _REBAC_MODEL_ID
	if context:
		payload["context"] = context

	try:
		result = _call("POST", f"/stores/{_REBAC_STORE_ID}/list-objects", payload)
		# OpenFGA döner: {"objects": ["order:ORD-9382", "order:ORD-9401"]}
		raw_objects = result.get("objects", [])
		# Type prefix soy
		prefix = f"{type}:"
		return [o[len(prefix):] if o.startswith(prefix) else o for o in raw_objects]

	except (ReBACUnavailable, ReBACError) as e:
		frappe.log_error(f"ReBAC list_objects failed: {e}", "rebac_client.list_objects")
		return []  # Fail-closed (boş liste döner — kullanıcı hiçbir şey görmez)


def write_tuples(tuples: list) -> bool:
	"""Birden çok tuple ekle (sync write).

	Args:
	    tuples: list of:
	      - 3-tuple: (user, relation, object) — koşulsuz
	      - 4-tuple: (user, relation, object, condition_name) — FGA condition'lı
	      - 5-tuple: (user, relation, object, condition_name, context_dict)
	      - dict: {"user": ..., "relation": ..., "object": ..., "condition": {...}}

	Returns:
	    True: hepsi yazıldı, False: hata
	"""
	if not tuples:
		return True

	payload_tuples = []
	for t in tuples:
		if isinstance(t, dict):
			payload_tuples.append(t)
		elif len(t) == 3:
			payload_tuples.append({"user": t[0], "relation": t[1], "object": t[2]})
		elif len(t) == 4:
			payload_tuples.append(
				{
					"user": t[0],
					"relation": t[1],
					"object": t[2],
					"condition": {"name": t[3]},
				}
			)
		elif len(t) == 5:
			payload_tuples.append(
				{
					"user": t[0],
					"relation": t[1],
					"object": t[2],
					"condition": {"name": t[3], "context": t[4] or {}},
				}
			)
		else:
			frappe.log_error(
				f"ReBAC write_tuples: invalid tuple length {len(t)}: {t}",
				"rebac_client.write_tuples",
			)
			continue

	payload = {"writes": {"tuple_keys": payload_tuples}}
	if _REBAC_MODEL_ID:
		payload["authorization_model_id"] = _REBAC_MODEL_ID

	try:
		_call("POST", f"/stores/{_REBAC_STORE_ID}/write", payload)
		return True
	except (ReBACUnavailable, ReBACError) as e:
		frappe.log_error(f"ReBAC write_tuples failed: {e}", "rebac_client.write_tuples")
		return False


def delete_tuples(tuples: list[tuple[str, str, str]]) -> bool:
	"""Birden çok tuple sil (sync delete)."""
	if not tuples:
		return True

	payload = {
		"deletes": {
			"tuple_keys": [
				{"user": user, "relation": relation, "object": obj}
				for (user, relation, obj) in tuples
			]
		}
	}
	if _REBAC_MODEL_ID:
		payload["authorization_model_id"] = _REBAC_MODEL_ID

	try:
		_call("POST", f"/stores/{_REBAC_STORE_ID}/write", payload)
		return True
	except (ReBACUnavailable, ReBACError) as e:
		frappe.log_error(f"ReBAC delete_tuples failed: {e}", "rebac_client.delete_tuples")
		return False


# ---------------------------------------------------------------------------
# AuthZEN-compatible wrapper (gelecekte interface koruyucu)
# ---------------------------------------------------------------------------


def authzen_check(subject: dict, action: dict, resource: dict, context: dict | None = None) -> bool:
	"""AuthZEN spec'ine uygun check wrapper.

	AuthZEN payload:
	  {
	    "subject": {"type": "user", "id": "ayse@x.com"},
	    "action": {"name": "can_view"},
	    "resource": {"type": "order", "id": "ORD-9382"}
	  }

	Bu wrapper OpenFGA native API'sini AuthZEN sözleşmesine dönüştürür.
	İlerideki sidecar değişikliklerinde (SpiceDB vb.) caller kodu dokunulmaz.
	"""
	user = f"{subject.get('type', 'user')}:{subject['id']}"
	relation = action["name"]
	obj = f"{resource['type']}:{resource['id']}"
	return check(user, relation, obj, context=context)


# ---------------------------------------------------------------------------
# Helper: Audit log (lazy import, circular önlemi)
# ---------------------------------------------------------------------------


def _log_decision_safely(
	*,
	action: str,
	decision: str,
	rule_id: str,
	actor: str | None = None,
	object_repr: str | None = None,
	context: dict | None = None,
	severity: str = "NORMAL",
) -> None:
	"""Best-effort audit log (ReBAC kararı için)."""
	try:
		from tradehub_core.audit import log_decision

		# 'user:email' → 'email' (actor field için)
		actor_clean = actor.split(":", 1)[1] if actor and ":" in actor else actor
		obj_doctype = None
		obj_name = None
		if object_repr and ":" in object_repr:
			obj_doctype, obj_name = object_repr.split(":", 1)

		log_decision(
			actor=actor_clean,
			action=action,
			decision=decision,
			rule_id=rule_id,
			layer="L2",
			object_doctype=obj_doctype,
			object_name=obj_name,
			severity=severity,
			context=context or {},
		)
	except Exception:
		# Audit kendisi başarısızsa business flow bozulmaz
		pass


# ---------------------------------------------------------------------------
# Health (test/monitoring için)
# ---------------------------------------------------------------------------


def healthz() -> bool:
	"""Sidecar erişilebilir mi?"""
	try:
		url = f"{_REBAC_BASE_URL}/healthz"
		resp = requests.get(url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
		return resp.ok
	except Exception:
		return False


def reset_circuit_breaker() -> None:
	"""Test/operasyon için circuit breaker'ı manuel reset et."""
	global _circuit_breaker
	_circuit_breaker = _CircuitBreaker()
