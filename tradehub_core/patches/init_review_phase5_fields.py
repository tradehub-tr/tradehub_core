"""Faz 5 — Translation Settings (Single) baseline + initial analytics snapshot.

- Translation Settings Single doctype default değerlerini set eder
- Bugün için ilk analytics snapshot'ı tetikler
"""

import frappe


def execute():
	_init_translation_settings()
	_initial_snapshot()
	frappe.db.commit()


def _init_translation_settings():
	if not frappe.db.exists("DocType", "Translation Settings"):
		return
	try:
		settings = frappe.get_single("Translation Settings")
		if not settings.provider:
			settings.provider = "stub"
		if not settings.openai_model:
			settings.openai_model = "gpt-4o-mini"
		if not settings.daily_quota:
			settings.daily_quota = 500
		settings.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="phase5_translation_settings_init")


def _initial_snapshot():
	if not frappe.db.table_exists("tabReview Analytics Snapshot"):
		return
	try:
		from tradehub_core.api.analytics import daily_snapshot

		daily_snapshot()
	except Exception:
		frappe.log_error(title="phase5_initial_snapshot_failed")
