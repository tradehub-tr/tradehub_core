"""T-040 — install missing Phase-4 DocTypes and project canonical policies.

The JSON files under ``media/pipeline/policy/slots`` remain the source of
truth.  This patch is repeatable: schema reloads are idempotent, profiles are
upserted by their deterministic key, and each policy projection is replaced
from the same canonical input on every run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import frappe
from frappe import _

from tradehub_core.media.pipeline.policy import SLOT_DIR
from tradehub_core.patches.v15_9_23_media_profile_seed import execute as seed_profiles

_DOCTYPES: tuple[tuple[str, str], ...] = (
	("media_policy_profile", "Media Policy Profile"),
	("media_content_rule", "Media Content Rule"),
	("media_policy", "Media Policy"),
	("media_source", "Media Source"),
)

_JSON_FIELDS: tuple[str, ...] = (
	"roles",
	"bound_to",
	"accept",
	"require",
	"master",
	"quality",
	"on_violation",
	"messages",
	"sources",
)


def execute() -> dict[str, Any]:
	loaded: list[str] = []
	for folder, doctype in _DOCTYPES:
		if not frappe.reload_doc("tradehub_core", "doctype", folder, force=True):
			frappe.throw(_("DocType şeması yüklenemedi: {0}").format(doctype))
		loaded.append(doctype)

	missing = [doctype for _, doctype in _DOCTYPES if not frappe.db.table_exists(doctype)]
	if missing:
		frappe.throw(_("Faz 4 DocType tabloları oluşmadı: {0}").format(", ".join(missing)))

	profile_result = seed_profiles()
	policy_result = _seed_policies()
	frappe.db.commit()
	return {"loaded": loaded, "profiles": profile_result, "policies": policy_result}


def _canonical(value: Any) -> str:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> str | None:
	return None if value is None else _canonical(value)


def _policy_fields(path: Path, raw: dict[str, Any]) -> dict[str, Any]:
	fields: dict[str, Any] = {
		"slot_key": str(raw["slot_key"]),
		"title": str(raw.get("title") or "")[:140],
		"description": str(raw.get("description") or ""),
		"schema_version": str(raw["schema_version"]),
		"status": str(raw.get("status") or "draft"),
		"source_file": str(path.relative_to(SLOT_DIR.parent.parent.parent)),
		"source_digest": hashlib.sha256(_canonical(raw).encode("utf-8")).hexdigest(),
	}
	for fieldname in _JSON_FIELDS:
		fields[fieldname] = _json_value(raw.get(fieldname))
	return fields


def _profile_rows(slot: str, raw: dict[str, Any]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for profile in raw.get("profiles") or ():
		name = str(profile.get("name") or "").strip()
		if not name:
			continue
		row: dict[str, Any] = {
			"profile": f"{slot}:{name}",
			"required": int(bool(profile.get("required", False))),
			"generation": str(profile.get("generation") or "eager"),
			"notes": str(profile.get("derived_from") or ""),
		}
		if profile.get("max_bytes") is not None:
			row["max_bytes"] = int(profile["max_bytes"])
		if profile.get("byte_reference"):
			row["byte_reference"] = str(profile["byte_reference"])[:140]
		rows.append(row)
	return rows


def _severity(action: str) -> str:
	if action == "reject":
		return "reject"
	if action in {"review", "manual_review"}:
		return "review"
	if action in {"warn", "auto_fix"}:
		return "warn"
	return "info"


def _content_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for rule in raw.get("content_rules") or ():
		action = str(rule.get("action") or "warn")
		rule_id = str(rule.get("rule") or "").strip()
		if not rule_id:
			continue
		rows.append(
			{
				"rule_id": rule_id,
				"metric": rule_id,
				"comparator": str(rule.get("comparator") or "gt"),
				"threshold": _json_value(rule.get("threshold")),
				"action": action,
				"severity": _severity(action),
				"message_key": str(rule.get("message_key") or "")[:64],
				"measured_on": str(rule.get("measured_on") or "")[:140],
				"source": str(rule.get("source") or ""),
			}
		)
	return rows


def _seed_policies() -> dict[str, int]:
	result = {"created": 0, "updated": 0}
	for path in sorted(SLOT_DIR.glob("*.json")):
		raw = json.loads(path.read_text(encoding="utf-8"))
		slot = str(raw["slot_key"])
		fields = _policy_fields(path, raw)
		if frappe.db.exists("Media Policy", slot):
			doc = frappe.get_doc("Media Policy", slot)
			result["updated"] += 1
		else:
			doc = frappe.new_doc("Media Policy")
			result["created"] += 1
		for fieldname, value in fields.items():
			doc.set(fieldname, value)
		doc.set("profiles", _profile_rows(slot, raw))
		doc.set("content_rules", _content_rows(raw))
		if doc.is_new():
			doc.insert(ignore_permissions=True)
		else:
			doc.save(ignore_permissions=True)
	return result
