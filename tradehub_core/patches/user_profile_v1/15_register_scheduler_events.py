"""Patch 15: hooks.py scheduler_events doğrulama (E2 fırsat).
hooks.py kod PR'ında scheduler_events'e tasks.py fonksiyonları eklenmiş olmalı."""

import frappe


def execute():
	from tradehub_core import hooks as hooks_mod

	expected_in_scheduler = [
		"tradehub_core.tasks.recalculate_buyer_metrics",
		"tradehub_core.tasks.calculate_buyer_scores",
		"tradehub_core.tasks.buyer_level_tasks",
		"tradehub_core.tasks.aggregate_buyer_kpi_summaries",
	]

	actual = set()
	for events in hooks_mod.scheduler_events.values():
		actual.update(events)

	missing = [fn for fn in expected_in_scheduler if fn not in actual]
	if missing:
		frappe.log_error(
			title="Patch 15: scheduler events missing",
			message=f"hooks.py'ye registered olmamış fonksiyonlar: {missing}",
		)
