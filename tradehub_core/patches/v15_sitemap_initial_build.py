"""BE-MAP: parçalı disk-cache sitemap'lerin ilk üretimini kuyruğa at.

Idempotent: job_id + deduplicate ile aynı anda tek rebuild koşar. Migrate
sonrası sitemap endpoint'lerinin 404/bayat dönmemesi için ısıtma adımı
(FAZ D runbook'undaki `rebuild_all_sitemaps_now` ısıtmasının otomatik hali).
"""

import frappe


def execute():
	try:
		frappe.enqueue(
			"tradehub_core.seo.tasks.rebuild_all_sitemaps",
			queue="long",
			job_id="seo-sitemap-rebuild",
			deduplicate=True,
		)
	except Exception:
		# Scheduler/redis henüz ayakta değilse migrate'i düşürme; cron zaten
		# her gün rebuild ediyor.
		frappe.log_error(frappe.get_traceback(), "sitemap initial build enqueue")
