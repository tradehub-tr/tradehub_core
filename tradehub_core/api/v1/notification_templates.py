"""Bildirim şablon yönetimi API'si (admin panel).

Sözleşme: `desing/bildirim-sablonlari-2026-10-02/BACKEND-API.openapi.json`. Okuma GET, yazma POST;
yanıt Frappe `message` zarfında. Beklenen hatalar durum kodlu `{error_code, …}` gövdesi döner.
Her uç sunucuda yetki denetler (`authz.require`); satıcı ve alıcı bu kayıtları okuyamaz.
"""

from __future__ import annotations

import json

import frappe

from tradehub_core.notifications import authz, errors, sendtest, templates


def _obj(value, name):
	"""Frappe form/JSON gövdesinden gelen nesneyi çöz; bozuk tipte 422."""
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			raise errors.validation(field_errors={name: "Geçerli JSON olmalı."})
	return value


def _int(value, name, minimum=0):
	try:
		number = int(value)
	except (TypeError, ValueError):
		raise errors.validation(field_errors={name: "Tam sayı olmalı."})
	if isinstance(value, bool) or number < minimum:
		raise errors.validation(field_errors={name: f"En az {minimum} olmalı."})
	return number


@frappe.whitelist(methods=["GET"])
@errors.guarded
def list_events(
	q=None, module=None, channel=None, publish=None, translation=None, delivery=None, start=0, page_length=20
):
	role = authz.require("goruntule")
	return templates.list_events(
		role,
		q,
		module,
		channel,
		publish,
		translation,
		delivery,
		_int(start, "start"),
		_int(page_length, "page_length", 1),
	)


@frappe.whitelist(methods=["GET"])
@errors.guarded
def get_event(key: str):
	return templates.get_event(authz.require("goruntule"), key)


@frappe.whitelist(methods=["GET"])
@errors.guarded
def get_template(key: str):
	return templates.get_template(authz.require("goruntule"), key)


@frappe.whitelist(methods=["GET"])
@errors.guarded
def validate(key: str):
	authz.require("goruntule")
	return templates.validate(key)


@frappe.whitelist(methods=["GET"])
@errors.guarded
def list_versions(key: str, start=0, page_length=20):
	authz.require("goruntule")
	return templates.list_versions(key, _int(start, "start"), _int(page_length, "page_length", 1))


@frappe.whitelist(methods=["GET"])
@errors.guarded
def get_version(key: str, version=None):
	authz.require("goruntule")
	return templates.get_version(key, _int(version, "version", 1))


@frappe.whitelist(methods=["POST"])
@errors.guarded
def save_event_channels(key: str, channels=None, defaults=None, delivery=None, revision=None):
	role = authz.require("kanal")
	return templates.save_event_channels(
		role,
		key,
		_obj(channels, "channels"),
		_obj(defaults, "defaults"),
		delivery,
		_int(revision, "revision"),
	)


@frappe.whitelist(methods=["POST"])
@errors.guarded
def save_draft(key: str, channel=None, lang=None, fields=None, revision=None):
	authz.require("duzenle")
	return templates.save_draft(key, channel, lang, _obj(fields, "fields"), _int(revision, "revision"))


@frappe.whitelist(methods=["POST"])
@errors.guarded
def save_draft_bulk(key: str, changes=None, revision=None):
	authz.require("duzenle")
	return templates.save_draft_bulk(key, _obj(changes, "changes"), _int(revision, "revision"))


@frappe.whitelist(methods=["POST"])
@errors.guarded
def publish(key: str, revision=None):
	authz.require("yayinla")
	return templates.publish(key, _int(revision, "revision"))


@frappe.whitelist(methods=["POST"])
@errors.guarded
def request_publish(key: str, revision=None):
	authz.require("duzenle")
	return templates.request_publish(key, _int(revision, "revision"))


@frappe.whitelist(methods=["POST"])
@errors.guarded
def set_translation_state(key: str, lang=None, state=None, revision=None):
	authz.require("duzenle")
	return templates.set_translation_state(key, lang, state, _int(revision, "revision"))


@frappe.whitelist(methods=["POST"])
@errors.guarded
def restore_version(key: str, version=None, revision=None):
	authz.require("yayinla")  # geçici kural: sürüme dönüş yalnız süper admin
	return templates.restore_version(key, _int(version, "version", 1), _int(revision, "revision"))


@frappe.whitelist(methods=["POST"])
@errors.guarded
def send_test(key: str, channel=None, lang=None, version=None, target=None, request_id=None):
	authz.require("test")
	return sendtest.send_test(key, channel, lang, version, target, request_id)
