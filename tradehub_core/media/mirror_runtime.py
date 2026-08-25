"""Canlı ``File`` yazımlarını asenkron S3 aynasına bağla.

Depolama adaptörleri kendi başlarına doğru çalışsa da Frappe'nin mevcut
``File`` yazma yolu onları kullanmaz: ``media.naming`` baytı doğrudan site
diskine yazar. Bu modül o iki dünyanın dar köprüsüdür:

* ``File.after_insert`` yalnız ``mirror`` kipi ve ``s3_upload_originals``
  açıkken içerik-adresli URL'i uzun kuyruğa bırakır.
* RQ işçisi ayarı yeniden okur, yerel dosyayı akışlı okuyup S3'e yazar.
* S3 ya da Redis hatası birincil yüklemeyi geri almaz. Başarısızlık Error
  Log'a düşer; günlük ``reconcile_scheduled`` eksik kopyayı yeniden kuyruğa
  alır.

``s3_primary`` burada sessizce taklit edilmez. Frappe dosya teslimi hâlâ yerel
disk beklediği için bu köprü yalnız gerçek davranışı olan ``mirror`` kipini
etkinleştirir. Bir ayar değişikliği iş kuyruktayken kipi kapatırsa iş S3'e
dokunmadan atlanır.
"""

from __future__ import annotations

from typing import Any

import frappe

from tradehub_core.media.pipeline.contracts.storage import ObjectRef, key_from_url
from tradehub_core.media.pipeline.storage import (
	DEFAULT_MIRROR_METHOD,
	MODE_MIRROR,
	StorageSettings,
	build_storage,
	normalize_mode,
)
from tradehub_core.media.pipeline.storage.mirror import (
	OP_DELETE,
	OP_MOVE,
	OP_PUT,
	FrappeEnqueueMirrorQueue,
	MirrorStorage,
	MirrorTask,
)

DOCTYPE: str = "Media Storage Settings"
QUEUE: str = "long"
DEFAULT_RECONCILE_LIMIT: int = 1_000
OPS: frozenset[str] = frozenset({OP_PUT, OP_DELETE, OP_MOVE})


def _storage_doc() -> Any:
	return frappe.get_cached_doc(DOCTYPE)


def _runtime_state(settings: Any, *, op: str = OP_PUT, kind: str = "original") -> tuple[bool, str]:
	"""Ayar bu işlemi gerçekten S3 aynasına göndermeli mi?"""
	if normalize_mode(settings.get("storage_mode") or settings.get("backend")) != MODE_MIRROR:
		return False, "storage_mode_not_mirror"
	if not int(settings.get("s3_enabled") or 0):
		return False, "s3_disabled"
	if op != OP_PUT:
		# Daha önce aynalanmış bir nesnenin silme/taşıması, yeni upload
		# bayrağı sonradan kapatılsa bile ikincile yansımalıdır.
		return True, "enabled"
	bayrak = "s3_upload_renditions" if kind == "rendition" else "s3_upload_originals"
	if not int(settings.get(bayrak) or 0):
		return False, f"{bayrak}_disabled"
	return True, "enabled"


def _ref_from_payload(
	url: str,
	*,
	scope: str = "",
	shard: str = "",
	name: str = "",
) -> ObjectRef:
	"""Kuyruk zarfını URL'den yeniden kur ve oynanmış alanı reddet."""
	key, parsed_scope = key_from_url(str(url or ""))
	if scope and scope != parsed_scope:
		raise ValueError("Ayna görevi scope alanı URL ile uyuşmuyor")
	if shard and shard != key.shard:
		raise ValueError("Ayna görevi shard alanı URL ile uyuşmuyor")
	if name and name != key.name:
		raise ValueError("Ayna görevi name alanı URL ile uyuşmuyor")
	return ObjectRef(key=key, scope=parsed_scope)


def _build_runtime_plan(settings: Any):
	return build_storage(
		StorageSettings.from_doctype(
			settings.storage_mapping(),
			site_path=frappe.get_site_path(),
		)
	)


def _safe_log(title: str, message: str) -> None:
	"""Alarm yolu ana akışı asla düşürmez; sır değeri kabul etmez."""
	try:
		frappe.log_error(title=title, message=str(message)[:2_000])
	except Exception:
		pass


def enqueue_operation(
	file_url: str,
	*,
	op: str = OP_PUT,
	kind: str = "original",
	target_scope: str = "",
) -> dict[str, Any]:
	"""Yerel URL işlemini commit-sonrası ayna kuyruğuna bırak."""
	operation = str(op or "").strip().lower()
	if operation not in OPS:
		raise ValueError(f"Bilinmeyen ayna işlemi: {operation!r}")
	settings = _storage_doc()
	etkin, sebep = _runtime_state(settings, op=operation, kind=kind)
	if not etkin:
		return {"queued": False, "reason": sebep}
	try:
		ref = _ref_from_payload(file_url)
	except ValueError:
		# Dış URL / eski shardsız URL yerel adaptör sözleşmesine ait
		# değil. Bu dosyayı yanlış anahtarla S3'e koymaktansa açıkça atla.
		return {"queued": False, "reason": "unsupported_file_url"}

	task = MirrorTask(op=operation, ref=ref, target_scope=str(target_scope or ""))
	queued = FrappeEnqueueMirrorQueue(DEFAULT_MIRROR_METHOD, queue=QUEUE).submit(task)
	if not queued:
		_safe_log("media.mirror.enqueue_failed", f"url={ref.url}")
	return {"queued": bool(queued), "reason": "queued" if queued else "queue_failed"}


def enqueue_file_url(file_url: str, *, kind: str = "original") -> dict[str, Any]:
	"""Yeni yerel dosyayı ayna kuyruğuna bırak."""
	return enqueue_operation(file_url, op=OP_PUT, kind=kind)


def maybe_mirror_on_insert(doc: Any, method: str | None = None) -> None:
	"""``File.after_insert`` kancası; her koşulda best-effort."""
	if int(getattr(doc, "is_folder", 0) or 0):
		return
	file_url = str(getattr(doc, "file_url", "") or "")
	if not file_url:
		return
	try:
		enqueue_file_url(file_url, kind="original")
	except Exception as exc:  # noqa: BLE001 - ikincil depo upload'u düşüremez
		_safe_log("media.mirror.hook_failed", f"url={file_url}; error={type(exc).__name__}")


def maybe_mirror_on_trash(doc: Any, method: str | None = None) -> None:
	"""``File.on_trash`` kancası; S3 silme işi DB commit'inden sonra koşar."""
	if int(getattr(doc, "is_folder", 0) or 0):
		return
	file_url = str(getattr(doc, "file_url", "") or "")
	if not file_url:
		return
	try:
		enqueue_operation(file_url, op=OP_DELETE)
	except Exception as exc:  # noqa: BLE001 - ikincil depo File silmeyi düşüremez
		_safe_log("media.mirror.delete_hook_failed", f"url={file_url}; error={type(exc).__name__}")


def run_mirror_task(
	op: str,
	url: str,
	scope: str = "",
	shard: str = "",
	name: str = "",
	target_scope: str = "",
	attempt: int = 0,
) -> dict[str, Any]:
	"""RQ işçisi: tek ayna görevini güncel ayarla yürüt.

	Fonksiyon whitelist edilmez; yalnız arka plan işi olarak çağrılır.
	"""
	operation = str(op or "").strip().lower()
	if operation not in OPS:
		raise ValueError(f"Bilinmeyen ayna işlemi: {operation!r}")
	ref = _ref_from_payload(url, scope=scope, shard=shard, name=name)
	task = MirrorTask(
		op=operation,
		ref=ref,
		target_scope=str(target_scope or ""),
		attempt=max(0, int(attempt or 0)),
	)

	settings = _storage_doc()
	etkin, sebep = _runtime_state(settings, op=operation)
	if not etkin:
		return {"ok": True, "skipped": True, "reason": sebep, "url": ref.url}

	plan = _build_runtime_plan(settings)
	if plan.mode != MODE_MIRROR or not isinstance(plan.adapter, MirrorStorage):
		_safe_log(
			"media.mirror.degraded",
			f"url={ref.url}; requested={plan.requested_mode}; actual={plan.mode}; reasons={','.join(plan.reasons)}",
		)
		raise RuntimeError("Ayna deposu kurulamadı; yerel birincil korunuyor")

	try:
		completed = plan.adapter.worker.execute(task)
		counters = plan.adapter.counters()
		failures = plan.adapter.failed_tasks()
		if not completed or counters.get("failed", 0):
			reason = (failures[-1].get("reason") if failures else "mirror_failed") or "mirror_failed"
			_safe_log("media.mirror.task_failed", f"url={ref.url}; reason={reason}")
			raise RuntimeError(f"Ayna görevi başarısız: {reason}")
		return {
			"ok": True,
			"skipped": False,
			"url": ref.url,
			"operation": operation,
			"attempt": task.attempt,
			"counters": counters,
		}
	finally:
		plan.adapter.close()


def reconcile_scheduled(limit: int = DEFAULT_RECONCILE_LIMIT) -> dict[str, Any]:
	"""Yerelde olup S3'te olmayan nesneleri günlük yeniden kuyruğa al."""
	settings = _storage_doc()
	etkin, sebep = _runtime_state(settings)
	if not etkin:
		return {"enabled": False, "reason": sebep, "results": []}
	plan = _build_runtime_plan(settings)
	if plan.mode != MODE_MIRROR or not isinstance(plan.adapter, MirrorStorage):
		_safe_log(
			"media.mirror.reconcile_degraded",
			f"requested={plan.requested_mode}; actual={plan.mode}; reasons={','.join(plan.reasons)}",
		)
		return {"enabled": False, "reason": "storage_degraded", "results": []}
	try:
		results = plan.adapter.reconcile_all(limit=max(0, int(limit or 0)))
		return {"enabled": True, "reason": "ok", "results": results}
	finally:
		plan.adapter.close()


def mirror_status(file_url: str) -> dict[str, Any]:
	"""Tek URL'in yerel ve S3 kopyasını salt-okunur ölç."""
	ref = _ref_from_payload(file_url)
	settings = _storage_doc()
	etkin, sebep = _runtime_state(settings)
	if not etkin:
		return {
			"enabled": False,
			"reason": sebep,
			"url": ref.url,
			"primary": False,
			"secondary": False,
			"replicated": False,
		}
	plan = _build_runtime_plan(settings)
	if plan.mode != MODE_MIRROR or not isinstance(plan.adapter, MirrorStorage):
		return {
			"enabled": False,
			"reason": "storage_degraded",
			"url": ref.url,
			"primary": False,
			"secondary": False,
			"replicated": False,
		}
	try:
		return {"enabled": True, "reason": "ok", **plan.adapter.replication_status(ref)}
	finally:
		plan.adapter.close()


__all__ = [
	"enqueue_file_url",
	"enqueue_operation",
	"maybe_mirror_on_insert",
	"maybe_mirror_on_trash",
	"run_mirror_task",
	"reconcile_scheduled",
	"mirror_status",
]
