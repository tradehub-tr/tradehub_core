"""Scheduler tasks: cleanup + stuck job detection."""

import time

import frappe
from frappe.utils import add_days, add_to_date, now_datetime

JOB_RETENTION_DAYS = 90
CLEANUP_BATCH_SIZE = 500
# `long` kuyruğu 1500 sn verir; yarısının altında kalınır ki yavaş bir gecede de iş kesilmeden bitsin.
# Ölçüldü (MOGEM-981, yerel): 500 bağsız job ~5 sn, 500 bağlı job ~1,2 sn → bütçe gecede ~60 bin job.
CLEANUP_TIME_BUDGET_SECONDS = 600
STUCK_JOB_HOURS = 2
PROFILE_RETENTION_DAYS = 90

_FINISHED_STATUSES = ("Completed", "Failed", "Partial")


def cleanup_old_bulk_import_jobs(
	batch_size: int = CLEANUP_BATCH_SIZE, time_budget: float = CLEANUP_TIME_BUDGET_SECONDS
) -> dict[str, int]:
	"""Saklama süresi dolan bitmiş job'ları temizle; ilanı bağlı job'ın başlığını KORU.

	`Listing.created_by_bulk_job` ilanın kalıcı kaynağıdır (panel rozeti, kaynak süzgeci). Başlık
	silinirse o ilanın her kaydı Frappe link doğrulamasında 417 ile düşer (MOGEM-981: PROD'da 866
	ilan kilitlendi). Bu yüzden bağlı job'ın yalnız ağır ekleri silinir, başlık `artifacts_purged_at`
	ile damgalanıp bir daha taranmaz. Bağsız job tamamen silinir — `force` OLMADAN: bilmediğimiz bir
	bağ varsa Frappe'nin kendi kontrolü silmeyi durdurur ve job korunanlara düşer.

	Her job ayrı commit'lenir; partiler zaman bütçesi dolana kadar sürer. API kanalı çağrı başına bir
	job açar — sabit bir gece sınırı birikmeye yetişemezdi. Bütçe dolarsa kalan ertesi gece sürer.
	O gece hata veren job yeniden seçilmez; aynı bozuk job'ın etrafında dönülmez.
	"""
	deadline = time.monotonic() + time_budget
	sayac = {"silindi": 0, "korundu": 0, "hata": 0}
	failed: list[str] = []
	while time.monotonic() < deadline:
		names = _due_jobs(batch_size, exclude=failed)
		if not names:
			break
		for name in names:
			try:
				sayac[_cleanup_job(name)] += 1
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
				failed.append(name)
				sayac["hata"] += 1
				frappe.log_error(title=f"bulk_import cleanup: {name}")
	return sayac


def _due_jobs(limit: int, exclude: list[str]) -> list[str]:
	filters = {
		"status": ["in", _FINISHED_STATUSES],
		"completed_at": ["<", add_days(now_datetime(), -JOB_RETENTION_DAYS)],
		"artifacts_purged_at": ["is", "not set"],
	}
	if exclude:
		filters["name"] = ["not in", exclude]
	return frappe.get_all(
		"Bulk Import Job", filters=filters, order_by="completed_at asc", limit=limit, pluck="name"
	)


def _cleanup_job(name: str) -> str:
	_delete_eca_logs(name)
	_purge_artifacts(name)
	if frappe.db.exists("Listing", {"created_by_bulk_job": name}):
		return "korundu"
	try:
		frappe.delete_doc("Bulk Import Job", name, delete_permanently=True)
	except frappe.LinkExistsError:
		return "korundu"
	return "silindi"


def _delete_eca_logs(job_name: str) -> None:
	if not frappe.db.exists("DocType", "ECA Rule Log"):
		return
	for log_name in frappe.get_all("ECA Rule Log", filters={"bulk_import_job": job_name}, pluck="name"):
		frappe.delete_doc("ECA Rule Log", log_name, force=True, delete_permanently=True)


def _purge_artifacts(job_name: str) -> None:
	"""Hata satırlarını, ekli ve yüklenen dosyaları sil; başlığı damgala."""
	data_file, images_zip = frappe.db.get_value("Bulk Import Job", job_name, ["data_file", "images_zip"])
	frappe.db.delete("Bulk Import Job Error", {"parent": job_name, "parenttype": "Bulk Import Job"})
	attached = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Bulk Import Job", "attached_to_name": job_name},
		pluck="name",
	)
	# Yükleme ucu dosyayı bağsız kaydeder (`save_file(dt="")`); yalnız başka bir belgeye
	# bağlanmamış olanı sil — aynı adres başka yerde kullanılıyorsa dokunma.
	urls = [u for u in (data_file, images_zip) if u]
	unattached = (
		frappe.get_all(
			"File",
			filters={"file_url": ["in", urls], "attached_to_doctype": ["is", "not set"]},
			pluck="name",
		)
		if urls
		else []
	)
	for file_name in {*attached, *unattached}:
		frappe.delete_doc("File", file_name, delete_permanently=True, ignore_permissions=True)
	frappe.db.set_value(
		"Bulk Import Job",
		job_name,
		{"data_file": None, "images_zip": None, "artifacts_purged_at": now_datetime()},
		update_modified=False,
	)


def detect_stuck_bulk_jobs() -> None:
	"""2 saatten eski Running job'ları Failed'a çevir."""
	from tradehub_core.bulk_import import notifications

	cutoff = add_to_date(now_datetime(), hours=-STUCK_JOB_HOURS)
	stuck = frappe.get_all(
		"Bulk Import Job",
		filters={"status": "Running", "started_at": ["<", cutoff]},
		pluck="name",
	)
	for name in stuck:
		try:
			job = frappe.get_doc("Bulk Import Job", name)
			job.status = "Failed"
			job.error_summary = "Worker timeout — 2 saatten uzun süredir asılı kaldı"
			job.save(ignore_permissions=True)
			notifications.notify("job_failed", {"job": job})
		except Exception as e:
			frappe.log_error(
				f"stuck job {name} failed: {e}",
				"bulk_import.tasks",
			)
	frappe.db.commit()


def cleanup_stale_seller_template_profiles() -> None:
	"""90 gün kullanılmayan Seller Template Profile'ları sil."""
	if not frappe.db.exists("DocType", "Seller Template Profile"):
		return
	cutoff = add_days(now_datetime(), -PROFILE_RETENTION_DAYS)
	stale = frappe.get_all(
		"Seller Template Profile",
		filters={"last_used": ["<", cutoff]},
		pluck="name",
	)
	for name in stale:
		try:
			frappe.delete_doc(
				"Seller Template Profile",
				name,
				force=True,
				delete_permanently=True,
			)
		except Exception as e:
			frappe.log_error(
				f"cleanup profile {name} failed: {e}",
				"bulk_import.tasks",
			)
	frappe.db.commit()
