"""Kullanıcı bildirim tercihleri: okuma (salt), atomik kayıt, eski tercih köprüsü, gönderim kararı.

- GET hiçbir şey yazmaz: kayıt yoksa hesaplanmış varsayılan + revision 0.
- Kayıt revizyon kilitlidir (`SELECT … FOR UPDATE`); ilk kayıt `user` tekilliğiyle atomik oluşur,
  aynı anda iki ilk kayıtta ikincisi 409 alır.
- Yalnız seçmeli kanalların değeri saklanır; zorunlu/kapalı kanal girdisi yok sayılır.
- Eski `User Email Preference`: "Genel bildirim e-postaları" (general_notification) ya da
  "Tüm bildirim e-postaları" (notification) kapalıysa 26 olayın SEÇMELİ e-postası kapalı taşınır.
  dispute_updates / pazarlama / anket anahtarlarının katalogda karşılığı yok; silinmez, ticari
  izne dönüştürülmez, eski kayıtta kalır.
"""

from __future__ import annotations

import json
from datetime import datetime

import frappe
from frappe.utils import now_datetime

from tradehub_core.notifications import catalog, errors, schedule, store

PREF = "Platform Notification Preference"
DEFAULT_QUIET = {"enabled": False, "start": "22:00", "end": "08:00"}
DEFAULT_TZ = "Europe/Istanbul"


# ── Kimlik / roller ───────────────────────────────────────────────────────


def roles_of(user: str) -> list[str]:
	"""Mevcut alıcı/satıcı yeteneklerinden türetilir; yeni yetki kazandırmaz."""
	roles = set(frappe.get_roles(user))
	flags = frappe.db.get_value("User Profile", {"user": user}, ["can_buy", "can_sell"], as_dict=True) or {}
	out = []
	if "Buyer" in roles or "Marketplace Buyer" in roles or flags.get("can_buy"):
		out.append("buyer")
	if "Seller" in roles or "Marketplace Seller" in roles or flags.get("can_sell"):
		out.append("seller")
	return out or ["buyer"]


def user_timezone(user: str) -> str:
	tz = frappe.db.get_value("User", user, "time_zone")
	return tz if tz and schedule.valid_tz(tz) else DEFAULT_TZ


# ── Olay kuralları ────────────────────────────────────────────────────────


def event_rules() -> dict:
	"""Etkin olayların güncel kanal kuralı (DB'deki yönetici kararı)."""
	rows = frappe.get_all(
		store.EVENT,
		filters={"enabled": 1},
		fields=["name", "channels", "defaults", "delivery", "recipients", "sort_order"],
		order_by="sort_order asc",
	)
	out = {}
	for r in rows:
		if not catalog.get(r.name):
			continue
		out[r.name] = {
			"channels": store._json(r.channels, {}),
			"defaults": store._json(r.defaults, {}),
			"delivery": r.delivery,
			"recipients": store._json(r.recipients, []),
		}
	return out


# ── Kayıt okuma ───────────────────────────────────────────────────────────


def _row(user: str, for_update: bool = False):
	return frappe.db.get_value(
		PREF,
		user,
		[
			"name",
			"events",
			"frequency",
			"quiet_enabled",
			"quiet_start",
			"quiet_end",
			"quiet_timezone",
			"revision",
		],
		as_dict=True,
		for_update=for_update,
	)


def legacy_email_off(user: str) -> bool:
	raw = frappe.db.get_value("User Email Preference", user, "preferences_json")
	if not raw:
		return False
	try:
		prefs = json.loads(raw) if isinstance(raw, str) else raw
	except (TypeError, ValueError):
		return False
	toggles = prefs.get("toggles") or {}
	checks = prefs.get("checks") or {}
	return toggles.get("notification") is False or checks.get("general_notification") is False


def stored_choices(user: str) -> tuple[dict, dict | None]:
	"""(olay seçimleri, ham kayıt). Kayıt yoksa eski tercihten hesaplanmış seçimler."""
	row = _row(user)
	if row:
		return store._json(row.events, {}), row
	choices = {}
	if legacy_email_off(user):
		for key, rule in event_rules().items():
			if rule["channels"].get("email") == "secmeli":
				choices[key] = {"email": False}
	return choices, None


def choice(rule: dict, choices: dict, key: str, channel: str) -> bool:
	"""Kanalın kullanıcı için açık olup olmadığı (zorunlu → True, kapalı → False)."""
	state = rule["channels"].get(channel, "kapali")
	if state == "zorunlu":
		return True
	if state == "kapali":
		return False
	value = (choices.get(key) or {}).get(channel)
	if value is None:
		value = rule["defaults"].get(channel, True)
	return bool(value)


# ── Özet zamanları ────────────────────────────────────────────────────────


def settings() -> dict:
	s = frappe.get_cached_doc("Platform Notification Settings")
	return {
		"digest_time": s.digest_time or "08:00",
		"digest_weekday": s.digest_weekday or "monday",
		"digest_timezone": s.digest_timezone if schedule.valid_tz(s.digest_timezone or "") else DEFAULT_TZ,
		"digest_group_limit": int(s.digest_group_limit or 3),
		"quiet_backlog_policy": s.quiet_backlog_policy or "summarize",
		"urgent_push_bypasses_quiet": bool(s.urgent_push_bypasses_quiet),
		"dispatch_enabled": bool(s.dispatch_enabled) if s.dispatch_enabled is not None else True,
		"sms_currency_as_text": bool(s.sms_currency_as_text),
		"order_reminder_enabled": bool(s.order_reminder_enabled),
		"order_reminder_after_hours": int(s.order_reminder_after_hours or 0),
		"test_hourly_limit": int(s.test_hourly_limit or 10),
		"test_email_allowlist": s.test_email_allowlist or "",
		"test_sms_allowlist": s.test_sms_allowlist or "",
		"test_user_allowlist": s.test_user_allowlist or "",
	}


def _aware_now() -> datetime:
	"""Sunucu zamanı (system timezone) aware değer olarak."""
	from zoneinfo import ZoneInfo

	tz = frappe.db.get_single_value("System Settings", "time_zone") or "UTC"
	return now_datetime().replace(tzinfo=ZoneInfo(tz))


def digest_times(now: datetime | None = None) -> dict:
	s = settings()
	now = now or _aware_now()
	return {
		"daily": schedule.next_daily(now, s["digest_time"], s["digest_timezone"]),
		"weekly": schedule.next_weekly(now, s["digest_time"], s["digest_weekday"], s["digest_timezone"]),
	}


def _iso(dt: datetime | None) -> str | None:
	return dt.isoformat() if dt else None


# ── Yanıt gövdesi ─────────────────────────────────────────────────────────


def build(user: str) -> dict:
	from tradehub_core.notifications import consent_bridge, push

	roles = roles_of(user)
	rules = event_rules()
	choices, row = stored_choices(user)
	events = []
	digestible = instant = 0
	for ev in catalog.EVENTS:
		key = ev["key"]
		rule = rules.get(key)
		if not rule or not set(rule["recipients"]) & set(roles):
			continue
		chans = rule["channels"]
		user_choice = {
			ch: choice(rule, choices, key, ch) for ch in catalog.USER_CHANNELS if chans.get(ch) == "secmeli"
		}
		events.append(
			{
				"key": key,
				"name": ev["name"],
				"category": ev["category"],
				"mandatory": catalog.mandatory_of(chans),
				"why": ev["why"],
				"delivery": rule["delivery"],
				"channels": {ch: chans.get(ch, "kapali") for ch in catalog.CHANNELS},
				"user": user_choice,
			}
		)
		if key in catalog.DIGEST_KEYS or chans.get("email", "kapali") == "kapali":
			continue
		if rule["delivery"] == "ozetlenebilir":
			digestible += 1
		else:
			instant += 1
	frequency = (row.frequency if row else None) or "instant"
	times = digest_times()
	quiet = {
		"enabled": bool(row.quiet_enabled) if row else DEFAULT_QUIET["enabled"],
		"start": (row.quiet_start if row else None) or DEFAULT_QUIET["start"],
		"end": (row.quiet_end if row else None) or DEFAULT_QUIET["end"],
		"timezone": (row.quiet_timezone if row else None) or user_timezone(user),
	}
	consent = consent_bridge.status(user)
	return {
		"role": "seller" if "seller" in roles else "buyer",
		"roles": roles,
		"events": events,
		"frequency": frequency,
		"quiet": quiet,
		"digest": {
			"next_at": _iso(times.get(frequency)),
			"daily": _iso(times["daily"]),
			"weekly": _iso(times["weekly"]),
			"digestible_count": digestible,
			"instant_count": instant,
		},
		"push_device": push.device_state(user),
		"consent": consent["consent"],
		"consent_history": consent["consent_history"],
		"revision": int(row.revision or 0) if row else 0,
	}


# ── Kayıt ─────────────────────────────────────────────────────────────────


def _validate_payload(events, frequency, quiet, revision, visible_keys: set[str]) -> tuple[dict, dict]:
	field_errors = {}
	if not isinstance(events, dict):
		field_errors["events"] = "Nesne olmalı."
		events = {}
	for key, val in events.items():
		if key not in visible_keys:
			field_errors[f"events.{key}"] = "Bilinmeyen olay."
			continue
		if not isinstance(val, dict):
			field_errors[f"events.{key}"] = "Nesne olmalı."
			continue
		for ch, v in val.items():
			if ch not in catalog.USER_CHANNELS:
				field_errors[f"events.{key}.{ch}"] = "Bilinmeyen kanal."
			elif not isinstance(v, bool):
				field_errors[f"events.{key}.{ch}"] = "true/false olmalı."
	if frequency not in catalog.FREQUENCIES:
		field_errors["frequency"] = "instant, daily ya da weekly olmalı."
	if not isinstance(quiet, dict) or set(quiet) - {"enabled", "start", "end", "timezone"}:
		field_errors["quiet"] = "Geçersiz sessiz saat."
		quiet = {}
	else:
		if not isinstance(quiet.get("enabled"), bool):
			field_errors["quiet.enabled"] = "true/false olmalı."
		for f in ("start", "end"):
			if not isinstance(quiet.get(f), str) or not schedule.HHMM.match(quiet.get(f) or ""):
				field_errors[f"quiet.{f}"] = "SS:DD biçiminde olmalı."
		if (
			not field_errors.get("quiet.start")
			and not field_errors.get("quiet.end")
			and quiet["start"] == quiet["end"]
		):
			field_errors["quiet.end"] = "Başlangıç ve bitiş aynı olamaz."
		if not isinstance(quiet.get("timezone"), str) or not schedule.valid_tz(quiet.get("timezone")):
			field_errors["quiet.timezone"] = "Geçerli bir IANA saat dilimi olmalı."
	if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
		field_errors["revision"] = "Negatif olmayan tam sayı olmalı."
	if field_errors:
		raise errors.validation(field_errors=field_errors)
	return events, quiet


def save(user: str, events, frequency, quiet, revision) -> dict:
	rules = event_rules()
	roles = roles_of(user)
	visible = {k for k, r in rules.items() if set(r["recipients"]) & set(roles)}
	events, quiet = _validate_payload(events, frequency, quiet, revision, visible)

	row = _row(user, for_update=True)
	current = int(row.revision or 0) if row else 0
	if revision != current:
		raise errors.conflict(current, theirs=build(user))

	base, _ = stored_choices(user)
	merged = {}
	for key in visible:
		rule = rules[key]
		kept = {}
		for ch in catalog.USER_CHANNELS:
			if rule["channels"].get(ch) != "secmeli":
				continue  # zorunlu / kapalı kanal girdisi yok sayılır
			incoming = (events.get(key) or {}).get(ch)
			if incoming is None:
				incoming = (base.get(key) or {}).get(ch)
			if incoming is not None:
				kept[ch] = bool(incoming)
		if kept:
			merged[key] = kept
	# Kullanıcının görmediği (diğer rol) olayların eski seçimleri korunur.
	for key, val in base.items():
		if key not in visible:
			merged[key] = val

	values = {
		"events": json.dumps(merged),
		"frequency": frequency,
		"quiet_enabled": int(quiet["enabled"]),
		"quiet_start": quiet["start"],
		"quiet_end": quiet["end"],
		"quiet_timezone": quiet["timezone"],
		"revision": current + 1,
	}
	old_frequency = row.frequency if row else "instant"
	with store._Write():
		if row:
			frappe.db.set_value(PREF, user, values)
		else:
			try:
				frappe.get_doc({"doctype": PREF, "user": user, "legacy_migrated": 1, **values}).insert(
					ignore_permissions=True  # kullanıcı yalnız kendi kaydını yazar (uçta oturumdan)
				)
			except (frappe.DuplicateEntryError, frappe.QueryDeadlockError):
				# Eşzamanlı ilk kayıt: diğer istek kazandı.
				frappe.db.rollback()
				fresh = _row(user)
				raise errors.conflict(int(fresh.revision or 0) if fresh else 0)
	from tradehub_core.notifications import dispatch

	dispatch.on_preferences_changed(user, old_frequency, frequency)
	return build(user)


# ── Eski "E-posta tercihleri" ucu köprüsü ─────────────────────────────────


def legacy_general_enabled(user: str) -> bool | None:
	"""Yeni kayıt varsa eski 'Genel bildirim e-postaları' anahtarının karşılığı; yoksa None."""
	row = _row(user)
	if not row:
		return None
	choices = store._json(row.events, {})
	rules = event_rules()
	optional = [k for k, r in rules.items() if r["channels"].get("email") == "secmeli"]
	return any(choice(rules[k], choices, k, "email") for k in optional)


def apply_legacy_general(user: str, enabled: bool) -> None:
	"""Eski uçtan gelen genel e-posta seçimini yeni kayda yazar (iki doğruluk kaynağı kalmaz).

	Revizyon kilidi altında: mevcut kayıt güncel revizyonla kaydedilir.
	"""
	row = _row(user, for_update=True)
	rules = event_rules()
	roles = roles_of(user)
	events = {
		k: {"email": bool(enabled)}
		for k, r in rules.items()
		if r["channels"].get("email") == "secmeli" and set(r["recipients"]) & set(roles)
	}
	quiet = {
		"enabled": bool(row.quiet_enabled) if row else False,
		"start": (row.quiet_start if row else None) or DEFAULT_QUIET["start"],
		"end": (row.quiet_end if row else None) or DEFAULT_QUIET["end"],
		"timezone": (row.quiet_timezone if row else None) or user_timezone(user),
	}
	save(
		user,
		events,
		(row.frequency if row else None) or "instant",
		quiet,
		int(row.revision or 0) if row else 0,
	)
