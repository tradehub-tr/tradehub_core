"""Kuyruk / olay tutarlılığı (14.4).

- `enqueue_after_commit`: iş yalnız işlem commit olduktan sonra kuyruğa girer (yarım veri yok).
- Her iş `SEO Sync Job` kaydıdır: `queued → running → done | failed → (backoff) … → dead`.
  Tekrar deneme 1/5/15/60/360 dk (MOGEM-665 webhook deseni ile aynı); 5. başarısızlık `dead`
  (hata kuyruğu) — panelde görünür, elle `requeue`.
- Olay kaybı: `dedupe_key` ile aynı iş iki kez açılmaz; `sweep_due_jobs` (*/5) süresi gelen
  `failed` ve kuyrukta unutulmuş `queued` işleri yeniden alır. Uzlaşma: `cms.bridge.reconcile_pages`.
- Kapasite ayrımı: kısa işler `default`, crawl/pSEO `seo_long`, MCP kaynaklı işler `mcp`
  (common_site_config `workers` — docs/OPERASYON.md).
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

BACKOFF_MINUTES = (1, 5, 15, 60, 360)
MAX_ATTEMPTS = len(BACKOFF_MINUTES)
QUEUES = {
	"default": "seo",
	"long": "seo_long",
	"mcp": "mcp",
}  # 14.4: kısa/crawl-pSEO/MCP ayrı işçi kapasitesi
STALE_QUEUED_MINUTES = 10
SWEEP_BATCH = 200


def enqueue_after_commit(
	job_type: str,
	payload: dict,
	*,
	store: str | None = None,
	queue: str = "default",
	dedupe_key: str | None = None,
	timeout: int = 300,
) -> str | None:
	"""SEO Sync Job aç, commit sonrası çalıştır. `dedupe_key` varsa açık aynı iş yeniden açılmaz."""
	if dedupe_key:
		mevcut = frappe.db.get_value(
			"SEO Sync Job",
			{"dedupe_key": dedupe_key, "status": ["in", ["queued", "running", "failed"]]},
			"name",
		)
		if mevcut:
			return mevcut
	job = frappe.get_doc(
		{
			"doctype": "SEO Sync Job",
			"job_type": job_type,
			"payload": json.dumps(payload, ensure_ascii=False, default=str),
			"store": store,
			"queue": QUEUES.get(queue, queue),
			"status": "queued",
			"attempts": 0,
			"dedupe_key": dedupe_key,
			"next_attempt_at": now_datetime(),
		}
	).insert(ignore_permissions=True)  # sistem kaydı; store alanı çağıranın izniyle belirlendi
	frappe.enqueue(
		"tradehub_core.seo_helper.core.queue.run_job",
		queue=QUEUES.get(queue, queue),
		timeout=timeout,
		enqueue_after_commit=True,
		job=job.name,
	)
	return job.name


HANDLERS: dict[str, str] = {
	"page.policy": "tradehub_core.seo_helper.core.policy.apply_for_page_job",
	"page.reconcile": "tradehub_core.seo_helper.cms.bridge.reconcile_pages",
	"entity.mirror": "tradehub_core.seo_helper.catalog.mirror.mirror_job",
	"sitemap.rebuild": "tradehub_core.seo_helper.adapters.tradehub.sitemap.rebuild_all",
	"mcp.long": "tradehub_core.seo_helper.mcp.jobs.run_long_tool",
	"crawl.run": "tradehub_core.seo_helper.crawler.manager.run_crawl_job",
	"gsc.sync": "tradehub_core.seo_helper.connectors.search_console.sync_job",
}


def run_job(job: str) -> dict:
	if not frappe.db.exists("SEO Sync Job", job):  # kayıt commit'ten sonra silinmiş olabilir; gürültü yapma
		return {"job": job, "status": "missing", "skipped": True}
	doc = frappe.get_doc("SEO Sync Job", job)
	if doc.status not in ("queued", "failed"):
		return {"job": job, "status": doc.status, "skipped": True}
	doc.db_set({"status": "running", "started_at": now_datetime()}, update_modified=False)
	frappe.db.commit()
	handler = HANDLERS.get(doc.job_type)
	try:
		if not handler:
			raise ValueError(f"bilinmeyen iş türü: {doc.job_type}")
		payload = json.loads(doc.payload or "{}")
		sonuc = (
			frappe.get_attr(handler)(**payload)
			if isinstance(payload, dict)
			else frappe.get_attr(handler)(payload)
		)
		doc.db_set(
			{
				"status": "done",
				"finished_at": now_datetime(),
				"attempts": int(doc.attempts or 0) + 1,
				"last_error": "",
				"result": json.dumps(sonuc, default=str)[:5000],
				"next_attempt_at": None,
			},
			update_modified=False,
		)
		return {"job": job, "status": "done"}
	except frappe.DoesNotExistError as e:
		# hedef kayıt (ör. SEO Crawl Run) iş kuyruktayken silinmiş: tekrar denemek hiçbir şeyi düzeltmez —
		# 5 deneme + Error Log gürültüsü yerine tek seferde kapat (25 Eyl 2026 kuyruk incelemesi: 18 böyle iş)
		frappe.db.rollback()
		doc.db_set(
			{
				"status": "done",
				"finished_at": now_datetime(),
				"attempts": int(doc.attempts or 0) + 1,
				"last_error": f"hedef yok, atlandı: {e}"[:1000],
				"result": json.dumps({"skipped": "target_missing"}),
				"next_attempt_at": None,
			},
			update_modified=False,
		)
		return {"job": job, "status": "done", "skipped": "target_missing"}
	except frappe.QueryDeadlockError:
		# kilit çekişmesi (ör. Builder kaydı ile aynı anda) — deneme sayılmaz, 1 dk sonra sessizce tekrar
		frappe.db.rollback()
		doc.db_set(
			{"status": "failed", "next_attempt_at": add_to_date(now_datetime(), minutes=1)},
			update_modified=False,
		)
		return {"job": job, "status": "failed", "deadlock": True}
	except Exception as e:  # noqa: BLE001 — iş kendi hatasını kaydeder, süreç düşmez
		frappe.db.rollback()
		attempts = int(doc.attempts or 0) + 1
		dead = attempts >= MAX_ATTEMPTS
		doc.db_set(
			{
				"status": "dead" if dead else "failed",
				"attempts": attempts,
				"last_error": f"{type(e).__name__}: {e}"[:1000],
				"finished_at": now_datetime(),
				"next_attempt_at": None
				if dead
				else add_to_date(now_datetime(), minutes=BACKOFF_MINUTES[attempts - 1]),
			},
			update_modified=False,
		)
		frappe.log_error(title=f"SEO Sync Job {doc.job_type} {job}", message=frappe.get_traceback())
		return {"job": job, "status": doc.status}


def requeue(job: str) -> None:
	frappe.db.set_value(
		"SEO Sync Job",
		job,
		{"status": "queued", "attempts": 0, "last_error": "", "next_attempt_at": now_datetime()},
		update_modified=False,
	)
	queue = frappe.db.get_value("SEO Sync Job", job, "queue") or "seo"
	frappe.enqueue(
		"tradehub_core.seo_helper.core.queue.run_job", queue=queue, enqueue_after_commit=True, job=job
	)


def sweep_due_jobs() -> dict:
	now = now_datetime()
	due = frappe.get_all(
		"SEO Sync Job",
		filters={"status": "failed", "next_attempt_at": ["<=", now]},
		pluck="name",
		limit_page_length=SWEEP_BATCH,
	)
	stale = frappe.get_all(
		"SEO Sync Job",
		filters={"status": "queued", "modified": ["<=", add_to_date(now, minutes=-STALE_QUEUED_MINUTES)]},
		pluck="name",
		limit_page_length=SWEEP_BATCH,
	)
	done = failed = 0
	for name in [*due, *stale]:
		r = run_job(name)
		done += r.get("status") == "done"
		failed += r.get("status") in ("failed", "dead")
		frappe.db.commit()
	return {"due": len(due), "stale": len(stale), "done": done, "failed": failed}


def is_due(next_attempt_at) -> bool:
	return bool(next_attempt_at) and get_datetime(next_attempt_at) <= now_datetime()
