import json

import frappe
from frappe import _
from frappe.model.document import Document

COLOR_PRESETS = {
	"violet": ("bg-violet-100 dark:bg-violet-500/10", "text-violet-500"),
	"blue": ("bg-blue-100 dark:bg-blue-500/10", "text-blue-500"),
	"emerald": ("bg-emerald-100 dark:bg-emerald-500/10", "text-emerald-500"),
	"amber": ("bg-amber-100 dark:bg-amber-500/10", "text-amber-500"),
	"rose": ("bg-rose-100 dark:bg-rose-500/10", "text-rose-500"),
	"indigo": ("bg-indigo-100 dark:bg-indigo-500/10", "text-indigo-500"),
	"teal": ("bg-teal-100 dark:bg-teal-500/10", "text-teal-500"),
	"orange": ("bg-orange-100 dark:bg-orange-500/10", "text-orange-500"),
	"gray": ("bg-gray-100 dark:bg-gray-500/10", "text-gray-500"),
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
		self._backfill_scope_field_from_config()
		self._validate_scope_field()

	def _backfill_scope_field_from_config(self):
		"""Legacy widget'lar config_json içinde scope_field tutuyordu. Yeni
		first-class field doluysa onu kullan; aksi halde config_json'dan
		otomatik kopyala. Bu, eski seed/widget'ların validate sırasında
		first-class field'a otomatik göçünü sağlar.
		"""
		if self.scope_field:
			return
		if not self.config_json:
			return
		try:
			config = json.loads(self.config_json)
		except (TypeError, ValueError):
			return
		legacy_scope_field = config.get("scope_field")
		if legacy_scope_field:
			self.scope_field = legacy_scope_field

	def _validate_scope_field(self):
		"""Satıcı dashboard widget'ı için scope_field zorunlu (fail-safe).

		Kurallar:
		- dashboard_key != 'seller_overview' → bu kontrol skip
		- source_doctype yoksa (quick_links, funnel_chart) → skip
		- scope_field set değil VE DEFAULT_SCOPE_FIELDS'te yoksa → hata
		- scope_field set ama source_doctype'ta o alan yoksa → hata
		"""
		if self.dashboard_key != "seller_overview":
			return
		if not self.source_doctype:
			return
		# quick_links/funnel_chart veri çekmiyor — scope filter gerekmez
		if self.widget_type in ("quick_links", "funnel_chart"):
			return

		# Import burada (circular import'tan kaçınmak için)
		from tradehub_core.tradehub_core.api.dashboard_engine import DEFAULT_SCOPE_FIELDS

		resolved_field = self.scope_field or DEFAULT_SCOPE_FIELDS.get(self.source_doctype)
		if not resolved_field:
			frappe.throw(
				_(
					"'{0}' doctype için satıcı dashboard widget'ında 'Scope Alanı' "
					"belirtilmesi zorunlu. Bu alan, source_doctype'ta hangi field'ın "
					"satıcıyı temsil ettiğini gösterir (örn: seller, seller_profile). "
					"Aksi halde satıcılar widget'ı göremez veya yanlış veri görür."
				).format(self.source_doctype)
			)

		# Field doctype'ta gerçekten var mı doğrula
		try:
			meta = frappe.get_meta(self.source_doctype)
		except Exception:
			# DocType bulunamadıysa (örn. silinmiş) sessizce geç — daha kritik
			# bir doğrulama zaten reqd=1 source_doctype tarafında yapılmış olur
			return

		valid_fields = {f.fieldname for f in meta.fields}
		# Standard fields (name, owner vs.) da geçerli
		valid_fields.update({"name", "creation", "modified", "owner", "modified_by"})
		if resolved_field not in valid_fields:
			frappe.throw(
				_(
					"'{0}' alanı '{1}' doctype'ında bulunmuyor. Lütfen geçerli bir "
					"alan adı girin (örn: seller, seller_profile, owner_seller)."
				).format(resolved_field, self.source_doctype)
			)

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
