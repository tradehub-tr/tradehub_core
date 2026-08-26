"""Public, stable media identity landing page."""

from __future__ import annotations

import json
from html import escape

import frappe
from werkzeug.wrappers import Response

from tradehub_core.media import seo, seo_index, seo_urls, usage, watch_slug
from tradehub_core.seo.schema_builder import build_image_object
from tradehub_core.seo.site_url import storefront_url

#: İzleme sayfası indexlenemezken basılan sabit `robots` direktifi —
#: `seo_index._ret`'in noindex biçimiyle AYNI (tek yerde iki farklı string olmasın).
_WATCH_NOINDEX_ROBOTS = (
	f"noindex, follow, nosnippet, {seo_index.PREVIEW_NONE}, {seo_index.VIDEO_PREVIEW_NONE}"
)


def _asset_file(asset_id: str) -> tuple[dict, dict]:
	asset = {}
	if frappe.db.table_exists("Media Asset"):
		asset = (
			frappe.db.get_value(
				"Media Asset",
				{"name": asset_id},
				["name", "source_file", "media_type", "state"],
				as_dict=True,
			)
			or frappe.db.get_value(
				"Media Asset",
				{"asset_key": asset_id},
				["name", "source_file", "media_type", "state"],
				as_dict=True,
			)
			or {}
		)
	file_name = asset.get("source_file") or asset_id
	file_row = (
		frappe.db.get_value(
			"File",
			file_name,
			["name", "file_url", "file_name", "is_private", "file_size"],
			as_dict=True,
		)
		or {}
	)
	return asset, file_row


def _sources(asset_name: str) -> tuple[list[dict], str]:
	if not asset_name:
		return [], ""
	rows = frappe.get_all(
		"Media Rendition",
		filters={"asset": asset_name, "benefit_gate_passed": 1},
		fields=["format", "width", "file_url"],
		order_by="width asc",
		limit_page_length=100,
	)
	by_format: dict[str, list[str]] = {}
	for row in rows:
		by_format.setdefault(row.format, []).append(f"{row.file_url} {int(row.width)}w")
	types = {"avif": "image/avif", "webp": "image/webp", "jpeg": "image/jpeg", "png": "image/png"}
	out = [
		{"type": types[fmt], "srcset": ", ".join(by_format[fmt])}
		for fmt in ("avif", "webp", "jpeg", "png")
		if by_format.get(fmt)
	]
	fallback = next(
		(
			items[-1].split(" ", 1)[0]
			for fmt in ("jpeg", "webp", "png", "avif")
			if (items := by_format.get(fmt))
		),
		"",
	)
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
		response = Response(
			"Not Found" if status == 404 else "Unavailable", status=status, mimetype="text/plain"
		)
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
	image_fields = {
		**fields,
		"asset_url": stable_url,
		"content_url": identity.get("delivery_url") or url,
		"encoding_format": identity.get("encoding_format", ""),
		"date_created": identity.get("date_created", ""),
	}
	schema = build_image_object(image_fields, site)
	schema_json = json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")

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
	caption = fields.get("caption") or ""
	caption_html = f"<p>{escape(caption)}</p>" if caption else ""
	html = f'''<!doctype html><html lang="{escape(fields.get("language") or "tr")}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description, quote=True)}">
<meta name="robots" content="{escape(robots, quote=True)}"><link rel="canonical" href="{escape(stable_url, quote=True)}">
<script type="application/ld+json">{schema_json}</script>
</head><body><main><h1>{escape(title)}</h1><picture>{source_html}{img}</picture>
{caption_html}
</main></body></html>'''
	response = Response(html, status=200, mimetype="text/html")
	response.headers["Cache-Control"] = "public, max-age=300"
	response.headers["X-Robots-Tag"] = robots
	return response


def _storefront_listings(file_url: str) -> list[dict]:
	"""Videonun bağlı olduğu, vitrinde görünen ilanlar — TEK sorgu (N+1 yasak).

	`usage.resolve` bağ dökümünü verir (kaç kaynakta, hangi ilanlarda); burada
	yalnız `Listing` bağları alınıp `storefront_visible` filtresiyle tek
	`get_all` çağrısında zenginleştirilir. Filtre boş küme için hiç sorgu
	açmaz — `resolve()` her çağrısı LIKE taraması yapan pahalı bir işlem.
	"""
	dokum = usage.resolve(file_url)
	adlar = sorted({
		u["name"] for u in dokum.get("usages", []) if u.get("doctype") == "Listing" and u.get("name")
	})
	if not adlar:
		return []
	return frappe.get_all(
		"Listing",
		filters={"name": ["in", adlar], "storefront_visible": 1},
		fields=["name", "slug", "title", "primary_image"],
	)


def watch_indexable(file_url: str) -> bool:
	"""İzleme sayfası indexlenebilir mi — W3 üçlüsü (spec: SEO kararı + poster + vitrin bağı).

	Üçü de sağlanmazsa video SİLİNMEZ, yalnız arama motoruna kapatılır
	(`get_watch_page`'in `robots: noindex` dalıyla aynı ilke — `seo_index`
	docstring'i: "private robots ile gizlenmez", burada tersi de geçerli:
	geçici olarak aranmaz olmak dosyayı silmez).
	"""
	url = (file_url or "").split("?")[0].strip()
	if not url:
		return False
	decision = seo_index.decide(url, check_usage=False)
	if not decision.get("indexable"):
		return False
	fields = seo.fields_for(url)
	if not fields.get("poster_url"):
		return False
	return bool(_storefront_listings(url))


def _video_sources(file_row: dict, url: str, mime: str) -> list[dict[str, str]]:
	"""Video kaynak listesi — asset'i varsa `_sources` (mevcut desen), yoksa ham adres.

	`_sources` görsel format haritasıyla (avif/webp/jpeg/png) çalışıyor; bir
	video asset'inin bugün eşleşen render'ı yoksa (henüz video rendition
	üretilmiyor) boş döner ve ham dosya adresine düşülür — motoru olmayan
	bir kaynak listesindense TEK gerçek adres göstermek yeğdir.
	"""
	asset_name = ""
	if frappe.db.table_exists("Media Asset"):
		asset_name = frappe.db.get_value("Media Asset", {"source_file": file_row.get("name")}, "name") or ""
	if asset_name:
		items, _fallback = _sources(asset_name)
		kaynaklar = []
		for item in items:
			ilk = (item.get("srcset") or "").split(",")[0].strip()
			src = ilk.split(" ")[0] if ilk else ""
			if src:
				kaynaklar.append({"src": src, "type": item["type"]})
		if kaynaklar:
			return kaynaklar
	return [{"src": url, "type": mime}]


def _watch_data(slug: str) -> dict:
	"""`/medya/v/<slug>` sayfa verisini HTTP'siz kurar — Task 3 resolver'ı bunu doğrudan çağırır.

	Slug'a ait kardeş `File` kayıtlarından İLK PUBLIC olanı çözülür (kardeşler
	aynı adrese işaret edebiliyor, `watch_slug` deseni). Bulunamayan ya da
	yalnız private kardeşleri olan slug `frappe.DoesNotExistError` fırlatır
	(HTTP 404) — private asset "sayfa yok" gibi davranır, `noindex` ile değil
	gerçek erişim reddiyle korunur (`seo_index` ilkesiyle aynı).
	"""
	slug = (slug or "").strip()
	kayitlar = (
		frappe.get_all(
			"File",
			filters={"th_media_slug": slug},
			fields=["name", "file_url", "file_name", "is_private"],
			order_by="creation asc",
		)
		if slug
		else []
	)
	file_row = next((k for k in kayitlar if not k.get("is_private") and k.get("file_url")), None)
	if not file_row:
		frappe.throw(frappe._("Video bulunamadı."), exc=frappe.DoesNotExistError)

	url = file_row["file_url"]
	fields = seo.fields_for(url)
	decision = seo_index.decide(url, check_usage=False)
	listings = _storefront_listings(url)
	indexable = bool(decision.get("indexable")) and bool(fields.get("poster_url")) and bool(listings)

	site = storefront_url()
	identity = seo_urls.identity_for(url, site_url=site)
	mime = identity.get("encoding_format") or ""
	sources = _video_sources(file_row, url, mime)
	canonical = f"{site}{watch_slug.watch_url(slug)}"

	return {
		"title": fields.get("title") or fields.get("alt") or file_row.get("file_name") or "",
		"caption": fields.get("caption") or "",
		"description": fields.get("description") or "",
		"transcript": fields.get("transcript") or "",
		"posterUrl": fields.get("poster_url") or "",
		"sources": sources,
		"captionsUrl": fields.get("captions_url") or "",
		"durationSec": fields.get("duration") or 0,
		"uploadDate": identity.get("date_created") or "",
		"license": {
			"creator": fields.get("creator") or "",
			"creatorType": fields.get("creator_type") or "",
			"creditText": fields.get("credit_text") or "",
			"copyrightNotice": fields.get("copyright_notice") or "",
			"licenseUrl": fields.get("license_url") or "",
			"acquireLicenseUrl": fields.get("acquire_license_url") or "",
			"usageRights": fields.get("usage_rights") or "",
			"rightsExpiresOn": fields.get("rights_expires_on") or "",
		},
		"listings": [
			{
				"slug": listing.get("slug") or "",
				"title": listing.get("title") or "",
				"image": listing.get("primary_image") or "",
			}
			for listing in listings
		],
		"indexable": indexable,
		"canonical": canonical,
		"robots": decision["robots"] if indexable else _WATCH_NOINDEX_ROBOTS,
	}


@frappe.whitelist(allow_guest=True)
def get_watch_page(slug: str) -> dict:
	"""`/medya/v/<slug>` için sayfa verisi — whitelist zarfı, mantık `_watch_data`'da.

	Bilinmeyen/private slug `frappe.DoesNotExistError` fırlatır (HTTP 404).
	"""
	return _watch_data(slug)
