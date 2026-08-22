"""Public, stable media identity landing page."""

from __future__ import annotations

import json
from html import escape

import frappe
from werkzeug.wrappers import Response

from tradehub_core.media import seo, seo_index, seo_urls
from tradehub_core.seo.schema_builder import build_image_object
from tradehub_core.seo.site_url import storefront_url


def _asset_file(asset_id: str) -> tuple[dict, dict]:
	asset = {}
	if frappe.db.table_exists("Media Asset"):
		asset = frappe.db.get_value(
			"Media Asset", {"name": asset_id},
			["name", "source_file", "media_type", "state"], as_dict=True,
		) or frappe.db.get_value(
			"Media Asset", {"asset_key": asset_id},
			["name", "source_file", "media_type", "state"], as_dict=True,
		) or {}
	file_name = asset.get("source_file") or asset_id
	file_row = frappe.db.get_value(
		"File", file_name,
		["name", "file_url", "file_name", "is_private", "file_size"], as_dict=True,
	) or {}
	return asset, file_row


def _sources(asset_name: str) -> tuple[list[dict], str]:
	if not asset_name:
		return [], ""
	rows = frappe.get_all(
		"Media Rendition", filters={"asset": asset_name, "benefit_gate_passed": 1},
		fields=["format", "width", "file_url"], order_by="width asc", limit_page_length=100,
	)
	by_format: dict[str, list[str]] = {}
	for row in rows:
		by_format.setdefault(row.format, []).append(f"{row.file_url} {int(row.width)}w")
	types = {"avif": "image/avif", "webp": "image/webp", "jpeg": "image/jpeg", "png": "image/png"}
	out = [
		{"type": types[fmt], "srcset": ", ".join(by_format[fmt])}
		for fmt in ("avif", "webp", "jpeg", "png") if by_format.get(fmt)
	]
	fallback = next((items[-1].split(" ", 1)[0] for fmt in ("jpeg", "webp", "png", "avif")
		if (items := by_format.get(fmt))), "")
	return out, fallback


@frappe.whitelist(allow_guest=True)
def asset_landing(asset_id: str):
	"""`/media/<asset-id>` için indexability-aware HTML response."""
	asset_id = str(asset_id or "").strip()[:140]
	if not asset_id or not all(ch.isalnum() or ch in "_-" for ch in asset_id):
		return Response("Not Found", status=404, mimetype="text/plain")
	asset, file_row = _asset_file(asset_id)
	if not file_row or not file_row.get("file_url"):
		return Response("Not Found", status=404, mimetype="text/plain")

	url = file_row.file_url
	decision = seo_index.decide(url, check_usage=True)
	status = int(decision.get("http_status") or 200)
	if status in (401, 404, 410):
		response = Response("Not Found" if status == 404 else "Unavailable", status=status, mimetype="text/plain")
		response.headers["X-Robots-Tag"] = decision["robots"]
		return response

	site = storefront_url().rstrip("/")
	identity = seo_urls.identity_for(url, site_url=site)
	fields = seo.fields_for(url)
	sources, fallback = _sources(asset.get("name") or "")
	content_url = fallback or identity.get("delivery_url") or url
	width = int(fields.get("width") or 0)
	height = int(fields.get("height") or 0)
	title = fields.get("title") or fields.get("alt") or file_row.file_name or "Media"
	description = fields.get("description") or fields.get("caption") or fields.get("alt") or title
	stable_url = identity.get("stable_url") or f"{site}/media/{asset_id}"
	image_fields = {**fields, "asset_url": stable_url, "content_url": identity.get("delivery_url") or url,
		"encoding_format": identity.get("encoding_format", ""), "date_created": identity.get("date_created", "")}
	schema = build_image_object(image_fields, site)

	source_html = "".join(
		f'<source type="{escape(s["type"], quote=True)}" srcset="{escape(s["srcset"], quote=True)}" sizes="100vw">'
		for s in sources[:-1]
	)
	fallback_srcset = sources[-1]["srcset"] if sources else ""
	img = (
		f'<img src="{escape(content_url, quote=True)}"'
		+ (f' srcset="{escape(fallback_srcset, quote=True)}" sizes="100vw"' if fallback_srcset else "")
		+ f' alt="{escape(fields.get("alt") or "", quote=True)}"'
		+ (f' width="{width}" height="{height}"' if width and height else "")
		+ ' decoding="async">'
	)
	robots = decision["robots"]
	html = f'''<!doctype html><html lang="{escape(fields.get("language") or "tr")}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description, quote=True)}">
<meta name="robots" content="{escape(robots, quote=True)}"><link rel="canonical" href="{escape(stable_url, quote=True)}">
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")}</script>
</head><body><main><h1>{escape(title)}</h1><picture>{source_html}{img}</picture>
{f'<p>{escape(fields.get("caption"))}</p>' if fields.get("caption") else ''}
</main></body></html>'''
	response = Response(html, status=200, mimetype="text/html")
	response.headers["Cache-Control"] = "public, max-age=300"
	response.headers["X-Robots-Tag"] = robots
	return response
