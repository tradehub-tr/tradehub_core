#!/usr/bin/env python3
"""T-003 — politika slotları için salt-okunur medya dağılımı.

Bu betik aktif ``media/pipeline/policy/slots/*.json`` dosyalarındaki
``bound_to`` alanlarını tek doğruluk kaynağı olarak kullanır. Her slot için
eşsiz URL sayısını ve diskte bulunabilen dosyaların bayt/genişlik/yükseklik/
kısa-kenar/megapiksel p50-p90-p99 değerlerini üretir.

Veritabanına veya medya dosyalarına yazmaz. Yalnız ``MEDIA_SLOT_STATS_OUT``
verilmişse aggregate JSON çıktısını o yola yazar; çıktı dosya URL'lerini veya
belge adlarını içermez.

Frappe bağlamında kullanım::

    bench --site istoc.localhost console <<'PY'
    exec(open('apps/tradehub_core/scripts/media_slot_stats.py').read())
    main()
    PY
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import frappe
from PIL import Image


ROOT = Path(os.environ.get("MEDIA_SLOT_STATS_ROOT", Path(__file__).resolve().parents[1]))
POLICY_ROOT = Path(
	os.environ.get(
		"MEDIA_SLOT_POLICY_ROOT",
		ROOT / "tradehub_core" / "media" / "pipeline" / "policy" / "slots",
	)
)
LOCAL_PREFIXES = ("/files/", "/private/files/")


def _percentile(values: list[float], probability: float) -> float | None:
	"""NumPy'nin varsayılan doğrusal enterpolasyonuyla aynı persentil."""
	if not values:
		return None
	ordered = sorted(values)
	if len(ordered) == 1:
		return float(ordered[0])
	position = (len(ordered) - 1) * probability
	lower = math.floor(position)
	upper = math.ceil(position)
	if lower == upper:
		return float(ordered[lower])
	return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def _distribution(values: list[float], digits: int = 2) -> dict:
	def rounded(value: float | None) -> float | None:
		return None if value is None else round(value, digits)

	return {
		"count": len(values),
		"p50": rounded(_percentile(values, 0.50)),
		"p90": rounded(_percentile(values, 0.90)),
		"p99": rounded(_percentile(values, 0.99)),
		"max": rounded(max(values) if values else None),
	}


def _extract_urls(value, *, key_filter: str | None = None) -> set[str]:
	"""Attach değeri veya JSON içinden medya URL'lerini çıkar."""
	if value is None:
		return set()
	if isinstance(value, str):
		text = value.strip()
		if not text:
			return set()
		try:
			decoded = json.loads(text)
		except (TypeError, ValueError):
			return {text} if _looks_like_media_url(text) else set()
		return _extract_urls(decoded, key_filter=key_filter)
	if isinstance(value, list):
		out: set[str] = set()
		for item in value:
			out.update(_extract_urls(item, key_filter=key_filter))
		return out
	if isinstance(value, dict):
		out: set[str] = set()
		for key, item in value.items():
			if key_filter and str(key).lower() != key_filter:
				if isinstance(item, (dict, list)):
					out.update(_extract_urls(item, key_filter=key_filter))
				continue
			out.update(_extract_urls(item, key_filter=None if key_filter else None))
		return out
	return set()


def _looks_like_media_url(text: str) -> bool:
	if text.startswith(LOCAL_PREFIXES) or text.startswith(("http://", "https://")):
		return True
	return False


def _field_and_filter(binding: dict) -> tuple[str, str | None]:
	declared = str(binding["field"])
	field = declared.split(" (", 1)[0]
	key_filter = "logo" if "header.logo" in declared else None
	return field, key_filter


def _binding_urls(binding: dict) -> set[str]:
	field, key_filter = _field_and_filter(binding)
	rows = frappe.get_all(
		binding["doctype"],
		fields=[field],
		filters={field: ["is", "set"]},
		limit_page_length=0,
	)
	out: set[str] = set()
	for row in rows:
		out.update(_extract_urls(row.get(field), key_filter=key_filter))
	return out


def _normalise_url(url: str) -> str:
	if url.startswith(LOCAL_PREFIXES):
		return unquote(url.split("?", 1)[0].split("#", 1)[0])
	parsed = urlparse(url)
	if parsed.path.startswith(LOCAL_PREFIXES):
		return unquote(parsed.path)
	return url


def _disk_path(url: str) -> Path | None:
	url = _normalise_url(url)
	if url.startswith("/private/files/"):
		return Path(frappe.get_site_path("private", "files", url.removeprefix("/private/files/")))
	if url.startswith("/files/"):
		return Path(frappe.get_site_path("public", "files", url.removeprefix("/files/")))
	return None


def _video_dimensions(path: Path) -> tuple[int, int] | None:
	command = [
		"ffprobe",
		"-v",
		"error",
		"-select_streams",
		"v:0",
		"-show_entries",
		"stream=width,height",
		"-of",
		"json",
		str(path),
	]
	try:
		result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
		stream = (json.loads(result.stdout).get("streams") or [])[0]
		return int(stream["width"]), int(stream["height"])
	except (FileNotFoundError, IndexError, KeyError, ValueError, subprocess.SubprocessError):
		return None


def _probe_dimensions(path: Path) -> tuple[int, int, str] | None:
	try:
		with Image.open(path) as image:
			return int(image.width), int(image.height), "image"
	except Exception:
		video = _video_dimensions(path)
		if video:
			return video[0], video[1], "video"
	return None


def _measure_slot(policy: dict) -> dict:
	urls: set[str] = set()
	binding_counts: dict[str, int] = {}
	for binding in policy.get("bound_to") or []:
		binding_urls = _binding_urls(binding)
		binding_key = f"{binding['doctype']}.{_field_and_filter(binding)[0]}"
		binding_counts[binding_key] = len(binding_urls)
		urls.update(binding_urls)

	bytes_values: list[float] = []
	widths: list[float] = []
	heights: list[float] = []
	short_edges: list[float] = []
	megapixels: list[float] = []
	media_kinds: Counter[str] = Counter()
	extensions: Counter[str] = Counter()
	external = missing = unreadable = 0

	for raw_url in sorted(urls):
		path = _disk_path(raw_url)
		if path is None:
			external += 1
			continue
		if not path.is_file():
			missing += 1
			continue
		bytes_values.append(float(path.stat().st_size))
		extensions[path.suffix.lower().lstrip(".") or "none"] += 1
		dimensions = _probe_dimensions(path)
		if not dimensions:
			media_kinds["document_or_unknown"] += 1
			continue
		width, height, kind = dimensions
		media_kinds[kind] += 1
		widths.append(float(width))
		heights.append(float(height))
		short_edges.append(float(min(width, height)))
		megapixels.append(width * height / 1_000_000)

	return {
		"slot_key": policy["slot_key"],
		"bindings": binding_counts,
		"references": {
			"unique": len(urls),
			"local_existing": len(bytes_values),
			"external": external,
			"missing_on_disk": missing,
			"unreadable": unreadable,
		},
		"media_kinds": dict(sorted(media_kinds.items())),
		"extensions": dict(sorted(extensions.items())),
		"bytes": _distribution(bytes_values, digits=0),
		"width_px": _distribution(widths, digits=0),
		"height_px": _distribution(heights, digits=0),
		"short_edge_px": _distribution(short_edges, digits=0),
		"megapixels": _distribution(megapixels, digits=2),
	}


def collect() -> dict:
	policies = [json.loads(path.read_text()) for path in sorted(POLICY_ROOT.glob("*.json"))]
	return {
		"schema_version": 1,
		"measured_at": datetime.now(timezone.utc).isoformat(),
		"site": getattr(frappe.local, "site", None) or frappe.conf.get("db_name", ""),
		"privacy": "aggregate-only; no media URL or document name is emitted",
		"percentile_method": "linear interpolation",
		"slots": [_measure_slot(policy) for policy in policies],
	}


def main() -> dict:
	result = collect()
	output = json.dumps(result, ensure_ascii=False, indent=2)
	print(output)
	if target := os.environ.get("MEDIA_SLOT_STATS_OUT"):
		Path(target).write_text(output + "\n")
	return result
