"""MOGEM-570 — üretim medya migration çalıştırıcısı.

Akış sürümlü ve özetli planı ``preflight -> dry-run -> validate -> wet-run``
kapısından geçirir. Her batch ayrı ``media-image-bulk`` RQ işidir ve sonucu
``Media Migration Run``/``Media Migration Batch`` kayıtlarına yazılır. Bu
sayede worker restart'ı ilerlemeyi kaybettirmez; stop/resume ve exact rollback
aynı kalıcı checkpoint'lerden yürür.
"""

from __future__ import annotations

import json
import os
import pickle
import shutil
from collections.abc import Mapping, Sequence
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime

from tradehub_core.media import archive, presets, runner, trash
from tradehub_core.media.pipeline.core.queues import IMAGE_BULK, IMAGE_LIVE
from tradehub_core.media.pipeline.migration.backfill import (
	PLAN_SCHEMA_VERSION,
	BackfillError,
	BackfillPlan,
	PlatformNotificationSink,
	StopPolicy,
	build_notices,
	evaluate_stop,
)

ACTIVE_KEY = "tradehub:media_migration:active"
ACTIVE_TTL = 24 * 3600
MAX_BATCH_SIZE = 2000
HEADROOM_MIN_BYTES = 64 * 1024 * 1024

ACTIVE_STATUSES = (
	"planned",
	"queued",
	"running",
	"stopping",
	"rolling_back",
)
RESUMABLE_STATUSES = ("paused", "halted", "stopped", "failed")
ROLLBACK_SOURCE_STATUSES = (
	"completed",
	"validated",
	"validation_failed",
	"halted",
	"stopped",
	"failed",
	"rollback_failed",
)

_REFRESH_LOCK = """
local current = redis.call('get', KEYS[1])
if not current then
  local created = redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2])
  return created and 1 or 0
end
if current == ARGV[1] then
  redis.call('expire', KEYS[1], ARGV[2])
  return 1
end
return 0
"""

_RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _dumps(value: Any) -> str:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: str | None, default: Any) -> Any:
	try:
		return json.loads(value or "")
	except (TypeError, ValueError):
		return default


def _cache_key() -> bytes:
	return frappe.cache.make_key(ACTIVE_KEY)


def _lock_payload(run_key: str) -> bytes:
	# RedisWrapper.get_value ile aynı pickle zarfı; ham SET yalnız NX/EX için.
	return pickle.dumps(str(run_key))


def _clear_local_cache() -> None:
	try:
		frappe.local.cache.pop(_cache_key(), None)
	except (AttributeError, TypeError):
		pass


def claim_active(run_key: str, ttl: int = ACTIVE_TTL) -> bool:
	"""Site başına tek aktif migration'ı atomik olarak sahiplen."""
	try:
		_clear_local_cache()
		claimed = bool(frappe.cache.set(_cache_key(), _lock_payload(run_key), nx=True, ex=max(1, int(ttl))))
		_clear_local_cache()
		return claimed
	except Exception:
		frappe.log_error(title="Media migration active lock claim failed", message=frappe.get_traceback())
		return False


def refresh_active(run_key: str, ttl: int = ACTIVE_TTL) -> bool:
	"""Boş kilidi al veya yalnız aynı sahibin süresini uzat."""
	try:
		_clear_local_cache()
		owned = bool(
			frappe.cache.eval(_REFRESH_LOCK, 1, _cache_key(), _lock_payload(run_key), max(1, int(ttl)))
		)
		_clear_local_cache()
		return owned
	except Exception:
		frappe.log_error(title="Media migration active lock refresh failed", message=frappe.get_traceback())
		return False


def release_active(run_key: str) -> bool:
	"""Compare-and-delete: başka koşumun kilidi yanlışlıkla silinemez."""
	try:
		_clear_local_cache()
		released = bool(frappe.cache.eval(_RELEASE_LOCK, 1, _cache_key(), _lock_payload(run_key)))
		_clear_local_cache()
		return released
	except Exception:
		frappe.log_error(title="Media migration active lock release failed", message=frappe.get_traceback())
		return False


def _clamp_batch_size(value: int | str | None) -> int:
	try:
		size = int(value or 200)
	except (TypeError, ValueError) as exc:
		raise BackfillError("batch_size tam sayı olmalıdır") from exc
	if not 1 <= size <= MAX_BATCH_SIZE:
		raise BackfillError(f"batch_size 1..{MAX_BATCH_SIZE} aralığında olmalıdır")
	return size


def _rows_for_names(names: Sequence[str]) -> dict[str, Any]:
	fields = [
		"name",
		"file_url",
		"file_size",
		"is_private",
		"attached_to_doctype",
		"content_hash",
		"th_optimized_at",
		"th_original_size",
	]
	out: dict[str, Any] = {}
	for offset in range(0, len(names), 500):
		part = list(names[offset : offset + 500])
		for row in frappe.get_all("File", filters={"name": ["in", part]}, fields=fields, limit_page_length=0):
			out[row.name] = row
	return out


def _expected_urls(plan: BackfillPlan) -> dict[str, str]:
	out: dict[str, str] = {}
	for row in plan.records:
		name = str(row.get("file_name") or "")
		if name:
			out[name] = str(row.get("file_url") or "")
	return out


def _workers_from_registry(connection: Any, wanted: Sequence[str] | set[str]) -> list[str]:
	"""Worker adlarını RQ'nun kuyruk-üyelik set'inden (`rq:workers:<kuyruk>`) oku."""
	adlar: list[str] = []
	for kuyruk in wanted:
		try:
			uyeler = connection.smembers(f"rq:workers:{kuyruk}")
		except Exception:
			# Redis erişim hatası preflight'ı düşürmesin — asıl sağlık kontrolü
			# kuyruk derinliği okumasında zaten patlar; burada yalnız loglanır.
			frappe.log_error(title="migration_runtime._workers_from_registry", message=frappe.get_traceback())
			continue
		for uye in uyeler or ():
			ad = uye.decode() if isinstance(uye, bytes) else str(uye)
			adlar.append(ad.rsplit(":", 1)[-1])
	return adlar


def _queue_health() -> dict[str, Any]:
	"""Redis erişimi, kuyruk derinlikleri ve bulk worker görünürlüğü."""
	from frappe.utils.background_jobs import get_queue, get_queue_list, get_redis_conn
	from rq import Worker

	bulk = get_queue(IMAGE_BULK.name)
	live = get_queue(IMAGE_LIVE.name)
	connection = get_redis_conn()
	wanted = {
		q.decode() if isinstance(q, bytes) else str(q)
		for q in get_queue_list([IMAGE_BULK.name], build_queue_name=True)
	}
	workers = Worker.all(connection=connection)
	matching = []
	for worker in workers:
		queue_names = getattr(worker, "queue_names", ())
		if callable(queue_names):
			queue_names = queue_names()
		names = {q.decode() if isinstance(q, bytes) else str(q) for q in queue_names}
		if names & wanted:
			matching.append(str(worker.name))
	if not matching:
		# Bu ortamın RQ sürümünde worker hash'i `queues` alanını taşımıyor ve
		# `Worker.queue_names()` boş dönüyor (ölçüm 2026-08-26: 8 worker, hepsi
		# boş) — yukarıdaki kesişim çalışan worker'ı "yok" sanıp preflight'ı
		# yanlış negatifle düşürüyordu. Kuyruğa üyelik set'i (`rq:workers:<k>`)
		# her RQ sürümünde worker kaydında tutulur; ikinci kaynak oradan okunur.
		matching = _workers_from_registry(connection, wanted)
	return {
		"bulk_queue": IMAGE_BULK.name,
		"bulk_depth": int(bulk.count),
		"live_queue": IMAGE_LIVE.name,
		"live_depth": int(live.count),
		"bulk_workers": matching,
	}


def preflight(plan_data: Mapping[str, Any], batch_size: int | str | None = None) -> dict:
	"""Planı, dosya kapsamını, disk alanını ve kuyruk topolojisini salt okunur doğrula."""
	errors: list[dict[str, Any]] = []
	warnings: list[dict[str, Any]] = []
	try:
		plan = BackfillPlan.from_plan_json(plan_data)
	except (BackfillError, TypeError, ValueError) as exc:
		return {
			"ok": False,
			"errors": [{"code": "invalid_plan", "message": str(exc)}],
			"warnings": [],
		}

	batch_plan = plan_data.get("batch_plan") or {}
	if not isinstance(batch_plan, Mapping):
		batch_plan = {}
	try:
		size = _clamp_batch_size(batch_size or batch_plan.get("batch_size"))
	except BackfillError as exc:
		return {
			"ok": False,
			"errors": [{"code": "invalid_batch_size", "message": str(exc)}],
			"warnings": [],
		}
	if not plan.a_class:
		errors.append({"code": "empty_a_class", "message": "A sınıfında işlenecek dosya yok."})
	if plan.unknown_count:
		errors.append(
			{
				"code": "unknown_records",
				"count": plan.unknown_count,
				"message": "BILINMIYOR kayıtlar tam disk probe ile sınıflandırılmalıdır.",
			}
		)
	if plan.unsupported_a:
		errors.append(
			{
				"code": "unsupported_a_prime",
				"count": len(plan.unsupported_a),
				"sample": [str(row.get("file_name") or "") for row in plan.unsupported_a[:20]],
				"message": "A_kapi_disi kayıtları mevcut runner ile güvenle işlenemez.",
			}
		)

	expected = _expected_urls(plan)
	missing_expected = [name for name in plan.a_class if not expected.get(name)]
	if missing_expected:
		errors.append(
			{
				"code": "missing_expected_url",
				"count": len(missing_expected),
				"sample": missing_expected[:20],
			}
		)

	rows = _rows_for_names(plan.a_class)
	missing = [name for name in plan.a_class if name not in rows]
	if missing:
		errors.append({"code": "missing_file_records", "count": len(missing), "sample": missing[:20]})

	from tradehub_core.media.inventory import EXCLUDED_DOCTYPES

	disk_missing: list[str] = []
	url_drift: list[str] = []
	out_of_scope: list[str] = []
	sensitive_twins: list[str] = []
	archive_bytes = 0
	for name in plan.a_class:
		row = rows.get(name)
		if not row:
			continue
		url = str(row.file_url or "")
		if expected.get(name) and url != expected[name]:
			url_drift.append(name)
		if int(row.is_private or 0) or not url.startswith("/files/"):
			out_of_scope.append(name)
		elif row.attached_to_doctype in EXCLUDED_DOCTYPES:
			out_of_scope.append(name)
		elif row.content_hash and runner._has_sensitive_twin(row.content_hash):
			sensitive_twins.append(name)
		try:
			path = trash._live_path(url)
		except Exception:
			path = ""
		if not path or not os.path.isfile(path):
			disk_missing.append(name)
		else:
			archive_bytes += os.path.getsize(path)

	for code, values in (
		("file_url_drift", url_drift),
		("out_of_scope", out_of_scope),
		("sensitive_content_twin", sensitive_twins),
		("disk_missing", disk_missing),
	):
		if values:
			errors.append({"code": code, "count": len(values), "sample": values[:20]})

	disk = shutil.disk_usage(frappe.get_site_path())
	required = archive_bytes + max(HEADROOM_MIN_BYTES, int(archive_bytes * 0.10))
	if disk.free < required:
		errors.append(
			{
				"code": "insufficient_disk",
				"required_bytes": required,
				"free_bytes": disk.free,
			}
		)

	queue: dict[str, Any] = {}
	try:
		queue = _queue_health()
		if not queue["bulk_workers"]:
			errors.append({"code": "bulk_worker_missing", "message": "media-image-bulk worker görünmüyor."})
		if queue["live_depth"] > 0:
			warnings.append(
				{
					"code": "live_queue_busy",
					"depth": queue["live_depth"],
					"message": "Koşum başlarsa ilk batch canlı kuyruk boşalana kadar duraklar.",
				}
			)
	except Exception as exc:
		errors.append({"code": "queue_unreachable", "message": str(exc)[:300]})

	return {
		"ok": not errors,
		"schema_version": PLAN_SCHEMA_VERSION,
		"plan_digest": plan.digest,
		"plan_id": str(plan_data.get("plan_id") or ""),
		"a_files": len(plan.a_class),
		"b_files": len(plan.b_class),
		"unsupported_a_files": len(plan.unsupported_a),
		"unknown_files": plan.unknown_count,
		"batch_size": size,
		"batch_count": len(plan.batches(size)),
		"archive_bytes_required": archive_bytes,
		"disk_free_bytes": disk.free,
		"disk_headroom_required": required,
		"queue": queue,
		"errors": errors,
		"warnings": warnings,
	}


def _approved_dry_run(run_key: str, digest: str) -> Any:
	if not run_key:
		frappe.throw(_("Gerçek koşum için approved_dry_run zorunludur."))
	doc = frappe.get_doc("Media Migration Run", run_key)
	if not int(doc.dry_run or 0) or doc.status != "validated":
		frappe.throw(_("Onay kaydı doğrulanmış bir kuru koşum değildir."))
	if doc.plan_digest != digest:
		frappe.throw(_("Kuru koşum ile gerçek koşum plan özetleri farklı."))
	return doc


def _active_db_run() -> str:
	if not frappe.db.table_exists("Media Migration Run"):
		return ""
	return str(frappe.db.get_value("Media Migration Run", {"status": ["in", ACTIVE_STATUSES]}, "name") or "")


def start(
	plan_data: Mapping[str, Any],
	*,
	dry_run: bool = True,
	batch_size: int | str | None = None,
	preset: str = presets.DEFAULT_PRESET,
	approved_dry_run: str = "",
	notify_sellers: bool = False,
) -> dict:
	"""Koşumu kaydet ve ilk batch'i commit sonrasında kuyruğa al."""
	if preset not in presets.PRESETS:
		frappe.throw(_("Geçersiz preset: {0}").format(preset))
	check = preflight(plan_data, batch_size=batch_size)
	if not check["ok"]:
		frappe.throw(_("Migration preflight başarısız: {0}").format(_dumps(check["errors"])))
	plan = BackfillPlan.from_plan_json(plan_data)
	size = int(check["batch_size"])
	if not dry_run:
		_approved_dry_run(approved_dry_run, plan.digest)
	active = _active_db_run()
	if active:
		frappe.throw(_("Zaten aktif bir medya migration koşumu var: {0}").format(active))

	run_key = f"mig-{frappe.generate_hash(length=20)}"
	if not claim_active(run_key):
		frappe.throw(_("Başka bir medya migration koşumu kilidi tutuyor."))

	now = now_datetime()
	deadline = add_days(now, presets.ARCHIVE_RETENTION_DAYS) if not dry_run else None
	try:
		doc = frappe.get_doc(
			{
				"doctype": "Media Migration Run",
				"run_key": run_key,
				"status": "queued",
				"dry_run": int(bool(dry_run)),
				"approved_dry_run": approved_dry_run or None,
				"requested_by": frappe.session.user,
				"plan_schema_version": PLAN_SCHEMA_VERSION,
				"plan_digest": plan.digest,
				"preset": preset,
				"notify_sellers": int(bool(notify_sellers)),
				"batch_size": size,
				"total_files": len(plan.a_class),
				"total_batches": len(plan.batches(size)),
				"next_batch_index": 1,
				"started_at": now,
				"last_heartbeat": now,
				"rollback_deadline": deadline,
				"archive_hold_until": deadline,
				"preflight_json": _dumps(check),
				"plan_json": _dumps(dict(plan_data)),
			}
		)
		for batch in plan.batches(size):
			doc.append(
				"batches",
				{
					"batch_index": batch.index,
					"job_key": f"{run_key}-{batch.index:04d}",
					"status": "queued" if batch.index == 1 else "planned",
					"total": batch.size,
					"file_names_json": _dumps(list(batch.file_names)),
					"changed_files_json": "[]",
				},
			)
		doc.insert(ignore_permissions=True)
		_enqueue_batch(run_key, 1, after_commit=True)
	except Exception:
		release_active(run_key)
		raise

	return {
		"run_key": run_key,
		"status": "queued",
		"dry_run": bool(dry_run),
		"plan_digest": plan.digest,
		"total_files": len(plan.a_class),
		"total_batches": len(plan.batches(size)),
		"queue": IMAGE_BULK.name,
	}


def _get_run(run_key: str) -> Any:
	if not run_key or not frappe.db.exists("Media Migration Run", run_key):
		frappe.throw(_("Migration koşumu bulunamadı: {0}").format(run_key))
	return frappe.get_doc("Media Migration Run", run_key)


def _get_batch(run: Any, index: int) -> Any:
	for batch in run.batches:
		if int(batch.batch_index or 0) == int(index):
			return batch
	frappe.throw(_("Migration batch bulunamadı: {0}/{1}").format(run.name, index))


def _set_run(run_key: str, values: Mapping[str, Any]) -> None:
	frappe.db.set_value("Media Migration Run", run_key, dict(values), update_modified=True)


def _set_batch(name: str, values: Mapping[str, Any]) -> None:
	frappe.db.set_value("Media Migration Batch", name, dict(values), update_modified=True)


def _enqueue_batch(run_key: str, index: int, *, after_commit: bool = False) -> None:
	frappe.enqueue(
		"tradehub_core.media.migration_runtime.execute_batch",
		queue=IMAGE_BULK.name,
		timeout=IMAGE_BULK.timeout_seconds,
		enqueue_after_commit=after_commit,
		# Resume aynı checkpoint'i yeniden kuyruğa koyabilir; RQ'nun bitmiş/failed
		# job kaydı sabit ID'yi bloke etmesin. Kalıcı idempotency anahtarı child
		# ``job_key`` alanıdır, teslimat ID'si her denemede benzersizdir.
		job_id=f"media-migration::{run_key}::{index:04d}::{frappe.generate_hash(length=8)}",
		run_key=run_key,
		batch_index=index,
	)


def _enqueue_rollback(run_key: str, index: int, *, after_commit: bool = False) -> None:
	frappe.enqueue(
		"tradehub_core.media.migration_runtime.execute_rollback_batch",
		queue=IMAGE_BULK.name,
		timeout=IMAGE_BULK.timeout_seconds,
		enqueue_after_commit=after_commit,
		job_id=f"media-migration-rollback::{run_key}::{index:04d}::{frappe.generate_hash(length=8)}",
		run_key=run_key,
		batch_index=index,
	)


def _live_depth() -> int:
	from frappe.utils.background_jobs import get_queue

	return int(get_queue(IMAGE_LIVE.name).count)


def _aggregate(run_key: str) -> dict[str, int]:
	rows = frappe.get_all(
		"Media Migration Batch",
		filters={"parent": run_key},
		fields=["processed", "optimized", "skipped", "errors", "original_bytes", "new_bytes"],
		limit_page_length=0,
	)
	return {
		field: sum(int(row.get(field) or 0) for row in rows)
		for field in ("processed", "optimized", "skipped", "errors", "original_bytes", "new_bytes")
	}


def _finish_or_enqueue_next(run_key: str, batch_index: int, decision: Any) -> None:
	run = _get_run(run_key)
	aggregate = _aggregate(run_key)
	next_index = batch_index + 1
	values: dict[str, Any] = {
		**aggregate,
		"next_batch_index": next_index,
		"last_heartbeat": now_datetime(),
	}
	if decision.halt:
		values.update(
			{
				"status": "halted",
				"stop_code": decision.code,
				"stop_reason": decision.reason,
			}
		)
		_set_run(run_key, values)
		frappe.db.commit()
		release_active(run_key)
		return

	# Stop isteği çalışan batch'i yarıda kesmez; tam checkpoint'ten sonra durur.
	current_status = frappe.db.get_value("Media Migration Run", run_key, "status")
	if current_status == "stopping":
		values.update(
			{"status": "stopped", "stop_code": "operator_stop", "stop_reason": _("Operatör durdurdu.")}
		)
		_set_run(run_key, values)
		frappe.db.commit()
		release_active(run_key)
		return

	if next_index > int(run.total_batches or 0):
		values.update({"status": "completed", "finished_at": now_datetime()})
		_set_run(run_key, values)
		frappe.db.commit()
		validate_run(run_key, automatic=True)
		return

	next_batch = _get_batch(run, next_index)
	_set_batch(next_batch.name, {"status": "queued"})
	values["status"] = "queued"
	_set_run(run_key, values)
	frappe.db.commit()
	_enqueue_batch(run_key, next_index)


def execute_batch(run_key: str, batch_index: int) -> dict:
	"""Tek checkpoint batch'ini çalıştır; RQ worker girişidir."""
	index = int(batch_index)
	if not refresh_active(run_key):
		raise RuntimeError(_("Migration koşum kilidi alınamadı."))
	run = _get_run(run_key)
	batch = _get_batch(run, index)

	# Aynı job_id yeniden teslim edilirse tamamlanmış batch ikinci kez yazılmaz.
	if batch.status in ("completed", "halted", "rolled_back"):
		return {"run_key": run_key, "batch": index, "status": batch.status, "idempotent": True}
	if run.status == "stopping":
		_set_run(
			run_key,
			{"status": "stopped", "stop_code": "operator_stop", "stop_reason": _("Operatör durdurdu.")},
		)
		_set_batch(batch.name, {"status": "planned"})
		frappe.db.commit()
		release_active(run_key)
		return {"run_key": run_key, "batch": index, "status": "stopped"}
	if index != int(run.next_batch_index or 1):
		raise RuntimeError(_("Sıra dışı migration batch'i: {0}").format(index))

	if _live_depth() > 0:
		_set_batch(batch.name, {"status": "planned"})
		_set_run(
			run_key,
			{
				"status": "paused",
				"stop_code": "live_queue_busy",
				"stop_reason": _("Canlı medya kuyruğu boş değil; devam için resume çağırın."),
			},
		)
		frappe.db.commit()
		release_active(run_key)
		return {"run_key": run_key, "batch": index, "status": "paused"}

	started = now_datetime()
	_set_batch(batch.name, {"status": "running", "started_at": started})
	_set_run(run_key, {"status": "running", "last_heartbeat": started})
	frappe.db.commit()
	files = _loads(batch.file_names_json, [])
	try:
		progress = runner.run_batch(
			files,
			preset=run.preset,
			job_key=batch.job_key,
			dry_run=int(run.dry_run or 0),
			collect_files=1,
		)
		decision = evaluate_stop(progress, StopPolicy())
		previous_changed = _loads(batch.changed_files_json, [])
		changed = (
			[]
			if int(run.dry_run or 0)
			else list(dict.fromkeys([*previous_changed, *(progress.get("optimized_files") or [])]))
		)
		processed = int(progress.get("processed") or 0)
		errors = int(progress.get("errors") or 0)
		optimized = int(progress.get("optimized") or 0) if int(run.dry_run or 0) else len(changed)
		skipped = (
			int(progress.get("skipped") or 0)
			if int(run.dry_run or 0)
			else max(0, processed - optimized - errors)
		)
		_set_batch(
			batch.name,
			{
				"status": "halted" if decision.halt else "completed",
				"processed": processed,
				"optimized": optimized,
				"skipped": skipped,
				"errors": errors,
				"original_bytes": int(progress.get("original_bytes") or 0),
				"new_bytes": int(progress.get("new_bytes") or 0),
				"changed_files_json": _dumps(changed),
				"progress_json": _dumps(progress),
				"decision_json": _dumps(decision.to_dict()),
				"finished_at": now_datetime(),
			},
		)
		frappe.db.commit()
		_finish_or_enqueue_next(run_key, index, decision)
		return {"run_key": run_key, "batch": index, "progress": progress, "decision": decision.to_dict()}
	except Exception:
		frappe.db.rollback()
		try:
			partial = runner.read_progress(batch.job_key)
		except Exception:
			partial = {}
		previous_changed = _loads(batch.changed_files_json, [])
		changed = (
			[]
			if int(run.dry_run or 0)
			else list(dict.fromkeys([*previous_changed, *(partial.get("optimized_files") or [])]))
		)
		processed = int(partial.get("processed") or 0)
		errors = int(partial.get("errors") or 0)
		optimized = int(partial.get("optimized") or 0) if int(run.dry_run or 0) else len(changed)
		skipped = (
			int(partial.get("skipped") or 0)
			if int(run.dry_run or 0)
			else max(0, processed - optimized - errors)
		)
		_set_batch(
			batch.name,
			{
				"status": "failed",
				"processed": processed,
				"optimized": optimized,
				"skipped": skipped,
				"errors": errors,
				"original_bytes": int(partial.get("original_bytes") or 0),
				"new_bytes": int(partial.get("new_bytes") or 0),
				"changed_files_json": _dumps(changed),
				"progress_json": _dumps(partial),
				"finished_at": now_datetime(),
				"decision_json": _dumps({"code": "worker_exception"}),
			},
		)
		aggregate = _aggregate(run_key)
		_set_run(
			run_key,
			{
				**aggregate,
				"status": "failed",
				"stop_code": "worker_exception",
				"stop_reason": str(frappe.get_traceback())[-1000:],
				"finished_at": now_datetime(),
			},
		)
		frappe.db.commit()
		release_active(run_key)
		raise


def _validation(run: Any) -> dict:
	plan_data = _loads(run.plan_json, {})
	errors: list[dict[str, Any]] = []
	try:
		plan = BackfillPlan.from_plan_json(plan_data)
	except BackfillError as exc:
		return {"ok": False, "errors": [{"code": "plan_invalid", "message": str(exc)}]}
	if plan.digest != run.plan_digest:
		errors.append({"code": "plan_digest_drift"})

	batches = sorted(run.batches, key=lambda row: int(row.batch_index or 0))
	if any(row.status not in ("completed", "halted") for row in batches):
		errors.append({"code": "non_terminal_batch"})
	if int(run.processed or 0) != int(run.total_files or 0):
		errors.append(
			{
				"code": "processed_total_mismatch",
				"processed": int(run.processed or 0),
				"total": int(run.total_files or 0),
			}
		)
	if int(run.errors or 0):
		errors.append({"code": "batch_errors", "count": int(run.errors or 0)})

	expected = _expected_urls(plan)
	rows = _rows_for_names(plan.a_class)
	from tradehub_core.media.inventory import EXCLUDED_DOCTYPES

	changed: list[str] = []
	for batch in batches:
		changed.extend(_loads(batch.changed_files_json, []))
	if not int(run.dry_run or 0) and len(changed) != int(run.optimized or 0):
		errors.append(
			{
				"code": "changed_count_mismatch",
				"changed": len(changed),
				"optimized": int(run.optimized or 0),
			}
		)

	url_drift: list[str] = []
	integrity_failed: list[dict[str, str]] = []
	for name in plan.a_class:
		row = rows.get(name)
		if not row:
			integrity_failed.append({"name": name, "reason": "file_record_missing"})
			continue
		if str(row.file_url or "") != expected.get(name):
			url_drift.append(name)
		if (
			int(row.is_private or 0)
			or not str(row.file_url or "").startswith("/files/")
			or row.attached_to_doctype in EXCLUDED_DOCTYPES
			or (row.content_hash and runner._has_sensitive_twin(row.content_hash))
		):
			integrity_failed.append({"name": name, "reason": "scope_drift"})
	if url_drift:
		errors.append({"code": "file_url_changed", "count": len(url_drift), "sample": url_drift[:20]})

	if not int(run.dry_run or 0):
		for name in changed:
			row = rows.get(name)
			if not row:
				continue
			url = str(row.file_url or "")
			try:
				path = trash._live_path(url)
				actual_size = os.path.getsize(path)
			except Exception:
				integrity_failed.append({"name": name, "reason": "disk_missing"})
				continue
			if actual_size != int(row.file_size or 0):
				integrity_failed.append({"name": name, "reason": "db_disk_size_mismatch"})
			if not row.th_optimized_at or int(row.th_original_size or 0) <= actual_size:
				integrity_failed.append({"name": name, "reason": "optimization_metadata_invalid"})
			try:
				archived = archive.exists(url)
			except Exception:
				archived = False
			if not archived:
				integrity_failed.append({"name": name, "reason": "archive_missing"})
	if integrity_failed:
		errors.append(
			{
				"code": "file_integrity_failed",
				"count": len(integrity_failed),
				"sample": integrity_failed[:20],
			}
		)
	return {
		"ok": not errors,
		"dry_run": bool(int(run.dry_run or 0)),
		"plan_digest": plan.digest,
		"checked_files": len(plan.a_class),
		"changed_files": len(changed),
		"errors": errors,
	}


def _send_seller_notifications(run: Any) -> dict[str, int]:
	"""Başarılı wet-run sonrası B sınıfını bir kez bildir; hataları koşumu bozmaz."""
	if int(run.dry_run or 0) or not int(run.notify_sellers or 0) or run.notifications_at:
		return {
			"sent": int(run.notifications_sent or 0),
			"skipped": int(run.notifications_skipped or 0),
		}
	plan = BackfillPlan.from_plan_json(_loads(run.plan_json, {}))
	sink = PlatformNotificationSink()
	for notice in build_notices(plan):
		try:
			sink.notify(notice)
		except Exception:
			sink.skipped += 1
			frappe.log_error(
				title=f"Media migration seller notice failed: {run.name}",
				message=frappe.get_traceback(with_context=True),
			)
	values = {
		"notifications_sent": sink.sent,
		"notifications_skipped": sink.skipped,
		"notifications_at": now_datetime(),
	}
	_set_run(run.name, values)
	return {"sent": sink.sent, "skipped": sink.skipped}


def validate_run(run_key: str, *, automatic: bool = False) -> dict:
	"""Batch muhasebesi + DB/disk/arşiv/file_url smoke doğrulaması."""
	run = _get_run(run_key)
	if run.status not in ("completed", "validated", "validation_failed"):
		frappe.throw(_("Bu durumda koşum doğrulanamaz: {0}").format(run.status))
	_set_run(run_key, {"status": "validating"})
	frappe.db.commit()
	run = _get_run(run_key)
	report = _validation(run)
	now = now_datetime()
	final_status = "validated" if report["ok"] else "validation_failed"
	_set_run(
		run_key,
		{
			"status": final_status,
			"validated_at": now,
			"finished_at": run.finished_at or now,
			"validation_json": _dumps(report),
		},
	)
	frappe.db.commit()
	if report["ok"]:
		report["notifications"] = _send_seller_notifications(_get_run(run_key))
		frappe.db.commit()
	# Rapor final state'i taşır; ``validating`` ara durumunu kalıcı özet diye
	# bırakmaz. İkinci yazım bildirim sayaçlarını da rapora dahil eder.
	_set_run(run_key, {"report_json": _dumps(status(run_key, include_plan=False))})
	frappe.db.commit()
	release_active(run_key)
	return {**report, "automatic": bool(automatic), "run_key": run_key}


def request_stop(run_key: str) -> dict:
	run = _get_run(run_key)
	if run.status not in ("queued", "running"):
		frappe.throw(_("Bu durumda koşum durdurulamaz: {0}").format(run.status))
	_set_run(
		run_key,
		{"status": "stopping", "stop_code": "operator_stop", "stop_reason": _("Durdurma istendi.")},
	)
	return {"run_key": run_key, "status": "stopping"}


def resume(run_key: str, *, acknowledge_stop: bool = False) -> dict:
	"""Paused/stopped koşumu checkpoint'ten devam ettir; halted için açık onay iste."""
	run = _get_run(run_key)
	if run.status not in RESUMABLE_STATUSES:
		frappe.throw(_("Bu durumda koşum devam ettirilemez: {0}").format(run.status))
	if run.status in ("halted", "failed") and not acknowledge_stop:
		frappe.throw(_("Otomatik durdurma nedenini kabul etmek için acknowledge_stop=1 gerekir."))
	index = int(run.next_batch_index or 1)
	if index > int(run.total_batches or 0):
		frappe.throw(_("Devam ettirilecek batch kalmadı."))
	if not claim_active(run_key):
		frappe.throw(_("Başka bir medya migration koşumu aktif."))
	batch = _get_batch(run, index)
	_set_batch(batch.name, {"status": "queued"})
	_set_run(
		run_key,
		{"status": "queued", "stop_code": None, "stop_reason": None, "last_heartbeat": now_datetime()},
	)
	_enqueue_batch(run_key, index, after_commit=True)
	return {"run_key": run_key, "status": "queued", "next_batch_index": index}


def start_rollback(run_key: str) -> dict:
	"""Wet-run'ın yalnız gerçekten değiştirdiği kimlikleri ters batch sırasıyla geri al."""
	run = _get_run(run_key)
	if int(run.dry_run or 0):
		frappe.throw(_("Kuru koşumda geri alınacak değişiklik yok."))
	if run.status not in ROLLBACK_SOURCE_STATUSES:
		frappe.throw(_("Bu durumda rollback başlatılamaz: {0}").format(run.status))
	if run.rollback_deadline and now_datetime() > get_datetime(run.rollback_deadline):
		frappe.throw(_("Rollback penceresi kapanmış."))
	indices = [
		int(batch.batch_index)
		for batch in run.batches
		if _loads(batch.changed_files_json, []) and batch.status not in ("rolled_back",)
	]
	if not indices:
		frappe.throw(_("Geri alınacak değiştirilmiş dosya yok."))
	if not claim_active(run_key):
		frappe.throw(_("Başka bir medya migration koşumu aktif."))
	index = max(indices)
	batch = _get_batch(run, index)
	_set_batch(batch.name, {"status": "rolling_back"})
	_set_run(
		run_key,
		{"status": "rolling_back", "rollback_batch_index": index, "last_heartbeat": now_datetime()},
	)
	_enqueue_rollback(run_key, index, after_commit=True)
	return {"run_key": run_key, "status": "rolling_back", "batch_index": index}


def _rollback_validation(run: Any) -> dict:
	"""Rollback sonucunda metadata/disk/arşiv üçlüsünün tekrar birleştiğini kanıtla."""
	plan = BackfillPlan.from_plan_json(_loads(run.plan_json, {}))
	expected = _expected_urls(plan)
	changed = list(
		dict.fromkeys(name for batch in run.batches for name in _loads(batch.changed_files_json, []))
	)
	rows = _rows_for_names(changed)
	errors: list[dict[str, str]] = []
	for name in changed:
		row = rows.get(name)
		if not row:
			errors.append({"name": name, "reason": "file_record_missing"})
			continue
		url = str(row.file_url or "")
		if url != expected.get(name):
			errors.append({"name": name, "reason": "file_url_changed"})
		try:
			actual = os.path.getsize(trash._live_path(url))
		except Exception:
			errors.append({"name": name, "reason": "disk_missing"})
			continue
		if actual != int(row.file_size or 0):
			errors.append({"name": name, "reason": "db_disk_size_mismatch"})
		if row.th_optimized_at or int(row.th_original_size or 0):
			errors.append({"name": name, "reason": "optimization_metadata_not_cleared"})
		try:
			still_archived = archive.exists(url)
		except Exception:
			still_archived = True
		if still_archived:
			errors.append({"name": name, "reason": "archive_not_dropped"})
	return {"ok": not errors, "checked_files": len(changed), "errors": errors[:50]}


def execute_rollback_batch(run_key: str, batch_index: int) -> dict:
	"""Exact changed-file listesini geri alan ters-zincir RQ işi."""
	index = int(batch_index)
	if not refresh_active(run_key):
		raise RuntimeError(_("Rollback koşum kilidi alınamadı."))
	run = _get_run(run_key)
	batch = _get_batch(run, index)
	files = _loads(batch.changed_files_json, [])
	if not files:
		_set_batch(batch.name, {"status": "rolled_back"})
		progress = {"state": "completed", "processed": 0, "errors": 0}
	else:
		try:
			progress = runner.restore_batch(files, job_key=f"{batch.job_key}-rollback", collect_files=1)
		except Exception:
			_set_batch(
				batch.name,
				{
					"status": "rollback_failed",
					"decision_json": _dumps({"rollback_exception": frappe.get_traceback()[-1000:]}),
					"finished_at": now_datetime(),
				},
			)
			_set_run(
				run_key,
				{
					"status": "rollback_failed",
					"stop_code": "rollback_exception",
					"stop_reason": _("Rollback worker hatası."),
				},
			)
			frappe.db.commit()
			release_active(run_key)
			raise
	if int(progress.get("errors") or 0):
		_set_batch(
			batch.name,
			{
				"status": "rollback_failed",
				"decision_json": _dumps({"rollback": progress}),
				"finished_at": now_datetime(),
			},
		)
		_set_run(
			run_key,
			{
				"status": "rollback_failed",
				"stop_code": "rollback_error",
				"stop_reason": _("Rollback batch hatası."),
			},
		)
		frappe.db.commit()
		release_active(run_key)
		return {"run_key": run_key, "batch": index, "status": "rollback_failed"}

	_set_batch(
		batch.name,
		{
			"status": "rolled_back",
			"decision_json": _dumps({"rollback": progress}),
			"finished_at": now_datetime(),
		},
	)
	remaining = sorted(
		(
			int(row.batch_index)
			for row in run.batches
			if int(row.batch_index) < index
			and _loads(row.changed_files_json, [])
			and row.status != "rolled_back"
		),
		reverse=True,
	)
	if remaining:
		next_index = remaining[0]
		next_batch = _get_batch(run, next_index)
		_set_batch(next_batch.name, {"status": "rolling_back"})
		_set_run(run_key, {"rollback_batch_index": next_index, "last_heartbeat": now_datetime()})
		frappe.db.commit()
		_enqueue_rollback(run_key, next_index)
		return {"run_key": run_key, "batch": index, "status": "rolling_back"}

	rollback_report = _rollback_validation(_get_run(run_key))
	final_status = "rolled_back" if rollback_report["ok"] else "rollback_failed"
	_set_run(
		run_key,
		{
			"status": final_status,
			"rollback_batch_index": 0,
			"archive_hold_until": None if rollback_report["ok"] else run.archive_hold_until,
			"finished_at": now_datetime(),
			"stop_code": None if rollback_report["ok"] else "rollback_validation_failed",
			"stop_reason": None if rollback_report["ok"] else _dumps(rollback_report["errors"]),
			"validation_json": _dumps({"rollback": rollback_report}),
		},
	)
	frappe.db.commit()
	release_active(run_key)
	return {"run_key": run_key, "batch": index, "status": final_status, "validation": rollback_report}


def status(run_key: str, *, include_plan: bool = False) -> dict:
	run = _get_run(run_key)
	batches = []
	for batch in sorted(run.batches, key=lambda row: int(row.batch_index or 0)):
		batches.append(
			{
				"batch_index": int(batch.batch_index or 0),
				"job_key": batch.job_key,
				"status": batch.status,
				"total": int(batch.total or 0),
				"processed": int(batch.processed or 0),
				"optimized": int(batch.optimized or 0),
				"skipped": int(batch.skipped or 0),
				"errors": int(batch.errors or 0),
				"started_at": batch.started_at,
				"finished_at": batch.finished_at,
				"decision": _loads(batch.decision_json, {}),
			}
		)
	out = {
		"run_key": run.name,
		"status": run.status,
		"dry_run": bool(int(run.dry_run or 0)),
		"approved_dry_run": run.approved_dry_run,
		"plan_schema_version": int(run.plan_schema_version or 0),
		"plan_digest": run.plan_digest,
		"preset": run.preset,
		"batch_size": int(run.batch_size or 0),
		"total_files": int(run.total_files or 0),
		"total_batches": int(run.total_batches or 0),
		"next_batch_index": int(run.next_batch_index or 0),
		"processed": int(run.processed or 0),
		"optimized": int(run.optimized or 0),
		"skipped": int(run.skipped or 0),
		"errors": int(run.errors or 0),
		"original_bytes": int(run.original_bytes or 0),
		"new_bytes": int(run.new_bytes or 0),
		"stop_code": run.stop_code,
		"stop_reason": run.stop_reason,
		"started_at": run.started_at,
		"finished_at": run.finished_at,
		"validated_at": run.validated_at,
		"rollback_deadline": run.rollback_deadline,
		"archive_hold_until": run.archive_hold_until,
		"notifications_sent": int(run.notifications_sent or 0),
		"notifications_skipped": int(run.notifications_skipped or 0),
		"notifications_at": run.notifications_at,
		"preflight": _loads(run.preflight_json, {}),
		"validation": _loads(run.validation_json, {}),
		"batches": batches,
	}
	if include_plan:
		out["plan"] = _loads(run.plan_json, {})
	return out


def archive_purge_hold() -> dict:
	"""Archive purge için kalıcı rollback hold bilgisini döndür (fail-closed)."""
	try:
		if not frappe.db.table_exists("Media Migration Run"):
			return {"held": False, "run_keys": [], "until": None}
		rows = frappe.get_all(
			"Media Migration Run",
			filters={
				"dry_run": 0,
				"status": ["not in", ["rolled_back"]],
			},
			or_filters={
				"archive_hold_until": [">=", now_datetime()],
				# Süre alanı yanlış/eskimiş olsa bile diske yazan aktif worker'ın
				# altından arşiv silinmez.
				"status": ["in", [*ACTIVE_STATUSES, "validating", "rolling_back"]],
			},
			fields=["name", "archive_hold_until"],
			order_by="archive_hold_until desc",
			limit_page_length=0,
		)
		return {
			"held": bool(rows),
			"run_keys": [row.name for row in rows],
			"until": rows[0].archive_hold_until if rows else None,
		}
	except Exception:
		frappe.log_error(title="Media migration archive hold check failed", message=frappe.get_traceback())
		return {"held": True, "run_keys": ["hold-check-failed"], "until": None}


def start_from_file(
	path: str,
	*,
	dry_run: bool = True,
	batch_size: int = 200,
	preset: str = presets.DEFAULT_PRESET,
	approved_dry_run: str = "",
) -> dict:
	"""Bench console girişi; HTTP payload yerine imzalı JSON dosyası okur."""
	with open(path, encoding="utf-8") as handle:
		plan_data = json.load(handle)
	return start(
		plan_data,
		dry_run=dry_run,
		batch_size=batch_size,
		preset=preset,
		approved_dry_run=approved_dry_run,
	)


__all__ = [
	"archive_purge_hold",
	"execute_batch",
	"execute_rollback_batch",
	"preflight",
	"request_stop",
	"resume",
	"start",
	"start_from_file",
	"start_rollback",
	"status",
	"validate_run",
]
