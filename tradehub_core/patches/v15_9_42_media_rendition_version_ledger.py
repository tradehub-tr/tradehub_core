# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""T-063/T-064 — version-bound Media Rendition and exact-output ledger.

Expand first (nullable columns), then backfill every legacy row from its
canonical immutable URL.  Older shard-style URLs fall back to the asset's
active version only when it exists.  Hash/signature failures leave the ledger
columns empty rather than inventing evidence; the patch is idempotent and a
later run can fill them after storage is restored.
"""

from __future__ import annotations

import os
from typing import Any

import frappe
from frappe import _
from frappe.utils.file_manager import get_files_path

from tradehub_core.media.rendition_ledger import (
	engine_signature,
	file_sha256,
	rendition_key,
	version_hash_from_url,
)

DOCTYPE = "Media Rendition"


def execute() -> dict[str, Any]:
	if not frappe.reload_doc("tradehub_core", "doctype", "media_rendition"):
		frappe.throw(_("Media Rendition DocType yüklenemedi."))
	if not frappe.db.table_exists(DOCTYPE):
		frappe.throw(_("Media Rendition tablosu oluşturulamadı."))

	updated = 0
	ledgered = 0
	rows = frappe.get_all(
		DOCTYPE,
		fields=[
			"name",
			"asset",
			"version_hash",
			"profile",
			"width",
			"format",
			"rendition_key",
			"file_url",
			"output_sha256",
			"engine_signature",
		],
		limit_page_length=0,
	)
	for row in rows:
		values = _backfill_values(dict(row))
		if not values:
			continue
		frappe.db.set_value(DOCTYPE, row["name"], values, update_modified=False)
		updated += 1
		ledgered += int(bool(values.get("output_sha256") and values.get("engine_signature")))

	frappe.db.commit()
	return {"doctype": DOCTYPE, "updated": updated, "ledgered": ledgered}


def _backfill_values(row: dict[str, Any]) -> dict[str, Any]:
	version_hash = str(row.get("version_hash") or "") or version_hash_from_url(row.get("file_url"))
	if not version_hash:
		version_hash = str(frappe.db.get_value("Media Asset", row["asset"], "active_version") or "")
	values: dict[str, Any] = {}
	if version_hash and not row.get("version_hash"):
		values["version_hash"] = version_hash

	output_hash = str(row.get("output_sha256") or "")
	path = _disk_path(str(row.get("file_url") or ""))
	if not output_hash and path and os.path.isfile(path):
		output_hash = file_sha256(path)
		values["output_sha256"] = output_hash

	signature = str(row.get("engine_signature") or "")
	if output_hash and not signature:
		engine_version = (
			frappe.db.get_value("Media Version", version_hash, "engine_version") if version_hash else None
		)
		values["engine_signature"] = engine_signature(
			engine_version=str(engine_version or "legacy"),
			version_hash=version_hash,
			profile=str(row.get("profile") or ""),
			width=int(row.get("width") or 0),
			fmt=str(row.get("format") or ""),
			output_sha256=output_hash,
		)

	new_key = rendition_key(
		str(row.get("asset") or ""),
		version_hash,
		str(row.get("profile") or ""),
		int(row.get("width") or 0),
		str(row.get("format") or ""),
	)
	if str(row.get("rendition_key") or "") != new_key:
		values["rendition_key"] = new_key
	return values


def _disk_path(file_url: str) -> str | None:
	if not file_url.startswith("/files/"):
		return None
	return os.path.join(get_files_path(is_private=0), file_url.removeprefix("/files/"))
