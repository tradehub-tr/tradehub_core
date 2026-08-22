"""Medya kimliği, teslimat adresi ve indexlenebilir bağlam için tek resolver."""

from __future__ import annotations

import mimetypes
from urllib.parse import urljoin, urlsplit

import frappe


def _clean(value: str | None) -> str:
	return str(value or "").split("?")[0].strip()


def _absolute(value: str, site_url: str) -> str:
	if not value:
		return ""
	if value.startswith(("http://", "https://")):
		return value
	parts = urlsplit(site_url)
	return urljoin(f"{parts.scheme}://{parts.netloc}/", value.lstrip("/"))


def identity_for(file_url: str, *, site_url: str = "") -> dict[str, str]:
	"""Delivery URL'den kararlı asset kimliğini çöz.

	Motor kaydı varsa ``Media Asset.name`` kanonik kimliktir. Legacy dosyada
	``File.name`` kullanılır; dosya adı/SEO slug değişse bile DocType name
	değişmez. ``stable_url`` bir kimlik URI'sidir, indexlenebilir sayfa olduğu
	iddiası taşımaz; canonical context ayrı çözülür.
	"""
	url = _clean(file_url)
	if not url:
		return {}
	file_row = frappe.db.get_value(
		"File",
		{"file_url": url},
		["name", "file_url", "file_name", "file_type", "creation", "modified"],
		as_dict=True,
	) or {}
	asset = {}
	if file_row and frappe.db.table_exists("Media Asset"):
		asset = frappe.db.get_value(
			"Media Asset", {"source_file": file_row.get("name")},
			["name", "asset_key", "media_type", "state", "published_at"], as_dict=True,
		) or {}
	identity = asset.get("name") or file_row.get("name") or ""
	origin = site_url or frappe.utils.get_url()
	delivery = _absolute(url, origin)
	landing = _absolute(f"/media/{identity}", origin) if identity else delivery
	encoding_format = (
		mimetypes.guess_type(file_row.get("file_name") or url)[0]
		or file_row.get("file_type")
		or ""
	)
	return {
		"asset_id": identity,
		"asset_key": asset.get("asset_key") or "",
		"identity_uri": f"media:{identity}" if identity else "",
		"stable_url": landing,
		"original_url": delivery,
		"delivery_url": delivery,
		"file_name": file_row.get("file_name") or "",
		"encoding_format": encoding_format,
		"date_created": str(file_row.get("creation") or ""),
		"date_modified": str(file_row.get("modified") or ""),
		"date_published": str(asset.get("published_at") or ""),
		"asset_state": asset.get("state") or "",
		"media_type": asset.get("media_type") or "",
	}


def canonical_context(
	*,
	ref_doctype: str = "",
	ref_name: str = "",
	context_doctype: str = "",
	context_name: str = "",
	site_url: str = "",
) -> dict[str, str]:
	"""Raw file'dan ayrı indexlenebilir kullanım sayfasını çöz."""
	dt = context_doctype or ref_doctype
	name = context_name or ref_name
	if dt == "Listing Image" and name:
		parent = frappe.db.get_value("Listing Image", name, "parent")
		if parent:
			dt, name = "Listing", parent
	path = ""
	if dt == "Listing" and name:
		slug = frappe.db.get_value("Listing", name, "slug") or ""
		path = f"/urun/{slug}" if slug else ""
	elif dt == "Product Category" and name:
		slug = frappe.db.get_value("Product Category", name, "url_slug") or ""
		path = f"/kategori/{slug}" if slug else ""
	elif dt == "Brand" and name:
		slug = frappe.db.get_value("Brand", name, "slug") or ""
		path = f"/marka/{slug}" if slug else ""
	origin = site_url or frappe.utils.get_url()
	return {"doctype": dt, "name": name, "canonical_url": _absolute(path, origin)}


def resolve(file_url: str, **context) -> dict[str, str]:
	return {**identity_for(file_url, site_url=context.get("site_url", "")), **canonical_context(**context)}
