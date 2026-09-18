"""Yayın sonrası eski public görsellerin kaldığı yerden süren türev üretimi.

Orijinaller değiştirilmez. Küçük batch'ler media-image-bulk kuyruğunda çalışır;
cursor ve sayaçlar veritabanında saklanır. Scheduler, worker kesintisi veya
kuyruk kesintisi sonrasında aynı checkpoint'ten devam eder.
"""

from __future__ import annotations

import json
import os
import time

import frappe
from frappe.utils import now_datetime
from frappe.utils.background_jobs import get_redis_conn

from tradehub_core.media import ownership, pipeline_bridge, pipeline_flags, upload_policy
from tradehub_core.media.pipeline.core.queues import IMAGE_BULK

STATE_KEY = "media_rendition_backfill_avif_v2"
LOCK_KEY = "media:rendition-backfill:v2"
BATCH_SIZE = 25
BATCH_SECONDS = 90
MAX_ATTEMPTS = IMAGE_BULK.max_attempts
MAX_ERROR_EXAMPLES = 20
TERMINAL = {"completed", "completed_with_errors"}


def status() -> dict:
	value = frappe.db.get_global(STATE_KEY)
	return json.loads(value) if value else {}


def _save(state: dict) -> None:
	state["updated_at"] = str(now_datetime())
	frappe.db.set_global(STATE_KEY, json.dumps(state, ensure_ascii=False))
	frappe.db.commit()


def _new_state() -> dict:
	return {
		"status": "running",
		"cursor": "",
		"current_file": "",
		"attempts": 0,
		"scanned": 0,
		"generated": 0,
		"already_ready": 0,
		"skipped": 0,
		"failed": 0,
		"skip_reasons": {},
		"error_examples": [],
		"started_at": str(now_datetime()),
	}


def start_after_migrate() -> dict:
	"""Şema/profil kurulumu bittikten sonra bir kez başlat veya devam et."""
	if not pipeline_flags.is_enabled("rendition_on_upload"):
		return {"status": "disabled"}
	if not status():
		_save(_new_state())
	return enqueue_pending()


def enqueue_pending() -> dict:
	"""Cron ve batch zinciri için aynı, site kapsamlı tekilleştirilmiş kuyruk."""
	state = status()
	if not state or state.get("status") in TERMINAL:
		return state
	pipeline_flags.clear_cache()
	if not pipeline_flags.is_enabled("rendition_on_upload"):
		return {**state, "status": "paused"}
	try:
		# Migrate sırasında Redis yoksa Frappe işi senkron çalıştırır. Buna
		# izin vermeyiz: yayın isteği binlerce görselin üretimini beklememeli.
		get_redis_conn().ping()
		frappe.enqueue(
			"tradehub_core.media.rendition_backfill.run_batch",
			queue=IMAGE_BULK.name,
			timeout=IMAGE_BULK.timeout_seconds,
			enqueue_after_commit=False,
			job_id=f"{STATE_KEY}:{state['cursor']}:{state['attempts']}",
			deduplicate=True,
		)
	except Exception:
		# Checkpoint DB'de durur; sonraki cron/migrate kuyruğu tekrar dener.
		frappe.log_error(title="Media rendition backfill enqueue failed", message=frappe.get_traceback())
		return {**state, "queue_pending": True}
	return state


def _candidates(cursor: str, limit: int) -> list[str]:
	extensions = tuple(ext.lstrip(".") for ext, kind in upload_policy.EXTENSIONS.items() if kind == "image")
	return [
		row[0]
		for row in frappe.db.sql(
			"""SELECT name FROM tabFile
			WHERE name > %(cursor)s AND is_folder=0 AND is_private=0
			  AND file_url LIKE '/files/%%'
			  AND COALESCE(th_media_state, '') NOT IN ('Trashed', 'Deleted')
			  AND th_trashed_at IS NULL
			  AND LOWER(SUBSTRING_INDEX(file_name, '.', -1)) IN %(extensions)s
			ORDER BY name LIMIT %(limit)s""",
			{"cursor": cursor, "limit": limit, "extensions": extensions},
		)
	]


def _ready(doc, content_hash: str, slot: str) -> bool:
	"""Güncel AVIF politikasıyla tamamlanmış, diskteki aktif sürümü atla."""
	from tradehub_core.media.pipeline.image.render import load_slot_policy

	policy = load_slot_policy(slot)
	rows = frappe.db.sql(
		"""SELECT r.file_url, r.format, v.policy_snapshot FROM `tabMedia Asset` a
		JOIN `tabMedia Version` v ON v.name=a.active_version
		JOIN `tabMedia Rendition` r ON r.asset=a.name AND r.version_hash=a.active_version
		WHERE a.content_sha256=%s AND a.slot_key=%s AND a.state='ready'
		  AND COALESCE(a.owner_seller, '')=%s
		  AND v.engine_version=%s
		  AND EXISTS (SELECT 1 FROM `tabMedia Quality Report` q
		              WHERE q.asset=a.name AND q.version=a.active_version)
		  AND r.state NOT IN ('purged', 'trashed')""",
		(content_hash, slot, ownership.store_of(doc.owner) or "", pipeline_bridge._engine_version()),
	)
	return bool(rows) and all(
		fmt.lower() == "avif"
		and json.loads(snapshot or "{}") == policy
		and url
		and url.startswith("/files/")
		and os.path.isfile(frappe.get_site_path("public", url.lstrip("/")))
		for url, fmt, snapshot in rows
	)


def _process_file(name: str) -> tuple[str, str]:
	if not frappe.db.exists("File", name):
		return "skipped", "deleted"
	doc = frappe.get_doc("File", name)
	# Dosya taramadan sonra private/arşiv yapılmış olabilir; güncel kaydı kullan.
	if doc.get("th_trashed_at") or doc.get("th_media_state") in {"Trashed", "Deleted"}:
		return "skipped", "archived"
	slot = pipeline_bridge._resolve_scope(doc)
	if not slot:
		return "skipped", "out_of_scope"
	if not pipeline_flags.is_slot_enabled(slot) or not pipeline_flags.is_store_enabled(
		ownership.store_of(doc.owner)
	):
		return "skipped", "scope_disabled"
	content_hash = pipeline_bridge.content_fingerprint(doc)
	if not content_hash:
		return "failed", "source_unreadable"
	if _ready(doc, content_hash, slot):
		return "already_ready", ""
	pipeline_bridge._run_rendition_job(doc.file_url, force=True, file_name=doc.name, backfill=True)
	if _ready(doc, content_hash, slot):
		return "generated", ""
	return "failed", "generation_incomplete"


def run_batch() -> dict:
	# Site cache temizliği üretim sürerken kilidi silebilir. İş kilidi,
	# Frappe cache yerine kalıcı iş kuyruğunun Redis bağlantısında tutulur.
	lock = get_redis_conn().lock(f"{frappe.local.site}:{LOCK_KEY}", timeout=IMAGE_BULK.timeout_seconds + 60)
	if not lock.acquire(blocking=False):
		return {"status": "busy"}
	try:
		state = status()
		if not state or state.get("status") in TERMINAL:
			return state
		started = time.monotonic()
		candidates = _candidates(state["cursor"], BATCH_SIZE)
		for name in candidates:
			pipeline_flags.clear_cache()
			if not pipeline_flags.is_enabled("rendition_on_upload"):
				state["status"] = "paused"
				_save(state)
				return state
			state["status"] = "running"
			if state["current_file"] != name:
				state.update(current_file=name, attempts=0)
			if state["attempts"] >= MAX_ATTEMPTS:
				outcome, reason = "failed", "worker_interrupted"
			else:
				# Önce denemeyi kaydet: worker öldürülse de aynı bozuk dosya
				# sonsuza dek kuyruğun geri kalanını bloke edemez.
				state["attempts"] += 1
				_save(state)
				try:
					outcome, reason = _process_file(name)
					if outcome == "failed" and state["attempts"] < MAX_ATTEMPTS:
						break
				except Exception as exc:
					frappe.db.rollback()
					outcome, reason = "failed", type(exc).__name__
					frappe.log_error(
						title="Media rendition backfill file failed", message=frappe.get_traceback()
					)
					if state["attempts"] < MAX_ATTEMPTS:
						break
			state[outcome] += 1
			state["scanned"] += 1
			if outcome == "skipped":
				state["skip_reasons"][reason] = state["skip_reasons"].get(reason, 0) + 1
			if outcome == "failed" and len(state["error_examples"]) < MAX_ERROR_EXAMPLES:
				state["error_examples"].append({"file": name, "reason": reason})
			state.update(cursor=name, current_file="", attempts=0)
			_save(state)
			if time.monotonic() - started >= BATCH_SECONDS:
				break
		if not candidates or not _candidates(state["cursor"], 1):
			state["status"] = "completed_with_errors" if state["failed"] else "completed"
			state["finished_at"] = str(now_datetime())
			_save(state)
	finally:
		lock.release()
	if state.get("status") not in TERMINAL:
		enqueue_pending()
	return state
