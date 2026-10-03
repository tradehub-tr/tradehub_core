"""Push kanalı adaptörü.

Web push: mevcut `tradehub_core.api.push` (Push Subscription + VAPID + pywebpush). Abonelik
yolu değişmedi: storefront `api.push.subscribe/unsubscribe` kullanır.
Native push (FCM/APNs): bu kurulumda sağlayıcı YOK (B0) — token kabul edilip "hazır" denmez.

Sunucu yalnız kayıtlı abonelik ve sağlayıcı kapasitesini bilir; o cihazdaki tarayıcı izni
(`izin-yok` / `engelli`) istemcide okunur.
"""

from __future__ import annotations

import frappe

from tradehub_core.notifications import errors


def provider_available() -> bool:
	try:
		import pywebpush  # noqa: F401
	except ImportError:
		return False
	from tradehub_core.api.push import _get_settings

	s = _get_settings()
	return bool(s.get("enabled") and s.get("public_key") and s.get("private_key"))


def device_state(user: str) -> dict:
	has_sub = bool(frappe.db.count("Push Subscription", {"user": user}))
	return {
		"state": "hazir" if has_sub else "cihaz-yok",
		"device_label": None,
		"provider_available": provider_available(),
	}


def register_native(token: str, platform: str) -> dict:
	raise errors.provider_unavailable("push")


def send(user: str, title: str, body: str, url: str | None) -> dict:
	"""Sonuç: {status: sent|failed, error_code?, provider_reference?}."""
	if not provider_available():
		return {"status": "failed", "error_code": "PROVIDER_UNAVAILABLE"}
	from tradehub_core.api.push import send_push

	res = send_push(user, title, body, url=url)
	if res.get("sent"):
		return {"status": "sent", "provider_reference": f"webpush:{res['sent']}/{res.get('total')}"}
	if res.get("no_subscription"):
		return {"status": "skipped", "error_code": "NO_DEVICE"}
	return {"status": "failed", "error_code": "PUSH_SEND_FAILED"}
