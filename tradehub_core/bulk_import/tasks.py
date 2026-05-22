"""Scheduler tasks: cleanup + stuck job detection."""

import frappe
from frappe.utils import add_days, add_to_date, now_datetime

JOB_RETENTION_DAYS = 90
STUCK_JOB_HOURS = 2
PROFILE_RETENTION_DAYS = 90


def cleanup_old_bulk_import_jobs() -> None:
	"""90 günden eski Completed/Failed/Partial job'ları sil."""
	cutoff = add_days(now_datetime(), -JOB_RETENTION_DAYS)
	old = frappe.get_all(
		"Bulk Import Job",
		filters={
			"status": ["in", ["Completed", "Failed", "Partial"]],
			"completed_at": ["<", cutoff],
		},
		pluck="name",
	)
	for name in old:
		try:
			if frappe.db.exists("DocType", "ECA Rule Log"):
				log_names = frappe.get_all(
					"ECA Rule Log",
					filters={"bulk_import_job": name},
					pluck="name",
				)
				for log_name in log_names:
					frappe.delete_doc(
						"ECA Rule Log",
						log_name,
						force=True,
						delete_permanently=True,
					)
			frappe.delete_doc(
				"Bulk Import Job",
				name,
				force=True,
				delete_permanently=True,
			)
		except Exception as e:
			frappe.log_error(
				f"cleanup job {name} failed: {e}",
				"bulk_import.tasks",
			)
	frappe.db.commit()


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
