"""
OG image (1200x630) otomatik resize + fallback chain.

`resize_to_og_dimensions(src_path, out_path)` Pillow ile pure dosya işlemi —
Frappe runtime gerektirmez.

`ensure_og_image(record, source_field)` Frappe-aware wrapper:
  - record.og_image varsa → onu döner
  - record.<source_field> varsa → resize edip cache'e koyar, cache URL'i döner
  - hiçbiri yoksa → Website Settings.seo_og_image fallback
"""

import hashlib
import os
from collections.abc import Callable

from PIL import Image

OG_WIDTH = 1200
OG_HEIGHT = 630
CACHE_DIR_NAME = "og_cache"


def resize_to_og_dimensions(src_path: str, out_path: str) -> str:
	"""Source resmi 1200x630'a crop+resize eder (cover-style, en-boy bozulmaz).

	Geniş resimler → yüksekliğe göre ölç, ortadan crop.
	Dar resimler → genişliğe göre ölç, ortadan crop.
	"""
	with Image.open(src_path) as img:
		img = img.convert("RGB")
		src_w, src_h = img.size
		target_ratio = OG_WIDTH / OG_HEIGHT
		src_ratio = src_w / src_h

		if src_ratio > target_ratio:
			new_h = OG_HEIGHT
			new_w = int(round(src_w * (OG_HEIGHT / src_h)))
			img = img.resize((new_w, new_h), Image.LANCZOS)
			left = (new_w - OG_WIDTH) // 2
			img = img.crop((left, 0, left + OG_WIDTH, OG_HEIGHT))
		else:
			new_w = OG_WIDTH
			new_h = int(round(src_h * (OG_WIDTH / src_w)))
			img = img.resize((new_w, new_h), Image.LANCZOS)
			top = (new_h - OG_HEIGHT) // 2
			img = img.crop((0, top, OG_WIDTH, top + OG_HEIGHT))

		img.save(out_path, "JPEG", quality=85, optimize=True)

	return out_path


def _cache_filename_for(source_url: str) -> str:
	"""Source URL için deterministik cache dosyası adı."""
	digest = hashlib.md5(source_url.encode("utf-8")).hexdigest()[:12]
	return f"{digest}.jpg"


def _resolve_to_disk_path(url_or_path: str, public_files_root: str) -> str:
	"""`/files/foo.png` → `<public_files_root>/foo.png`; abs path varsa pass-through."""
	if not url_or_path:
		return ""
	if os.path.isabs(url_or_path) and os.path.exists(url_or_path):
		return url_or_path
	if url_or_path.startswith("/files/"):
		return os.path.join(public_files_root, url_or_path[len("/files/") :])
	return ""


def _produce_resized(
	source_url: str,
	*,
	public_files_root: str,
	cache_dir: str,
	on_error: Callable[[Exception], None] | None = None,
) -> str:
	"""Source'u 1200x630'a resize edip cache'e koyar, /files/.. URL döner.

	Pure-ish: tüm dependency'ler parametre. on_error callback hata logu için.
	"""
	src_path = _resolve_to_disk_path(source_url, public_files_root)
	if not src_path or not os.path.exists(src_path):
		return ""

	out_filename = _cache_filename_for(source_url)
	out_path = os.path.join(cache_dir, out_filename)

	if not os.path.exists(out_path):
		os.makedirs(cache_dir, exist_ok=True)
		try:
			resize_to_og_dimensions(src_path, out_path)
		except Exception as exc:
			if on_error:
				on_error(exc)
			return ""

	return f"/files/{CACHE_DIR_NAME}/{out_filename}"


# Frappe-aware wrapper -------------------------------------------------------


def ensure_og_image(record: dict, source_field: str = "main_image") -> str:
	"""OG image URL'ini garantile.

	Fallback chain:
		1. record["og_image"] (manuel yüklenmiş)
		2. record[source_field] → otomatik resize (cache'lenir)
		3. Website Settings.seo_og_image (site default)
	"""
	if record.get("og_image"):
		return record["og_image"]

	import frappe

	source = record.get(source_field)
	if source:
		public_files_root = frappe.get_site_path("public", "files")
		cache_dir = os.path.join(public_files_root, CACHE_DIR_NAME)

		def _log_error(exc):
			frappe.log_error(f"OG image resize failed: {exc}", "SEO og_image")

		result = _produce_resized(
			source,
			public_files_root=public_files_root,
			cache_dir=cache_dir,
			on_error=_log_error,
		)
		if result:
			return result

	ws = frappe.get_single("Website Settings")
	return ws.get("seo_og_image") or ""
