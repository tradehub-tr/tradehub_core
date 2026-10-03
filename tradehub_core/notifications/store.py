"""Olay / şablon / sürüm deposu — revizyon kilitli yazmalar.

Eşzamanlılık: her yazma önce olay satırını `SELECT … FOR UPDATE` ile kilitler, revizyonu
kilit altında karşılaştırır ve aynı transaction içinde artırır. İki eşzamanlı istekte ikincisi
kilidi bekler, güncel revizyonu görür ve 409 alır (GET → kontrol → koşulsuz kayıt değil).
Olay revizyonu kanal kuralı, taslak, çeviri durumu, yayın ve sürüme dönüş için ORTAKTIR.
"""

from __future__ import annotations

import copy
import json

import frappe
from frappe.utils import now_datetime

from tradehub_core.notifications import catalog, errors

EVENT = "Platform Notification Event"
TEMPLATE = "Platform Notification Template"
VERSION = "Platform Notification Version"
DELIVERY = "Platform Notification Delivery"

EVENT_FIELDS = [
	"name",
	"category",
	"recipients",
	"channels",
	"defaults",
	"delivery",
	"mandatory",
	"revision",
	"modified",
]
TEMPLATE_FIELDS = [
	"name", "draft", "translation_states", "published_version", "draft_changed", "saved_by", "saved_at",
	"review_state", "review_revision", "representative",
]  # fmt: skip


class _Write:
	"""Bu modül dışından (ör. /api/resource) yönetim kayıtlarına yazmayı engelleyen bayrak."""

	def __enter__(self):
		frappe.flags.notification_store_write = True

	def __exit__(self, *exc):
		frappe.flags.notification_store_write = False


def writing() -> bool:
	return bool(
		frappe.flags.notification_store_write
		or frappe.flags.in_install
		or frappe.flags.in_migrate
		or frappe.flags.in_patch
	)


def _json(value, default):
	if value in (None, ""):
		return copy.deepcopy(default)
	if isinstance(value, dict | list):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return copy.deepcopy(default)


def empty_content() -> dict:
	return {ch: {lang: None for lang in catalog.LANGS} for ch in catalog.CHANNELS}


def load_event(key: str, for_update: bool = False) -> dict:
	if not catalog.get(key):
		raise errors.not_found(key)
	row = frappe.db.get_value(EVENT, key, EVENT_FIELDS, as_dict=True, for_update=for_update)
	if not row:
		raise errors.not_found(key)
	row.recipients = _json(row.recipients, [])
	row.channels = _json(row.channels, {})
	row.defaults = _json(row.defaults, {})
	row.revision = int(row.revision or 0)
	return row


def load_template(key: str, for_update: bool = False) -> dict:
	row = frappe.db.get_value(TEMPLATE, key, TEMPLATE_FIELDS, as_dict=True, for_update=for_update)
	if not row:
		raise errors.not_found(key)
	row.draft = _json(row.draft, empty_content())
	row.translation_states = _json(row.translation_states, {lang: "eksik" for lang in catalog.LANGS})
	return row


def lock(key: str, revision: int) -> tuple[dict, dict]:
	"""Olay + şablonu kilitler; revizyon eşleşmezse 409 (güncel taslak `theirs`)."""
	event = load_event(key, for_update=True)
	template = load_template(key, for_update=True)
	if int(revision) != event.revision:
		raise errors.conflict(event.revision, template.draft, template.saved_by, template.saved_at)
	return event, template


def bump(key: str, event: dict) -> int:
	new = event.revision + 1
	frappe.db.set_value(EVENT, key, "revision", new)
	return new


def published_version_number(template: dict) -> int:
	if not template.published_version:
		return 0
	return int(frappe.db.get_value(VERSION, template.published_version, "version") or 0)


def publish_state(template: dict) -> dict:
	version = published_version_number(template)
	if not version:
		return {"state": "taslak", "version": 0}
	return {"state": "yayinda-taslak" if template.draft_changed else "yayinda", "version": version}


def published_content(key: str) -> tuple[dict | None, int, dict]:
	"""Yayındaki içerik, sürüm no ve sürümün dil durumları (snapshot)."""
	ref = frappe.db.get_value(TEMPLATE, key, "published_version")
	if not ref:
		return None, 0, {}
	row = frappe.db.get_value(VERSION, ref, ["content", "version", "translation_states"], as_dict=True)
	if not row:
		return None, 0, {}
	return _json(row.content, empty_content()), int(row.version), _json(row.translation_states, {})


def monthly_estimates(keys: list[str]) -> dict:
	"""Son 30 günde sağlayıcıya teslim edilmiş gerçek gönderim sayısı; ölçüm yoksa None."""
	if not keys:
		return {}
	D = frappe.qb.DocType(DELIVERY)
	from frappe.query_builder.functions import Count

	since = frappe.utils.add_days(now_datetime(), -30)
	rows = (
		frappe.qb.from_(D)
		.select(D.event, Count(D.name).as_("n"))
		.where(D.event.isin(keys))
		.where(D.is_test == 0)
		.where(D.status.isin(["sent", "accepted", "captured"]))
		.where(D.creation >= since)
		.groupby(D.event)
	).run(as_dict=True)
	return {r.event: int(r.n) for r in rows}


def send_counts(key: str) -> dict:
	D = frappe.qb.DocType(DELIVERY)
	from frappe.query_builder.functions import Count

	rows = (
		frappe.qb.from_(D)
		.select(D.template_version, Count(D.name).as_("n"))
		.where(D.event == key)
		.where(D.is_test == 0)
		.where(D.status.isin(["sent", "accepted", "captured"]))
		.groupby(D.template_version)
	).run(as_dict=True)
	return {int(r.template_version or 0): int(r.n) for r in rows}


def save_template_fields(key: str, values: dict) -> None:
	with _Write():
		frappe.db.set_value(TEMPLATE, key, values)


def save_event_fields(key: str, values: dict) -> None:
	with _Write():
		frappe.db.set_value(EVENT, key, values)


def insert_version(key: str, version: int, content: dict, langs: dict, note: str) -> str:
	name = f"{key}::v{version}"
	with _Write():
		doc = frappe.get_doc(
			{
				"doctype": VERSION,
				"name": name,
				"event": key,
				"version": version,
				"content": json.dumps(content, ensure_ascii=False),
				"translation_states": json.dumps(langs),
				"note": note,
				"created_by": frappe.session.user,
				"created_at": now_datetime(),
			}
		)
		doc.flags.name_set = True
		# Yönetim kaydı yalnız bu modülden yazılır; kullanıcı yetkisi uçta denetlendi.
		doc.insert(ignore_permissions=True, set_name=name)
	return name


def max_version(key: str) -> int:
	V = frappe.qb.DocType(VERSION)
	from frappe.query_builder.functions import Max

	row = frappe.qb.from_(V).select(Max(V.version).as_("v")).where(V.event == key).run(as_dict=True)
	return int((row[0].v if row else 0) or 0)
