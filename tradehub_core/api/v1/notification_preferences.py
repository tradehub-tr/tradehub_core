"""Kullanıcının kendi bildirim tercihleri API'si (storefront).

Sözleşme: `BACKEND-API.openapi.json`. Kullanıcı yalnız KENDİ kaydını okur/yazar; başka kullanıcı
kimliği parametresi yoktur. GET hiçbir kayıt/izin/log yazmaz.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from tradehub_core.notifications import consent_bridge, errors, preferences, push

CONSENT_CHANNELS = ("email", "sms")


def _me() -> str:
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Oturum açmanız gerekiyor."), frappe.AuthenticationError)
	return user


def _obj(value, name):
	if isinstance(value, str):
		try:
			return json.loads(value)
		except ValueError:
			raise errors.validation(field_errors={name: "Geçerli JSON olmalı."})
	return value


def _bool(value, name):
	if isinstance(value, bool):
		return value
	if value in ("true", "1", 1):
		return True
	if value in ("false", "0", 0):
		return False
	raise errors.validation(field_errors={name: "true/false olmalı."})


@frappe.whitelist(methods=["GET"])
@errors.guarded
def get_preferences():
	return preferences.build(_me())


@frappe.whitelist(methods=["POST"])
@errors.guarded
def save_preferences(events=None, frequency=None, quiet=None, revision=None):
	user = _me()
	rev = _obj(revision, "revision")
	if isinstance(rev, str) and rev.isdigit():
		rev = int(rev)
	return preferences.save(user, _obj(events, "events"), frequency, _obj(quiet, "quiet"), rev)


@frappe.whitelist(methods=["GET"])
@errors.guarded
def get_consent_status():
	return consent_bridge.status(_me())


@frappe.whitelist(methods=["POST"])
@errors.guarded
def set_commercial_consent(channel=None, granted=None):
	user = _me()
	if channel not in CONSENT_CHANNELS:
		raise errors.validation(field_errors={"channel": "email ya da sms olmalı."})
	granted = _bool(granted, "granted")
	if granted:
		consent_bridge.assert_grantable(user, channel)
	from tradehub_core.privacy.consent import record_consent

	# Karar mevcut izin günlüğüne yazılır; köprü aktarım satırını aynı transaction'da açar.
	record_consent(
		user, consent_bridge.TYPES[channel], "granted" if granted else "withdrawn", source="settings"
	)
	return consent_bridge.status(user)


@frappe.whitelist(methods=["POST"])
@errors.guarded
def retry_consent_sync(channel=None):
	user = _me()
	if channel not in CONSENT_CHANNELS:
		raise errors.validation(field_errors={"channel": "email ya da sms olmalı."})
	if not consent_bridge.provider_available():
		raise errors.provider_unavailable("iys")
	return {"consent": consent_bridge.status(user)["consent"]}


@frappe.whitelist(methods=["POST"])
@errors.guarded
def register_push_device(token=None, platform=None):
	_me()
	if not isinstance(token, str) or not 1 <= len(token) <= 4096:
		raise errors.validation(field_errors={"token": "1–4096 karakter."})
	if platform not in ("ios", "android"):
		raise errors.validation(field_errors={"platform": "ios ya da android olmalı."})
	return {"push_device": push.register_native(token, platform)}
