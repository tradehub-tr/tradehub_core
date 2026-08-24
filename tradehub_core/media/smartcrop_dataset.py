"""T-014 gerçek ürün görsellerinden kimliksiz insan etiketleme seti üretimi.

Bu modül Frappe sınırındadır; saf smartcrop algoritması ``pipeline/core``
altında Frappe import etmez. Dışarı yalnız içerik hash'i, ölçü ve genel SCxxxx
kimliği çıkar; dosya adı, Listing adı ve satıcı bilgisi manifestte yer almaz.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_public_path(file_url: str, public_files: Path) -> Path | None:
	url = str(file_url or "")
	if not url.startswith("/files/") or ".." in url:
		return None
	candidate = (public_files / url.removeprefix("/files/")).resolve()
	try:
		candidate.relative_to(public_files.resolve())
	except ValueError:
		return None
	return candidate if candidate.is_file() else None


def export_labeling_dataset(output_dir: str, limit: int = 50) -> dict[str, Any]:
	"""Listing primary_image kayıtlarından ``limit`` tekil, gerçek görsel çıkar.

	``bench --site ... execute`` ile çağrılır. Çıktı dizini bilinçli olarak repo
	``.gitignore``undaki ``.smartcrop-work/`` olmalıdır; canlı ürün görselleri
	kaynak kontrolüne eklenmez.
	"""
	import frappe
	from PIL import Image

	limit = int(limit)
	if limit < 50 or limit > 200:
		raise ValueError("T-014 örnek sayısı 50..200 aralığında olmalıdır")
	root = Path(output_dir).expanduser().resolve()
	root.mkdir(parents=True, exist_ok=True)
	images_dir = root / "images"
	images_dir.mkdir(parents=True, exist_ok=True)
	public_files = Path(frappe.get_site_path("public", "files")).resolve()

	rows = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Listing",
			"attached_to_field": "primary_image",
			"is_private": 0,
		},
		fields=["file_url", "file_size"],
		order_by="creation asc",
		limit_page_length=max(limit * 20, 1000),
	)

	seen: set[str] = set()
	items: list[dict[str, Any]] = []
	for row in rows:
		source = _safe_public_path(row.file_url, public_files)
		if source is None:
			continue
		try:
			raw_hash = hashlib.sha256(source.read_bytes()).hexdigest()
			if raw_hash in seen:
				continue
			with Image.open(source) as image:
				image.seek(0)
				width, height = image.size
				fmt = str(image.format or "").lower()
				animated = bool(getattr(image, "is_animated", False))
		except Exception:
			continue
		if animated or width < 96 or height < 96 or fmt not in {"jpeg", "png", "webp"}:
			continue
		seen.add(raw_hash)
		index = len(items) + 1
		ext = ".jpg" if fmt == "jpeg" else f".{fmt}"
		name = f"SC{index:04d}{ext}"
		shutil.copyfile(source, images_dir / name)
		items.append(
			{
				"id": f"SC{index:04d}",
				"image": f"images/{name}",
				"sha256": raw_hash,
				"width": int(width),
				"height": int(height),
				"human_focal": None,
				"background": None,
			}
		)
		if len(items) == limit:
			break
	if len(items) < limit:
		raise RuntimeError(f"yalnız {len(items)} tekil Listing primary image bulundu; gereken={limit}")

	manifest = {
		"schema_version": "1.0.0",
		"task": "T-014",
		"created_at": datetime.now(timezone.utc).isoformat(),
		"source": "live Listing.primary_image; identifiers stripped; public files only",
		"human_labels": 0,
		"label_status": "pending_human_clicks",
		"items": items,
	}
	manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
	(root / "manifest.json").write_bytes(manifest_bytes)

	app_root = Path(frappe.get_app_path("tradehub_core")).parent
	template = app_root / "prototypes" / "smartcrop" / "annotate.html"
	if not template.is_file():
		raise FileNotFoundError(f"etiketleme aracı yok: {template}")
	shutil.copyfile(template, root / "annotate.html")
	return {
		"ok": True,
		"count": len(items),
		"output_dir": str(root),
		"manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
		"identifiers_exported": False,
	}


__all__ = ["export_labeling_dataset"]
