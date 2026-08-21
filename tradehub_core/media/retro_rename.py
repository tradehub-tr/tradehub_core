"""Medya retro-rename — eski tahmin edilebilir adların içerik-adresli ada taşınması.

Spec: docs/superpowers/specs/2026-08-21-medya-retro-rename-design.md

Üç aşama: `plan()` (salt okunur rapor) → `run_job()` (kuyruk; dosya başına
disk `os.replace` → `tabFile.file_url` → `refs.retarget` → `Media URL Redirect`
→ commit; hata → rollback + ters taşıma) → `run_rollback()` (job_key'in
satırlarını ters oynatır). Şablon `media/access_level.py::set_level`.

İdempotent: `is_legacy_name` yeni adı tanımaz → ikinci koşu aday bulmaz.
"""

from __future__ import annotations

import hashlib
import os
import re

import frappe
from frappe.utils import get_files_path

from tradehub_core.media import naming, refs

PUBLIC_PREFIX = "/files/"
MEDIA_PREFIX = "/files/media/"
REDIRECT_TTL_DAYS = 90
ERROR_RATE_STOP = 0.02
DEFAULT_BATCH = 200
PLAN_ITEM_LIMIT = 5000
PROGRESS_TTL = 3600

_HASHED_SHARDED = re.compile(r"^/files/[0-9a-f]{2}/[0-9a-f]{32}\.[a-z0-9]+$")


def is_legacy_name(file_url: str) -> bool:
	"""`/files/` altında, `/files/media/` dışında, hash+shard biçiminde OLMAYAN adres."""
	url = (file_url or "").split("?")[0]
	if not url.startswith(PUBLIC_PREFIX) or url.startswith(MEDIA_PREFIX):
		return False
	if ".." in url or url.endswith("/"):
		return False
	return not _HASHED_SHARDED.match(url)


def _disk_path(file_url: str) -> str:
	rel = file_url[len(PUBLIC_PREFIX) :]
	return os.path.join(get_files_path(is_private=0), rel)


def target_url(file_url: str) -> str:
	"""Diskteki GÜNCEL bayt'lardan hedef adres. Dosya yoksa `FileNotFoundError`."""
	path = _disk_path(file_url)
	with open(path, "rb") as f:
		content = f.read()
	hashed = naming._hashed_name(os.path.basename(file_url), content)
	return f"{PUBLIC_PREFIX}{naming._shard(hashed)}/{hashed}"


def _content_sha(path: str) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(1 << 20), b""):
			h.update(chunk)
	return h.hexdigest()


def legacy_urls() -> list[str]:
	"""`tabFile`'daki distinct public, hash-dışı adresler (scripts/media_stats.py ile aynı SQL)."""
	rows = frappe.db.sql(
		"""select file_url from `tabFile`
			where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
			  and left(file_url,13) <> '/files/media/'
			  and substring_index(substring_index(file_url,'/',-1),'.',1) not regexp '^[0-9a-f]{32}$'
			group by file_url order by file_url""",
		as_list=True,
	)
	return [r[0] for r in rows if is_legacy_name(r[0])]


def _ref_counts(url: str) -> tuple[int, int, int]:
	exact = readonly = embedded = 0
	for ref in refs.find(url):
		if ref["readonly"]:
			readonly += 1
		elif ref["exact"]:
			exact += 1
		else:
			embedded += 1
	return exact, readonly, embedded


def _inspect(url: str) -> dict:
	path = _disk_path(url)
	item = {
		"source_url": url,
		"target_url": None,
		"file_rows": frappe.db.count("File", {"file_url": url}),
		"refs_exact": 0,
		"refs_readonly": 0,
		"refs_embedded": 0,
		"orphan": False,
		"disk_missing": not os.path.isfile(path),
		"collision": False,
	}
	item["refs_exact"], item["refs_readonly"], item["refs_embedded"] = _ref_counts(url)
	item["orphan"] = not (item["refs_exact"] or item["refs_readonly"] or item["refs_embedded"])
	if item["disk_missing"]:
		return item
	item["target_url"] = target_url(url)
	hedef = _disk_path(item["target_url"])
	if os.path.isfile(hedef) and _content_sha(hedef) != _content_sha(path):
		item["collision"] = True
	return item


def plan(limit: int | None = None) -> dict:
	"""Salt okunur rapor. Hiçbir şey yazmaz.

	Sayaçlar (`renamable`, `orphans`, ...) HER ZAMAN tüm aday listesi üzerinden
	hesaplanır — `limit` yalnız dönen `items` listesinin boyutunu sınırlar.
	Aksi hâlde `truncated=True` olduğunda sayaçlar eksik raporlanırdı.
	`limit=0` → boş `items`, ama sayaçlar yine tam.
	"""
	urls = legacy_urls()
	cap = PLAN_ITEM_LIMIT if limit is None else min(max(0, limit), PLAN_ITEM_LIMIT)
	all_items = [_inspect(u) for u in urls]
	out = {
		"total": len(urls),
		"truncated": len(urls) > cap,
		"renamable": 0,
		"orphans": 0,
		"disk_missing": 0,
		"collisions": 0,
		"refs_exact": 0,
		"refs_readonly": 0,
		"refs_embedded": 0,
		"file_rows": 0,
		"items": all_items[:cap],
	}
	for it in all_items:
		out["orphans"] += int(it["orphan"])
		out["disk_missing"] += int(it["disk_missing"])
		out["collisions"] += int(it["collision"])
		out["refs_exact"] += it["refs_exact"]
		out["refs_readonly"] += it["refs_readonly"]
		out["refs_embedded"] += it["refs_embedded"]
		out["file_rows"] += it["file_rows"]
		if not it["disk_missing"] and not it["collision"]:
			out["renamable"] += 1
	return out
