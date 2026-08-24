# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Dedicated low-priority RQ worker for scheduled media backfills.

Frappe v15's ``bench worker`` starts RQ with ``with_scheduler=False``.  That is
correct for its default immediate queues, but policy reprocessing deliberately
uses ``enqueue_in`` so rate-limit waits do not occupy a worker process.  This
entrypoint mirrors Frappe's worker envelope and enables RQ's scheduler for the
single custom queue.
"""

from __future__ import annotations

import os
from pathlib import Path

import frappe
from frappe.utils.background_jobs import get_queue_list, get_redis_conn
from rq import Worker

BULK_QUEUE = "media-image-bulk"


def _sites_path() -> str:
	"""Resolve the bench sites directory for direct ``python -m`` startup."""
	explicit = os.environ.get("SITES_PATH")
	candidates = [Path(explicit)] if explicit else []
	candidates.extend((Path.cwd() / "sites", Path.cwd()))
	for candidate in candidates:
		if (candidate / "apps.txt").is_file():
			return str(candidate)
	raise RuntimeError("Unable to locate Frappe sites/apps.txt; set SITES_PATH")


def main() -> None:
	"""Start one scheduler-enabled worker for the namespaced bulk queue."""
	# Best-effort process niceness is a second low-priority boundary after queue
	# isolation; containers without permission still start normally.
	try:
		os.nice(10)
	except OSError:
		pass

	# ``bench worker`` runs from the sites directory.  Match that invariant so
	# Frappe's later ``execute_job -> frappe.init(site=...)`` calls resolve the
	# tenant with their default ``sites_path='.'`` as well.
	os.chdir(_sites_path())
	with frappe.init_site():
		connection = get_redis_conn()
		queue_names = get_queue_list([BULK_QUEUE], build_queue_name=True)
	worker = Worker(queue_names, connection=connection)
	worker.work(
		with_scheduler=True,
		logging_level="INFO",
		date_format="%Y-%m-%d %H:%M:%S",
		log_format="%(asctime)s,%(msecs)03d %(message)s",
	)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
	main()
