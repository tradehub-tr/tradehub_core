"""Faz 6 — Public API v1 (3rd-party developers).

OAuth2 / Client Credentials flow ile authentication. Mevcut whitelisted
endpoint'leri stable v1 contract olarak sarar.

Client Credentials kullanımı:
  POST /api/method/tradehub_core.api.v1.public_api.token
       grant_type=client_credentials&client_id=...&client_secret=...

  → { "access_token": "...", "expires_in": 86400, "token_type": "Bearer" }

Sonra:
  GET  /api/method/tradehub_core.api.v1.public_api.listings_get_reviews?listing=LST-00002
       Authorization: Bearer <access_token>
"""

from __future__ import annotations

import time

import frappe

from tradehub_core.api.mobile_api import _decode_jwt, _encode_jwt
from tradehub_core.api.rate_limit import rate_limit

RATE_LIMITS = {
	"free": {"max_calls": 60, "window": 60},
	"pro": {"max_calls": 600, "window": 60},
	"enterprise": {"max_calls": 6000, "window": 60},
}


def _verify_client(client_id: str, client_secret: str) -> dict:
	"""API Application'a karşı client_id + client_secret doğrula."""
	app = frappe.db.get_value(
		"API Application",
		{"client_id": client_id, "is_active": 1},
		["name", "rate_limit_tier", "developer_email"],
		as_dict=True,
	)
	if not app:
		frappe.throw("Geçersiz client_id", frappe.AuthenticationError)
	doc = frappe.get_doc("API Application", app.name)
	expected_secret = doc.get_password("client_secret", raise_exception=False)
	if expected_secret:
		# T-134 §2 — API Application client_secret okuması denetime yazılır. Değer
		# YOK; kimlik = uygulama adı. Yalnız geçerli bir client_id'ye ait sır
		# okunduğunda yazılır (var olmayan client'ta get_password çağrılmaz).
		from tradehub_core.audit.secret_access import log_secret_access

		log_secret_access(
			service="api_application",
			field="client_secret",
			object_doctype="API Application",
			object_name=app.name,
		)
	if not expected_secret or expected_secret != client_secret:
		frappe.throw("Geçersiz client_secret", frappe.AuthenticationError)
	return {
		"app_name": app.name,
		"tier": app.rate_limit_tier,
		"scopes": [s.scope for s in doc.scopes],
		# MOGEM-665: mağaza bağı jetona da yazılır (tanı amaçlı; yetki kararı
		# her istekte DB'den yeniden okunur — kapatılan uygulama anında düşsün).
		"seller": getattr(doc, "seller_profile", None) or None,  # stub'lı testler (.get yok)
	}


def _verify_bearer() -> dict:
	"""Authorization header'dan OAuth2 token'ı doğrula."""
	auth = frappe.local.request.headers.get("Authorization", "") if frappe.local.request else ""
	if not auth or not auth.startswith("Bearer "):
		frappe.throw("Bearer token zorunlu", frappe.AuthenticationError)
	token = auth[7:].strip()
	payload = _decode_jwt(token)
	if payload.get("type") != "oauth_access":
		frappe.throw("Yanlış token tipi", frappe.AuthenticationError)
	return payload


@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=30, window_seconds=60, scope="oauth_token", per_user=True)
def token(grant_type: str, client_id: str, client_secret: str, scope: str = ""):
	"""OAuth2 token endpoint (Client Credentials grant).

	Hız sınırı istemci IP'si başına 30/dk (MOGEM-665 ölçümü, 15 Eyl): eski
	`per_user=False` + 5/dk kovası PLATFORM GENELİ tek sayaçtı — altıncı mağaza
	o dakika jeton alamıyordu; tek bir saldırgan da 5 istekle herkesi kilitliyordu.
	Kaba kuvvet koruması IP başına sürer; misafir kimliği `Guest:<ip>` kovasıdır.
	"""
	if grant_type != "client_credentials":
		frappe.throw("Sadece client_credentials desteklenir")
	client = _verify_client(client_id, client_secret)
	now_ts = int(time.time())
	payload = {
		"sub": client["app_name"],
		"iat": now_ts,
		"exp": now_ts + 86400,  # 24h
		"type": "oauth_access",
		"tier": client["tier"],
		"scopes": client["scopes"],
		"seller": client.get("seller"),
	}
	access = _encode_jwt(payload)
	return {
		"access_token": access,
		"token_type": "Bearer",
		"expires_in": 86400,
		"scope": " ".join(client["scopes"]),
	}


def _check_scope(required: str, token_payload: dict):
	scopes = token_payload.get("scopes") or []
	if required not in scopes:
		frappe.throw(f"Scope '{required}' eksik", frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
def listings_get_reviews(listing: str, page: int = 1, page_size: int = 10):
	"""GET /v1/listings/{id}/reviews"""
	t = _verify_bearer()
	_check_scope("read_reviews", t)
	tier = t.get("tier", "free")
	limits = RATE_LIMITS.get(tier, RATE_LIMITS["free"])

	# Manuel rate_limit (tier-aware)
	# Decorator dinamik kullanılamaz; manuel cache check
	cache = frappe.cache()
	key = f"oauth_rl:{t['sub']}:reviews"
	current = cache.get_value(key)
	current = int(current) if current else 0
	if current >= limits["max_calls"]:
		from tradehub_core.api.rate_limit import TooManyRequestsError

		raise TooManyRequestsError(
			f"Tier '{tier}' rate limit aşıldı ({limits['max_calls']}/{limits['window']}s)"
		)
	cache.delete_value(key)
	cache.set_value(key, current + 1, expires_in_sec=limits["window"])

	from tradehub_core.api.review import list_listing_reviews

	return list_listing_reviews(listing=listing, page=page, page_size=page_size)


@frappe.whitelist(allow_guest=True)
def listings_get_analytics(listing: str):
	"""GET /v1/listings/{id}/analytics"""
	t = _verify_bearer()
	_check_scope("read_analytics", t)
	from tradehub_core.api.review import get_listing_rating_summary

	return get_listing_rating_summary(listing=listing)


@frappe.whitelist()
def my_app_info():
	"""Admin manuel — kendi developer app'lerini listele."""
	user = frappe.session.user
	rows = frappe.get_all(
		"API Application",
		filters={"developer_email": user},
		fields=["name", "client_id", "rate_limit_tier", "is_active", "redirect_uri"],
	)
	return {"apps": rows}
