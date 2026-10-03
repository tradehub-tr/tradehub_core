"""Şablon yönetimi iş kuralları (B2). Yetki API katmanında `authz.require` ile denetlenir.

Yaşam döngüsü:
  - Taslak kaydı canlı içeriği DEĞİŞTİRMEZ. Eksik içerikli taslak kaydedilebilir; güvensiz HTML
    temizlenir, izinsiz alan / aşırı boyut reddedilir; normalize alanlar yanıtta döner.
  - `publish` güncel taslağı sunucuda yeniden doğrular, değişmez sürüm yazar, canlı işaretçiyi aynı
    transaction'da değiştirir. Eski revizyonla yayın / tekrar tıklama 409 alır, ikinci sürüm çıkmaz.
  - `restore_version` eski içeriği YENİ TASLAĞA kopyalar (canlı sürüm değişmez; yayın ayrı işlem —
    geçici davranış, ürün kararı değil).
  - Onay isteği o anki revizyona bağlıdır; sonraki her yazma isteği geçersiz kılar.
  - Çeviri durumu yayından bağımsızdır; yayınlanan sürüm o anki dil durumlarını snapshot'lar.
"""

from __future__ import annotations

import copy
import json

import frappe
from frappe.utils import now_datetime

from tradehub_core.notifications import authz, catalog, errors, preferences, store, validation


def _fold(value) -> str:
	s = str(value or "").replace("İ", "i").replace("I", "ı").lower()
	for a, b in (("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ü", "u"), ("ö", "o"), ("ç", "c")):
		s = s.replace(a, b)
	import unicodedata

	return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def _review_state(t) -> str | None:
	return "onay-bekliyor" if t.review_state == "onay-bekliyor" else None


def event_out(event, template, role, estimates=None) -> dict:
	ev = catalog.get(event.name)
	langs = {lang: template.translation_states.get(lang, "eksik") for lang in catalog.LANGS}
	return {
		"key": event.name,
		"name": ev["name"],
		"category": ev["category"],
		"module": catalog.module_of(ev["category"]),
		"recipients": event.recipients,
		"mandatory": catalog.mandatory_of(event.channels),
		"why": ev["why"],
		"delivery": event.delivery,
		"channels": {ch: event.channels.get(ch, "kapali") for ch in catalog.CHANNELS},
		"defaults": {ch: bool(v) for ch, v in event.defaults.items() if event.channels.get(ch) == "secmeli"},
		"langs": langs,
		"publish": store.publish_state(template),
		"updated_by": template.saved_by or None,
		"updated_at": str(template.saved_at) if template.saved_at else None,
		"monthly_estimate": (estimates or {}).get(event.name),
		"representative": bool(template.representative),
		"review_state": _review_state(template),
		"revision": event.revision,
		"template_role": role,
		"capabilities": authz.capabilities(role),
	}


def _load(key):
	return store.load_event(key), store.load_template(key)


# ── Okuma ─────────────────────────────────────────────────────────────────

FILTERS = {
	"module": set(catalog.CATEGORIES),
	"channel": set(catalog.CHANNELS),
	"publish": {"yayinda", "yayinda-taslak", "taslak"},
	"translation": set(catalog.TRANSLATION_STATES),
	"delivery": set(catalog.DELIVERY),
}


def list_events(
	role,
	q=None,
	module=None,
	channel=None,
	publish=None,
	translation=None,
	delivery=None,
	start=0,
	page_length=20,
):
	field_errors = {}
	for name, value in (
		("module", module),
		("channel", channel),
		("publish", publish),
		("translation", translation),
		("delivery", delivery),
	):
		if value and value not in FILTERS[name]:
			field_errors[name] = "Bilinmeyen değer."
	if start < 0:
		field_errors["start"] = "0 ya da büyük olmalı."
	if not 1 <= page_length <= 100:
		field_errors["page_length"] = "1 ile 100 arasında olmalı."
	if field_errors:
		raise errors.validation(field_errors=field_errors)
	events = []
	for ev in catalog.EVENTS:
		try:
			e, t = _load(ev["key"])
		except errors.ApiError:
			continue
		events.append((e, t))
	estimates = store.monthly_estimates([e.name for e, _t in events])
	rows = [event_out(e, t, role, estimates) for e, t in events]
	needle = _fold((q or "").strip())

	def keep(r):
		if needle and not any(needle in _fold(v) for v in (r["name"], r["key"], r["module"])):
			return False
		if module and r["category"] != module:
			return False
		if channel and r["channels"][channel] == "kapali":
			return False
		if publish == "yayinda" and r["publish"]["state"] == "taslak":
			return False
		if publish and publish != "yayinda" and r["publish"]["state"] != publish:
			return False
		if translation and translation not in r["langs"].values():
			return False
		if delivery and r["delivery"] != delivery:
			return False
		return True

	matched = [r for r in rows if keep(r)]
	stats = {
		"total": len(matched),
		"email": 0,
		"push": 0,
		"sms": 0,
		"published": 0,
		"draft": 0,
		"pendingDraft": 0,
		"missingLang": 0,
	}
	for r in matched:
		for ch in ("email", "push", "sms"):
			if r["channels"][ch] != "kapali":
				stats[ch] += 1
		if r["publish"]["state"] == "taslak":
			stats["draft"] += 1
		else:
			stats["published"] += 1
		if r["publish"]["state"] == "yayinda-taslak":
			stats["pendingDraft"] += 1
		if any(v != "hazir" for v in r["langs"].values()):
			stats["missingLang"] += 1
	return {
		"events": matched[start : start + page_length],
		"total": len(matched),
		"stats": stats,
		"template_role": role,
	}


def get_event(role, key):
	e, t = _load(key)
	return event_out(e, t, role, store.monthly_estimates([key]))


def get_template(role, key):
	e, t = _load(key)
	published, _v, _s = store.published_content(key)
	return {
		"event": event_out(e, t, role, store.monthly_estimates([key])),
		"variables": catalog.variables_for(key),
		"required_by_channel": catalog.required_for(key),
		# Koşul değişkeni doğruysa o dalın kanal bazlı zorunluları (ör. başvuru sonucu iki dalı).
		"conditional_required": catalog.conditional_for(key),
		"draft": t.draft,
		"published": published,
		"revision": e.revision,
		"saved_at": str(t.saved_at) if t.saved_at else None,
		"saved_by": t.saved_by or None,
		"template_role": role,
	}


def validate(key):
	e, t = _load(key)
	return validation.validate_all(
		key, e.channels, t.translation_states, t.draft, preferences.settings()["sms_currency_as_text"]
	)


def list_versions(key, start=0, page_length=20):
	if start < 0 or not 1 <= page_length <= 100:
		raise errors.validation(field_errors={"page_length": "1 ile 100 arasında olmalı."})
	e, t = _load(key)
	live = store.published_version_number(t)
	counts = store.send_counts(key)
	rows = frappe.get_all(
		store.VERSION,
		filters={"event": key},
		fields=["version", "created_by", "created_at", "note"],
		order_by="version desc",
		start=start,
		page_length=page_length,
	)
	total = frappe.db.count(store.VERSION, {"event": key})
	versions = [
		{
			"version": int(r.version),
			"status": "live" if int(r.version) == live else "old",
			"created_at": str(r.created_at),
			"created_by": r.created_by or "",
			"note": r.note or "",
			"send_count": counts.get(int(r.version), 0),
		}
		for r in rows
	]
	return {"versions": versions, "total": total}


def get_version(key, version):
	store.load_event(key)
	row = frappe.db.get_value(
		store.VERSION,
		{"event": key, "version": int(version)},
		["content", "version", "translation_states"],
		as_dict=True,
	)
	if not row:
		raise errors.not_found(f"{key} v{version}")
	return {
		"content": store._json(row.content, store.empty_content()),
		"version": int(row.version),
		"langs": {lang: store._json(row.translation_states, {}).get(lang, "eksik") for lang in catalog.LANGS},
	}


# ── Yazma ─────────────────────────────────────────────────────────────────


def _receipt(key, revision, draft):
	t = store.load_template(key)
	return {"revision": revision, "saved_at": str(t.saved_at), "saved_by": t.saved_by, "draft": draft}


def _write_draft(key, event, template, draft, extra=None):
	revision = store.bump(key, event)
	values = {
		"draft": json.dumps(draft, ensure_ascii=False),
		"draft_changed": 1,
		"saved_by": frappe.session.user,
		"saved_at": now_datetime(),
		"representative": 0,
		# Onay isteği yalnız istendiği revizyon için geçerli; içerik değişince düşer.
		"review_state": None,
		"review_revision": 0,
		"review_requested_by": None,
	}
	values.update(extra or {})
	store.save_template_fields(key, values)
	return revision


def _apply_change(key, draft, channel, lang, fields):
	if channel not in catalog.CHANNELS:
		raise errors.validation(field_errors={"channel": "Bilinmeyen kanal."})
	if lang not in catalog.LANGS:
		raise errors.validation(field_errors={"lang": "Bilinmeyen dil."})
	try:
		normalized = validation.normalize_fields(channel, fields)
	except validation.FieldError as e:
		raise errors.validation(field_errors={f"{channel}.{lang}.{k}": v for k, v in e.field_errors.items()})
	draft.setdefault(channel, {})[lang] = normalized


def save_draft(key, channel, lang, fields, revision):
	event, template = store.lock(key, revision)
	draft = copy.deepcopy(template.draft)
	_apply_change(key, draft, channel, lang, fields)
	return _receipt(key, _write_draft(key, event, template, draft), draft)


def save_draft_bulk(key, changes, revision):
	if not isinstance(changes, list) or not 1 <= len(changes) <= 16:
		raise errors.validation(field_errors={"changes": "1 ile 16 arasında değişiklik gönderin."})
	seen = set()
	for c in changes:
		if not isinstance(c, dict) or set(c) - {"channel", "lang", "fields"}:
			raise errors.validation(
				field_errors={"changes": "Her değişiklik yalnız channel, lang, fields taşır."}
			)
		pair = (c.get("channel"), c.get("lang"))
		if pair in seen:
			raise errors.validation(field_errors={"changes": f"Tekrarlanan kanal/dil: {pair[0]}/{pair[1]}"})
		seen.add(pair)
	event, template = store.lock(key, revision)
	draft = copy.deepcopy(template.draft)
	for c in changes:
		_apply_change(key, draft, c.get("channel"), c.get("lang"), c.get("fields"))
	# Tek transaction, tek revizyon artışı.
	return _receipt(key, _write_draft(key, event, template, draft), draft)


def restore_version(key, version, revision):
	event, template = store.lock(key, revision)
	content = get_version(key, version)["content"]
	return _receipt(key, _write_draft(key, event, template, content), content)


def set_translation_state(key, lang, state, revision):
	if lang not in catalog.LANGS or state not in catalog.TRANSLATION_STATES:
		raise errors.validation(field_errors={"lang": "Bilinmeyen dil ya da durum."})
	event, template = store.lock(key, revision)
	states = dict(template.translation_states)
	states[lang] = state
	new = store.bump(key, event)
	store.save_template_fields(
		key,
		{
			"translation_states": json.dumps(states),
			"saved_by": frappe.session.user,
			"saved_at": now_datetime(),
		},
	)
	return {"langs": {lg: states.get(lg, "eksik") for lg in catalog.LANGS}, "revision": new}


def publish(key, revision):
	event, template = store.lock(key, revision)
	result = validation.validate_all(
		key,
		event.channels,
		template.translation_states,
		template.draft,
		preferences.settings()["sms_currency_as_text"],
	)
	if result["blocking"]:
		raise errors.validation(
			blocking=result["blocking"],
			warnings=result["warnings"],
			message="Yayını engelleyen sorunlar var.",
		)
	number = store.max_version(key) + 1
	note = (
		"Onay isteğinden yayınlandı"
		if template.review_state == "onay-bekliyor" and template.review_revision == event.revision
		else ""
	)
	name = store.insert_version(key, number, template.draft, template.translation_states, note)
	new = store.bump(key, event)
	now = now_datetime()
	store.save_template_fields(
		key,
		{
			"published_version": name,
			"draft_changed": 0,
			"review_state": None,
			"review_revision": 0,
			"review_requested_by": None,
			"saved_by": frappe.session.user,
			"saved_at": now,
		},
	)
	return {"version": number, "published_at": str(now), "revision": new}


def request_publish(key, revision):
	event, template = store.lock(key, revision)
	result = validation.validate_all(key, event.channels, template.translation_states, template.draft)
	if result["blocking"]:
		raise errors.validation(blocking=result["blocking"], warnings=result["warnings"])
	store.save_template_fields(
		key,
		{
			"review_state": "onay-bekliyor",
			"review_revision": event.revision,
			"review_requested_by": frappe.session.user,
		},
	)
	return {"state": "onay-bekliyor", "revision": event.revision}


def save_event_channels(role, key, channels, defaults, delivery, revision):
	field_errors = {}
	if (
		not isinstance(channels, dict)
		or set(channels) != set(catalog.CHANNELS)
		or any(v not in catalog.CHANNEL_STATES for v in channels.values())
	):
		field_errors["channels"] = "Dört kanalın her biri zorunlu / secmeli / kapali olmalı."
	if not isinstance(defaults, dict) or any(
		k not in catalog.USER_CHANNELS or not isinstance(v, bool) for k, v in defaults.items()
	):
		field_errors["defaults"] = "Yalnız email/push/sms için true/false."
	if delivery not in catalog.DELIVERY:
		field_errors["delivery"] = "aninda ya da ozetlenebilir olmalı."
	if field_errors:
		raise errors.validation(field_errors=field_errors)
	for ch, locked in catalog.STRUCTURAL_LOCKS.get(key, {}).items():
		if channels[ch] != locked:
			raise errors.validation(
				field_errors={f"channels.{ch}": "Bu olayda bu kanal yapısal olarak kilitli."}
			)
	if all(v == "kapali" for v in channels.values()):
		raise errors.validation(field_errors={"channels": "En az bir kanal açık olmalı."})
	event, template = store.lock(key, revision)
	published, version, _s = store.published_content(key)
	if version:
		blocking = []
		for ch in catalog.CHANNELS:
			opening = event.channels.get(ch, "kapali") == "kapali" and channels[ch] != "kapali"
			if opening and not ((published or {}).get(ch) or {}).get(catalog.SOURCE_LANG):
				blocking.append(validation.issue("empty_required_field", ch, "tr", catalog.PRIMARY_FIELD[ch]))
		if blocking:
			raise errors.validation(
				blocking=blocking, message="Yeni açılan kanalda yayınlanmış TR içerik yok."
			)
	clean_defaults = {
		ch: bool(defaults.get(ch, True)) for ch in catalog.USER_CHANNELS if channels[ch] == "secmeli"
	}
	new = store.bump(key, event)
	store.save_event_fields(
		key,
		{
			"channels": json.dumps(channels),
			"defaults": json.dumps(clean_defaults),
			"delivery": delivery,
			"mandatory": int(catalog.mandatory_of(channels)),
		},
	)
	store.save_template_fields(key, {"saved_by": frappe.session.user, "saved_at": now_datetime()})
	_cancel_closed(key, event.channels, channels)
	e, t = _load(key)
	assert e.revision == new
	return event_out(e, t, role, store.monthly_estimates([key]))


def _cancel_closed(key, old, new):
	"""Kapatılan kanalın bekleyen gönderimleri iptal edilir (worker da gönderimde yeniden bakar)."""
	from tradehub_core.notifications import dispatch

	closed = [ch for ch in catalog.CHANNELS if old.get(ch) != "kapali" and new[ch] == "kapali"]
	if not closed:
		return
	for name in frappe.get_all(
		store.DELIVERY,
		filters={"event": key, "channel": ["in", closed], "status": ["in", list(dispatch.PENDING)]},
		pluck="name",
	):
		dispatch._finish(name, "cancelled", error_code="CHANNEL_CLOSED")
