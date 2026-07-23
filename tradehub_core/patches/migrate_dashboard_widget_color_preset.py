# Copyright (c) 2024, TR TradeHub and contributors
# For license information, please see license.txt

"""
Backfill `color_preset` on existing Dashboard Widget records.

When the DocType schema switched from raw `icon_bg_class` / `icon_color_class`
text fields to a single `color_preset` Select, existing rows had classes but
no preset. Reverse-map class strings to preset keys so downstream widgets
keep their colors.

Idempotent: skips widgets that already have a non-empty color_preset.
"""

import frappe

REVERSE_MAP = {
	"bg-violet-100 dark:bg-violet-500/10": "violet",
	"bg-blue-100 dark:bg-blue-500/10": "blue",
	"bg-emerald-100 dark:bg-emerald-500/10": "emerald",
	"bg-amber-100 dark:bg-amber-500/10": "amber",
	"bg-rose-100 dark:bg-rose-500/10": "rose",
	"bg-indigo-100 dark:bg-indigo-500/10": "indigo",
	"bg-teal-100 dark:bg-teal-500/10": "teal",
	"bg-orange-100 dark:bg-orange-500/10": "orange",
	"bg-gray-100 dark:bg-gray-500/10": "gray",
}


def execute():
	# Patches run before the implicit model-sync pass, so the new
	# color_preset column may not exist yet. Add it directly via DDL if
	# missing, then backfill values from the existing class strings.
	if not frappe.db.has_column("Dashboard Widget", "color_preset"):
		frappe.db.sql_ddl(
			"ALTER TABLE `tabDashboard Widget` ADD COLUMN `color_preset` VARCHAR(140) DEFAULT 'violet'"
		)

	widgets = frappe.db.sql(
		"""
		SELECT name, icon_bg_class, color_preset
		FROM `tabDashboard Widget`
		""",
		as_dict=True,
	)
	updated = 0
	for w in widgets:
		if w.get("color_preset") and w["color_preset"] != "violet":
			continue
		preset = REVERSE_MAP.get((w.get("icon_bg_class") or "").strip(), "violet")
		frappe.db.sql(
			"UPDATE `tabDashboard Widget` SET color_preset = %s WHERE name = %s",
			(preset, w["name"]),
		)
		updated += 1
	frappe.db.commit()
	frappe.logger("patches").info(f"Dashboard Widget color_preset backfilled for {updated} rows.")
