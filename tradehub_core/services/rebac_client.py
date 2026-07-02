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

# #C5 — Config env'den HER KULLANIMDA okunur (import-time değil). deploy_model.sh
# STORE_ID/MODEL_ID'yi worker ayağa kalktıktan sonra .env'e yazar; import-time
# cache boş string'i kalıcılaştırıyordu → model deploy edilse bile no-op kalıyordu.
def _base_url() -> str:
	return os.getenv("REBAC_BASE_URL", "http://rebac-sidecar:8080")


def _api_key() -> str:
	return os.getenv("REBAC_API_KEY", "")


def _store_id() -> str:
	return os.getenv("REBAC_STORE_ID", "")


def _model_id() -> str:
	return os.getenv("REBAC_MODEL_ID", "")

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
				# #C5 — Authorization header'ı session'a GÖMÜLMEZ; her istekte
				# _api_key() ile taze set edilir (key rotasyonu/geç-doldurma için).
				s.headers.update({"Content-Type": "application/json"})
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
	if not _store_id():
		raise ReBACConfigError("REBAC_STORE_ID env değişkeni boş. 'make rebac-model-deploy' çalıştır.")

	if _circuit_breaker.is_open():
		raise ReBACUnavailable("ReBAC sidecar circuit breaker OPEN (fail-closed)")

	url = f"{_base_url()}{endpoint}"
	session = _get_session()
	auth_headers = {"Authorization": f"Bearer {_api_key()}"}  # #C5 — taze key
	last_err: Exception | None = None

	for attempt in range(_MAX_RETRIES):
		try:
			if method == "POST":
				resp = session.post(
					url,
					data=json.dumps(payload or {}),
					headers=auth_headers,
					timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
				)
			else:
				resp = session.get(url, headers=auth_headers, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))

			# 5xx → retry; 4xx → exception (config/data hatası)
			if 500 <= resp.status_code < 600:
				last_err = ReBACError(f"5xx from sidecar: {resp.status_code}")
				time.sleep(_RETRY_BACKOFF[attempt])
				continue

			if not resp.ok:
				# #C3 — 4xx = veri/config hatası (erişilebilirlik DEĞİL). Sidecar
				# yanıt verdi → bağlantı sağlam; breaker'ı TETİKLEME, aksine
				# connectivity fail sayacını sıfırla. Yalnız 5xx/timeout/bağlantı
				# hataları breaker'ı açar (bkz. son satır record_failure).
				_circuit_breaker.record_success()
				raise ReBACError(f"ReBAC sidecar {resp.status_code}: {resp.text[:200]}")

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


# #C6/Faz4 — OpenFGA consistency modları (zookie/new-enemy koruması).
#   MINIMIZE_LATENCY: cache'ten sunabilir (browse/okuma-ağırlıklı yol — varsayılan).
#   HIGHER_CONSISTENCY: cache atlar, read-your-writes (güvenlik-azaltıcı mutasyon
#     sonrası: askıya-alma, üye-çıkarma, rol-iptal → eski erişim hemen kesilsin).
CONSISTENCY_MINIMIZE_LATENCY = "MINIMIZE_LATENCY"
CONSISTENCY_HIGHER = "HIGHER_CONSISTENCY"


def check(
	user: str,
	relation: str,
	object: str,
	context: dict[str, Any] | None = None,
	consistency: str | None = None,
) -> bool:
	"""Bir ilişkinin var olup olmadığını kontrol et.

	Args:
	    user: 'user:ayse@x.com' veya 'group:acme-marketing#member'
	    relation: 'member', 'can_view', 'can_approve_l1', ...
	    object: 'buyer_org:acme', 'order:ORD-9382', ...
	    context: ABAC condition input'ları (örn. {"amount": 7450})
	    consistency: HIGHER_CONSISTENCY (güvenlik-kritik, read-your-writes) veya
	        MINIMIZE_LATENCY (varsayılan, cache'li). Bkz. CONSISTENCY_* sabitleri.

	Returns:
	    True: izinli, False: değil veya hata (fail-closed)
	"""
	payload: dict[str, Any] = {
		"tuple_key": {"user": user, "relation": relation, "object": object},
	}
	if _model_id():
		payload["authorization_model_id"] = _model_id()
	if context:
		payload["context"] = context
	if consistency:
		payload["consistency"] = consistency

	try:
		result = _call("POST", f"/stores/{_store_id()}/check", payload)
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
	if _model_id():
		payload["authorization_model_id"] = _model_id()
	if context:
		payload["context"] = context

	try:
		result = _call("POST", f"/stores/{_store_id()}/list-objects", payload)
		# OpenFGA döner: {"objects": ["order:ORD-9382", "order:ORD-9401"]}
		raw_objects = result.get("objects", [])
		# Type prefix soy
		prefix = f"{type}:"
		return [o[len(prefix) :] if o.startswith(prefix) else o for o in raw_objects]

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

	return _send_tuple_op("writes", payload_tuples, "write_tuples")


def _tuple_op_payload(op: str, tuple_keys: list) -> dict:
	payload: dict[str, Any] = {op: {"tuple_keys": tuple_keys}}
	mid = _model_id()
	if mid:
		payload["authorization_model_id"] = mid
	return payload


def _is_idempotency_error(err) -> bool:
	"""OpenFGA 4xx'i idempotency (zaten var / mevcut değil) mi yoksa gerçek hata
	(validation_error / invalid object) mı ayırır. Yalnız idempotency tolere edilir."""
	msg = str(err).lower()
	return "already exist" in msg or "does not exist" in msg or "cannot delete" in msg


def _send_tuple_op(op: str, tuple_keys: list, scope: str) -> bool:
	"""#C1 — OpenFGA Write API transactional'dır: batch'teki TEK geçersiz tuple
	(write'ta zaten var / delete'te mevcut değil) tüm batch'i 400 ile düşürür.
	Bu yüzden: önce batch dene; batch 4xx (ReBACError) alırsa per-tuple fallback
	ile idempotency hatalarını tolere et — stale-cleanup ve fresh-write artık tek
	bozuk tuple yüzünden komple kaybolmaz. Sidecar erişilemezse (ReBACUnavailable)
	fallback yapılmaz (N kez fail etmesin)."""
	if not tuple_keys:
		return True
	store = _store_id()
	try:
		_call("POST", f"/stores/{store}/write", _tuple_op_payload(op, tuple_keys))
		return True
	except ReBACUnavailable as e:
		frappe.log_error(f"ReBAC {scope} unavailable: {e}", f"rebac_client.{scope}")
		return False
	except ReBACError:
		ok = True
		for tk in tuple_keys:
			try:
				_call("POST", f"/stores/{store}/write", _tuple_op_payload(op, [tk]))
			except ReBACUnavailable as e:
				frappe.log_error(f"ReBAC {scope} unavailable (per-tuple): {e}", f"rebac_client.{scope}")
				ok = False
			except ReBACError as e:
				if _is_idempotency_error(e):
					frappe.log_error(
						f"ReBAC {scope} tuple tolerated (idempotent): {tk}: {e}",
						f"rebac_client.{scope}",
					)
				else:
					# Gerçek hata (validation_error / invalid object) → YUTMA; başarısızlık say.
					frappe.log_error(
						f"ReBAC {scope} tuple FAILED (non-idempotent): {tk}: {e}",
						f"rebac_client.{scope}",
					)
					ok = False
		return ok


def delete_tuples(tuples: list[tuple[str, str, str]]) -> bool:
	"""Birden çok tuple sil (sync delete). Idempotent — bkz. _send_tuple_op (#C1)."""
	if not tuples:
		return True
	tuple_keys = [{"user": user, "relation": relation, "object": obj} for (user, relation, obj) in tuples]
	return _send_tuple_op("deletes", tuple_keys, "delete_tuples")


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
		url = f"{_base_url()}/healthz"
		# #C5/#12 — auth açıkken healthz de Bearer key ister; aksi halde 401'i
		# "unavailable" sanır (yanıltıcı sinyal).
		headers = {"Authorization": f"Bearer {_api_key()}"} if _api_key() else {}
		resp = requests.get(url, headers=headers, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
		return resp.ok
	except Exception:
		return False


def reset_circuit_breaker() -> None:
	"""Test/operasyon için circuit breaker'ı manuel reset et."""
	global _circuit_breaker
	_circuit_breaker = _CircuitBreaker()
