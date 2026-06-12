"""Faz 6 — Mobile API (JWT auth + native-app friendly endpoint'ler).

`PyJWT` paketi mevcutsa gerçek JWT; yoksa HMAC-tabanlı kendi token formatı
(fallback). Token tablosunda da kalıcı kayıt tutulur ki revoke edilebilsin.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from tradehub_core.api.rate_limit import rate_limit

JWT_ALGO = "HS256"
ACCESS_TOKEN_TTL_HOURS = 24
REFRESH_TOKEN_TTL_DAYS = 30


def _jwt_secret() -> str:
	"""Mobil JWT imza anahtarı — site secret'ından (fail-closed).

	C5 fix — eskiden hardcoded fallback ("tradehub-mobile-jwt-fallback-secret")
	döndürülüyordu; bu string kaynak kodda public olduğundan saldırgan geçerli
	token imzalayabiliyordu. Artık site secret yoksa hata fırlatılır (fail-closed):
	hiçbir koşulda tahmin edilebilir bir anahtarla imza atılmaz.
	Tercihen ayrı bir anahtar (`mobile_jwt_secret`) tanımlanır; yoksa Frappe'nin
	site-özgü `encryption_key`/`secret_key`'ine düşer.
	"""
	key = (
		frappe.conf.get("mobile_jwt_secret")
		or frappe.conf.get("encryption_key")
		or frappe.conf.get("secret_key")
	)
	if not key:
		frappe.throw(
			_("Mobil JWT secret yapılandırılmamış (site_config.encryption_key eksik)"),
			exc=frappe.ValidationError,
		)
	return key


def _b64u(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
	s = s + "=" * ((4 - len(s) % 4) % 4)
	return base64.urlsafe_b64decode(s.encode("ascii"))


def _encode_jwt(payload: dict) -> str:
	"""Manuel JWT HS256 encode (PyJWT bağımsız)."""
	header = {"alg": "HS256", "typ": "JWT"}
	h = _b64u(json.dumps(header, separators=(",", ":")).encode())
	p = _b64u(json.dumps(payload, separators=(",", ":")).encode())
	signing_input = f"{h}.{p}".encode()
	sig = hmac.new(_jwt_secret().encode(), signing_input, hashlib.sha256).digest()
	return f"{h}.{p}.{_b64u(sig)}"


def _decode_jwt(token: str) -> dict:
	try:
		h, p, s = token.split(".")
	except ValueError:
		frappe.throw("Geçersiz token formatı", frappe.AuthenticationError)
	signing_input = f"{h}.{p}".encode()
	expected = _b64u(hmac.new(_jwt_secret().encode(), signing_input, hashlib.sha256).digest())
	if not hmac.compare_digest(s, expected):
		frappe.throw("Geçersiz token imzası", frappe.AuthenticationError)
	payload = json.loads(_b64u_decode(p))
	if payload.get("exp", 0) < int(time.time()):
		frappe.throw("Token süresi doldu", frappe.AuthenticationError)
	return payload


def _create_token_pair(user: str, device_id: str = "", device_type: str = "android") -> dict:
	now_ts = int(time.time())
	access_payload = {
		"sub": user,
		"iat": now_ts,
		"exp": now_ts + ACCESS_TOKEN_TTL_HOURS * 3600,
		"type": "access",
	}
	refresh_payload = {
		"sub": user,
		"iat": now_ts,
		"exp": now_ts + REFRESH_TOKEN_TTL_DAYS * 86400,
		"type": "refresh",
		"jti": secrets.token_urlsafe(16),
	}
	access = _encode_jwt(access_payload)
	refresh = _encode_jwt(refresh_payload)

	# DB kayıt (revoke için)
	doc = frappe.new_doc("Mobile API Token")
	doc.user = user
	doc.device_id = device_id
	doc.device_type = device_type
	doc.issued_at = now_datetime()
	doc.expires_at = add_to_date(now_datetime(), hours=ACCESS_TOKEN_TTL_HOURS)
	doc.token = access
	doc.refresh_token = refresh
	doc.revoked = 0
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {
		"access_token": access,
		"refresh_token": refresh,
		"token_type": "Bearer",
		"expires_in": ACCESS_TOKEN_TTL_HOURS * 3600,
	}


def _authenticate_with_password(email: str, password: str) -> str:
	"""Frappe'in built-in auth'unu kullan."""
	from frappe.auth import LoginManager

	lm = LoginManager()
	try:
		lm.authenticate(user=email, pwd=password)
	except Exception:
		frappe.throw("Geçersiz kimlik bilgileri", frappe.AuthenticationError)
	return email


@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=10, window_seconds=60, scope="mobile_login", per_user=False)
def mobile_login(email: str, password: str, device_id: str = "", device_type: str = "android"):
	"""Mobile app login → token pair üretir."""
	if not email or not password:
		frappe.throw("Email ve şifre zorunlu")
	user = _authenticate_with_password(email, password)
	return _create_token_pair(user, device_id, device_type)


@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=30, window_seconds=60, scope="mobile_refresh", per_user=False)
def mobile_refresh(refresh_token: str):
	"""Refresh token ile yeni access token al."""
	if not refresh_token:
		frappe.throw("Refresh token zorunlu")
	payload = _decode_jwt(refresh_token)
	if payload.get("type") != "refresh":
		frappe.throw("Yanlış token tipi", frappe.AuthenticationError)
	user = payload.get("sub")
	if not user or not frappe.db.exists("User", user):
		frappe.throw("Kullanıcı bulunamadı", frappe.AuthenticationError)
	# Eski tokenları revoke et
	frappe.db.sql("UPDATE `tabMobile API Token` SET revoked=1 WHERE user=%s AND revoked=0", (user,))
	return _create_token_pair(user)


def _verify_request_token() -> str:
	"""Authorization header'dan token al, decode et, user döndür."""
	# Frappe whitelisted'larda req header'a doğrudan erişim:
	auth = frappe.local.request.headers.get("Authorization", "") if frappe.local.request else ""
	if not auth or not auth.startswith("Bearer "):
		frappe.throw("Bearer token zorunlu", frappe.AuthenticationError)
	token = auth[7:].strip()
	payload = _decode_jwt(token)
	user = payload.get("sub")
	if not user:
		frappe.throw("Geçersiz token", frappe.AuthenticationError)
	# Revoke check (opsiyonel — performance için sample)
	revoked = frappe.db.exists("Mobile API Token", {"user": user, "token": token, "revoked": 1})
	if revoked:
		frappe.throw("Token iptal edildi", frappe.AuthenticationError)
	return user


# ─────────────────────────────────────────────────────────────────────────────
# Mobile endpoint'ler
# ─────────────────────────────────────────────────────────────────────────────
@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=120, window_seconds=60, scope="mobile_feed")
def mobile_get_review_feed(limit: int = 20):
	"""Buyer'ın takip ettiği ürünlerin yeni Approved review'ları.

	Şimdilik son 20 Approved review'i döner (gerçek follow sistemi yok).
	"""
	user = _verify_request_token()
	rows = frappe.get_all(
		"Listing Review",
		filters={"status": "Approved"},
		fields=[
			"name",
			"listing",
			"rating",
			"title",
			"body",
			"reviewer_display_name",
			"published_at",
			"helpful_count",
			"is_verified_purchase",
		],
		order_by="published_at DESC",
		limit=int(limit),
	)
	return {"feed": rows, "user": user}


@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=60, window_seconds=60, scope="mobile_pending")
def mobile_get_pending_reviews():
	"""Kullanıcının yazması gereken yorumlar (Tamamlandı/Kargoda)."""
	user = _verify_request_token()
	rows = frappe.db.sql(
		"""
		SELECT oi.name AS order_item, oi.listing, oi.listing_title,
			o.name AS `order`, o.order_date
		FROM `tabOrder Item` oi
		JOIN `tabOrder` o ON o.name = oi.parent
		WHERE o.buyer = %s AND o.status IN ('Tamamlandı','Kargoda')
		  AND COALESCE(oi.has_review, 0) = 0
		ORDER BY o.order_date DESC LIMIT 20
	""",
		(user,),
		as_dict=True,
	)
	return {"pending": rows, "total": len(rows)}


@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=20, window_seconds=60, scope="mobile_quick_review")
def mobile_quick_review(order_item: str, rating, body: str, title: str = None):
	"""Minimal payload review submit."""
	user = _verify_request_token()
	from tradehub_core.api.review import submit_listing_review

	# Geçici session user değiştir
	original_user = frappe.session.user
	try:
		frappe.set_user(user)
		return submit_listing_review(order_item=order_item, rating=rating, body=body, title=title)
	finally:
		frappe.set_user(original_user)


@frappe.whitelist(allow_guest=True)
def mobile_me():
	"""Token sahibi user'ın profili."""
	user = _verify_request_token()
	row = frappe.db.get_value("User", user, ["email", "full_name", "language"], as_dict=True)
	rep = frappe.db.get_value("Reviewer Reputation", user, ["score", "tier"], as_dict=True)
	return {"user": user, "profile": row, "reputation": rep or {"score": 45, "tier": "Newcomer"}}


@frappe.whitelist(allow_guest=True)
def mobile_logout():
	"""Mevcut access token'ı revoke et."""
	user = _verify_request_token()
	auth = frappe.local.request.headers.get("Authorization", "")
	token = auth[7:].strip() if auth.startswith("Bearer ") else ""
	if token:
		frappe.db.sql("UPDATE `tabMobile API Token` SET revoked=1 WHERE token=%s", (token,))
		frappe.db.commit()
	return {"success": True, "logged_out": user}
