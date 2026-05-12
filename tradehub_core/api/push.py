"""Faz 6 — Web Push Notification (VAPID + Service Worker).

`pywebpush` paketi yüklü değilse stub mode: subscription kaydı tutulur ama
gerçek push gönderilmez. Production'da `bench pip install pywebpush` ve
Push Notification Settings'te VAPID anahtarları set edilir.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from tradehub_core.api.rate_limit import rate_limit


def _ensure_logged_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Giriş yapın"), frappe.AuthenticationError)


def _get_settings():
	try:
		settings = frappe.get_single("Push Notification Settings")
		return {
			"enabled": bool(settings.enabled),
			"subject": settings.vapid_subject or "mailto:admin@tradehub.local",
			"public_key": settings.vapid_public_key,
			"private_key": settings.get_password("vapid_private_key", raise_exception=False),
		}
	except Exception:
		return {"enabled": False, "subject": "", "public_key": "", "private_key": ""}


@frappe.whitelist()
@rate_limit(max_calls=5, window_seconds=60, scope="push_subscribe")
def subscribe(endpoint: str, p256dh: str, auth: str):
	"""Storefront service worker'dan subscription kaydı."""
	_ensure_logged_in()
	user = frappe.session.user

	# Duplicate kontrol (endpoint unique)
	existing = frappe.db.get_value("Push Subscription", {"endpoint": endpoint}, "name")
	if existing:
		frappe.db.set_value(
			"Push Subscription",
			existing,
			{"user": user, "p256dh": p256dh, "auth": auth, "last_used_at": now_datetime()},
			update_modified=False,
		)
		frappe.db.commit()
		return {"success": True, "subscription": existing, "updated": True}

	doc = frappe.new_doc("Push Subscription")
	doc.user = user
	doc.endpoint = endpoint
	doc.p256dh = p256dh
	doc.auth = auth
	doc.subscribed_at = now_datetime()
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "subscription": doc.name, "created": True}


@frappe.whitelist()
def unsubscribe(endpoint: str | None = None):
	"""Kullanıcı kendi subscription'unu siler."""
	_ensure_logged_in()
	user = frappe.session.user
	filters = {"user": user}
	if endpoint:
		filters["endpoint"] = endpoint
	rows = frappe.get_all("Push Subscription", filters=filters, pluck="name")
	for n in rows:
		frappe.delete_doc("Push Subscription", n, ignore_permissions=True, force=True)
	frappe.db.commit()
	return {"success": True, "deleted": len(rows)}


@frappe.whitelist(allow_guest=True)
def get_public_key():
	"""Service worker subscribe için VAPID public key."""
	s = _get_settings()
	return {"public_key": s["public_key"], "enabled": s["enabled"]}


def _send_via_pywebpush(sub: dict, payload: dict, settings: dict) -> bool:
	"""pywebpush yüklüyse gerçek push gönder."""
	try:
		from pywebpush import webpush
	except ImportError:
		return False
	try:
		webpush(
			subscription_info={
				"endpoint": sub["endpoint"],
				"keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
			},
			data=json.dumps(payload),
			vapid_private_key=settings["private_key"],
			vapid_claims={"sub": settings["subject"]},
		)
		return True
	except Exception as e:
		frappe.log_error(title="webpush_send_failed", message=str(e))
		return False


def send_push(user: str, title: str, body: str, url: str | None = None, icon: str | None = None) -> dict:
	"""Bir kullanıcının tüm aktif subscription'larına push gönder."""
	if not user or user == "Guest":
		return {"sent": 0, "skipped": 1}
	settings = _get_settings()
	if not settings["enabled"]:
		return {"sent": 0, "disabled": True}

	subs = frappe.get_all(
		"Push Subscription", filters={"user": user}, fields=["name", "endpoint", "p256dh", "auth"]
	)
	if not subs:
		return {"sent": 0, "no_subscription": True}

	payload = {"title": title, "body": body, "url": url or "/", "icon": icon or "/favicon.ico"}
	sent = 0
	for sub in subs:
		ok = _send_via_pywebpush(sub, payload, settings)
		if ok:
			frappe.db.set_value(
				"Push Subscription", sub["name"], "last_used_at", now_datetime(), update_modified=False
			)
			sent += 1
	frappe.db.commit()
	return {"sent": sent, "total": len(subs)}


def notify_status_change(doc, method=None):
	"""hooks.py — Listing Review on_update; status değişimi için push."""
	if not doc:
		return
	old = doc.get_doc_before_save()
	if not old or old.status == doc.status:
		return
	if not doc.reviewer_user:
		return
	if doc.status == "Approved":
		send_push(
			doc.reviewer_user,
			"Yorumunuz yayınlandı",
			f"{doc.listing} için yorumunuz onaylandı.",
			url=f"/app/listing-review/{doc.name}",
		)
	elif doc.status == "Rejected":
		send_push(
			doc.reviewer_user,
			"Yorumunuz reddedildi",
			doc.rejected_reason or "Topluluk kurallarına uygun değil.",
			url=f"/app/listing-review/{doc.name}",
		)


@frappe.whitelist()
def admin_test_push(target_user: str = None):
	"""Admin manuel test."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)
	target = target_user or frappe.session.user
	return send_push(target, "TradeHub Test Push", "Bu bir test bildirimidir.", url="/")
