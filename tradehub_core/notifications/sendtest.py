"""Şablon test gönderimi.

- E-posta/SMS hedefi: oturumdaki kullanıcının DOĞRULANMIŞ e-postası ya da Platform Notification
  Settings'teki izinli test adresleri. Uygulama içi / push: oturumdaki kullanıcı ya da izinli
  yerel test kullanıcısı. Keyfi başka kullanıcıya bildirim attırılamaz.
- Aynı `request_id` aynı sonucu döndürür (ikinci ileti yok). Kullanıcı ve hedef başına saatlik sınır.
- Yanıt kuyruğa alındığını söyler (`queued`); SMTP kabulü teslim değildir. Sağlayıcı yoksa 503.
- İçerik örnek veriyle doldurulur; örnek veri yalnız test/önizleme içindir.
"""

from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe.utils import add_to_date, now_datetime

from tradehub_core.notifications import catalog, errors, preferences, push, store

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _allow(raw: str) -> set[str]:
	return {x.strip().lower() for x in re.split(r"[\s,;]+", raw or "") if x.strip()}


def _resolve_target(channel: str, target: str) -> tuple[str | None, str]:
	"""(alıcı kullanıcı, teslim hedefi). Uygun değilse 422."""
	me = frappe.session.user
	s = preferences.settings()
	target = (target or "").strip()
	if channel == "email":
		own = (frappe.db.get_value("User", me, "email") or "").lower()
		own_verified = bool(frappe.db.get_value("User Profile", {"user": me}, "email_verified"))
		if target.lower() == own and own_verified or target.lower() in _allow(s["test_email_allowlist"]):
			return me, target
		raise errors.validation(
			field_errors={"target": "Hedef doğrulanmış kendi adresiniz ya da izinli test adresi olmalı."}
		)
	if channel == "sms":
		if target in _allow(s["test_sms_allowlist"]):
			return me, target
		raise errors.validation(field_errors={"target": "Hedef izinli test telefonu olmalı."})
	user = target or me
	if user == me or user.lower() in _allow(s["test_user_allowlist"]):
		if not frappe.db.exists("User", user):
			raise errors.validation(field_errors={"target": "Kullanıcı bulunamadı."})
		return user, user
	raise errors.validation(
		field_errors={"target": "Yalnız kendinize ya da izinli test kullanıcısına gönderebilirsiniz."}
	)


def _rate_check(target_hash: str) -> None:
	limit = preferences.settings()["test_hourly_limit"]
	since = add_to_date(now_datetime(), hours=-1)
	base = {"is_test": 1, "creation": [">=", since]}
	if frappe.db.count(store.DELIVERY, {**base, "owner": frappe.session.user}) >= limit:
		raise errors.rate_limited()
	if frappe.db.count(store.DELIVERY, {**base, "occurrence_id": f"test:{target_hash}"}) >= limit:
		raise errors.rate_limited()


def _receipt(row) -> dict:
	sent = row.status == "sent" and row.channel == "inapp"
	return {
		"state": "sent" if sent else "queued",
		"delivery_id": row.name,
		"queued_at": str(row.creation),
		"sent_at": str(row.sent_at) if sent and row.sent_at else None,
	}


def send_test(key, channel, lang, version, target, request_id) -> dict:
	field_errors = {}
	if channel not in catalog.CHANNELS:
		field_errors["channel"] = "Bilinmeyen kanal."
	if lang not in catalog.LANGS:
		field_errors["lang"] = "Bilinmeyen dil."
	if version not in ("draft", "published"):
		field_errors["version"] = "draft ya da published olmalı."
	if not UUID_RE.match(str(request_id or "")):
		field_errors["request_id"] = "UUID olmalı."
	if field_errors:
		raise errors.validation(field_errors=field_errors)
	idem = hashlib.sha256(f"test:{frappe.session.user}:{request_id}".encode()).hexdigest()
	existing = frappe.db.get_value(
		store.DELIVERY,
		{"idempotency_key": idem},
		["name", "status", "channel", "creation", "sent_at"],
		as_dict=True,
	)
	if existing:
		return _receipt(existing)
	event = store.load_event(key)
	template = store.load_template(key)
	if version == "draft":
		content = template.draft
	else:
		content, _v, _s = store.published_content(key)
	fields = ((content or {}).get(channel) or {}).get(lang)
	if not fields:
		raise errors.validation(field_errors={"lang": "Bu kanal ve dilde içerik yok."})
	# Sağlayıcı yoksa hedef ne olursa olsun gönderim yapılamaz: önce kapasite, sonra hedef denetlenir.
	if channel == "sms" or (channel == "push" and not push.provider_available()):
		raise errors.provider_unavailable(channel)
	user, delivery_target = _resolve_target(channel, target)
	target_hash = hashlib.sha256(delivery_target.lower().encode()).hexdigest()[:32]
	_rate_check(target_hash)
	sample = {v["name"]: v.get("sample") for v in catalog.variables_for(key) if not v.get("scope")}
	payload = {
		"data": sample,
		"meta": {"type": "system"},
		"content": {channel: {lang: fields}},
		"states": {lang: "hazir"},
		"version": store.published_version_number(template) if version == "published" else 0,
		"mandatory": event.channels.get(channel) == "zorunlu",
		"target": delivery_target if channel in ("email", "sms") else None,
	}
	doc = frappe.get_doc(
		{
			"doctype": store.DELIVERY,
			"occurrence_id": f"test:{target_hash}",
			"event": key,
			"user": user,
			"target_ref": delivery_target if channel in ("inapp", "push") else delivery_target[:2] + "•••",
			"channel": channel,
			"template_version": payload["version"],
			"language_requested": lang,
			"status": "queued",
			"due_at": now_datetime(),
			"idempotency_key": idem,
			"is_test": 1,
			"payload": json.dumps(payload, ensure_ascii=False, default=str),
		}
	)
	with store._Write():
		doc.insert(ignore_permissions=True)  # yetki uçta denetlendi
	frappe.enqueue(
		"tradehub_core.notifications.dispatch.process",
		queue="short",
		delivery=doc.name,
		enqueue_after_commit=True,
	)
	frappe.local.response.http_status_code = 202
	return _receipt(
		frappe._dict(name=doc.name, status="queued", channel=channel, creation=doc.creation, sent_at=None)
	)
