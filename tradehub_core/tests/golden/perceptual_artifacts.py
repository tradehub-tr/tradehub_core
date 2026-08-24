"""Deterministic expected-image artifacts for the T-067 perceptual gate."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any

PREVIEW_SIZE = (256, 256)
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ARTIFACT_MANIFEST_MEMBER = "artifact-manifest.json"


def canonical_json_bytes(value: Any) -> bytes:
	return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def golden_contract_sha256(golden: Mapping[str, Any]) -> str:
	"""Hash semantic golden data without the archive's self-reference."""
	contract = dict(golden)
	contract.pop("preview_archive", None)
	return hashlib.sha256(canonical_json_bytes(contract)).hexdigest()


def _safe_component(value: Any) -> str:
	component = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
	if not component:
		raise ValueError("empty perceptual artifact path component")
	return component


def preview_member(fixture: str, row: Sequence[Any]) -> str:
	"""Return a stable, metadata-bound member name for a golden rendition."""
	profile, image_format, width, height = row[:4]
	return (
		f"previews/{_safe_component(fixture)}/"
		f"{_safe_component(profile)}-{_safe_component(image_format)}-{int(width)}x{int(height)}.webp"
	)


def rendition_preview(content: bytes) -> bytes:
	"""Decode a real rendition and place it on a fixed checkerboard preview."""
	from PIL import Image, ImageDraw

	with Image.open(io.BytesIO(content)) as source:
		source.seek(0)
		image = source.convert("RGBA")
	image.thumbnail(PREVIEW_SIZE, Image.Resampling.LANCZOS)

	canvas = Image.new("RGBA", PREVIEW_SIZE, "white")
	draw = ImageDraw.Draw(canvas)
	cell = 16
	for y in range(0, PREVIEW_SIZE[1], cell):
		for x in range(0, PREVIEW_SIZE[0], cell):
			if (x // cell + y // cell) % 2:
				draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#d1d5db")
	offset = ((PREVIEW_SIZE[0] - image.width) // 2, (PREVIEW_SIZE[1] - image.height) // 2)
	canvas.alpha_composite(image, dest=offset)

	buffer = io.BytesIO()
	canvas.convert("RGB").save(buffer, "WEBP", quality=88, method=6, exact=True)
	return buffer.getvalue()


def deterministic_zip_bytes(entries: Mapping[str, bytes]) -> bytes:
	"""Build byte-identical ZIPs: ordered names, fixed time/mode, no host metadata."""
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w") as archive:
		for name in sorted(entries):
			if name.startswith("/") or ".." in name.split("/"):
				raise ValueError(f"unsafe archive member: {name}")
			info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIMESTAMP)
			info.compress_type = zipfile.ZIP_STORED
			info.create_system = 3
			info.external_attr = 0o100644 << 16
			archive.writestr(info, entries[name])
	return buffer.getvalue()


__all__ = [
	"ARTIFACT_MANIFEST_MEMBER",
	"FIXED_ZIP_TIMESTAMP",
	"PREVIEW_SIZE",
	"canonical_json_bytes",
	"deterministic_zip_bytes",
	"golden_contract_sha256",
	"preview_member",
	"rendition_preview",
]
