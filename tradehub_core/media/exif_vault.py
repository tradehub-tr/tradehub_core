"""Source EXIF/IPTC-like metadata retention with encrypted-at-rest payload."""

from __future__ import annotations

import hashlib
import io
import json
from typing import Any

import frappe

POLICY_VERSION = "public-strip-private-retain-v1"
GPS_IFD = 0x8825
ORIENTATION = 0x0112
DATETIME_ORIGINAL = 0x9003
MAX_JSON_BYTES = 64 * 1024


def _json_value(value: Any) -> Any:
	if value is None or isinstance(value, (bool, int, float, str)):
		return value
	if isinstance(value, bytes):
		return {"bytes_hex": value[:256].hex(), "truncated": len(value) > 256}
	if isinstance(value, dict):
		return {str(k): _json_value(v) for k, v in value.items()}
	if isinstance(value, (list, tuple)):
		return [_json_value(v) for v in value]
	return str(value)


def extract(source: bytes) -> dict[str, Any]:
	"""Read metadata without returning it to any public caller."""
	from PIL import ExifTags, Image

	with Image.open(io.BytesIO(source)) as image:
		exif = image.getexif()
		payload: dict[str, Any] = {}
		for tag, value in exif.items():
			payload[ExifTags.TAGS.get(tag, str(tag))] = _json_value(value)
		gps = {}
		try:
			gps = dict(exif.get_ifd(GPS_IFD)) if exif and GPS_IFD in exif else {}
		except Exception:
			gps = {}
		if gps:
			payload["GPSInfo"] = {
				ExifTags.GPSTAGS.get(tag, str(tag)): _json_value(value) for tag, value in gps.items()
			}
		raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
		if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
			raw = json.dumps({"truncated": True, "tag_names": sorted(payload)})
		return {
			"raw": raw,
			"has_exif": bool(payload),
			"has_gps": bool(gps),
			"orientation": int(exif.get(ORIENTATION, 1) or 1) if exif else 1,
			"captured_at": str(exif.get(DATETIME_ORIGINAL) or "").replace(":", "-", 2) if exif else "",
		}


def retain(asset: Any, source: bytes) -> bool:
	"""Upsert encrypted metadata for an asset. Empty EXIF is still recorded."""
	if not frappe.db.table_exists("Media Metadata Vault"):
		return False
	try:
		metadata = extract(source)
		existing = frappe.db.exists("Media Metadata Vault", asset.name)
		doc = frappe.get_doc("Media Metadata Vault", existing) if existing else frappe.new_doc("Media Metadata Vault")
		doc.asset = asset.name
		doc.source_file = asset.source_file
		doc.metadata_policy = POLICY_VERSION
		doc.has_exif = int(metadata["has_exif"])
		doc.has_gps = int(metadata["has_gps"])
		doc.orientation = metadata["orientation"]
		doc.captured_at = metadata["captured_at"] or None
		doc.metadata_encrypted = metadata["raw"]
		doc.metadata_sha256 = hashlib.sha256(metadata["raw"].encode("utf-8")).hexdigest()
		doc.save(ignore_permissions=True)
		return True
	except Exception:
		frappe.log_error(title="media EXIF vault", message=frappe.get_traceback())
		return False
