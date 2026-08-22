# Medya Retro-Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eski tahmin edilebilir adlı public medya dosyalarını (`/files/0505.jpg`) içerik-adresli shard'lı ada (`/files/ab/<sha256[:32]>.jpg`) taşıyan, referansları güncelleyen, 90 gün 301 köprüleyen, geri alınabilir ve admin panelden tek tuşla yürütülen bir migration aracı.

**Architecture:** Backend'de `media/retro_rename.py` (plan → apply → rollback; `access_level.set_level` deseni: disk `os.replace` önce, DB sonra, hata → ters taşıma), `Media URL Redirect` DocType + `page_renderer` hook ile tek-sorgu 301, günlük cron ile süre dolumu. Admin panelde `Sistem → Medya Optimizasyonu` ekranına `useMediaRetroRename` composable + `MediaRetroRenameCard` (Önizle → Onay → İlerleme → Geri al).

**Tech Stack:** Frappe v15 (Python 3.10+, tab indent, Ruff 110), MariaDB, Redis; Vue 3.5 `<script setup>` + vue-i18n; `node:test` + Vite SSR testleri; OpenAPI üreteci `scripts/gen_http_openapi.py` → `npm run sync:api`.

**Spec:** `docs/superpowers/specs/2026-08-21-medya-retro-rename-design.md`

## Global Constraints

- Python: **tab** girinti, satır ≤ 110, Ruff `E,F,W,I,B,UP`; type annotation zorunlu; `frappe.throw(_("..."))`; `except Exception:` yalnız `frappe.log_error` ile.
- `frappe.db.sql(f"...")` yalnız tablo/kolon `_WRITABLE` allow-list'inden geliyorsa ve `# noqa: S608` yorumuyla (mevcut `refs.py` sözleşmesi).
- Whitelisted uçlar: `_guard_destructive()` (System Manager) — `media_admin.py` deseni; hepsi `methods=[...]` belirtir.
- `hooks.py`'ye **ekle**, üzerine yazma. `page_renderer` ve `scheduler_events["daily"]`.
- Testler `FrappeTestCase`; çalıştırma: `docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.<modül>`.
- Admin panel: `node:test` + Vite SSR (`npm test`), ESLint (`npm run lint`), i18n `tr` + `en` zorunlu (`ar`/`ru` isteğe bağlı, anahtar yoksa `tr` fallback).
- Panel dist Docker imajında: `npm run build` sonrası `cd docker && docker compose build admin-panel` (hafıza notu).
- Commit mesajları Türkçe, conventional prefix (`feat(media): …`). Repo `tradehub_core` default branch `version-15`; panel `master`. **İş dalı:** `feature/media-retro-rename` (her iki repoda).
- 90 gün = `REDIRECT_TTL_DAYS = 90` tek sabit; `%2` hata eşiği = `ERROR_RATE_STOP = 0.02`.

---

## Dosya haritası

**tradehub_core (backend)**
- Create `tradehub_core/tradehub_core/doctype/media_url_redirect/{__init__.py, media_url_redirect.json, media_url_redirect.py}` — 301 haritası DocType.
- Create `tradehub_core/media/retro_rename.py` — `is_legacy_name`, `target_url`, `plan`, `run_job` (apply), `run_rollback`, `purge_expired_redirects`, progress/stop yardımcıları.
- Create `tradehub_core/media/redirect_renderer.py` — `MediaRedirectRenderer`.
- Modify `tradehub_core/media/refs.py:197-236` — `retarget` gömülü/JSON desteği.
- Modify `tradehub_core/media/audit.py` — `ACTION_RETRO_RENAME`, `ACTION_RETRO_ROLLBACK` (+ `MEDIA_ACTIONS`, `_HIGH_SEVERITY_ACTIONS`).
- Modify `tradehub_core/api/media_admin.py` — 5 uç.
- Modify `tradehub_core/hooks.py` — `page_renderer`, `scheduler_events["daily"]`.
- Create `tradehub_core/tests/test_media_retro_rename.py`, `tests/test_media_redirect_renderer.py`, `tests/test_media_refs_retarget_embedded.py`, `tests/test_media_admin_retro_rename.py`.
- Modify `docs/MEDYA-DEPOLAMA-STANDARDI.md`, `docs/plans/migration.md`, `CHANGELOG.md`; regenerate `docs/api/openapi-http.yaml`.

**admin-panel/frontend**
- Create `src/composables/useMediaRetroRename.js` + `src/composables/__tests__/mediaRetroRename.test.js`.
- Create `src/components/media/MediaRetroRenameCard.vue`.
- Modify `src/views/system/MediaOptimizeView.vue` (kartı yerleştir), `src/i18n/locales/tr.js`, `en.js`; regenerate `src/lib/api/types.gen.ts`.

---

### Task 1: `Media URL Redirect` DocType

**Files:**
- Create: `tradehub_core/tradehub_core/doctype/media_url_redirect/__init__.py` (boş)
- Create: `tradehub_core/tradehub_core/doctype/media_url_redirect/media_url_redirect.json`
- Create: `tradehub_core/tradehub_core/doctype/media_url_redirect/media_url_redirect.py`
- Test: `tradehub_core/tests/test_media_retro_rename.py` (ilk sınıf)

**Interfaces:**
- Produces: DocType `Media URL Redirect` alanları `source_url` (unique), `target_url`, `job_key`, `expires_at`, `file_rows`, `hit_count`. Sonraki görevler `frappe.get_doc({"doctype": "Media URL Redirect", ...}).insert(ignore_permissions=True)` ve `frappe.db.get_value("Media URL Redirect", {"source_url": ...}, ...)` kullanır.

- [ ] **Step 1: Failing test**

```python
"""Medya retro-rename (MOGEM-582 alt görevi) — eski tahmin edilebilir adların
içerik-adresli ada taşınması, 301 köprüsü ve geri alma.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_retro_rename
"""

from __future__ import annotations

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_files_path, now_datetime


class TestMediaUrlRedirectDoctype(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(lambda: frappe.db.delete("Media URL Redirect", {"job_key": "TEST-DT"}))

	def test_source_url_tekil(self):
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": "/files/test-dt-eski.jpg",
				"target_url": "/files/ab/abcdef.jpg",
				"job_key": "TEST-DT",
				"expires_at": add_days(now_datetime(), 90),
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc(
				{
					"doctype": "Media URL Redirect",
					"source_url": "/files/test-dt-eski.jpg",
					"target_url": "/files/ab/ffffff.jpg",
					"job_key": "TEST-DT",
					"expires_at": add_days(now_datetime(), 90),
				}
			).insert(ignore_permissions=True)
```

- [ ] **Step 2: Run, expect fail** — `DoesNotExistError: DocType Media URL Redirect not found`.

- [ ] **Step 3: DocType JSON**

```json
{
 "$comment": "MOGEM-582 retro-rename: eski /files/<ad> → yeni /files/<ab>/<hash>.<ext> 301 haritası. Satır süresi dolunca (expires_at) günlük cron siler; o andan sonra eski adres 404. Satırlar job_key ile gruplanır — geri alma bu gruptan okur.",
 "actions": [],
 "allow_rename": 0,
 "autoname": "hash",
 "creation": "2026-08-21 00:00:00.000000",
 "doctype": "DocType",
 "editable_grid": 0,
 "engine": "InnoDB",
 "field_order": ["source_url", "target_url", "cb", "job_key", "expires_at", "file_rows", "hit_count"],
 "fields": [
  {"fieldname": "source_url", "fieldtype": "Data", "label": "Eski adres", "reqd": 1, "unique": 1, "search_index": 1, "in_list_view": 1, "length": 500},
  {"fieldname": "target_url", "fieldtype": "Data", "label": "Yeni adres", "reqd": 1, "in_list_view": 1, "length": 500},
  {"fieldname": "cb", "fieldtype": "Column Break"},
  {"fieldname": "job_key", "fieldtype": "Data", "label": "İş anahtarı", "reqd": 1, "search_index": 1, "in_list_view": 1},
  {"fieldname": "expires_at", "fieldtype": "Datetime", "label": "Süre sonu", "reqd": 1, "search_index": 1, "in_list_view": 1},
  {"fieldname": "file_rows", "fieldtype": "Int", "label": "File satırı", "default": "0", "read_only": 1, "description": "Bu eski adresi paylaşan tabFile satırı sayısı; dedup (aynı hedefe giden birden çok eski ad) durumunda rollback yalnız bu kadar satırı geri çevirir."},
  {"fieldname": "hit_count", "fieldtype": "Int", "label": "İsabet", "default": "0", "read_only": 1, "description": "İlk sürümde yazılmaz (her 301'de yazma = yük)."}
 ],
 "index_web_pages_for_search": 0,
 "links": [],
 "modified": "2026-08-21 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Tradehub Core",
 "name": "Media URL Redirect",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "export": 1, "report": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "track_changes": 0
}
```

`media_url_redirect.py`:

```python
from frappe.model.document import Document


class MediaURLRedirect(Document):
	"""Davranış yok; iş mantığı `media/retro_rename.py` ve `media/redirect_renderer.py`."""
```

- [ ] **Step 4: Migrate + test pass**

```
docker exec istoc-dev-backend-1 bench --site istoc.localhost migrate
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_retro_rename
```
Expected: PASS.

- [ ] **Step 5: Commit** — `feat(media): Media URL Redirect DocType (retro-rename 301 haritası)`

---

### Task 2: `retro_rename.is_legacy_name` + `target_url` + `plan()`

**Files:**
- Create: `tradehub_core/media/retro_rename.py`
- Test: `tradehub_core/tests/test_media_retro_rename.py`

**Interfaces:**
- Consumes: `naming._hashed_name(original, content) -> str`, `naming._shard(hashed_name) -> str` (`media/naming.py:49,59`); `refs.find(url) -> list[dict]` (`exact`, `readonly` anahtarları).
- Produces:
  - `is_legacy_name(file_url: str) -> bool`
  - `target_url(file_url: str) -> str` (diski okur; dosya yoksa `FileNotFoundError`)
  - `legacy_urls() -> list[str]` (distinct, `tabFile` public hash-dışı)
  - `plan(limit: int | None = None) -> dict` şekli:
    `{"total": int, "renamable": int, "orphans": int, "disk_missing": int, "collisions": int, "refs_exact": int, "refs_readonly": int, "refs_embedded": int, "file_rows": int, "items": [ {source_url, target_url, file_rows, refs_exact, refs_readonly, refs_embedded, orphan, disk_missing, collision} ... ], "truncated": bool}`

- [ ] **Step 1: Failing tests** (aynı test dosyasına ekle)

```python
from tradehub_core.media import retro_rename


def _write_flat_public(name: str, content: bytes) -> str:
	"""Eski düzen: shard'sız, public/files/<name>. `/files/<name>` döner."""
	base = get_files_path(is_private=0)
	with open(os.path.join(base, name), "wb") as f:
		f.write(content)
	return f"/files/{name}"


class TestLegacyNameAndTarget(FrappeTestCase):
	def test_is_legacy_name(self):
		self.assertTrue(retro_rename.is_legacy_name("/files/0505.jpg"))
		self.assertTrue(retro_rename.is_legacy_name("/files/515804-5.jpg"))
		self.assertTrue(retro_rename.is_legacy_name("/files/Adsız tasarım.png"))
		self.assertFalse(retro_rename.is_legacy_name("/files/ab/" + "a" * 32 + ".jpg"))
		self.assertFalse(retro_rename.is_legacy_name("/files/media/ASSET/" + "f" * 64 + "/thumb-320.webp"))
		self.assertFalse(retro_rename.is_legacy_name("/private/files/0505.jpg"))
		self.assertFalse(retro_rename.is_legacy_name(""))
		# Alt dizinli ama hash'siz eski dosya da eski sayılır (ör. /files/eski/foto.JPG)
		self.assertTrue(retro_rename.is_legacy_name("/files/eski/foto.JPG"))

	def test_target_url_icerik_hashli_ve_shardli(self):
		suffix = frappe.generate_hash(length=8)
		name = f"rr-{suffix}.JPG"
		content = f"retro-{suffix}".encode()
		url = _write_flat_public(name, content)
		self.addCleanup(lambda: os.path.exists(p := os.path.join(get_files_path(0), name)) and os.remove(p))
		import hashlib

		h = hashlib.sha256(content).hexdigest()[:32]
		self.assertEqual(retro_rename.target_url(url), f"/files/{h[:2]}/{h}.jpg")

	def test_target_url_dosya_yoksa_hata(self):
		with self.assertRaises(FileNotFoundError):
			retro_rename.target_url("/files/rr-yok-boyle-dosya.jpg")


class TestPlan(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.name = f"rr-plan-{self.suffix}.jpg"
		self.content = f"plan-{self.suffix}".encode()
		self.url = _write_flat_public(self.name, self.content)
		self.addCleanup(lambda: os.path.exists(p := os.path.join(get_files_path(0), self.name)) and os.remove(p))
		for _ in range(2):  # aynı URL'yi paylaşan iki File satırı
			d = frappe.get_doc(
				{"doctype": "File", "file_name": self.name, "file_url": self.url, "is_private": 0}
			).insert(ignore_permissions=True)
			self.addCleanup(lambda n=d.name: frappe.delete_doc("File", n, force=True, ignore_permissions=True))
		frappe.db.commit()

	def test_plan_adayi_ve_sayaclari_listeler(self):
		p = retro_rename.plan()
		item = next(i for i in p["items"] if i["source_url"] == self.url)
		self.assertEqual(item["file_rows"], 2)
		self.assertTrue(item["orphan"])
		self.assertFalse(item["disk_missing"])
		self.assertFalse(item["collision"])
		self.assertTrue(item["target_url"].startswith("/files/"))
		self.assertGreaterEqual(p["total"], 1)
		self.assertGreaterEqual(p["orphans"], 1)

	def test_plan_diskte_olmayani_isaretler(self):
		os.remove(os.path.join(get_files_path(0), self.name))
		p = retro_rename.plan()
		item = next(i for i in p["items"] if i["source_url"] == self.url)
		self.assertTrue(item["disk_missing"])
		self.assertIsNone(item["target_url"])
		self.assertGreaterEqual(p["disk_missing"], 1)

	def test_plan_salt_okunur(self):
		before = frappe.db.get_value("File", {"file_url": self.url}, "file_url")
		retro_rename.plan()
		self.assertEqual(frappe.db.get_value("File", {"file_url": self.url}, "file_url"), before)
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(0), self.name)))
```

- [ ] **Step 2: Run, expect fail** — `ImportError: cannot import name 'retro_rename'`.

- [ ] **Step 3: Implementation** — `tradehub_core/media/retro_rename.py`

```python
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
from frappe import _
from frappe.utils import add_days, get_files_path, now_datetime

from tradehub_core.media import audit, naming, refs

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
	"""Salt okunur rapor. Hiçbir şey yazmaz."""
	urls = legacy_urls()
	cap = min(limit or PLAN_ITEM_LIMIT, PLAN_ITEM_LIMIT)
	items = [_inspect(u) for u in urls[:cap]]
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
		"items": items,
	}
	for it in items:
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
```

- [ ] **Step 4: Run tests** — PASS (TestLegacyNameAndTarget, TestPlan).
- [ ] **Step 5: Ruff** — `docker exec istoc-dev-backend-1 sh -c 'cd apps/tradehub_core && ruff check tradehub_core/media/retro_rename.py && ruff format --check tradehub_core/media/retro_rename.py'`
- [ ] **Step 6: Commit** — `feat(media): retro_rename plan() — aday tespiti ve salt okunur rapor`

---

### Task 3: `refs.retarget` gömülü metin + JSON desteği

**Files:**
- Modify: `tradehub_core/media/refs.py:197-236`
- Test: `tradehub_core/tests/test_media_refs_retarget_embedded.py`

**Interfaces:**
- Produces: `refs.retarget(old_url, new_url) -> dict` aynı şekil (`updated`, `skipped`, `total`); artık `exact=False` satırlar için: kolon JSON parse ediliyorsa yürüyerek değiştirir, değilse ham metinde tam-dize (`old_url` ve JSON-kaçışlı yazımı) değiştirir; yalnız `_WRITABLE` kolonlarda. `READONLY_TABLES` hâlâ atlanır.

- [ ] **Step 1: Failing tests**

```python
"""`refs.retarget` gömülü referans desteği (retro-rename için).

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_refs_retarget_embedded
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import refs


class TestRetargetEmbedded(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.old = f"/files/rr-emb-{frappe.generate_hash(length=8)}.jpg"
		self.new = "/files/ab/" + "c" * 32 + ".jpg"

	def _layout(self, sections) -> str:
		doc = frappe.get_doc(
			{"doctype": "Storefront Layout", "sections": json.dumps(sections, ensure_ascii=True)}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Storefront Layout", doc.name, force=True, ignore_permissions=True))
		return doc.name

	def test_json_icindeki_adres_degistirilir(self):
		name = self._layout([{"type": "hero", "image": self.old}, {"type": "text", "body": "x"}])
		out = refs.retarget(self.old, self.new)
		data = json.loads(frappe.db.get_value("Storefront Layout", name, "sections"))
		self.assertEqual(data[0]["image"], self.new)
		self.assertEqual(out["total"], 1)
		self.assertFalse(out["skipped"])

	def test_json_kacisli_yazim_da_degistirilir(self):
		old_tr = "/files/rr-ı-" + frappe.generate_hash(length=6) + ".jpg"
		name = self._layout([{"image": old_tr}])  # ensure_ascii → ı
		refs.retarget(old_tr, self.new)
		self.assertEqual(json.loads(frappe.db.get_value("Storefront Layout", name, "sections"))[0]["image"], self.new)

	def test_bozuk_json_atlanir(self):
		doc = frappe.get_doc({"doctype": "Storefront Layout"})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Storefront Layout", doc.name, force=True, ignore_permissions=True))
		frappe.db.set_value("Storefront Layout", doc.name, "sections", '{"image": "' + self.old + '"', update_modified=False)
		out = refs.retarget(self.old, self.new)
		self.assertEqual(out["total"], 0)
		self.assertTrue(any("gömülü" in s for s in out["skipped"]))
		self.assertIn(self.old, frappe.db.get_value("Storefront Layout", doc.name, "sections"))
```

> `Storefront Layout` zorunlu alanları nedeniyle insert başarısız olursa test fixture'ını en küçük geçerli dokümanla kur (mevcut `test_media_usage_store.py` fixture'ına bak) — testin özü `sections` kolonunun güncellenmesi.

- [ ] **Step 2: Run, expect fail** — `total == 0`, `skipped` içinde "gömülü metin".

- [ ] **Step 3: Implementation** — `refs.py` içinde `retarget` döngüsünü değiştir:

```python
def _replace_embedded(value: str, old_url: str, new_url: str) -> str | None:
	"""Gömülü değerde adresi değiştir. JSON ise yapısal, değilse tam-dize.
	Değişiklik yoksa ya da JSON bozuksa None."""
	if not value:
		return None
	yazimlar = usage._search_variants(old_url)
	stripped = value.lstrip()
	if stripped[:1] in "[{":
		try:
			data = json.loads(value)
		except ValueError:
			return None

		def walk(node):
			if isinstance(node, str):
				return new_url if node == old_url else node
			if isinstance(node, list):
				return [walk(x) for x in node]
			if isinstance(node, dict):
				return {k: walk(v) for k, v in node.items()}
			return node

		yeni = walk(data)
		if yeni == data:
			return None
		return json.dumps(yeni, ensure_ascii=True)
	yeni = value
	for y in yazimlar:
		yeni = yeni.replace(y, new_url)
	return None if yeni == value else yeni
```

`retarget` döngüsünde `if not ref["exact"]:` dalını şöyle değiştir:

```python
		if not ref["exact"]:
			_assert_writable(ref["table"], ref["column"])
			mevcut = frappe.db.get_value(ref["table"][3:], ref["row"], ref["column"])
			yeni = _replace_embedded(mevcut or "", old_url, new_url)
			if yeni is None:
				atlanan.append(f"{hedef} (gömülü metin)")
				continue
			frappe.db.sql(  # noqa: S608 — tablo/kolon _WRITABLE allow-list'inden
				f"update `{ref['table']}` set `{ref['column']}`=%s where name=%s",
				(yeni, ref["row"]),
			)
			guncellenen.append(hedef)
			continue
```

`import json` dosya başına ekle. Docstring'deki "gömülü metin atlanır" cümlesini "JSON yapısal, düz metin tam-dize değiştirilir; parse edilemeyen JSON atlanır" olarak güncelle.

- [ ] **Step 4: Run** — yeni test + `test_media_access_level` (regresyon) PASS.
- [ ] **Step 5: Commit** — `feat(media): refs.retarget gömülü JSON/metin referanslarını da taşır`

---

### Task 4: `run_job` (apply) + ilerleme + durdurma + `run_rollback`

**Files:**
- Modify: `tradehub_core/media/retro_rename.py`
- Modify: `tradehub_core/media/audit.py` (iki aksiyon)
- Test: `tradehub_core/tests/test_media_retro_rename.py`

**Interfaces:**
- Consumes: `audit.log_media_event(action=..., file_url=..., context=...)`, `audit.log_media_batch(action=..., job_key=..., summary=...)`, `av.in_quarantine(url)`, `av.in_hold(url)`.
- Produces:
  - `progress_key(job_key) -> str` = `f"tradehub_media_retro:{job_key}"`; `read_progress(job_key) -> dict` (`{"state": "not_found"}` yoksa)
  - `request_stop(job_key) -> None`; `ACTIVE_KEY = "tradehub:retro_rename:active"`
  - `run_job(job_key: str, dry_run: int = 0, batch_size: int = DEFAULT_BATCH) -> None` (kuyruk girişi)
  - `run_rollback(job_key: str, rollback_key: str) -> None`
  - `rename_one(url: str, job_key: str, expires_at) -> dict` `{status: renamed|skipped|error, reason, target_url, refs_updated, refs_skipped}`
  - Progress şekli: `{state: running|completed|partial|error|stopped, mode: rename|rollback, dry_run, total, processed, renamed, skipped, errors, skip_reasons: {}, expires_at: str|None, message}`
  - `audit.ACTION_RETRO_RENAME = "media.retro_rename"`, `audit.ACTION_RETRO_ROLLBACK = "media.retro_rollback"` (ikisi HIGH)

- [ ] **Step 1: Failing tests**

```python
from unittest import mock

from tradehub_core.media import refs


class _RenameBase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.name = f"rr-job-{self.suffix}.jpg"
		self.content = f"job-{self.suffix}".encode()
		self.url = _write_flat_public(self.name, self.content)
		self.files = []
		for _ in range(3):
			d = frappe.get_doc(
				{"doctype": "File", "file_name": self.name, "file_url": self.url, "is_private": 0}
			).insert(ignore_permissions=True)
			self.files.append(d.name)
		self.listing = frappe.get_doc(
			{"doctype": "Listing", "listing_title": f"RR {self.suffix}", "primary_image": self.url}
		)
		self.listing.flags.ignore_mandatory = True
		self.listing.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.db.rollback()
		for n in self.files:
			if frappe.db.exists("File", n):
				frappe.delete_doc("File", n, force=True, ignore_permissions=True)
		if frappe.db.exists("Listing", self.listing.name):
			frappe.delete_doc("Listing", self.listing.name, force=True, ignore_permissions=True)
		frappe.db.delete("Media URL Redirect", {"source_url": self.url})
		frappe.db.commit()
		base = get_files_path(is_private=0)
		for p in [os.path.join(base, self.name), getattr(self, "_new_path", "")]:
			if p and os.path.isfile(p):
				os.remove(p)
		frappe.cache.delete_value(retro_rename.ACTIVE_KEY)

	def _expected_target(self) -> str:
		import hashlib

		h = hashlib.sha256(self.content).hexdigest()[:32]
		self._new_path = os.path.join(get_files_path(0), h[:2], f"{h}.jpg")
		return f"/files/{h[:2]}/{h}.jpg"


class TestRenameOne(_RenameBase):
	def test_tam_akis(self):
		hedef = self._expected_target()
		out = retro_rename.rename_one(self.url, "JOB-T", add_days(now_datetime(), 90))
		self.assertEqual(out["status"], "renamed")
		self.assertEqual(out["target_url"], hedef)
		self.assertFalse(os.path.isfile(os.path.join(get_files_path(0), self.name)))
		self.assertTrue(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": hedef}), 3)
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 0)
		self.assertEqual(frappe.db.get_value("Listing", self.listing.name, "primary_image"), hedef)
		r = frappe.db.get_value("Media URL Redirect", {"source_url": self.url}, ["target_url", "job_key"], as_dict=True)
		self.assertEqual((r.target_url, r.job_key), (hedef, "JOB-T"))

	def test_db_hatasinda_disk_geri_alinir(self):
		self._expected_target()
		with mock.patch.object(refs, "retarget", side_effect=RuntimeError("boom")):
			out = retro_rename.rename_one(self.url, "JOB-E", add_days(now_datetime(), 90))
		self.assertEqual(out["status"], "error")
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(0), self.name)))
		self.assertFalse(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.url}))

	def test_idempotent_ikinci_kosu_atlar(self):
		self._expected_target()
		retro_rename.rename_one(self.url, "JOB-I", add_days(now_datetime(), 90))
		out = retro_rename.rename_one(self.url, "JOB-I", add_days(now_datetime(), 90))
		self.assertEqual((out["status"], out["reason"]), ("skipped", "disk_missing"))


class TestRunJobAndRollback(_RenameBase):
	def test_run_job_ilerleme_ve_rollback(self):
		hedef = self._expected_target()
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-R", dry_run=0, batch_size=10)
		p = retro_rename.read_progress("JOB-R")
		self.assertEqual(p["state"], "completed")
		self.assertEqual((p["total"], p["processed"], p["renamed"], p["errors"]), (1, 1, 1, 0))
		self.assertEqual(frappe.db.get_value("Listing", self.listing.name, "primary_image"), hedef)

		retro_rename.run_rollback("JOB-R", "RB-1")
		rp = retro_rename.read_progress("RB-1")
		self.assertEqual(rp["state"], "completed")
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(0), self.name)))
		self.assertFalse(os.path.isfile(self._new_path))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)
		self.assertEqual(frappe.db.get_value("Listing", self.listing.name, "primary_image"), self.url)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.url}))

	def test_dry_run_hicbir_sey_yazmaz(self):
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-D", dry_run=1, batch_size=10)
		p = retro_rename.read_progress("JOB-D")
		self.assertEqual(p["state"], "completed")
		self.assertTrue(p["dry_run"])
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(0), self.name)))
		self.assertEqual(frappe.db.count("File", {"file_url": self.url}), 3)

	def test_stop_bayragi_batch_sinirinda_durdurur(self):
		retro_rename.request_stop("JOB-S")
		with mock.patch.object(retro_rename, "legacy_urls", return_value=[self.url]):
			retro_rename.run_job("JOB-S", dry_run=0, batch_size=1)
		self.assertEqual(retro_rename.read_progress("JOB-S")["state"], "stopped")
		self.assertTrue(os.path.isfile(os.path.join(get_files_path(0), self.name)))
```

> `Listing` zorunlu alanları için `flags.ignore_mandatory` yetmezse `test_media_access_level.py`'deki Listing fixture'ını kullan.

- [ ] **Step 2: Run, expect fail** — `AttributeError: rename_one`.

- [ ] **Step 3: audit.py** — `ACTION_VERSION_ROLLBACK` satırının altına:

```python
# MOGEM-582 retro-rename: eski ad → içerik-adresli ad; ikisi de geri dönüşü
# olan ama kütüphane çapında etkili işler → HIGH.
ACTION_RETRO_RENAME: str = "media.retro_rename"
ACTION_RETRO_ROLLBACK: str = "media.retro_rollback"
```
`MEDIA_ACTIONS` tuple'ına ve `_HIGH_SEVERITY_ACTIONS` kümesine ikisini ekle.

- [ ] **Step 4: retro_rename.py'ye ekle**

```python
ACTIVE_KEY = "tradehub:retro_rename:active"


def progress_key(job_key: str) -> str:
	return f"tradehub_media_retro:{job_key}"


def _stop_key(job_key: str) -> str:
	return f"tradehub_media_retro_stop:{job_key}"


def read_progress(job_key: str) -> dict:
	return frappe.cache.get_value(progress_key(job_key)) or {"state": "not_found"}


def _write_progress(job_key: str, payload: dict) -> None:
	frappe.cache.set_value(progress_key(job_key), payload, expires_in_sec=PROGRESS_TTL)


def request_stop(job_key: str) -> None:
	frappe.cache.set_value(_stop_key(job_key), 1, expires_in_sec=PROGRESS_TTL)


def _stop_requested(job_key: str) -> bool:
	return bool(frappe.cache.get_value(_stop_key(job_key)))


def _new_state(total: int, mode: str, dry_run: bool, expires_at=None) -> dict:
	return {
		"state": "running",
		"mode": mode,
		"dry_run": bool(dry_run),
		"total": total,
		"processed": 0,
		"renamed": 0,
		"skipped": 0,
		"errors": 0,
		"skip_reasons": {},
		"expires_at": str(expires_at) if expires_at else None,
		"message": "",
	}


def _skip(reason: str, **extra) -> dict:
	return {"status": "skipped", "reason": reason, "target_url": None, "refs_updated": 0, "refs_skipped": 0, **extra}


def rename_one(url: str, job_key: str, expires_at, *, dry_run: bool = False) -> dict:
	"""Tek dosya: disk → File → refs → redirect → commit. Hata → rollback + ters taşıma."""
	from tradehub_core.media import av

	if not is_legacy_name(url):
		return _skip("not_legacy")
	old_path = _disk_path(url)
	if not os.path.isfile(old_path):
		return _skip("disk_missing")
	if av.in_quarantine(url) or av.in_hold(url):
		return _skip("quarantined")

	new_url = target_url(url)
	new_path = _disk_path(new_url)
	dedup = False
	if os.path.isfile(new_path):
		if _content_sha(new_path) != _content_sha(old_path):
			return _skip("collision", target_url=new_url)
		dedup = True
	if dry_run:
		return {"status": "renamed", "reason": "dry_run", "target_url": new_url, "refs_updated": 0, "refs_skipped": 0}

	frappe.create_folder(os.path.dirname(new_path))
	if dedup:
		os.remove(old_path)
	else:
		os.replace(old_path, new_path)

	try:
		file_rows = frappe.db.count("File", {"file_url": url})
		frappe.db.set_value("File", {"file_url": url}, {"file_url": new_url}, update_modified=False)
		ref_result = refs.retarget(url, new_url)
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": url,
				"target_url": new_url,
				"job_key": job_key,
				"expires_at": expires_at,
				"file_rows": file_rows,
			}
		).insert(ignore_permissions=True)  # sistem işi; çağıran uç System Manager kapısından geçti
		frappe.cache.delete_value(f"tradehub:file_url_ambiguous:{url}")
	except Exception:
		frappe.db.rollback()
		try:
			if dedup:
				with open(new_path, "rb") as src, open(old_path, "wb") as dst:
					dst.write(src.read())
			else:
				os.replace(new_path, old_path)
		except OSError:
			frappe.log_error(
				title=f"Retro-rename disk revert failed for {url}",
				message=frappe.get_traceback(with_context=True),
			)
		frappe.log_error(title=f"Retro-rename failed for {url}", message=frappe.get_traceback(with_context=True))
		return {"status": "error", "reason": "exception", "target_url": new_url, "refs_updated": 0, "refs_skipped": 0}

	frappe.db.commit()
	audit.log_media_event(
		action=audit.ACTION_RETRO_RENAME,
		file_url=new_url,
		context={
			"operation": "retro_rename",
			"old_url": url,
			"job_key": job_key,
			"refs_updated": ref_result["total"],
			"refs_skipped": len(ref_result["skipped"]),
			"dedup": dedup,
		},
	)
	return {
		"status": "renamed",
		"reason": "dedup" if dedup else "",
		"target_url": new_url,
		"refs_updated": ref_result["total"],
		"refs_skipped": len(ref_result["skipped"]),
	}


def run_job(job_key: str, dry_run: int = 0, batch_size: int = DEFAULT_BATCH) -> None:
	"""Kuyruk girişi. Her batch sınırında stop bayrağı ve hata oranı kontrol edilir."""
	frappe.cache.set_value(ACTIVE_KEY, job_key, expires_in_sec=PROGRESS_TTL)
	try:
		_run_job(job_key, bool(dry_run), max(1, int(batch_size or DEFAULT_BATCH)))
	except Exception:
		durum = read_progress(job_key)
		durum["state"] = "error"
		durum["message"] = _("İşlem tamamlanamadı.")
		_write_progress(job_key, durum)
		frappe.log_error(title=f"Retro-rename job failed: {job_key}", message=frappe.get_traceback(with_context=True))
	finally:
		frappe.cache.delete_value(ACTIVE_KEY)


def _run_job(job_key: str, dry_run: bool, batch_size: int) -> None:
	urls = legacy_urls()
	expires_at = add_days(now_datetime(), REDIRECT_TTL_DAYS)
	durum = _new_state(len(urls), "rename", dry_run, expires_at)
	_write_progress(job_key, durum)

	for i, url in enumerate(urls):
		if i and i % batch_size == 0:
			if _stop_requested(job_key):
				durum["state"] = "stopped"
				durum["message"] = _("Operatör durdurdu.")
				_write_progress(job_key, durum)
				break
			if durum["processed"] and durum["errors"] / durum["processed"] > ERROR_RATE_STOP:
				durum["state"] = "partial"
				durum["message"] = _("Hata oranı eşiği aşıldı; iş durduruldu.")
				_write_progress(job_key, durum)
				break
		out = rename_one(url, job_key, expires_at, dry_run=dry_run)
		durum["processed"] += 1
		if out["status"] == "renamed":
			durum["renamed"] += 1
		elif out["status"] == "skipped":
			durum["skipped"] += 1
			durum["skip_reasons"][out["reason"]] = durum["skip_reasons"].get(out["reason"], 0) + 1
		else:
			durum["errors"] += 1
		if durum["processed"] % 25 == 0:
			_write_progress(job_key, durum)
	else:
		durum["state"] = "partial" if durum["errors"] else "completed"

	_write_progress(job_key, durum)
	audit.log_media_batch(action=audit.ACTION_RETRO_RENAME, job_key=job_key, summary=dict(durum))


def run_rollback(job_key: str, rollback_key: str) -> None:
	"""`job_key` ile yazılmış yönlendirme satırlarını ters oynatır."""
	rows = frappe.get_all(
		"Media URL Redirect", filters={"job_key": job_key}, fields=["name", "source_url", "target_url", "file_rows"]
	)
	durum = _new_state(len(rows), "rollback", False)
	_write_progress(rollback_key, durum)
	frappe.cache.set_value(ACTIVE_KEY, rollback_key, expires_in_sec=PROGRESS_TTL)
	try:
		for row in rows:
			ok = _rollback_one(row)
			durum["processed"] += 1
			durum["renamed" if ok else "errors"] += 1
			if durum["processed"] % 25 == 0:
				_write_progress(rollback_key, durum)
		durum["state"] = "partial" if durum["errors"] else "completed"
	finally:
		frappe.cache.delete_value(ACTIVE_KEY)
	_write_progress(rollback_key, durum)
	audit.log_media_batch(action=audit.ACTION_RETRO_ROLLBACK, job_key=job_key, summary=dict(durum))


def _rollback_one(row) -> bool:
	new_path = _disk_path(row.target_url)
	old_path = _disk_path(row.source_url)
	if not os.path.isfile(new_path):
		frappe.log_error(title=f"Retro-rollback: hedef diskte yok {row.target_url}")
		return False
	# Aynı hedefi paylaşan başka redirect satırı varsa (dedup) dosya KOPYALANIR, taşınmaz.
	paylasan = frappe.db.count("Media URL Redirect", {"target_url": row.target_url}) > 1
	frappe.create_folder(os.path.dirname(old_path))
	if paylasan:
		with open(new_path, "rb") as src, open(old_path, "wb") as dst:
			dst.write(src.read())
	else:
		os.replace(new_path, old_path)
	try:
		# Dedup'ta birden çok eski ad aynı hedefe gitmiş olabilir — yalnız bu
		# satırın kendi File kayıtları kadarı geri çevrilir (file_rows).
		adlar = frappe.get_all("File", filters={"file_url": row.target_url}, pluck="name", order_by="creation asc")
		for ad in adlar[: max(1, int(row.file_rows or 0))]:
			frappe.db.set_value("File", ad, "file_url", row.source_url, update_modified=False)
		refs.retarget(row.target_url, row.source_url)
		frappe.delete_doc("Media URL Redirect", row.name, ignore_permissions=True, force=True)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		try:
			if paylasan:
				os.remove(old_path)
			else:
				os.replace(old_path, new_path)
		except OSError:
			frappe.log_error(title=f"Retro-rollback disk revert failed {row.source_url}", message=frappe.get_traceback())
		frappe.log_error(title=f"Retro-rollback failed {row.source_url}", message=frappe.get_traceback(with_context=True))
		return False
	return True
```

> Dedup tuzağı: iki farklı eski ad aynı içeriğe (aynı hedefe) sahipse rollback ilk satırda tüm `File` kayıtlarını geri çevirmemeli. `file_rows` bunu sınırlar. Bunu `test_dedup_rollback_yalniz_kendi_satirlarini_dondurur` testiyle kilitle: aynı içerikli iki eski ad (`a.jpg`, `b.jpg`, her birine 1 File), `run_job` → ikisi de aynı hedefe, ikincisi `dedup`; `run_rollback` → `a.jpg` 1 File, `b.jpg` 1 File, hedefte 0 File, diskte ikisi de var, hedef yok.

- [ ] **Step 5: Run tests** — PASS (TestRenameOne, TestRunJobAndRollback). Ruff temiz.
- [ ] **Step 6: Commit** — `feat(media): retro_rename run_job/rollback — disk+DB+refs+301, durdurma ve hata eşiği`

---

### Task 5: `MediaRedirectRenderer` + hook + süre dolumu cron

**Files:**
- Create: `tradehub_core/media/redirect_renderer.py`
- Modify: `tradehub_core/media/retro_rename.py` (`purge_expired_redirects`)
- Modify: `tradehub_core/hooks.py` (`page_renderer`, `scheduler_events["daily"]`)
- Test: `tradehub_core/tests/test_media_redirect_renderer.py`

**Interfaces:**
- Produces: `MediaRedirectRenderer(path, http_status_code=None)` ile `.can_render() -> bool`, `.render() -> Response` (301); `retro_rename.purge_expired_redirects() -> int`.

- [ ] **Step 1: Failing tests**

```python
"""301 köprüsü: eski /files/<ad> → yeni adres; süre dolunca 404.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_redirect_renderer
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from tradehub_core.media import retro_rename
from tradehub_core.media.redirect_renderer import MediaRedirectRenderer


class TestMediaRedirectRenderer(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.old = f"/files/rr-301-{frappe.generate_hash(length=8)}.jpg"
		self.new = "/files/ab/" + "d" * 32 + ".jpg"
		self.addCleanup(lambda: frappe.db.delete("Media URL Redirect", {"source_url": self.old}))

	def _row(self, days: int) -> None:
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": self.old,
				"target_url": self.new,
				"job_key": "T301",
				"expires_at": add_days(now_datetime(), days),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_eski_adres_301(self):
		self._row(30)
		r = MediaRedirectRenderer(self.old.lstrip("/"))
		self.assertTrue(r.can_render())
		resp = r.render()
		self.assertEqual(resp.status_code, 301)
		self.assertEqual(resp.headers["Location"], self.new)
		self.assertIn("no-store", resp.headers["Cache-Control"])

	def test_suresi_dolmus_404(self):
		self._row(-1)
		self.assertFalse(MediaRedirectRenderer(self.old.lstrip("/")).can_render())

	def test_bilinmeyen_ve_files_disi(self):
		self.assertFalse(MediaRedirectRenderer("files/rr-yok.jpg").can_render())
		self.assertFalse(MediaRedirectRenderer("urunler/x").can_render())

	def test_hook_kayitli(self):
		self.assertIn(
			"tradehub_core.media.redirect_renderer.MediaRedirectRenderer", frappe.get_hooks("page_renderer")
		)
		self.assertIn(
			"tradehub_core.media.retro_rename.purge_expired_redirects",
			frappe.get_hooks("scheduler_events")["daily"],
		)

	def test_purge_expired(self):
		self._row(-1)
		silinen = retro_rename.purge_expired_redirects()
		self.assertGreaterEqual(silinen, 1)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": self.old}))
```

- [ ] **Step 2: Run, expect fail** — `ModuleNotFoundError: redirect_renderer`.

- [ ] **Step 3: Implementation**

`tradehub_core/media/redirect_renderer.py`:

```python
"""Eski medya adresleri için 301 köprüsü (MOGEM-582 retro-rename).

Yalnız diskte OLMAYAN `/files/…` istekleri buraya düşer (frappe-frontend nginx
`try_files public/$uri @webserver`). `Website Route Redirect` bilinçli
kullanılmadı: `resolve_redirect` her istekte tüm kuralları çekip regex ile
tarıyor; 2.843 kural her sayfayı yavaşlatırdı. Burada tek indeksli sorgu var.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime
from frappe.website.page_renderers.redirect_page import RedirectPage


class MediaRedirectRenderer:
	def __init__(self, path: str, http_status_code: int | None = None) -> None:
		self.path = path or ""
		self.http_status_code = http_status_code
		self.target: str | None = None

	def can_render(self) -> bool:
		if not self.path.startswith("files/"):
			return False
		source = "/" + self.path.split("?")[0]
		self.target = frappe.db.get_value(
			"Media URL Redirect",
			{"source_url": source, "expires_at": (">", now_datetime())},
			"target_url",
		)
		return bool(self.target)

	def render(self):
		frappe.flags.redirect_location = self.target
		return RedirectPage(self.path, 301).render()
```

`retro_rename.py`'ye:

```python
def purge_expired_redirects() -> int:
	"""Günlük cron: süresi dolan 301 satırlarını sil (sonrası 404)."""
	adlar = frappe.get_all("Media URL Redirect", filters={"expires_at": ("<", now_datetime())}, pluck="name")
	for ad in adlar:
		frappe.delete_doc("Media URL Redirect", ad, ignore_permissions=True, force=True)
	if adlar:
		frappe.db.commit()
		audit.log_media_batch(action=audit.ACTION_RETRO_RENAME, summary={"purged_redirects": len(adlar)})
	return len(adlar)
```

`hooks.py` — `doc_events = {` satırının ÜSTÜNE (yeni top-level):

```python
# MOGEM-582 retro-rename: eski /files/<ad> istekleri için tek-sorgu 301 köprüsü.
# Yalnız diskte olmayan dosya istekleri buraya düşer (nginx try_files).
page_renderer = ["tradehub_core.media.redirect_renderer.MediaRedirectRenderer"]
```

`scheduler_events["daily"]` listesine (`trash.purge_expired` satırının altına):

```python
		# MOGEM-582 — retro-rename 301 köprüsü 90 gün sonra kalkar; eski adres 404.
		"tradehub_core.media.retro_rename.purge_expired_redirects",
```

- [ ] **Step 4: Restart + test** — `docker exec istoc-dev-backend-1 bench --site istoc.localhost clear-cache` sonra testler PASS.
- [ ] **Step 5: HTTP doğrulama** — bir satır ekleyip `curl -sI http://istoc.localhost/files/<eski> | head -3` → `301` + `Location`. Satırı sil.
- [ ] **Step 6: Commit** — `feat(media): MediaRedirectRenderer page_renderer hook + 90 gün süre dolumu cron`

---

### Task 6: Admin API uçları + OpenAPI yeniden üretimi

**Files:**
- Modify: `tradehub_core/api/media_admin.py` (dosya sonuna)
- Test: `tradehub_core/tests/test_media_admin_retro_rename.py`
- Regenerate: `docs/api/openapi-http.yaml`

**Interfaces:**
- Produces (hepsi System Manager, `_guard_destructive()`):
  - `GET retro_rename_plan(limit: int = 200) -> dict` — `plan()` özeti + `items[:limit]`
  - `POST start_retro_rename(dry_run: int = 0, batch_size: int = 200) -> {job_key, total, dry_run}` — aktif iş varsa `frappe.throw`
  - `GET get_retro_rename_status(job_key: str) -> dict` — `read_progress`
  - `POST stop_retro_rename(job_key: str) -> {ok: True}`
  - `POST rollback_retro_rename(job_key: str) -> {job_key}` (rollback işinin anahtarı)
  - `GET retro_rename_history() -> {jobs: [{job_key, count, expires_at, first_created}]}` — `Media URL Redirect` `group by job_key`

- [ ] **Step 1: Failing tests**

```python
"""Retro-rename admin uçları (System Manager).

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_admin_retro_rename
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin
from tradehub_core.media import retro_rename


class TestRetroRenameEndpoints(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(lambda: frappe.cache.delete_value(retro_rename.ACTIVE_KEY))

	def test_plan_ozet_doner(self):
		with mock.patch.object(retro_rename, "plan", return_value={"total": 3, "renamable": 3, "items": [1, 2, 3], "orphans": 0, "disk_missing": 0, "collisions": 0, "refs_exact": 0, "refs_readonly": 0, "refs_embedded": 0, "file_rows": 3, "truncated": False}):
			out = media_admin.retro_rename_plan(limit=2)
		self.assertEqual(out["total"], 3)
		self.assertEqual(len(out["items"]), 2)

	def test_start_enqueue_eder_ve_job_key_doner(self):
		with mock.patch.object(media_admin.frappe, "enqueue") as enq, mock.patch.object(
			retro_rename, "legacy_urls", return_value=["/files/a.jpg"]
		):
			out = media_admin.start_retro_rename(dry_run=1, batch_size=50)
		self.assertTrue(out["job_key"])
		self.assertEqual(out["total"], 1)
		kwargs = enq.call_args.kwargs
		self.assertEqual(kwargs["queue"], "long")
		self.assertEqual(kwargs["dry_run"], 1)

	def test_aktif_is_varken_ikinci_baslatilamaz(self):
		frappe.cache.set_value(retro_rename.ACTIVE_KEY, "X", expires_in_sec=60)
		with self.assertRaises(frappe.ValidationError):
			media_admin.start_retro_rename()

	def test_status_bilinmeyen_not_found(self):
		self.assertEqual(media_admin.get_retro_rename_status("yok")["state"], "not_found")

	def test_rollback_enqueue(self):
		with mock.patch.object(media_admin.frappe, "enqueue") as enq:
			out = media_admin.rollback_retro_rename("JOB-X")
		self.assertTrue(out["job_key"])
		self.assertEqual(enq.call_args.kwargs["job_key"], "JOB-X")

	def test_yetkisiz_reddedilir(self):
		frappe.set_user("Guest")
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				media_admin.retro_rename_plan()
		finally:
			frappe.flags.in_test = True
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run, expect fail** — `AttributeError: retro_rename_plan`.

- [ ] **Step 3: Implementation** — `media_admin.py` sonuna:

```python
# ─── MOGEM-582 retro-rename ────────────────────────────────────────────────
from tradehub_core.media import retro_rename  # noqa: E402 — bölüm başı import, dosya deseni


@frappe.whitelist(methods=["GET"])
def retro_rename_plan(limit: int = 200) -> dict:
	"""Eski adlı dosyaların salt okunur taşınma planı (System Manager)."""
	_guard_destructive()
	p = retro_rename.plan()
	p["items"] = p["items"][: max(0, int(limit or 0))]
	return p


@frappe.whitelist(methods=["POST"])
def start_retro_rename(dry_run: int = 0, batch_size: int = 200) -> dict:
	"""Retro-rename işini kuyruğa al; aynı anda tek iş."""
	_guard_destructive()
	if frappe.cache.get_value(retro_rename.ACTIVE_KEY):
		frappe.throw(_("Zaten çalışan bir yeniden adlandırma işi var."))
	total = len(retro_rename.legacy_urls())
	if not total:
		frappe.throw(_("Taşınacak eski adlı dosya yok."))
	job_key = frappe.generate_hash(length=12)
	frappe.enqueue(
		"tradehub_core.media.retro_rename.run_job",
		queue="long",
		timeout=4 * 3600,
		enqueue_after_commit=True,
		job_key=job_key,
		dry_run=int(dry_run or 0),
		batch_size=int(batch_size or 200),
	)
	return {"job_key": job_key, "total": total, "dry_run": int(dry_run or 0)}


@frappe.whitelist(methods=["GET"])
def get_retro_rename_status(job_key: str) -> dict:
	"""Redis'teki ilerleme. Kayıt yoksa {"state": "not_found"}."""
	_guard_destructive()
	return retro_rename.read_progress(job_key)


@frappe.whitelist(methods=["POST"])
def stop_retro_rename(job_key: str) -> dict:
	"""Bir sonraki batch sınırında durdur."""
	_guard_destructive()
	retro_rename.request_stop(job_key)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def rollback_retro_rename(job_key: str) -> dict:
	"""Bir işin yeniden adlandırmalarını geri al (yönlendirme satırları durduğu sürece)."""
	_guard_destructive()
	if frappe.cache.get_value(retro_rename.ACTIVE_KEY):
		frappe.throw(_("Zaten çalışan bir iş var; bitmesini bekleyin."))
	rollback_key = frappe.generate_hash(length=12)
	frappe.enqueue(
		"tradehub_core.media.retro_rename.run_rollback",
		queue="long",
		timeout=4 * 3600,
		enqueue_after_commit=True,
		job_key=job_key,
		rollback_key=rollback_key,
	)
	return {"job_key": rollback_key, "source_job_key": job_key}


@frappe.whitelist(methods=["GET"])
def retro_rename_history() -> dict:
	"""Geri alınabilir işler: job_key başına satır sayısı ve süre sonu."""
	_guard_destructive()
	rows = frappe.db.sql(
		"""select job_key, count(*) as count, min(expires_at) as expires_at, min(creation) as first_created
			from `tabMedia URL Redirect` group by job_key order by first_created desc""",
		as_dict=True,
	)
	return {"jobs": rows}
```

- [ ] **Step 4: Run tests** — PASS. `test_http_api_contracts` de koş (OpenAPI sapma testi) — FAIL bekleniyor, bir sonraki adım düzeltir.
- [ ] **Step 5: OpenAPI yeniden üret** — `docker exec istoc-dev-backend-1 sh -c 'cd apps/tradehub_core && python3 scripts/gen_http_openapi.py'` → `docs/api/openapi-http.yaml` güncellenir; `test_http_api_contracts` PASS.
- [ ] **Step 6: Commit** — `feat(media): retro-rename admin uçları (plan/start/status/stop/rollback/history) + OpenAPI`

---

### Task 7: Belgeler + CHANGELOG

**Files:**
- Modify: `docs/MEDYA-DEPOLAMA-STANDARDI.md:21` (tablo satırı), `:116-136` (§5), `:148-161` (§7)
- Modify: `docs/plans/migration.md:738-779` (§8.1 not), `:825-849` (§8.3.2 not)
- Modify: `CHANGELOG.md` (Unreleased)

- [ ] **Step 1: §1 tablo satırı 21** →
`| **Türev** | Ayrı kökte, asset+sürüm adresli: `/files/media/{asset}/{version_hash}/{profil}-{genişlik}.{ext}` (`pipeline_bridge._write_rendition_file`); video yerinde üzerine yazılır, suffix yok |`
- [ ] **Step 2: §5** — örnek ağacı gerçek yola göre yeniden yaz:

```
/files/ab/<hash>.jpg                                    ← orijinal (içerik-adresli, shard)
/files/media/<asset>/<version_hash>/thumb-320.webp     ← thumbnail
/files/media/<asset>/<version_hash>/card-768.webp      ← profil × genişlik
/files/media/<asset>/<version_hash>/hls/master.m3u8    ← video (HLS); tek dosya video yerinde üzerine yazılır
```
Açıklama: türev adresi orijinalin yolundan bağımsız (asset adı + sürüm hash'i) — orijinal yeniden adlandırılsa türevler kırılmaz. Eski shard-yanı türevler (`/files/xx/<hash>.webp`) `Media Rendition.file_url` üzerinden okunmaya devam eder.
- [ ] **Step 3: §7** başlığı "Ertelenen" → "Retro-rename (uygulandı)"; içerik: araç `media/retro_rename.py`, 301 köprüsü 90 gün, admin panel kartı, spec bağlantısı; eski "2.166" sayısı yerine "lokal ölçüm 2.843 distinct URL / 4.319 File satırı (2026-08-21)".
- [ ] **Step 4: migration.md** §8.1 başına not: "2026-08-21: nginx sertleştirmesi kaynak şablonda (`tradehubfront/nginx.conf.template:207,421`); retro-rename uygulandı — bkz. spec". §8.3.2'ye: "LIVE_SOURCES 17 alan; `retarget` artık JSON/gömülü destekli".
- [ ] **Step 5: CHANGELOG** Unreleased altına: `feat(media): retro-rename — eski adlı public dosyalar içerik-adresli ada taşınır; 90 gün 301; admin panel kartı (MOGEM-582)`.
- [ ] **Step 6: Commit** — `docs(media): depolama standardı §5 türev yolu düzeltildi, §7 retro-rename uygulandı`

---

### Task 8: Admin panel composable `useMediaRetroRename`

**Files:**
- Create: `admin-panel/frontend/src/composables/useMediaRetroRename.js`
- Test: `admin-panel/frontend/src/composables/__tests__/mediaRetroRename.test.js`

**Interfaces:**
- Produces: `useMediaRetroRename(fetchers?)` → `{ plan, planLoading, planError, loadPlan, job, running, start({dryRun}), stop, rollback(jobKey), history, loadHistory, resetJob }`. `fetchers` testte enjekte edilir: `{ plan, start, status, stop, rollback, history }`; varsayılan `api.callMethod*` ile `tradehub_core.api.media_admin.*`.

- [ ] **Step 1: Failing test**

```js
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import { createServer } from "vite";

/**
 * Retro-rename composable (MOGEM-582): plan → start → poll → terminal;
 * rollback görünürlüğü history'ye bağlı. Uçlar uydurulmadı:
 * `tradehub_core.api.media_admin.{retro_rename_plan,start_retro_rename,
 * get_retro_rename_status,stop_retro_rename,rollback_retro_rename,retro_rename_history}`.
 */

const frontendRoot = fileURLToPath(new URL("../../..", import.meta.url));
let server;
let useMediaRetroRename;

before(async () => {
  server = await createServer({
    configFile: false,
    root: frontendRoot,
    logLevel: "silent",
    resolve: { alias: [{ find: "@", replacement: `${frontendRoot}/src` }] },
    server: { middlewareMode: true },
    appType: "custom",
  });
  ({ useMediaRetroRename } = await server.ssrLoadModule("/src/composables/useMediaRetroRename.js"));
});
after(async () => {
  await server?.close();
});

function sahte({ statuses = [] } = {}) {
  const calls = [];
  let i = 0;
  return {
    calls,
    fetchers: {
      plan: async () => (calls.push("plan"), { total: 3, renamable: 3, orphans: 1, disk_missing: 0, collisions: 0, refs_exact: 5, refs_embedded: 0, refs_readonly: 2, file_rows: 4, items: [] }),
      start: async (args) => (calls.push(["start", args]), { job_key: "J1", total: 3, dry_run: args.dry_run }),
      status: async () => (calls.push("status"), statuses[Math.min(i++, statuses.length - 1)]),
      stop: async () => (calls.push("stop"), { ok: true }),
      rollback: async (args) => (calls.push(["rollback", args]), { job_key: "RB1" }),
      history: async () => (calls.push("history"), { jobs: [{ job_key: "J1", count: 3, expires_at: "2026-11-19 00:00:00" }] }),
    },
  };
}

test("plan yüklenmeden total null; yüklenince sayılar gelir", async () => {
  const s = sahte();
  const r = useMediaRetroRename(s.fetchers, { pollMs: 1 });
  assert.equal(r.plan.value, null);
  await r.loadPlan();
  assert.equal(r.plan.value.total, 3);
  assert.equal(r.plan.value.orphans, 1);
});

test("start → running → completed; polling durur; history yenilenir", async () => {
  const s = sahte({
    statuses: [
      { state: "running", total: 3, processed: 1, renamed: 1, skipped: 0, errors: 0, skip_reasons: {} },
      { state: "completed", total: 3, processed: 3, renamed: 3, skipped: 0, errors: 0, skip_reasons: {}, expires_at: "2026-11-19 00:00:00" },
    ],
  });
  const r = useMediaRetroRename(s.fetchers, { pollMs: 1 });
  await r.start({ dryRun: false });
  assert.equal(r.job.key, "J1");
  assert.equal(r.running.value, true);
  await new Promise((res) => setTimeout(res, 30));
  assert.equal(r.job.state, "completed");
  assert.equal(r.running.value, false);
  assert.equal(r.job.expires_at, "2026-11-19 00:00:00");
  assert.ok(s.calls.includes("history"), "iş bitince history yenilenmeli");
  const statusCalls = s.calls.filter((c) => c === "status").length;
  await new Promise((res) => setTimeout(res, 10));
  assert.equal(s.calls.filter((c) => c === "status").length, statusCalls, "terminal sonrası polling sürdü");
});

test("dry-run bayrağı uca 1 olarak gider", async () => {
  const s = sahte({ statuses: [{ state: "completed", total: 0, processed: 0, renamed: 0, skipped: 0, errors: 0, skip_reasons: {} }] });
  const r = useMediaRetroRename(s.fetchers, { pollMs: 1 });
  await r.start({ dryRun: true });
  const startCall = s.calls.find((c) => Array.isArray(c) && c[0] === "start");
  assert.equal(startCall[1].dry_run, 1);
});

test("rollback yalnız history'de iş varsa mümkün; rollback yeni job_key ile izlenir", async () => {
  const s = sahte({ statuses: [{ state: "completed", total: 3, processed: 3, renamed: 3, skipped: 0, errors: 0, skip_reasons: {} }] });
  const r = useMediaRetroRename(s.fetchers, { pollMs: 1 });
  assert.equal(r.canRollback.value, false);
  await r.loadHistory();
  assert.equal(r.canRollback.value, true);
  await r.rollback("J1");
  assert.equal(r.job.key, "RB1");
  assert.equal(r.job.mode, "rollback");
});

test("başlatma hatası job'u kirletmez", async () => {
  const s = sahte();
  s.fetchers.start = async () => {
    throw new Error("Zaten çalışan bir iş var.");
  };
  const r = useMediaRetroRename(s.fetchers, { pollMs: 1 });
  const out = await r.start({});
  assert.equal(out, null);
  assert.equal(r.job.key, null);
  assert.equal(r.lastError.value, "Zaten çalışan bir iş var.");
});
```

- [ ] **Step 2: Run, expect fail** — `npm test -- src/composables/__tests__/mediaRetroRename.test.js` → SSR load hatası (modül yok).

- [ ] **Step 3: Implementation**

```js
import { computed, onUnmounted, reactive, ref } from "vue";

import api from "@/utils/api";

const M = "tradehub_core.api.media_admin";
const TERMINAL = new Set(["completed", "partial", "error", "stopped", "not_found"]);

/**
 * Retro-rename (MOGEM-582): eski adlı public dosyaları içerik-adresli ada taşıma.
 *
 * Akış: `loadPlan` (salt okunur özet) → `start` (kuyruk, job_key) → 3 sn polling →
 * terminal → `loadHistory` (rollback görünürlüğü). `rollback` yeni bir iş başlatır
 * ve aynı progress sözleşmesiyle izlenir (`mode: "rollback"`).
 *
 * `fetchers` yalnız test içindir; üretimde uçlar `media_admin.*`.
 */
const varsayilanUclar = {
  plan: (args) => api.callMethodGET(`${M}.retro_rename_plan`, args).then((r) => r.message || {}),
  start: (args) => api.callMethod(`${M}.start_retro_rename`, args).then((r) => r.message || {}),
  status: (args) => api.callMethodGET(`${M}.get_retro_rename_status`, args).then((r) => r.message || {}),
  stop: (args) => api.callMethod(`${M}.stop_retro_rename`, args).then((r) => r.message || {}),
  rollback: (args) => api.callMethod(`${M}.rollback_retro_rename`, args).then((r) => r.message || {}),
  history: () => api.callMethodGET(`${M}.retro_rename_history`).then((r) => r.message || {}),
};

function bosIs() {
  return {
    key: null,
    mode: "rename",
    state: null,
    dry_run: false,
    total: 0,
    processed: 0,
    renamed: 0,
    skipped: 0,
    errors: 0,
    skip_reasons: {},
    expires_at: null,
    message: "",
  };
}

export function useMediaRetroRename(fetchers = varsayilanUclar, { pollMs = 3000 } = {}) {
  const uc = { ...varsayilanUclar, ...fetchers };
  const plan = ref(null);
  const planLoading = ref(false);
  const planError = ref("");
  const lastError = ref("");
  const history = ref([]);
  const job = reactive(bosIs());
  let timer = null;

  const running = computed(() => !!job.key && job.state === "running");
  const canRollback = computed(() => history.value.length > 0 && !running.value);

  async function loadPlan(limit = 200) {
    planLoading.value = true;
    planError.value = "";
    try {
      plan.value = await uc.plan({ limit });
    } catch (e) {
      planError.value = e?.message || "Plan yüklenemedi";
      plan.value = null;
    } finally {
      planLoading.value = false;
    }
    return plan.value;
  }

  async function loadHistory() {
    try {
      const d = await uc.history();
      history.value = d.jobs || [];
    } catch (e) {
      console.warn("retro-rename history failed:", e?.message || e);
    }
    return history.value;
  }

  function resetJob() {
    stopPolling();
    Object.assign(job, bosIs());
  }

  function stopPolling() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  function startPolling(jobKey) {
    stopPolling();
    timer = setInterval(async () => {
      try {
        const d = await uc.status({ job_key: jobKey });
        Object.assign(job, {
          state: d.state || "running",
          dry_run: !!d.dry_run,
          total: d.total || 0,
          processed: d.processed || 0,
          renamed: d.renamed || 0,
          skipped: d.skipped || 0,
          errors: d.errors || 0,
          skip_reasons: d.skip_reasons || {},
          expires_at: d.expires_at || null,
          message: d.message || "",
        });
        if (TERMINAL.has(d.state)) {
          stopPolling();
          await Promise.all([loadHistory(), loadPlan()]);
        }
      } catch (e) {
        console.warn("retro-rename polling failed:", e?.message || e);
      }
    }, pollMs);
  }

  async function start({ dryRun = false, batchSize = 200 } = {}) {
    lastError.value = "";
    try {
      const d = await uc.start({ dry_run: dryRun ? 1 : 0, batch_size: batchSize });
      Object.assign(job, bosIs(), { key: d.job_key, mode: "rename", state: "running", dry_run: !!d.dry_run, total: d.total || 0 });
      startPolling(d.job_key);
      return d;
    } catch (e) {
      lastError.value = e?.message || "Başlatılamadı";
      return null;
    }
  }

  async function stop() {
    if (!job.key) return;
    try {
      await uc.stop({ job_key: job.key });
    } catch (e) {
      lastError.value = e?.message || "Durdurulamadı";
    }
  }

  async function rollback(jobKey) {
    lastError.value = "";
    try {
      const d = await uc.rollback({ job_key: jobKey });
      Object.assign(job, bosIs(), { key: d.job_key, mode: "rollback", state: "running" });
      startPolling(d.job_key);
      return d;
    } catch (e) {
      lastError.value = e?.message || "Geri alınamadı";
      return null;
    }
  }

  onUnmounted(stopPolling);

  return { plan, planLoading, planError, lastError, loadPlan, history, loadHistory, canRollback, job, running, start, stop, rollback, resetJob };
}
```

> `onUnmounted` bileşen dışında çağrılırsa Vue uyarı verir; testte `getCurrentInstance()` yoksa atla: `if (getCurrentInstance()) onUnmounted(stopPolling);` (import `getCurrentInstance`).

- [ ] **Step 4: Run** — test PASS; `npm run lint` temiz.
- [ ] **Step 5: Commit (admin-panel)** — `feat(media): useMediaRetroRename composable`

---

### Task 9: `MediaRetroRenameCard` + görünüme yerleşim + i18n

**Files:**
- Create: `admin-panel/frontend/src/components/media/MediaRetroRenameCard.vue`
- Modify: `admin-panel/frontend/src/views/system/MediaOptimizeView.vue` (import + `<!-- ── İş ilerlemesi ── -->` bloğunun hemen ÜSTÜNE `<MediaRetroRenameCard v-if="auth.isAdmin" />`)
- Modify: `src/i18n/locales/tr.js`, `en.js` (`mediaRetroRename` kökü)

**Interfaces:**
- Consumes: `useMediaRetroRename()` (Task 8), `ConfirmDialog` (`open`, `title`, `message`, `confirmLabel`, `tone`, `@confirm`, `@cancel`), `AppIcon`, `useAuthStore().isAdmin`.

- [ ] **Step 1: i18n anahtarları** (tr; en eşdeğerleri aynı anahtarlarla)

```js
mediaRetroRename: {
  title: "Eski adlandırma",
  pending: "{count} dosya hâlâ tahmin edilebilir adla duruyor (0505.jpg gibi).",
  hint: "Yeni standarda taşı → eski linkler {days} gün yönlendirilir, sonra kapanır.",
  allDone: "Tüm dosyalar yeni adlandırma standardında.",
  preview: "Önizle",
  previewTitle: "Önizleme",
  stats: {
    renamable: "Taşınacak",
    refs: "Referans güncellenecek",
    orphans: "Yetim (referanssız)",
    diskMissing: "Diskte yok",
    collisions: "Çakışma",
    embedded: "Gömülü referans",
    readonly: "Sipariş geçmişi (dokunulmaz)",
    truncated: "Liste ilk {n} kayıtla sınırlı; sayılar tam.",
  },
  dryRun: "Önce prova (dry-run) çalıştır",
  cancel: "İptal",
  start: "Yeniden adlandırmayı başlat",
  confirmTitle: "Emin misiniz?",
  confirmMessage: "{count} dosya yeniden adlandırılacak, {refs} referans güncellenecek. Eski adresler {days} gün yönlendirilir. İş {days} gün içinde geri alınabilir.",
  confirmOk: "Başlat",
  running: "Çalışıyor",
  rollingBack: "Geri alınıyor",
  dryRunning: "Prova çalışıyor",
  stop: "Durdur",
  done: "Tamamlandı",
  partial: "Kısmen tamamlandı",
  stopped: "Durduruldu",
  error: "Hata",
  renamed: "Taşındı",
  skipped: "Atlandı",
  errors: "Hata",
  redirectUntil: "Yönlendirme {date} tarihine kadar",
  rollback: "Geri al",
  rollbackConfirm: "{count} dosya eski adına döndürülecek. Devam?",
  close: "Kapat",
  skip: {
    disk_missing: "Diskte yok",
    collision: "Çakışma",
    quarantined: "Karantinada",
    not_legacy: "Zaten yeni",
  },
},
```

- [ ] **Step 2: Bileşen**

```vue
<script setup>
  import { computed, onMounted, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import AppIcon from "@/components/common/AppIcon.vue";
  import ConfirmDialog from "@/components/common/ConfirmDialog.vue";
  import { useMediaRetroRename } from "@/composables/useMediaRetroRename";
  import { formatDay } from "@/utils/dateFormat";

  const DAYS = 90;
  const { t, locale } = useI18n();
  const r = useMediaRetroRename();

  const previewOpen = ref(false);
  const dryRun = ref(false);
  const confirmOpen = ref(false);
  const rollbackOpen = ref(false);
  const rollbackTarget = ref(null);

  onMounted(() => {
    r.loadPlan();
    r.loadHistory();
  });

  const pendingCount = computed(() => r.plan.value?.total ?? null);
  const percent = computed(() => (r.job.total ? Math.round((r.job.processed / r.job.total) * 100) : 0));
  const terminal = computed(() => !!r.job.key && !r.running.value);
  const refsTotal = computed(() => (r.plan.value?.refs_exact || 0) + (r.plan.value?.refs_embedded || 0));

  function openPreview() {
    previewOpen.value = true;
    r.loadPlan();
  }
  function askStart() {
    confirmOpen.value = true;
  }
  async function onConfirm() {
    confirmOpen.value = false;
    previewOpen.value = false;
    await r.start({ dryRun: dryRun.value });
  }
  function askRollback(job) {
    rollbackTarget.value = job;
    rollbackOpen.value = true;
  }
  async function onRollback() {
    rollbackOpen.value = false;
    if (rollbackTarget.value) await r.rollback(rollbackTarget.value.job_key);
  }
  const jobTitle = computed(() => {
    if (r.job.mode === "rollback") return t("mediaRetroRename.rollingBack");
    if (r.running.value) return r.job.dry_run ? t("mediaRetroRename.dryRunning") : t("mediaRetroRename.running");
    return t(`mediaRetroRename.${r.job.state === "completed" ? "done" : r.job.state || "done"}`);
  });
</script>

<template>
  <div class="card mb-3 mrr" data-testid="retro-rename-card">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h3 class="font-semibold">{{ t("mediaRetroRename.title") }}</h3>
        <p v-if="pendingCount === null" class="text-sm opacity-70">…</p>
        <p v-else-if="pendingCount === 0" class="text-sm text-emerald-700 dark:text-emerald-300">
          {{ t("mediaRetroRename.allDone") }}
        </p>
        <template v-else>
          <p class="text-sm">{{ t("mediaRetroRename.pending", { count: pendingCount }) }}</p>
          <p class="text-xs opacity-70">{{ t("mediaRetroRename.hint", { days: DAYS }) }}</p>
        </template>
        <p v-if="r.lastError.value" class="text-sm text-red-600">{{ r.lastError.value }}</p>
      </div>
      <button
        v-if="pendingCount > 0 && !r.running.value"
        type="button"
        class="btn btn-secondary"
        @click="openPreview"
      >
        {{ t("mediaRetroRename.preview") }}
      </button>
    </div>

    <!-- Önizleme -->
    <div v-if="previewOpen && r.plan.value" class="mt-3 border-t pt-3">
      <strong>{{ t("mediaRetroRename.previewTitle") }}</strong>
      <dl class="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-2 text-sm">
        <div><dt class="opacity-70">{{ t("mediaRetroRename.stats.renamable") }}</dt><dd><b>{{ r.plan.value.renamable }}</b></dd></div>
        <div><dt class="opacity-70">{{ t("mediaRetroRename.stats.refs") }}</dt><dd><b>{{ refsTotal }}</b></dd></div>
        <div><dt class="opacity-70">{{ t("mediaRetroRename.stats.orphans") }}</dt><dd><b>{{ r.plan.value.orphans }}</b></dd></div>
        <div><dt class="opacity-70">{{ t("mediaRetroRename.stats.diskMissing") }}</dt><dd><b>{{ r.plan.value.disk_missing }}</b></dd></div>
        <div><dt class="opacity-70">{{ t("mediaRetroRename.stats.collisions") }}</dt><dd><b>{{ r.plan.value.collisions }}</b></dd></div>
        <div><dt class="opacity-70">{{ t("mediaRetroRename.stats.readonly") }}</dt><dd><b>{{ r.plan.value.refs_readonly }}</b></dd></div>
      </dl>
      <label class="flex items-center gap-2 mt-3 text-sm">
        <input v-model="dryRun" type="checkbox" /> {{ t("mediaRetroRename.dryRun") }}
      </label>
      <div class="flex justify-end gap-2 mt-3">
        <button type="button" class="btn btn-ghost" @click="previewOpen = false">{{ t("mediaRetroRename.cancel") }}</button>
        <button type="button" class="btn btn-primary" :disabled="!r.plan.value.renamable" @click="askStart">
          {{ t("mediaRetroRename.start") }}
        </button>
      </div>
    </div>

    <!-- İlerleme / sonuç -->
    <div v-if="r.job.key" class="mt-3 border-t pt-3">
      <div class="flex items-center justify-between">
        <strong>{{ jobTitle }}</strong>
        <span class="text-sm">
          {{ r.job.processed }} / {{ r.job.total }} — %{{ percent }}
          <button v-if="terminal" type="button" class="ml-2" :title="t('mediaRetroRename.close')" @click="r.resetJob()">
            <AppIcon name="x" :size="14" />
          </button>
        </span>
      </div>
      <div class="mo__progress"><span class="mo__progress-fill" :style="{ width: percent + '%' }" /></div>
      <div class="flex flex-wrap gap-3 text-sm mt-1">
        <span>{{ t("mediaRetroRename.renamed") }}: <b>{{ r.job.renamed }}</b></span>
        <span>{{ t("mediaRetroRename.skipped") }}: <b>{{ r.job.skipped }}</b></span>
        <span v-if="r.job.errors" class="text-red-600">{{ t("mediaRetroRename.errors") }}: <b>{{ r.job.errors }}</b></span>
      </div>
      <div v-if="Object.keys(r.job.skip_reasons).length" class="mo__reasons mt-1">
        <span v-for="(count, reason) in r.job.skip_reasons" :key="reason" class="mo__chip">
          {{ t(`mediaRetroRename.skip.${reason}`) }} <b>{{ count }}</b>
        </span>
      </div>
      <p v-if="r.job.message" class="text-sm mt-1 opacity-80">{{ r.job.message }}</p>
      <p v-if="terminal && !r.job.dry_run && r.job.mode === 'rename' && r.job.expires_at" class="text-sm mt-1">
        {{ t("mediaRetroRename.redirectUntil", { date: formatDay(r.job.expires_at, locale) }) }}
      </p>
      <button v-if="r.running.value && r.job.mode === 'rename'" type="button" class="btn btn-ghost mt-2" @click="r.stop()">
        {{ t("mediaRetroRename.stop") }}
      </button>
    </div>

    <!-- Geri alınabilir işler -->
    <div v-if="r.canRollback.value" class="mt-3 border-t pt-3 text-sm">
      <div v-for="j in r.history.value" :key="j.job_key" class="flex items-center justify-between py-1">
        <span>{{ j.count }} · {{ t("mediaRetroRename.redirectUntil", { date: formatDay(j.expires_at, locale) }) }}</span>
        <button type="button" class="btn btn-ghost btn-sm" @click="askRollback(j)">{{ t("mediaRetroRename.rollback") }}</button>
      </div>
    </div>

    <ConfirmDialog
      v-model:open="confirmOpen"
      :title="t('mediaRetroRename.confirmTitle')"
      :message="t('mediaRetroRename.confirmMessage', { count: r.plan.value?.renamable || 0, refs: refsTotal, days: DAYS })"
      :confirm-label="t('mediaRetroRename.confirmOk')"
      tone="warning"
      @confirm="onConfirm"
      @cancel="confirmOpen = false"
    />
    <ConfirmDialog
      v-model:open="rollbackOpen"
      :title="t('mediaRetroRename.rollback')"
      :message="t('mediaRetroRename.rollbackConfirm', { count: rollbackTarget?.count || 0 })"
      :confirm-label="t('mediaRetroRename.rollback')"
      tone="danger"
      @confirm="onRollback"
      @cancel="rollbackOpen = false"
    />
  </div>
</template>
```

> `formatDay(value, locale)` imzasını `@/utils/dateFormat` içinde doğrula; farklıysa ona uy. `btn` sınıfları projede yoksa `MediaOptimizeView`'daki mevcut buton sınıflarını kullan (`mo__btn` vb.) — görsel tutarlılık için aynı ekrandaki butonlarla **aynı sınıf**.

- [ ] **Step 3: View'a yerleştir** — `MediaOptimizeView.vue` `<script setup>`: `import MediaRetroRenameCard from "@/components/media/MediaRetroRenameCard.vue"; import { useAuthStore } from "@/stores/auth"; const auth = useAuthStore();`. Template'te `<!-- ── İş ilerlemesi ── -->` yorumunun hemen üstüne: `<MediaRetroRenameCard v-if="auth.isAdmin" />`.
- [ ] **Step 4: Lint + test** — `npm run lint && npm test`.
- [ ] **Step 5: Tarayıcı doğrulaması** — `npm run build && cd ../../docker && docker compose build admin-panel && docker compose up -d admin-panel`; panelde Sistem → Medya Optimizasyonu: kart "2.843 dosya…" gösteriyor; Önizle sayıları getiriyor; satıcı hesabında kart yok.
- [ ] **Step 6: Commit (admin-panel)** — `feat(media): retro-rename kartı — önizle/onay/ilerleme/geri al`

---

### Task 10: API tipleri senkronu + uçtan uca lokal koşu

**Files:**
- Regenerate: `admin-panel/frontend/src/lib/api/types.gen.ts` (`npm run sync:api`)

- [ ] **Step 1:** `cd admin-panel/frontend && npm run sync:api && npm run sync:api:check` → 6 yeni uç `types.gen.ts`'te.
- [ ] **Step 2:** Commit (admin-panel) — `chore(api): retro-rename uçları için tip senkronu`
- [ ] **Step 3: Uçtan uca (lokal, gerçek veri):** panelden **Önizle** → **prova (dry-run)** → progress `completed`, `errors: 0` → gerçek **Başlat** → bitince:
  ```
  docker exec istoc-dev-backend-1 bench --site istoc.localhost mariadb -e "select count(*) from tabFile where is_private=0 and left(file_url,7)='/files/' and left(file_url,13)<>'/files/media/' and substring_index(substring_index(file_url,'/',-1),'.',1) not regexp '^[0-9a-f]{32}\$'"   # → 0
  docker exec istoc-dev-backend-1 sh -c 'cd sites/istoc.localhost/public/files && find . -maxdepth 1 -type f | wc -l'   # → 0 ya da yalnız hash'li
  curl -sI http://istoc.localhost/files/<eski-bir-ad> | grep -E "HTTP|Location"   # → 301 + yeni yol
  curl -sI http://istoc.localhost/files/<ab>/<hash>.jpg | grep -E "HTTP|Cache-Control"   # → 200, immutable
  ```
  Storefront'ta 20 ürün sayfası açılıyor, görseller yükleniyor; `refs.find_dangling()` → 0.
- [ ] **Step 4: Geri al provası:** panelden **Geri al** → sayılar eski hâline döndü (yukarıdaki SQL tekrar 2.843). Sonra tekrar **Başlat** (son durum: taşınmış).
- [ ] **Step 5:** Sonuçları `docs/reports/` altına kısa rapor olarak yaz: `docs/reports/95-retro-rename-lokal-kosu.md` (sayılar, süre, hata, curl çıktıları). Commit — `docs(media): retro-rename lokal koşu raporu`.

---

### Task 11: Plane güncellemesi

- [ ] **Step 1:** MOGEM-582 (`0e4bf7ea-a117-4e8f-ae54-a88be081a7c5`, proje `bec934dc-feec-48e5-8402-4d1f41cb197a`) altına alt görev: **"[G-16]-17a Retro-rename: eski adların içerik-adresli ada taşınması + 301 köprüsü + admin kartı"** — açıklamada spec + plan yolları, ortam sırası (lokal tamam / alpha / prod bekliyor).
- [ ] **Step 2:** MOGEM-582 açıklamasındaki "Türev yeri" maddesini gerçek yola göre düzelt; "Ertelenen" paragrafını "Alt görev MOGEM-xxx'te uygulandı" yap.
- [ ] **Step 3:** Yorum (düz metin, emoji yok — hafıza notu): "Kod tabanı doğrulaması (tarih) — Yapıldı: belge §5 düzeltildi; retro-rename aracı ve 301 köprüsü lokalde koştu (2.843 dosya). Yapılmadı: alpha/prod koşusu (ayrı bakım penceresi)."
- [ ] **Step 4:** Kullanıcı onayıyla MOGEM-582 → Done (alt görev açık kalır, alpha/prod koşusu onu kapatır).

---

## Self-review notları

- **Spec kapsaması:** §4.1 → T2/T4; §4.2 → T1; §4.3 → T3; §4.4 → T5; §4.5 → T5; §4.6 → T6; §4.7 → T8/T9/T10; §5 ortam sırası → T10 (lokal) + T11 (alpha/prod ayrı pencere, plan dışı operasyon); §6 hata tablosu → T4 (`disk_missing/collision/quarantined/exception/stop/eşik`), M-A arşiv yolu taşıma **kapsama alınmadı** — `archive.relative_path_for` eski URL'yi gösterir; lokal/alpha'da M-A arşivi boş (report 06). Prod'da arşiv varsa T10 öncesi `archive.purge_expired` koşulmalı; T11 açıklamasına not düş. §7 testler → T2-T6, T8; §9 belgeler → T7, T11.
- **Tip tutarlılığı:** `read_progress` şekli T4'te tanımlı, T8 polling aynı alanları okuyor (`renamed/skipped/errors/skip_reasons/expires_at/message/state`); `start_retro_rename` → `{job_key,total,dry_run}`, composable `d.job_key/d.total/d.dry_run`; `rollback_retro_rename` → `{job_key}` (rollback anahtarı) ve composable `mode: "rollback"`; `retro_rename_history` → `{jobs:[{job_key,count,expires_at}]}`.
- **Dedup-rollback tuzağı** T4 notunda kilitlendi (`file_rows` alanı + sınırlı `File` güncellemesi) — uygulayıcı bu testi yazmadan T4'ü kapatmasın.
