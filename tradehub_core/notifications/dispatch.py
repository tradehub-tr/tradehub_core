"""Olay odaklı gönderim servisi.

Sıra: gerçek domain olayı → olay politikası → kullanıcı tercihi / kanal kapasitesi → yayınlanmış
şablon ve dil → güvenli render → kalıcı gönderim kaydı → commit SONRASI worker → sağlayıcı sonucu.

Kanal başına karar (`emit` dönüşündeki `handled`):
  - kapalı kanal ya da kullanıcının kapattığı seçmeli kanal → hiçbir yol göndermez (legacy dahil);
  - yayınlanmış içeriği olan açık kanal → yeni yol (Delivery + worker), legacy o kanalı GÖNDERMEZ;
  - yayınlanmış içerik yoksa → kanal çağıranın legacy yoluna bırakılır (mevcut davranış).
Böylece aynı e-posta hem eski `send_email=True` hem worker tarafından gönderilmez.

Mükerrer engeli DB'dedir: `idempotency_key` unique (olay oluşumu × alıcı × kanal). Worker satırı
`FOR UPDATE` ile kilitler; e-posta ve uygulama içi bildirimde sağlayıcı kaydı (Email Queue /
Platform Notification) ile durum güncellemesi AYNI transaction'dadır — çökme olursa ikisi de geri
alınır, tekrar deneme ikinci ileti üretmez. Dış HTTP çağrısı olan kanalda (push) önce "sending"
commit edilir; çağrı sırasında çökme olursa süpürücü satırı "uncertain" yapar, kör tekrar yok.
SMTP kuyruğuna kabul ("accepted") teslim/okundu anlamına gelmez.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_to_date, get_url, now_datetime

from tradehub_core.notifications import catalog, preferences, push, render, schedule, store, validation

DELIVERY = store.DELIVERY
TERMINAL = ("sent", "accepted", "captured", "failed", "skipped", "cancelled", "uncertain", "digested")
PENDING = ("queued", "deferred", "digest_pending")
SENSITIVE = {"identity.otp", "identity.password_reset"}
LANG_MAP = {"tr": "tr", "en": "en", "ar": "ar", "ru": "ru"}
MONTHS_TR = ("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")


# ── Yardımcılar ───────────────────────────────────────────────────────────


def fmt_dt(value) -> str:
	if not value:
		return ""
	dt = frappe.utils.get_datetime(value)
	return f"{dt.day} {MONTHS_TR[dt.month - 1]} {dt.year}, {dt:%H:%M}"


def fmt_date(value) -> str:
	if not value:
		return ""
	d = frappe.utils.getdate(value)
	return f"{d.day} {MONTHS_TR[d.month - 1]} {d.year}"


def user_lang(user: str | None) -> str:
	if not user:
		return catalog.SOURCE_LANG
	lang = (frappe.db.get_value("User", user, "language") or "tr").split("-")[0].lower()
	return LANG_MAP.get(lang, catalog.SOURCE_LANG)


def _mask(value: str) -> str:
	if "@" in (value or ""):
		local, domain = value.split("@", 1)
		return f"{local[:2]}•••@{domain}"
	return (value or "")[:3] + "•••" if value else ""


def _naive(dt: datetime) -> datetime:
	"""Aware → sistem saat dilimine göre naive (Frappe Datetime alanları naive tutar)."""
	from zoneinfo import ZoneInfo

	tz = frappe.db.get_single_value("System Settings", "time_zone") or "UTC"
	return dt.astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def base_url() -> str:
	try:
		from tradehub_core.api.v1.identity import storefront_url

		return storefront_url().rstrip("/")
	except Exception:  # noqa: BLE001 — yardımcı yoksa site adresi yeterli
		return get_url().rstrip("/")


def _rule(event_key: str) -> dict | None:
	row = frappe.db.get_value(
		store.EVENT, event_key, ["channels", "defaults", "delivery", "enabled"], as_dict=True
	)
	if not row or not row.enabled:
		return None
	return {
		"channels": store._json(row.channels, {}),
		"defaults": store._json(row.defaults, {}),
		"delivery": row.delivery,
	}


def _published(event_key: str) -> tuple[dict | None, int, dict]:
	return store.published_content(event_key)


def _has_content(content: dict | None, channel: str) -> bool:
	return bool(content and ((content.get(channel) or {}).get(catalog.SOURCE_LANG)))


# ── Emit ──────────────────────────────────────────────────────────────────


def emit(
	event_key: str,
	user: str | None,
	data: dict,
	occurrence_id: str,
	*,
	meta: dict | None = None,
	only_channels: tuple | None = None,
) -> dict:
	"""Olayı kanallara dağıtır. Dönüş: {"handled": set(kanal), "deliveries": [ad]}.

	`meta`: uygulama içi bildirim alanları (type, reference_doctype, reference_name, recipient_role).
	"""
	out = {"handled": set(), "deliveries": []}
	s = preferences.settings()
	if (
		not s["dispatch_enabled"]
		or not catalog.get(event_key)
		or not user
		or user in ("Guest", "Administrator")
	):
		return out
	rule = _rule(event_key)
	if not rule:
		return out
	content, version, _states = _published(event_key)
	choices, row = preferences.stored_choices(user)
	frequency = (row.frequency if row else None) or "instant"
	for channel in catalog.CHANNELS:
		if only_channels and channel not in only_channels:
			continue  # bu kanal başka bir yoldan (ör. kimlik akışının kendi e-postası) gidiyor
		state = rule["channels"].get(channel, "kapali")
		if state == "kapali" or not preferences.choice(rule, choices, event_key, channel):
			out["handled"].add(channel)  # kapalı/kapatılmış kanala hiçbir yol göndermez
			continue
		if not _has_content(content, channel):
			continue  # yayınlanmış şablon yok → legacy yolu
		missing = validation.missing_event_data(event_key, channel, data)
		if missing and state == "zorunlu":
			continue  # zorunlu kanalda eksik veri: güvenilir legacy gönderimi devreye girsin
		name = _create(event_key, user, channel, data, occurrence_id, version, rule, frequency, meta, missing)
		out["handled"].add(channel)
		if name:
			out["deliveries"].append(name)
	return out


def _create(event_key, user, channel, data, occurrence_id, version, rule, frequency, meta, missing):
	key = f"{event_key}:{occurrence_id}:{user}:{channel}"
	idem = hashlib.sha256(key.encode()).hexdigest()
	if frappe.db.exists(DELIVERY, {"idempotency_key": idem}):
		return None  # aynı olay oluşumu daha önce kaydedildi
	now = now_datetime()
	status, due = "queued", now
	payload = {"data": data, "meta": meta or {}}
	if missing:
		status, payload = "skipped", None
	elif (
		channel == "email"
		and rule["delivery"] == "ozetlenebilir"
		and frequency in ("daily", "weekly")
		and event_key not in catalog.DIGEST_KEYS  # özetin kendisi özete alınmaz
	):
		if _has_content(_published(f"digest.{frequency}")[0], "email"):
			status = "digest_pending"
			due = _naive(preferences.digest_times()[frequency])
			payload["digest_item"] = _digest_item(event_key, data, meta)
		# Özet şablonu yayında değilse e-posta özetlenmez, anında gider (bekletip kaybetmek yerine).
	elif channel == "push":
		deferred = _quiet_due(user, rule)
		if deferred:
			status, due = "deferred", deferred
	doc = frappe.get_doc(
		{
			"doctype": DELIVERY,
			"occurrence_id": str(occurrence_id)[:140],
			"event": event_key,
			"user": user,
			"channel": channel,
			"template_version": version,
			"language_requested": user_lang(user),
			"status": status,
			"due_at": due,
			"attempts": 0,
			"idempotency_key": idem,
			"error_code": "MISSING_EVENT_DATA" if missing else None,
			"payload": json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
		}
	)
	try:
		with store._Write():
			doc.insert(ignore_permissions=True)  # sistem kaydı; alıcı olay sahibi koddan geliyor
	except frappe.DuplicateEntryError:
		return None
	if status == "queued":
		frappe.enqueue(
			"tradehub_core.notifications.dispatch.process",
			queue="short",
			delivery=doc.name,
			enqueue_after_commit=True,
		)
	return doc.name


def _digest_item(event_key, data, meta) -> dict:
	ev = catalog.get(event_key)
	ref = data.get("reference_no") or data.get("order_no") or ""
	return {
		"category": ev["category"],
		"title": f"{ev['name']}{': ' + str(ref) if ref else ''}",
		"url": data.get("action_url") or data.get("order_url") or "",
		"at": str(now_datetime()),
	}


def _quiet_due(user: str, rule: dict):
	row = frappe.db.get_value(
		preferences.PREF, user, ["quiet_enabled", "quiet_start", "quiet_end", "quiet_timezone"], as_dict=True
	)
	if not row or not row.quiet_enabled or not row.quiet_start or not row.quiet_end:
		return None
	s = preferences.settings()
	if rule["delivery"] == "aninda" and s["urgent_push_bypasses_quiet"]:
		return None
	now = preferences._aware_now()
	tz = row.quiet_timezone or preferences.DEFAULT_TZ
	if not schedule.in_quiet(now, row.quiet_start, row.quiet_end, tz):
		return None
	return _naive(schedule.quiet_end(now, row.quiet_start, row.quiet_end, tz))


# ── Worker ────────────────────────────────────────────────────────────────


def process(delivery: str) -> str:
	"""Tek gönderim kaydını işler. İdempotent: terminal durumdaki kayda dokunmaz."""
	row = frappe.db.get_value(
		DELIVERY,
		delivery,
		[
			"name",
			"event",
			"user",
			"channel",
			"status",
			"due_at",
			"attempts",
			"payload",
			"language_requested",
			"is_test",
			"target_ref",
		],
		as_dict=True,
		for_update=True,
	)
	if not row or row.status != "queued":
		frappe.db.commit()
		return row.status if row else "missing"
	if row.due_at and frappe.utils.get_datetime(row.due_at) > now_datetime() + timedelta(seconds=5):
		frappe.db.commit()
		return "not_due"
	payload = store._json(row.payload, {})
	try:
		result = _deliver(row, payload)
	except Exception:  # noqa: BLE001 — sağlayıcı hatası kayda yazılır, iş kuyruğu düşmez
		frappe.db.rollback()
		frappe.log_error(title=f"notification delivery {delivery}")
		_finish(delivery, "failed", error_code="INTERNAL_ERROR", attempts=(row.attempts or 0) + 1)
		frappe.db.commit()
		return "failed"
	frappe.db.commit()
	return result


def _finish(name: str, status: str, **values) -> None:
	values = {k: v for k, v in values.items() if v is not None or k == "error_code"}
	values["status"] = status
	if status in ("sent", "accepted", "captured"):
		values["sent_at"] = now_datetime()
	if status in TERMINAL and status != "digested":
		values["payload"] = None  # teslim günlüğünde tam içerik tutulmaz
	with store._Write():
		frappe.db.set_value(DELIVERY, name, values, update_modified=True)


def _deliver(row, payload) -> str:
	data = payload.get("data") or {}
	meta = payload.get("meta") or {}
	attempts = (row.attempts or 0) + 1
	if not row.is_test:
		rule = _rule(row.event)
		choices, _r = preferences.stored_choices(row.user)
		if not rule or not preferences.choice(rule, choices, row.event, row.channel):
			_finish(row.name, "cancelled", error_code="PREFERENCE_OFF", attempts=attempts)
			return "cancelled"
		if not preferences.settings()["dispatch_enabled"]:
			_finish(row.name, "cancelled", error_code="DISPATCH_DISABLED", attempts=attempts)
			return "cancelled"
		content, version, states = _published(row.event)
		mandatory = rule["channels"].get(row.channel) == "zorunlu"
	else:
		content = payload.get("content")
		version = payload.get("version") or 0
		states = payload.get("states") or {}
		mandatory = payload.get("mandatory", False)
	fields, lang_used = render.resolve_lang(
		content or {}, row.channel, row.language_requested or "tr", states
	)
	if not fields:
		_finish(row.name, "skipped", error_code="TEMPLATE_NOT_PUBLISHED", attempts=attempts)
		return "skipped"
	missing = [] if row.is_test else validation.missing_event_data(row.event, row.channel, data)
	if missing:
		_finish(row.name, "skipped", error_code="MISSING_EVENT_DATA", attempts=attempts)
		return "skipped"
	msg = render.build_message(
		row.event,
		row.channel,
		fields,
		data,
		lang_used,
		mandatory=mandatory,
		base_url=base_url(),
		sms_currency_as_text=preferences.settings()["sms_currency_as_text"],
	)
	common = {"attempts": attempts, "language_used": lang_used, "template_version": version}
	return CHANNEL_SENDERS[row.channel](row, msg, meta, payload, common)


def _send_inapp(row, msg, meta, payload, common):
	doc = frappe.get_doc(
		{
			"doctype": "Platform Notification",
			"recipient_user": row.user,
			"recipient_role": meta.get("recipient_role") or "",
			"type": meta.get("type") or "system",
			"title": msg["title"] or "(Bildirim)",
			"message": msg["message"],
			"action_url": msg["action_url"],
			"reference_doctype": meta.get("reference_doctype") or "",
			"reference_name": meta.get("reference_name") or "",
			"channel": "in_app",  # depodaki değer; API'deki "inapp" ile eşlenir
			"is_read": 0,
		}
	)
	doc.insert(ignore_permissions=True)  # sistem bildirimi; alıcı olay sahibinden çözüldü
	_finish(row.name, "sent", provider_reference=doc.name, **common)
	return "sent"


def _send_email(row, msg, meta, payload, common):
	recipient = payload.get("target") or (
		frappe.db.get_value("User", row.user, "email") if row.user else None
	)
	if not recipient:
		_finish(row.name, "skipped", error_code="TARGET_MISSING", **common)
		return "skipped"
	kwargs = {
		"recipients": [recipient],
		"subject": msg["subject"],
		"message": msg["html"],
		"now": False,
		"delayed": True,
		"header": None,
		"with_container": False,
	}
	if meta.get("reference_doctype") and meta.get("reference_name"):
		kwargs["reference_doctype"] = meta["reference_doctype"]
		kwargs["reference_name"] = meta["reference_name"]
	queue = frappe.sendmail(**kwargs)
	if not queue:
		_finish(row.name, "skipped", error_code="EMAIL_NOT_QUEUED", **common)
		return "skipped"
	# SMTP kuyruğuna kabul: teslim değil. Gerçek SMTP sonucu süpürücüde Email Queue'dan okunur.
	_finish(row.name, "accepted", provider_reference=queue.name, **common)
	return "accepted"


def _send_push(row, msg, meta, payload, common):
	if not push.provider_available():
		_finish(row.name, "failed", error_code="PROVIDER_UNAVAILABLE", **common)
		return "failed"
	with store._Write():
		frappe.db.set_value(DELIVERY, row.name, {"status": "sending", "attempts": common["attempts"]})
	frappe.db.commit()  # dış çağrı öncesi; çökme olursa süpürücü "uncertain" yapar
	count = (meta or {}).get("quiet_summary_count") or 0
	if count > 1:  # sessiz saatte biriken push'lar tek özet push olarak gider (politika: summarize)
		msg = {"title": "iStoc", "body": f"Sessiz saatlerde {count} yeni bildiriminiz oldu."}
	res = push.send(row.user, msg["title"], msg["body"], None)
	_finish(
		row.name,
		res["status"],
		error_code=res.get("error_code"),
		provider_reference=res.get("provider_reference"),
		**common,
	)
	return res["status"]


def _send_sms(row, msg, meta, payload, common):
	# SMS sağlayıcısı bu kurulumda yok (B0). Başarı taklit edilmez.
	_finish(row.name, "failed", error_code="PROVIDER_UNAVAILABLE", **common)
	return "failed"


CHANNEL_SENDERS = {"inapp": _send_inapp, "email": _send_email, "push": _send_push, "sms": _send_sms}


# ── Güvenlik e-postaları (OTP / şifre sıfırlama) ─────────────────────────


def send_security_email(event_key: str, recipient: str, data: dict, *, user: str | None, legacy) -> str:
	"""Yayınlanmış şablon varsa onu, yoksa mevcut güvenilir kimlik gönderimini (`legacy`) kullanır.

	Kod/bağlantı teslim günlüğüne YAZILMAZ: kayıt yalnız durum, maskeli hedef ve sürüm tutar.
	Taşıma kanalı kimlik akışınındır (e-posta); aynı kod SMS'e otomatik gönderilmez.
	"""
	content, version, states = (
		_published(event_key) if preferences.settings()["dispatch_enabled"] else (None, 0, {})
	)
	rule = _rule(event_key)
	if not rule or rule["channels"].get("email") == "kapali" or not _has_content(content, "email"):
		legacy()
		return "legacy"
	if validation.missing_event_data(event_key, "email", data):
		legacy()
		return "legacy"
	lang = user_lang(user)
	fields, lang_used = render.resolve_lang(content, "email", lang, states)
	msg = render.build_message(
		event_key, "email", fields, data, lang_used, mandatory=True, base_url=base_url()
	)
	idem = hashlib.sha256(f"{event_key}:{frappe.generate_hash(length=20)}".encode()).hexdigest()
	frappe.sendmail(
		recipients=recipient,
		subject=msg["subject"],
		message=msg["html"],
		now=True,
		header=None,
		with_container=False,
	)
	with store._Write():
		frappe.get_doc(
			{
				"doctype": DELIVERY,
				"occurrence_id": f"{event_key}:security",
				"event": event_key,
				"user": user if user and frappe.db.exists("User", user) else None,
				"target_ref": _mask(recipient),
				"channel": "email",
				"template_version": version,
				"language_requested": lang,
				"language_used": lang_used,
				"status": "accepted",
				"sent_at": now_datetime(),
				"attempts": 1,
				"idempotency_key": idem,
			}
		).insert(ignore_permissions=True)  # sistem kaydı; içerik yazılmaz
	return "template"


# ── Tercih değişikliği ────────────────────────────────────────────────────


def on_preferences_changed(user: str, old_frequency: str, new_frequency: str) -> None:
	"""Bekleyen seçmeli gönderimleri yeni tercihe göre iptal / yeniden planla."""
	rows = frappe.get_all(
		DELIVERY,
		filters={"user": user, "status": ["in", list(PENDING)], "is_test": 0},
		fields=["name", "event", "channel", "status"],
		limit=500,
	)
	if not rows:
		return
	rules = preferences.event_rules()
	choices, _row = preferences.stored_choices(user)
	times = preferences.digest_times()
	for r in rows:
		rule = rules.get(r.event)
		if not rule or not preferences.choice(rule, choices, r.event, r.channel):
			_finish(r.name, "cancelled", error_code="PREFERENCE_OFF")
			continue
		if r.status != "digest_pending" or old_frequency == new_frequency:
			continue
		if new_frequency in ("daily", "weekly"):
			# Aynı olay iki özette görünmez: kayıt tek bir özete bağlanır, yalnız zamanı taşınır.
			with store._Write():
				frappe.db.set_value(DELIVERY, r.name, "due_at", _naive(times[new_frequency]))
		else:
			with store._Write():
				frappe.db.set_value(DELIVERY, r.name, {"status": "queued", "due_at": now_datetime()})
			frappe.enqueue(
				"tradehub_core.notifications.dispatch.process",
				queue="short",
				delivery=r.name,
				enqueue_after_commit=True,
			)


# ── Zamanlanmış işler ─────────────────────────────────────────────────────


def sweep() -> dict:
	"""5 dakikada bir: kayıp kuyruk işi, sessiz saati biten push, belirsiz gönderim, SMTP sonucu."""
	now = now_datetime()
	stats = {"requeued": 0, "released": 0, "uncertain": 0, "smtp": 0}
	for name in frappe.get_all(
		DELIVERY,
		filters={"status": "queued", "due_at": ["<=", add_to_date(now, minutes=-2)]},
		pluck="name",
		limit=200,
	):
		frappe.enqueue("tradehub_core.notifications.dispatch.process", queue="short", delivery=name)
		stats["requeued"] += 1
	stats["released"] = release_deferred(now)
	stale = frappe.get_all(
		DELIVERY,
		filters={"status": "sending", "modified": ["<", add_to_date(now, minutes=-15)]},
		pluck="name",
		limit=200,
	)
	for name in stale:
		_finish(name, "uncertain", error_code="PROVIDER_RESULT_UNKNOWN")
		stats["uncertain"] += 1
	stats["smtp"] = reconcile_email_queue()
	frappe.db.commit()
	return stats


def release_deferred(now) -> int:
	"""Sessiz saati biten push'lar. Politika `summarize`: kullanıcı başına tek özet push."""
	rows = frappe.get_all(
		DELIVERY,
		filters={"status": "deferred", "due_at": ["<=", now]},
		fields=["name", "user", "event"],
		order_by="user asc, creation asc",
		limit=500,
	)
	policy = preferences.settings()["quiet_backlog_policy"]
	by_user: dict[str, list] = {}
	for r in rows:
		by_user.setdefault(r.user, []).append(r)
	for items in by_user.values():
		if policy == "drop":
			for r in items:
				_finish(r.name, "cancelled", error_code="QUIET_HOURS_DROPPED")
			continue
		if policy == "summarize" and len(items) > 1:
			keep, rest = items[-1], items[:-1]
			for r in rest:
				_finish(r.name, "cancelled", error_code="QUIET_HOURS_SUMMARIZED")
			_summarize_push(keep.name, len(items))
			items = [keep]
		for r in items:
			with store._Write():
				frappe.db.set_value(DELIVERY, r.name, "status", "queued")
			frappe.enqueue(
				"tradehub_core.notifications.dispatch.process",
				queue="short",
				delivery=r.name,
				enqueue_after_commit=True,
			)
	return len(rows)


def _summarize_push(name: str, count: int) -> None:
	payload = store._json(frappe.db.get_value(DELIVERY, name, "payload"), {})
	payload.setdefault("meta", {})["quiet_summary_count"] = count
	with store._Write():
		frappe.db.set_value(DELIVERY, name, "payload", json.dumps(payload, ensure_ascii=False, default=str))


def reconcile_email_queue() -> int:
	"""accepted → sent (SMTP sunucusu kabul etti) / failed (SMTP hatası). Okundu bilgisi yok."""
	rows = frappe.get_all(
		DELIVERY,
		filters={"status": "accepted", "channel": "email", "provider_reference": ["is", "set"]},
		fields=["name", "provider_reference"],
		limit=500,
	)
	if not rows:
		return 0
	queues = {
		q.name: q.status
		for q in frappe.get_all(
			"Email Queue",
			filters={"name": ["in", [r.provider_reference for r in rows]]},
			fields=["name", "status"],
		)
	}
	changed = 0
	for r in rows:
		st = queues.get(r.provider_reference)
		if st == "Sent":
			with store._Write():
				frappe.db.set_value(DELIVERY, r.name, "status", "sent")
			changed += 1
		elif st == "Error":
			with store._Write():
				frappe.db.set_value(DELIVERY, r.name, {"status": "failed", "error_code": "SMTP_ERROR"})
			changed += 1
	return changed
