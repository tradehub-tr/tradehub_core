"""Read-only upload status, separate from delivery/thumbnail generation.

Both queries retain Frappe permission filters. Missing and inaccessible keys
have the same null result. No lazy rendition, scan or reprocessing is started.
"""

from __future__ import annotations

import json

import frappe


@frappe.whitelist()
def get_status(files: str | list[str] | None = None) -> dict:
	if frappe.session.user in (None, "", "Guest"):
		frappe.throw(frappe._("Bu işlem için giriş yapmalısınız."), frappe.PermissionError)
	if isinstance(files, str):
		if len(files) > 20000:
			frappe.throw(frappe._("Dosya listesi çok uzun."))
		try:
			files = json.loads(files)
		except (TypeError, ValueError):
			frappe.throw(frappe._("Geçersiz dosya listesi."))
	if (
		not isinstance(files, list)
		or len(files) > 50
		or any(not isinstance(x, str) or len(x) > 512 for x in files)
	):
		frappe.throw(frappe._("Tek istekte en fazla 50 dosya sorgulanabilir."))
	keys = list(dict.fromkeys(files))
	result = dict.fromkeys(keys)
	if not keys:
		return {"files": result}
	rows = frappe.get_list(
		"File",
		or_filters=[["name", "in", keys], ["file_url", "in", keys]],
		fields=[
			"name", "file_name", "file_url", "file_size", "th_media_scan_status", "th_media_video_status"
		],
		order_by="creation desc",
		limit_page_length=0,
	)
	if not rows:
		return {"files": result}
	# Aynı içerik yeniden yüklenince yeni bir File satırı açılır ama Media Asset
	# ilk satıra bağlı kalır; yalnız sorulan satıra bakınca dosya hiç "hazır"
	# olmuyordu. Aynı adresli, bu kullanıcının OKUYABİLDİĞİ ikizler de katılır.
	twins = frappe.get_list(
		"File",
		filters={"file_url": ["in", list({r["file_url"] for r in rows if r.get("file_url")})]},
		fields=["name", "file_url"],
		limit_page_length=0,
	)
	# URL duplicates are included only when this user can read them. Never
	# broaden to get_all: that would leak another seller's pipeline state.
	try:
		assets = frappe.get_list(
			"Media Asset",
			filters={
				"source_file": ["in", list({r["name"] for r in rows} | {t["name"] for t in twins})],
				"state": ["not in", ["archived", "deleted"]],
			},
			fields=["source_file", "state"],
			limit_page_length=0,
		)
	except frappe.PermissionError:
		# Document-only users may read File but not Media Asset. Unknown is
		# deliberately not equivalent to a completed processing job.
		assets = []
	for key in keys:
		matching = [r for r in rows if r["name"] == key or r.get("file_url") == key]
		if not matching:
			continue
		row = matching[0]
		names = {r["name"] for r in matching}
		urls = {r.get("file_url") for r in matching if r.get("file_url")}
		asset_names = names | {t["name"] for t in twins if t["file_url"] in urls}
		scans = {r.get("th_media_scan_status") or "" for r in matching}
		videos = {r.get("th_media_video_status") or "" for r in matching}
		result[key] = {
			"file": row["name"],
			"file_name": row.get("file_name") or "",
			"file_url": row.get("file_url") or "",
			"bytes": row.get("file_size") or 0,
			"scan_status": next(
				(s for s in ("infected", "failed", "pending", "", "clean") if s in scans), ""
			),
			"video_status": next((s for s in ("failed", "processing", "ready") if s in videos), ""),
			"asset_states": [a["state"] for a in assets if a["source_file"] in asset_names],
		}
	return {"files": result}
