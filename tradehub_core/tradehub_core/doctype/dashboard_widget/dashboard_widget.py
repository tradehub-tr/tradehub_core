import json

import frappe
from frappe import _
from frappe.model.document import Document


COLOR_PRESETS = {
	"violet":  ("bg-violet-100 dark:bg-violet-500/10",  "text-violet-500"),
	"blue":    ("bg-blue-100 dark:bg-blue-500/10",      "text-blue-500"),
	"emerald": ("bg-emerald-100 dark:bg-emerald-500/10", "text-emerald-500"),
	"amber":   ("bg-amber-100 dark:bg-amber-500/10",    "text-amber-500"),
	"rose":    ("bg-rose-100 dark:bg-rose-500/10",      "text-rose-500"),
	"indigo":  ("bg-indigo-100 dark:bg-indigo-500/10",  "text-indigo-500"),
	"teal":    ("bg-teal-100 dark:bg-teal-500/10",      "text-teal-500"),
	"orange":  ("bg-orange-100 dark:bg-orange-500/10",  "text-orange-500"),
	"gray":    ("bg-gray-100 dark:bg-gray-500/10",      "text-gray-500"),
}


class DashboardWidget(Document):
	def before_insert(self):
		# Auto-append to the end of the dashboard.
		# Sıralama drag-drop ile yönetilir; yeni widget sona eklenir.
		if not self.position:
			max_position = frappe.db.sql(
				"""
				SELECT COALESCE(MAX(position), 0) AS max_pos
				FROM `tabDashboard Widget`
				WHERE dashboard_key = %(key)s
				""",
				{"key": self.dashboard_key},
			)
			current_max = max_position[0][0] if max_position else 0
			self.position = int(current_max) + 10

	def validate(self):
		self._apply_color_preset()
		self._validate_json_fields()

	def _apply_color_preset(self):
		"""Compute icon_bg_class / icon_color_class from color_preset.

		Admin selects a preset; Tailwind class pairs are generated in a single
		source of truth to guarantee visual consistency across the dashboard.
		"""
		preset = (self.color_preset or "violet").lower()
		bg, color = COLOR_PRESETS.get(preset, COLOR_PRESETS["violet"])
		self.icon_bg_class = bg
		self.icon_color_class = color

	def _validate_json_fields(self):
		for field in ("filters_json", "config_json"):
			value = self.get(field)
			if not value:
				continue
			try:
				json.loads(value)
			except (TypeError, ValueError):
				frappe.throw(_("{0} geçerli JSON olmalı.").format(field))
